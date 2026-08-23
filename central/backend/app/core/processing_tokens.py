"""Short-lived processing authorization tokens (ES256, asymmetric).

The central server signs with a private key that never leaves the server.
Every Local AI Agent only holds the public key and can verify that a job was
authorized centrally without being able to mint tokens itself.

Claims (no secrets, no passwords):

    iss, aud, sub (user id), jti (nonce), iat, exp,
    job_id, session_id, recording_id, user_id, session_number,
    allowed_action = "process_recording",
    accept_by  -> the Local Agent must accept the job before this instant
    exp        -> results / audio may be synchronized until this instant
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.config import get_settings

ALLOWED_ACTION = "process_recording"


class ProcessingTokenError(Exception):
    pass


def ensure_keypair(private_path: Path, public_path: Path) -> None:
    """Generate an ES256 (P-256) key pair on first start if none exists."""
    if private_path.exists() and public_path.exists():
        return
    private_path.parent.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    private_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    try:
        private_path.chmod(0o600)
    except OSError:
        pass


def load_private_key() -> str:
    settings = get_settings()
    ensure_keypair(settings.processing_token_private_key_path, settings.processing_token_public_key_path)
    return settings.processing_token_private_key_path.read_text()


def load_public_key() -> str:
    settings = get_settings()
    ensure_keypair(settings.processing_token_private_key_path, settings.processing_token_public_key_path)
    return settings.processing_token_public_key_path.read_text()


@dataclass
class IssuedProcessingToken:
    token: str
    nonce: str
    issued_at: datetime
    accept_by: datetime
    expires_at: datetime


def issue_processing_token(
    *,
    job_id: uuid.UUID,
    session_id: uuid.UUID,
    recording_id: uuid.UUID,
    user_id: uuid.UUID,
    session_number: str,
) -> IssuedProcessingToken:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    accept_by = now + timedelta(seconds=settings.processing_token_accept_ttl_seconds)
    expires_at = now + timedelta(seconds=settings.processing_token_submit_ttl_seconds)
    nonce = uuid.uuid4().hex
    payload = {
        "iss": settings.processing_token_issuer,
        "aud": settings.processing_token_audience,
        "sub": str(user_id),
        "jti": nonce,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()) - 30,
        "exp": int(expires_at.timestamp()),
        "accept_by": int(accept_by.timestamp()),
        "job_id": str(job_id),
        "session_id": str(session_id),
        "recording_id": str(recording_id),
        "user_id": str(user_id),
        "session_number": session_number,
        "allowed_action": ALLOWED_ACTION,
    }
    token = jwt.encode(payload, load_private_key(), algorithm="ES256", headers={"kid": "central-es256-v1"})
    return IssuedProcessingToken(
        token=token, nonce=nonce, issued_at=now, accept_by=accept_by, expires_at=expires_at
    )


def verify_processing_token(token: str) -> dict:
    """Verify a processing token with the public key (same code path the agent uses)."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            load_public_key(),
            algorithms=["ES256"],
            audience=settings.processing_token_audience,
            issuer=settings.processing_token_issuer,
            options={"require": ["exp", "iat", "jti", "aud", "iss"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise ProcessingTokenError("expired") from exc
    except jwt.InvalidTokenError as exc:
        raise ProcessingTokenError("invalid") from exc
    if payload.get("allowed_action") != ALLOWED_ACTION:
        raise ProcessingTokenError("invalid_action")
    return payload
