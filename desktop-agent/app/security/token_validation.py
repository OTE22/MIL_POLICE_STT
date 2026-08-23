"""Validation of central processing tokens (ES256, public key only).

The agent never holds the central private key. It verifies:
  * signature, issuer, audience, nbf/exp
  * allowed_action == process_recording
  * accept_by (short-lived acceptance window) has not passed
  * the nonce (jti) has never been used on this workstation (replay protection)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import jwt

from app.config import Settings
from app.jobs.store import JobStore

log = logging.getLogger(__name__)

ALLOWED_ACTION = "process_recording"


class TokenValidationError(Exception):
    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


@dataclass
class ProcessingClaims:
    job_id: str
    session_id: str
    recording_id: str
    user_id: str
    nonce: str
    session_number: str | None
    issued_at: datetime
    accept_by: datetime
    expires_at: datetime
    raw: str


class PublicKeyProvider:
    """Loads the central verification key from disk (optionally fetched once)."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._pem: str | None = None

    @property
    def path(self) -> Path:
        return self._settings.public_key_path

    def load(self) -> str:
        if self._pem:
            return self._pem
        if self.path.exists():
            self._pem = self.path.read_text(encoding="utf-8")
            return self._pem
        if self._settings.central_public_key_auto_fetch:
            self._pem = self._fetch_and_store()
            return self._pem
        raise TokenValidationError(
            "public_key_missing",
            f"central public key not installed at {self.path} (see docs/offline-provisioning.md)",
        )

    def _fetch_and_store(self) -> str:
        import httpx

        url = self._settings.central_url.rstrip("/") + "/api/local-processing/public-key"
        verify: bool | str = self._settings.central_verify_tls
        if self._settings.central_ca_bundle:
            verify = str(self._settings.central_ca_bundle)
        log.warning("Fetching central public key from %s (trust-on-first-use)", url)
        resp = httpx.get(url, timeout=15, verify=verify)
        resp.raise_for_status()
        pem = resp.json()["public_key_pem"]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(pem, encoding="utf-8")
        return pem


class ProcessingTokenValidator:
    def __init__(self, settings: Settings, store: JobStore, keys: PublicKeyProvider):
        self._settings = settings
        self._store = store
        self._keys = keys

    def validate(self, token: str, *, consume_nonce: bool = True) -> ProcessingClaims:
        if not token or len(token) > 8192:
            raise TokenValidationError("token_invalid")
        try:
            pem = self._keys.load()
        except TokenValidationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise TokenValidationError("public_key_missing", str(exc)) from exc
        try:
            claims = jwt.decode(
                token,
                pem,
                algorithms=["ES256"],
                audience=self._settings.token_audience,
                issuer=self._settings.token_issuer,
                leeway=self._settings.clock_skew_seconds,
                options={"require": ["exp", "iat", "jti", "aud", "iss"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenValidationError("token_expired") from exc
        except jwt.InvalidTokenError as exc:
            raise TokenValidationError("token_invalid", str(exc)) from exc

        if claims.get("allowed_action") != ALLOWED_ACTION:
            raise TokenValidationError("token_invalid", "unexpected allowed_action")
        now = datetime.now(timezone.utc)
        try:
            accept_by = datetime.fromtimestamp(int(claims["accept_by"]), tz=timezone.utc)
            issued_at = datetime.fromtimestamp(int(claims["iat"]), tz=timezone.utc)
            expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc)
            job_id = str(uuid.UUID(claims["job_id"]))
            session_id = str(uuid.UUID(claims["session_id"]))
            recording_id = str(uuid.UUID(claims["recording_id"]))
            user_id = str(uuid.UUID(claims["user_id"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise TokenValidationError("token_invalid", f"missing/invalid claim: {exc}") from exc
        if (now - accept_by).total_seconds() > self._settings.clock_skew_seconds:
            raise TokenValidationError("token_expired", "acceptance window has passed")
        nonce = str(claims["jti"])
        if consume_nonce and not self._store.consume_nonce(nonce, job_id, expires_at):
            raise TokenValidationError("token_replay", "token already used")
        return ProcessingClaims(
            job_id=job_id,
            session_id=session_id,
            recording_id=recording_id,
            user_id=user_id,
            nonce=nonce,
            session_number=claims.get("session_number"),
            issued_at=issued_at,
            accept_by=accept_by,
            expires_at=expires_at,
            raw=token,
        )
