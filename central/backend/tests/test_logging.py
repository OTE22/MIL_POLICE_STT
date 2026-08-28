"""Central logging: correlation, redaction, the JSON sink, and SQL timing.

The observation channel for most assertions is the real file sink pointed at a tmp
directory - the same pipeline production uses, filters and all. A bare capture handler
would bypass the handler-level filters and test nothing.
"""

import json
import logging
import logging.handlers
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings, get_settings
from app.core.logging_setup import REQUEST_ID_HEADER, setup_logging
from app.db.session import engine
from app.main import app

from conftest import ADMIN, auth


@pytest.fixture()
def log_file(tmp_path: Path):
    """Route the real JSON sink into tmp for one test, then restore the suite default."""
    setup_logging(Settings(log_dir=str(tmp_path)))
    try:
        yield tmp_path / "backend.jsonl"
    finally:
        setup_logging(get_settings())


def _lines(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------


def test_every_response_carries_a_request_id(client):
    res = client.get("/api/health")
    assert REQUEST_ID_HEADER in res.headers
    assert len(res.headers[REQUEST_ID_HEADER]) >= 8


def test_an_inbound_request_id_is_honoured_and_echoed(client):
    res = client.get("/api/health", headers={REQUEST_ID_HEADER: "agent-sync-12345"})
    assert res.headers[REQUEST_ID_HEADER] == "agent-sync-12345"


def test_a_malformed_inbound_id_is_replaced_not_trusted(client):
    """The id ends up in log files - caller-controlled bytes do not."""
    res = client.get("/api/health", headers={REQUEST_ID_HEADER: "bad id \n injection"})
    echoed = res.headers[REQUEST_ID_HEADER]
    assert echoed != "bad id \n injection"
    assert len(echoed) == 12


def test_a_500_returns_the_request_id_and_the_file_holds_the_traceback(client, log_file):
    # A throwaway failing route, exercised through the real middleware + handler stack.
    if not any(getattr(r, "path", "") == "/api/_test_boom" for r in app.router.routes):

        @app.get("/api/_test_boom")
        def _boom():
            raise RuntimeError("deliberate-test-explosion")

    with TestClient(app, raise_server_exceptions=False) as crash_client:
        res = crash_client.get("/api/_test_boom", headers={REQUEST_ID_HEADER: "boom-trace-1"})
    assert res.status_code == 500
    body = res.json()
    assert body["detail"] == "internal_error"
    assert body["request_id"] == "boom-trace-1"

    records = _lines(log_file)
    tracebacks = [r for r in records if r.get("request_id") == "boom-trace-1" and "exception" in r]
    assert tracebacks, "the traceback must be findable by the id the user quotes"
    assert "deliberate-test-explosion" in tracebacks[0]["exception"]


def test_records_emitted_inside_a_request_carry_its_id_and_user(client, log_file):
    """The filter works app-wide: a service's own log line joins the request's story."""
    if not any(getattr(r, "path", "") == "/api/_test_log" for r in app.router.routes):
        from fastapi import Depends

        from app.core.deps import get_current_user

        # Authenticated on purpose: the user only lands in the log context when the
        # request actually passes through get_current_user.
        @app.get("/api/_test_log")
        def _emit(user=Depends(get_current_user)):
            logging.getLogger("app.services.somewhere").info("inside-service-marker")
            return {"ok": True}

    login = client.post("/api/auth/login", json=ADMIN).json()
    res = client.get(
        "/api/_test_log",
        headers={**auth(login["access_token"]), REQUEST_ID_HEADER: "svc-corr-1"},
    )
    assert res.status_code == 200

    inside = [r for r in _lines(log_file) if r["message"] == "inside-service-marker"]
    assert inside and inside[0]["request_id"] == "svc-corr-1"

    access = [
        r
        for r in _lines(log_file)
        if r.get("path_template") == "/api/_test_log" and r.get("request_id") == "svc-corr-1"
    ]
    assert access, "one access line per request"
    assert access[0]["user"] == "admin", "get_current_user must bind the username"
    assert access[0]["status_code"] == 200
    assert access[0]["duration_ms"] >= 0


def test_the_access_line_uses_the_route_template_not_raw_ids(client, log_file):
    login = client.post("/api/auth/login", json=ADMIN).json()
    session_id = uuid.uuid4()
    client.get(f"/api/investigations/{session_id}", headers=auth(login["access_token"]))
    paths = {r.get("path_template") for r in _lines(log_file) if "path_template" in r}
    assert "/api/investigations/{session_id}" in paths
    assert not any(str(session_id) in (p or "") for p in paths), "raw UUIDs must not name endpoints"


def test_health_polling_stays_out_of_info(client, log_file):
    client.get("/api/health")
    assert not any(
        r.get("path_template") == "/api/health" for r in _lines(log_file)
    ), "health checks would drown INFO; they log at DEBUG only"


# ---------------------------------------------------------------------------
# Redaction - enforced in the pipeline, on the real sink
# ---------------------------------------------------------------------------


def test_bearer_tokens_and_embeddings_cannot_reach_the_file(log_file):
    logger = logging.getLogger("app.redaction_probe")
    logger.info("auth used Bearer abc.def.ghi for the call")
    logger.info("vector was [" + ", ".join("0.123" for _ in range(32)) + "]")
    logger.info(
        "structured",
        extra={
            "password": "hunter2",
            "processing_token": "eyJhbGciOi...",
            "embedding": [0.1] * 256,
        },
    )
    records = _lines(log_file)
    text_dump = json.dumps(records)
    assert "abc.def.ghi" not in text_dump
    assert "hunter2" not in text_dump
    assert "eyJhbGciOi" not in text_dump
    assert "Bearer [redacted]" in text_dump
    assert "[vector]" in text_dump or "[vector:32]" in text_dump
    structured = next(r for r in records if r["message"] == "structured")
    assert structured["password"] == "[redacted]"
    assert structured["embedding"] == "[vector:256]"


def test_the_console_sink_is_redacted_too(capsys, log_file):
    logging.getLogger("app.redaction_probe").info("console Bearer secret.token.here end")
    captured = capsys.readouterr()
    stream = captured.err + captured.out
    assert "secret.token.here" not in stream
    assert "Bearer [redacted]" in stream


# ---------------------------------------------------------------------------
# SQL timing
# ---------------------------------------------------------------------------


def test_slow_queries_warn_without_their_parameters(log_file):
    with engine.connect() as conn:
        conn.execute(
            text("SELECT pg_sleep(0.3), :marker AS m"), {"marker": "PARAM-MUST-NOT-APPEAR"}
        )
        conn.execute(text("SELECT 1"))
    records = _lines(log_file)
    slow = [r for r in records if r["logger"] == "app.sql" and "pg_sleep" in r["message"]]
    assert slow, "a 300ms statement must produce a slow-query warning at the 200ms threshold"
    assert slow[0]["level"] == "WARNING"
    dump = json.dumps(records)
    assert "PARAM-MUST-NOT-APPEAR" not in dump, "parameters are the data; never logged"
    assert not any(
        r["logger"] == "app.sql" and r["message"].startswith("query ") for r in records
    ), "fast queries stay silent below DEBUG"


# ---------------------------------------------------------------------------
# Sinks and hygiene
# ---------------------------------------------------------------------------


def test_every_file_line_is_valid_json_and_uvicorn_access_is_silenced(client, log_file):
    client.get("/api/health")
    logging.getLogger("app.jsoncheck").info("عربي unicode {} \" quotes")
    for line in log_file.read_text(encoding="utf-8").splitlines():
        json.loads(line)  # raises if any line is not standalone JSON
    assert logging.getLogger("uvicorn.access").level == logging.WARNING


def test_an_empty_log_dir_disables_the_file_sink(tmp_path):
    setup_logging(Settings(log_dir=""))
    try:
        logging.getLogger("app.nosink").info("goes to console only")
        root = logging.getLogger()
        assert not any(
            isinstance(h, logging.handlers.RotatingFileHandler) for h in root.handlers
        )
    finally:
        setup_logging(get_settings())
