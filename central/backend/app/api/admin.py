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


# ---------------------------------------------------------------------------
# Runtime configuration (the إعدادات النظام page)
# ---------------------------------------------------------------------------
#
# A WHITELIST, not a reflection of Settings: secrets (JWT, DB URL, key paths) and
# boot-structural values (storage root, CORS) must never reach a browser or change under a
# running server. Only settings that take effect immediately are listed - every one below is
# read per-request via get_settings() or applied through the logging runtime, so a change
# here changes the very next request. Changes are EPHEMERAL by design: boot always re-reads
# the environment, so a bad interactive change is one restart away from undone - and the
# page says so.
#
# Changes are recorded by the logging system itself (logger "app.admin", which carries the
# admin's username and request id via the context filter) - old value, new value, who, when.

import logging as _logging

from app.config import get_settings as _get_settings
from app.core.logging_setup import apply_runtime_logging, get_runtime_logging
from app.schemas.admin import ConfigFieldOut, ConfigOut, ConfigUpdateIn

_admin_log = _logging.getLogger("app.admin")

_LOG_LEVEL_OPTIONS = ["DEBUG", "INFO", "WARNING", "ERROR"]

# key -> (group, label, description, type, min, max, options)
_CONFIG_REGISTRY: dict[str, dict] = {
    "log_level": {
        "group": "السجلّات",
        "label": "مستوى السجلّ العام",
        "description": "DEBUG يُظهر كل شيء (بما فيه فحوص الصحة)؛ INFO هو المعتاد للتشغيل.",
        "type": "select", "options": _LOG_LEVEL_OPTIONS,
    },
    "log_levels": {
        "group": "السجلّات",
        "label": "مستويات لسجلّات محددة",
        "description": "مثال: app.services.voice_matching=DEBUG,sqlalchemy.engine=WARNING — لرفع تفصيل نظامٍ واحد دون إغراق الباقي.",
        "type": "text",
    },
    "slow_query_ms": {
        "group": "السجلّات",
        "label": "عتبة الاستعلام البطيء (مللي ثانية)",
        "description": "كل استعلام أبطأ من هذا يُسجَّل تحذيراً (النص مختصر، والقيم لا تُسجَّل أبداً).",
        "type": "int", "min": 10, "max": 60000,
    },
    "voice_match_threshold": {
        "group": "المطابقة الصوتية",
        "label": "عتبة اقتراح الهوية",
        "description": "أقل تشابه يُنتج اقتراحاً. مُعايَرة على 0.65 (نفس المتحدث 0.76–0.90، مختلفان 0.34–0.52) — خفضها يزيد الاقتراحات الخاطئة.",
        "type": "float", "min": 0.50, "max": 0.95,
    },
    "voice_match_margin": {
        "group": "المطابقة الصوتية",
        "label": "هامش الغموض بين شخصين",
        "description": "إذا تقارب أفضل شخصين أكثر من هذا، يمتنع النظام عن الاقتراح بدل أن يخمّن.",
        "type": "float", "min": 0.0, "max": 0.30,
    },
    "access_token_expire_minutes": {
        "group": "الجلسات والرموز",
        "label": "مدة صلاحية جلسة الدخول (دقائق)",
        "description": "تسري على تسجيلات الدخول الجديدة فقط؛ الجلسات القائمة تُكمل مدتها.",
        "type": "int", "min": 15, "max": 1440,
    },
    "processing_token_accept_ttl_seconds": {
        "group": "الجلسات والرموز",
        "label": "مهلة قبول تصريح المعالجة (ثوانٍ)",
        "description": "المدة بين إصدار التصريح وقبول الوكيل للمهمة على المحطة.",
        "type": "int", "min": 60, "max": 3600,
    },
    "processing_token_submit_ttl_seconds": {
        "group": "الجلسات والرموز",
        "label": "مهلة إرسال النتائج (دقائق)",
        "description": "المدة التي يظل فيها للوكيل حق مزامنة نتيجة المهمة وصوتها. 1440 دقيقة = يوم كامل.",
        # Edited in MINUTES for humans; stored canonically in seconds (the .env value and
        # every consumer stay in seconds). Bounds are in the DISPLAYED unit.
        "type": "int", "min": 60, "max": 10080, "scale": 60,
    },
    "max_upload_bytes": {
        "group": "الرفع",
        "label": "الحد الأقصى لحجم الملف الصوتي (ميغابايت)",
        "description": "يُطبَّق عند التحقق من كل رفع. 2048 ميغابايت = 2 غيغابايت.",
        # Edited in MB; stored canonically in bytes. Bounds are in the DISPLAYED unit.
        "type": "int", "min": 1, "max": 8192, "scale": 1_048_576,
    },
}

_LOGGING_KEYS = {"log_level", "log_levels", "slow_query_ms"}


def _canonical_value(key: str):
    if key in _LOGGING_KEYS:
        return get_runtime_logging()[key]
    return getattr(_get_settings(), key)


def _current_value(key: str):
    """What the page shows: the canonical value divided into its display unit."""
    value = _canonical_value(key)
    scale = _CONFIG_REGISTRY[key].get("scale", 1)
    return round(value / scale) if scale != 1 else value


def _config_out() -> ConfigOut:
    fields = []
    for key, spec in _CONFIG_REGISTRY.items():
        fields.append(
            ConfigFieldOut(
                key=key, group=spec["group"], label=spec["label"],
                description=spec["description"], type=spec["type"],
                value=_current_value(key),
                min=spec.get("min"), max=spec.get("max"), options=spec.get("options"),
            )
        )
    return ConfigOut(fields=fields)


def _validate(key: str, raw):
    from fastapi import HTTPException, status as _status

    spec = _CONFIG_REGISTRY.get(key)
    if spec is None:
        raise HTTPException(_status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={"code": "unknown_config_key", "key": key})
    try:
        if spec["type"] == "int":
            value = int(raw)
        elif spec["type"] == "float":
            value = float(raw)
        else:
            value = str(raw).strip()
    except (TypeError, ValueError):
        raise HTTPException(_status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={"code": "invalid_config_value", "key": key}) from None
    if spec["type"] in ("int", "float"):
        lo, hi = spec.get("min"), spec.get("max")
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            raise HTTPException(_status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail={"code": "config_value_out_of_bounds", "key": key,
                                        "min": lo, "max": hi})
    if spec["type"] == "select" and value not in (spec.get("options") or []):
        raise HTTPException(_status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={"code": "invalid_config_value", "key": key})
    # Bounds were checked in the DISPLAYED unit; what gets stored is canonical.
    scale = spec.get("scale", 1)
    return value * scale if scale != 1 else value


@router.get("/admin/config", response_model=ConfigOut)
def get_runtime_config(
    _: User = Depends(require_permission("system.configure")),
) -> ConfigOut:
    return _config_out()


@router.put("/admin/config", response_model=ConfigOut)
def update_runtime_config(
    body: ConfigUpdateIn,
    user: User = Depends(require_permission("system.configure")),
) -> ConfigOut:
    # Validate EVERYTHING before applying ANYTHING: a request with one bad key must not
    # half-apply the rest.
    validated = {key: _validate(key, raw) for key, raw in body.values.items()}

    settings = _get_settings()
    for key, value in validated.items():
        old = _canonical_value(key)
        if old == value:
            continue
        if key in _LOGGING_KEYS:
            apply_runtime_logging(**{key: value})
        else:
            setattr(settings, key, value)
        # The logging system records its own reconfiguration - the context filter stamps
        # the admin's username and the request id onto this line.
        _admin_log.info("config changed %s: %s -> %s", key, old, value)
    return _config_out()
