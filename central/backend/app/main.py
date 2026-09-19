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
from app.api.investigations import ParticipantIdentityRequired
from app.services.person_identifiers import IdentifierAlreadyAssigned
from app.services.person_identity import PersonNameRequired, IdentityNameMismatch
from app.api import (
    admin,
    auth,
    investigations,
    llm_capabilities,
    processing,
    report_templates,
    reports,
    subject_documents,
    transcripts,
    users,
    voice,
)
from app.services.llm.hardware import get_hardware
from app.config import get_settings
from app.core.logging_setup import RequestContextMiddleware, current_request_id, setup_logging
from app.core.processing_tokens import ensure_keypair
from app.db.session import SessionLocal, engine
from app.services.bootstrap import run_bootstrap

setup_logging(get_settings())
log = logging.getLogger("central")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.recordings_dir.mkdir(parents=True, exist_ok=True)
    ensure_keypair(settings.processing_token_private_key_path, settings.processing_token_public_key_path)
    with SessionLocal() as db:
        run_bootstrap(db)
    # Detect CPU/GPU/RAM/runtime ONCE here and cache it, so no report request ever pays for
    # shelling out to nvidia-smi or probing a runtime. Never fatal: a machine with no local
    # model simply reports Fusha assistance as unavailable.
    try:
        get_hardware()
    except Exception as exc:  # detection must never stop the server from starting
        log.warning("hardware detection skipped: %s", exc.__class__.__name__)
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

    @app.exception_handler(IdentifierAlreadyAssigned)
    async def _identifier_assigned(_: Request, exc: IdentifierAlreadyAssigned) -> JSONResponse:
        """A passport / card number already belongs to a different canonical person.

        Never resolved by moving it: an identifier changing hands is either a typo or two
        records of one human, and only an operator can say which. The response names the
        person holding it so they can be reused - and nothing about the investigations that
        person appears in, which this caller may have no right to see.
        """
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "person_identifier_already_assigned",
                "identifier_type": exc.identifier_type,
                "identifier_value": exc.value,
                "held_by_name": exc.held_by.person_name if exc.held_by else None,
                "held_by_identity_id": str(exc.held_by.id) if exc.held_by else None,
            },
        )

    @app.exception_handler(ParticipantIdentityRequired)
    async def _participant_identity_required(_: Request, exc: ParticipantIdentityRequired) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "participant_identity_required"})

    @app.exception_handler(PersonNameRequired)
    async def _person_name_required(_: Request, exc: PersonNameRequired) -> JSONResponse:
        """A canonical identity was about to be created with no name.

        Handled globally for the same reason as the mismatch below: session save, speaker
        identification and enrolment all resolve identities, and a missing name must fail the
        same way from each of them. The alternative - substituting the reference - is what put
        a person called "CIV-00000019" in the registry.
        """
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": "person_name_required"},
        )

    @app.exception_handler(IdentityNameMismatch)
    async def _identity_conflict(_: Request, exc: IdentityNameMismatch) -> JSONResponse:
        """A reference number already belongs to someone else.

        Deterministic and identical from every path that resolves an identity (session save,
        speaker identification, enrolment), so the UI can always show the same review prompt
        with both names instead of each endpoint inventing its own error.
        """
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": "person_identity_name_mismatch",
                "identity_id": str(exc.identity.id),
                "existing_name": exc.existing_name,
                "submitted_name": exc.submitted_name,
            },
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # This handler runs OUTSIDE the context middleware's task, so the contextvar may
        # already read "-" here; request.state crosses tasks and holds the real id.
        request_id = getattr(request.state, "request_id", None) or current_request_id()
        log.exception("Unhandled error: %s", exc, extra={"request_id": request_id})
        # Never leak stack traces / internals to the client. The request id is the ONE
        # thing worth returning: what the user quotes is exactly what an engineer greps
        # in storage/logs/backend.jsonl to find the full traceback and every record of
        # this request.
        return JSONResponse(
            status_code=500,
            content={"detail": "internal_error", "request_id": request_id},
        )

    # Outermost of our middlewares (added last), so the request id exists before
    # anything else runs and the access line times the whole request.
    app.add_middleware(RequestContextMiddleware)

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
    app.include_router(subject_documents.router, prefix=api_prefix)
    app.include_router(voice.router, prefix=api_prefix)
    app.include_router(reports.router, prefix=api_prefix)
    app.include_router(report_templates.router, prefix=api_prefix)
    app.include_router(llm_capabilities.router, prefix=api_prefix)
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
