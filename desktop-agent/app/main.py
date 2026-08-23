"""Local AI Agent entrypoint (FastAPI on 127.0.0.1 by default)."""

from __future__ import annotations

import ipaddress
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.ai.runtime import ModelRuntime
from app.api import health, jobs
from app.config import Settings, get_settings
from app.jobs.job_manager import JobManager
from app.jobs.store import JobStore
from app.security.token_validation import ProcessingTokenValidator, PublicKeyProvider
from app.sync.central_client import CentralClient

log = logging.getLogger("agent")


def assert_loopback_binding(settings: Settings) -> None:
    host = settings.bind_host
    try:
        is_loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = host in ("localhost",)
    if not is_loopback and not settings.allow_non_loopback_bind:
        raise SystemExit(
            f"Refusing to bind the Local AI Agent to {host}. The agent must listen on 127.0.0.1 "
            "unless an administrator sets AGENT_ALLOW_NON_LOOPBACK_BIND=true."
        )
    if not is_loopback:
        log.warning("Local AI Agent bound to non-loopback address %s (administrator override)", host)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        store = JobStore(settings.db_path)
        runtime = ModelRuntime(settings)
        client = CentralClient(settings)
        manager = JobManager(settings, store, runtime, client)
        app.state.settings = settings
        app.state.store = store
        app.state.runtime = runtime
        app.state.client = client
        app.state.manager = manager
        app.state.token_validator = ProcessingTokenValidator(settings, store, PublicKeyProvider(settings))
        manager.start()
        if settings.preload_models:
            runtime.load_in_background()
        log.info(
            "Local AI Agent %s ready on %s:%s (models: %s, data: %s)",
            __version__,
            settings.bind_host,
            settings.port,
            settings.model_dir,
            settings.data_dir,
        )
        try:
            yield
        finally:
            manager.stop()
            client.close()
            store.close()

    app = FastAPI(title="Military STT AI - Local AI Agent", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
        max_age=600,
    )

    @app.middleware("http")
    async def _private_network_access(request: Request, call_next):
        response = await call_next(request)
        # Chrome/Edge Private Network Access: a public/LAN page calling loopback
        # must receive this header on the preflight response.
        if request.method == "OPTIONS" and request.headers.get("access-control-request-private-network"):
            response.headers["Access-Control-Allow-Private-Network"] = "true"
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error: %s", exc)
        return JSONResponse(status_code=500, content={"detail": {"code": "agent_processing", "message": "internal error"}})

    app.include_router(health.router)
    app.include_router(jobs.router)
    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    assert_loopback_binding(settings)
    uvicorn.run("app.main:app", host=settings.bind_host, port=settings.port, log_level=settings.log_level.lower(), workers=1)


if __name__ == "__main__":
    main()
