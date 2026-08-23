"""Workstation registry and audit log access."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.processing import _upsert_workstation
from app.core.deps import client_ip, get_accessible_session, get_current_user, require_permission
from app.db.session import get_db
from app.models import AuditLog, User, Workstation, WorkstationStatus
from app.schemas.admin import AuditListOut, AuditLogOut, WorkstationOut
from app.schemas.processing import WorkstationInfo

router = APIRouter(tags=["admin"])

_OFFLINE_AFTER = timedelta(minutes=15)


def _ws_out(db: Session, ws: Workstation) -> WorkstationOut:
    status = ws.status
    if ws.last_seen_at and datetime.now(timezone.utc) - ws.last_seen_at > _OFFLINE_AFTER:
        status = WorkstationStatus.OFFLINE
    registered_by_name = None
    if ws.registered_by:
        user = db.get(User, ws.registered_by)
        if user:
            registered_by_name = user.profile.full_name if user.profile else user.username
    return WorkstationOut(
        id=ws.id,
        agent_id=ws.agent_id,
        device_name=ws.device_name,
        agent_version=ws.agent_version,
        stt_provider=ws.stt_provider,
        stt_model=ws.stt_model,
        stt_model_revision=ws.stt_model_revision,
        diarization_provider=ws.diarization_provider,
        diarization_model=ws.diarization_model,
        diarization_model_revision=ws.diarization_model_revision,
        processing_device=ws.processing_device,
        gpu_name=ws.gpu_name,
        status=status,
        last_seen_at=ws.last_seen_at,
        registered_by=ws.registered_by,
        registered_by_name=registered_by_name,
        created_at=ws.created_at,
    )


@router.get("/workstations", response_model=list[WorkstationOut])
def list_workstations(
    _: User = Depends(require_permission("workstations.read")), db: Session = Depends(get_db)
) -> list[WorkstationOut]:
    rows = db.scalars(select(Workstation).order_by(Workstation.last_seen_at.desc().nullslast())).all()
    return [_ws_out(db, w) for w in rows]


@router.post("/workstations/register", response_model=WorkstationOut)
def register_workstation(
    body: WorkstationInfo,
    user: User = Depends(require_permission("workstations.register")),
    db: Session = Depends(get_db),
) -> WorkstationOut:
    """Called by the frontend after reading the Local Agent capabilities."""
    ws = _upsert_workstation(db, body, user.id)
    db.commit()
    db.refresh(ws)
    return _ws_out(db, ws)


@router.get("/audit-logs", response_model=AuditListOut)
def list_audit_logs(
    action: str | None = Query(default=None, max_length=64),
    user_id: uuid.UUID | None = Query(default=None),
    entity_type: str | None = Query(default=None, max_length=64),
    entity_id: str | None = Query(default=None, max_length=64),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: User = Depends(require_permission("audit.read")),
    db: Session = Depends(get_db),
) -> AuditListOut:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action.upper())
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc))
    if date_to:
        stmt = stmt.where(AuditLog.created_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    usernames: dict[uuid.UUID, str] = {}
    for row in rows:
        if row.user_id and row.user_id not in usernames:
            u = db.get(User, row.user_id)
            usernames[row.user_id] = (u.profile.full_name if u and u.profile else (u.username if u else "?"))
    return AuditListOut(
        items=[
            AuditLogOut(
                id=r.id,
                user_id=r.user_id,
                username=usernames.get(r.user_id) if r.user_id else None,
                action=r.action,
                entity_type=r.entity_type,
                entity_id=r.entity_id,
                safe_metadata=r.safe_metadata,
                ip_address=r.ip_address,
                created_at=r.created_at,
            )
            for r in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/investigations/{session_id}/activity", response_model=AuditListOut)
def session_activity(
    request: Request,
    session=Depends(get_accessible_session),
    user: User = Depends(get_current_user),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> AuditListOut:
    """Activity history of one session (visible to anyone who can access the session)."""
    sid = str(session.id)
    stmt = select(AuditLog).where(
        (AuditLog.entity_id == sid) | (AuditLog.safe_metadata["session_id"].astext == sid)
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    names: dict[uuid.UUID, str] = {}
    items = []
    for r in rows:
        if r.user_id and r.user_id not in names:
            u = db.get(User, r.user_id)
            names[r.user_id] = u.profile.full_name if u and u.profile else (u.username if u else "?")
        items.append(
            AuditLogOut(
                id=r.id,
                user_id=r.user_id,
                username=names.get(r.user_id) if r.user_id else None,
                action=r.action,
                entity_type=r.entity_type,
                entity_id=r.entity_id,
                safe_metadata=r.safe_metadata,
                ip_address=None,
                created_at=r.created_at,
            )
        )
    _ = client_ip(request)
    return AuditListOut(items=items, total=total, page=page, page_size=page_size)
