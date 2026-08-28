"""Central structured logging: follow ONE request through everything it touched.

Design, and the reasons it looks this way:

* Two sinks. Stdout stays human (`docker compose logs -f backend` remains readable);
  the JSON-lines file under /storage survives `--force-recreate` - losing the logs with the
  container is a trap this project has already fallen into - and ships with the existing
  backup guidance for /storage.
* Correlation by contextvar + a ROOT-logger filter, not by touching call sites. Every
  record emitted anywhere while a request is in flight - services, SQL warnings, matching
  decisions - carries that request's id and user, without editing the sixty modules that
  do not log today.
* Redaction is enforced in the pipeline, not promised by convention. Tokens, passwords,
  `Bearer ...` strings and embedding vectors are scrubbed before ANY formatter sees the
  record, so a future `log.info(token)` mistake cannot leak into either sink. This backend
  handles evidence; "we are careful" is not a control.
* The audit table stays the LEGAL record of who did what. This is the engineering record
  of what the system did. They are deliberately separate systems.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# ---------------------------------------------------------------- request context

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("log_request_id", default="-")
_request_user: contextvars.ContextVar[str] = contextvars.ContextVar("log_request_user", default="-")
_request_route: contextvars.ContextVar[str] = contextvars.ContextVar("log_request_route", default="-")

REQUEST_ID_HEADER = "X-Request-ID"
# Inbound ids are caller-controlled bytes headed for log files - constrain them.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")


def current_request_id() -> str:
    return _request_id.get()


def bind_user(username: str) -> None:
    """Attach the authenticated username to every later record of this request.

    Called once from `get_current_user` - the single door every authenticated route
    passes through - so no endpoint needs to remember to do it.
    """
    _request_user.set(username)


class _ContextFilter(logging.Filter):
    """Stamp request context onto EVERY record, whoever emitted it.

    Explicit values win: BaseHTTPMiddleware runs `dispatch` in a CHILD task, so a
    contextvar set deeper (the endpoint) or read shallower (the outer 500 handler) may not
    line up - callers that know better pass request_id/request_user via `extra`, and this
    filter must not overwrite them with the current context's view.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = _request_id.get()
        if not hasattr(record, "request_user"):
            record.request_user = _request_user.get()
        if not hasattr(record, "request_route"):
            record.request_route = _request_route.get()
        return True


# ---------------------------------------------------------------- redaction

_SENSITIVE_KEY_RE = re.compile(r"authorization|token|password|secret|embedding|private_key", re.I)
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._\-]+")
# 16+ comma-separated floats inside brackets is an embedding being printed.
_VECTOR_RE = re.compile(r"\[(?:\s*-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\s*,){15,}[^\]]*\]")

_STANDARD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"request_id", "request_user", "request_route", "message", "asctime", "taskName"}


def _scrub_text(text: str) -> str:
    text = _BEARER_RE.sub("Bearer [redacted]", text)
    return _VECTOR_RE.sub("[vector]", text)


def _scrub_value(key: str, value: Any) -> Any:
    if _SENSITIVE_KEY_RE.search(key):
        if isinstance(value, (list, tuple)) and len(value) >= 16:
            return f"[vector:{len(value)}]"
        return "[redacted]"
    if isinstance(value, (list, tuple)) and len(value) >= 16 and all(
        isinstance(x, (int, float)) for x in value
    ):
        return f"[vector:{len(value)}]"
    if isinstance(value, str):
        return _scrub_text(value)
    return value


class _RedactionFilter(logging.Filter):
    """Runs BEFORE any formatter, on both sinks. What it removes never existed."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Both sinks run this filter on the SAME record object. Without the marker the
        # second pass re-scrubs the first pass's output - "[vector:256]" is a string whose
        # key still says "embedding", so it became "[redacted]" and the dimension was lost.
        if getattr(record, "_redacted", False):
            return True
        record._redacted = True
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a broken format string must not kill logging
            message = str(record.msg)
        record.msg = _scrub_text(message)
        record.args = None
        for key in list(record.__dict__):
            if key in _STANDARD_ATTRS or key.startswith("_"):
                continue
            record.__dict__[key] = _scrub_value(key, record.__dict__[key])
        return True


# ---------------------------------------------------------------- formatters

class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S")
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "user": getattr(record, "request_user", "-"),
            "route": getattr(record, "request_route", "-"),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRS or key.startswith("_") or key in payload:
                continue
            payload[key] = value
        if record.exc_info and record.exc_info != (None, None, None):
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


_CONSOLE_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"


class _LiveStderrHandler(logging.StreamHandler):
    """A stderr handler that resolves the stream AT EMIT TIME.

    A plain StreamHandler captures sys.stderr once, at construction. Under pytest that is
    a per-test capture object which is CLOSED when the test ends - the next emit through a
    stale handler raises, and Python's logging-error report then prints the CALLER'S SOURCE
    LINE, which is exactly how a redacted secret leaked back into the output during the
    redaction test. Resolving lazily makes the handler immune to stream replacement.
    """

    def __init__(self) -> None:
        super().__init__(stream=sys.stderr)

    @property
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, value):  # the base __init__ assigns; the live property stands
        pass


# ---------------------------------------------------------------- middleware

access_log = logging.getLogger("app.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign the correlation id, time the request, emit ONE access line.

    An inbound X-Request-ID is honoured (the desktop agent can correlate its sync calls
    across both machines' logs) and always echoed back - so whatever a user or the agent
    quotes is exactly what an engineer greps.
    """

    async def dispatch(self, request: Request, call_next):
        supplied = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = supplied if _REQUEST_ID_RE.match(supplied) else uuid.uuid4().hex[:12]
        # Deliberately NO reset in finally: Starlette's 500 handler (ServerErrorMiddleware)
        # runs OUTSIDE this middleware, and it must still read this id to put it in the
        # response body. Every request overwrites these on entry, so nothing leaks between
        # requests - the only "leak" is the window the outer handler needs.
        _request_id.set(request_id)
        _request_user.set("-")
        _request_route.set(f"{request.method} {request.url.path}")
        # The scope's state dict crosses task boundaries; contextvars do not. The outer 500
        # handler and this middleware's own access line both read from here.
        request.state.request_id = request_id
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            # The ROUTE TEMPLATE, not the raw path: one name per endpoint, so the access
            # log aggregates instead of scattering across every UUID.
            route = request.scope.get("route")
            template = getattr(route, "path", request.url.path)
            client = request.client.host if request.client else "-"
            # The endpoint ran in a CHILD task, so bind_user's contextvar write is not
            # visible here - but get_current_user also put the user on request.state,
            # and the scope crosses tasks.
            state_user = getattr(request.state, "user", None)
            username = getattr(state_user, "username", None) or _request_user.get()
            # Health polling would drown INFO; it is still there at DEBUG.
            level = logging.DEBUG if request.url.path == "/api/health" else logging.INFO
            access_log.log(
                level,
                "%s %s -> %d in %sms",
                request.method,
                template,
                status_code,
                duration_ms,
                extra={
                    "request_user": username,
                    "method": request.method,
                    "path_template": template,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "client_ip": client,
                },
            )


# ---------------------------------------------------------------- SQL timing

sql_log = logging.getLogger("app.sql")
_sql_listeners_installed = False
# Read at emit time so the admin config page can change these in a RUNNING server.
_runtime: dict[str, object] = {"slow_ms": 200, "log_levels": ""}


def _install_sql_timing(slow_ms: int) -> None:
    """One WARNING per slow statement. Parameters are NEVER logged - they are the data."""
    global _sql_listeners_installed
    _runtime["slow_ms"] = slow_ms
    if _sql_listeners_installed:
        return
    from sqlalchemy import event

    from app.db.session import engine

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("_query_start", []).append(time.perf_counter())

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        starts = conn.info.get("_query_start")
        if not starts:
            return
        duration_ms = (time.perf_counter() - starts.pop()) * 1000
        if duration_ms >= float(_runtime["slow_ms"]):  # live value, not install-time capture
            sql_log.warning(
                "slow query %.0fms: %s",
                duration_ms,
                " ".join(statement.split())[:300],
                extra={"duration_ms": round(duration_ms, 1)},
            )
        elif sql_log.isEnabledFor(logging.DEBUG):
            sql_log.debug(
                "query %.1fms: %s", duration_ms, " ".join(statement.split())[:200]
            )

    _sql_listeners_installed = True


# ---------------------------------------------------------------- setup

def setup_logging(settings) -> None:
    """Configure the root logger: console + optional JSON file, context + redaction.

    Idempotent: handlers are replaced, not stacked, so repeated app factories (tests)
    do not multiply output.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    context_filter = _ContextFilter()
    redaction_filter = _RedactionFilter()

    console = _LiveStderrHandler()
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT))

    handlers: list[logging.Handler] = [console]

    log_dir = settings.resolved_log_dir
    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_dir / "backend.jsonl",
                maxBytes=20 * 1024 * 1024,
                backupCount=10,
                encoding="utf-8",
            )
            file_handler.setFormatter(_JsonFormatter())
            handlers.append(file_handler)
        except OSError as exc:  # pragma: no cover - depends on the host filesystem
            # A missing volume must degrade to console-only, never kill the server.
            console.handle(
                logging.LogRecord(
                    "app.logging", logging.WARNING, __file__, 0,
                    f"file sink disabled ({exc}) - logging to stdout only", (), None,
                )
            )

    for handler in handlers:
        handler.addFilter(context_filter)
        handler.addFilter(redaction_filter)

    root.handlers = handlers

    # Our access line replaces uvicorn's unstructured duplicate.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    _apply_logger_overrides(settings.log_levels or "")
    _install_sql_timing(settings.slow_query_ms)


def _apply_logger_overrides(spec: str) -> None:
    """Apply "name=LEVEL,name=LEVEL"; loggers dropped from the spec return to inherited."""
    previous = str(_runtime.get("log_levels") or "")
    named_before = {p.partition("=")[0].strip() for p in previous.split(",") if "=" in p}
    named_now = set()
    for pair in spec.split(","):
        name, _, level = pair.strip().partition("=")
        if name and level:
            logging.getLogger(name).setLevel(getattr(logging, level.upper(), logging.INFO))
            named_now.add(name)
    for name in named_before - named_now:
        logging.getLogger(name).setLevel(logging.NOTSET)
    _runtime["log_levels"] = spec.strip()


def get_runtime_logging() -> dict:
    """What the running process is actually doing right now (the admin page reads this)."""
    return {
        "log_level": logging.getLevelName(logging.getLogger().level),
        "log_levels": str(_runtime.get("log_levels") or ""),
        "slow_query_ms": int(float(_runtime["slow_ms"])),
    }


def apply_runtime_logging(*, log_level: str | None = None, log_levels: str | None = None,
                          slow_query_ms: int | None = None) -> None:
    """Change the running process. Ephemeral by design: boot always reads the env again,
    so a bad interactive change is one restart away from undone."""
    if log_level is not None:
        logging.getLogger().setLevel(getattr(logging, log_level.upper(), logging.INFO))
    if log_levels is not None:
        _apply_logger_overrides(log_levels)
    if slow_query_ms is not None:
        _runtime["slow_ms"] = int(slow_query_ms)
