"""FastAPI application factory for the central server."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.api import admin, auth, investigations, processing, subject_documents, transcripts, users
from app.config import get_settings
from app.core.processing_tokens import ensure_keypair
from app.db.session import SessionLocal, engine
from app.services.bootstrap import run_bootstrap

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("central")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.recordings_dir.mkdir(parents=True, exist_ok=True)
    ensure_keypair(settings.processing_token_private_key_path, settings.processing_token_public_key_path)
    with SessionLocal() as db:
        run_bootstrap(db)
    log.info("Central server %s ready (%s)", __version__, settings.environment)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url="/api/docs" if settings.debug else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": "validation_error",
                "errors": [
                    {"loc": [str(x) for x in e.get("loc", [])], "msg": str(e.get("msg", "")), "type": str(e.get("type", ""))}
                    for e in exc.errors()
                ],
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error: %s", exc)
        # Never leak stack traces / internals to the client.
        return JSONResponse(status_code=500, content={"detail": "internal_error"})

    @app.middleware("http")
    async def _security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    api_prefix = "/api"
    app.include_router(auth.router, prefix=api_prefix)
    app.include_router(users.router, prefix=api_prefix)
    app.include_router(investigations.router, prefix=api_prefix)
    app.include_router(processing.router, prefix=api_prefix)
    app.include_router(subject_documents.router, prefix=api_prefix)
    app.include_router(transcripts.router, prefix=api_prefix)
    app.include_router(admin.router, prefix=api_prefix)

    @app.get("/api/health", tags=["health"])
    def health() -> dict:
        db_ok = True
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            db_ok = False
        return {"status": "ok" if db_ok else "degraded", "version": __version__, "database": db_ok}

    return app


app = create_app()
