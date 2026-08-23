"""Audit log writer. Metadata is whitelisted: never pass secrets here."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditAction, AuditLog

_FORBIDDEN_KEYS = {"password", "password_hash", "token", "access_token", "secret", "private_key", "authorization"}


def _sanitize(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not metadata:
        return None
    clean: dict[str, Any] = {}
    for key, value in metadata.items():
        if any(bad in key.lower() for bad in _FORBIDDEN_KEYS):
            continue
        if isinstance(value, uuid.UUID):
            value = str(value)
        elif isinstance(value, (list, tuple)):
            value = [str(v) if isinstance(v, uuid.UUID) else v for v in value]
        elif hasattr(value, "value") and not isinstance(value, (str, int, float, bool)):
            value = getattr(value, "value")
        clean[key] = value
    return clean


def record_audit(
    db: Session,
    *,
    action: AuditAction | str,
    user_id: uuid.UUID | None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | str | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        action=action.value if isinstance(action, AuditAction) else str(action),
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        safe_metadata=_sanitize(metadata),
        ip_address=ip_address,
    )
    db.add(entry)
    return entry
