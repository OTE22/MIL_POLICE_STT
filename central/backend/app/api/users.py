"""User administration + investigator directory."""

from __future__ import annotations

import uuid

from fastapi import Response, APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import client_ip, require_permission
from app.core.security import hash_password
from app.db.session import get_db
from app.models import AuditAction, InvestigatorProfile, Role, User
from app.schemas.auth import InvestigatorProfileOut
from app.schemas.users import (
    PasswordResetRequest,
    UserCreate,
    UserListOut,
    UserOut,
    UserStatusUpdate,
    UserUpdate,
)
from app.services.audit import record_audit

router = APIRouter(tags=["users"])


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        roles=user.role_names,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
        profile=user.profile,
    )


def _get_user_or_404(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user_not_found")
    return user


def _set_roles(db: Session, user: User, role_names: list[str]) -> None:
    roles = db.scalars(select(Role).where(Role.name.in_(role_names))).all()
    user.roles = list(roles)


@router.get("/users", response_model=UserListOut)
def list_users(
    q: str | None = Query(default=None, max_length=100),
    role: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    _: User = Depends(require_permission("users.read", "users.manage")),
    db: Session = Depends(get_db),
) -> UserListOut:
    stmt = select(User).outerjoin(InvestigatorProfile, InvestigatorProfile.user_id == User.id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                User.username.ilike(like),
                InvestigatorProfile.full_name.ilike(like),
                InvestigatorProfile.military_id.ilike(like),
            )
        )
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    if role:
        stmt = stmt.where(User.roles.any(Role.name == role.upper()))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    users = db.scalars(stmt.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return UserListOut(items=[_user_out(u) for u in users], total=total)


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreate,
    request: Request,
    admin: User = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
) -> UserOut:
    if db.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="username_taken")
    if body.profile.military_id and db.scalar(
        select(InvestigatorProfile.id).where(InvestigatorProfile.military_id == body.profile.military_id)
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="military_id_taken")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        is_active=True,
        must_change_password=body.must_change_password,
        created_by=admin.id,
    )
    _set_roles(db, user, body.roles)
    db.add(user)
    db.flush()
    profile = InvestigatorProfile(user_id=user.id, created_by=admin.id, **body.profile.model_dump())
    db.add(profile)
    db.flush()
    record_audit(
        db,
        action=AuditAction.USER_CREATED,
        user_id=admin.id,
        entity_type="user",
        entity_id=user.id,
        metadata={"username": user.username, "roles": body.roles},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(
    user_id: uuid.UUID,
    _: User = Depends(require_permission("users.read", "users.manage")),
    db: Session = Depends(get_db),
) -> UserOut:
    return _user_out(_get_user_or_404(db, user_id))


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    request: Request,
    admin: User = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
) -> UserOut:
    user = _get_user_or_404(db, user_id)
    changes: dict = {}
    if body.roles is not None and body.roles != user.role_names:
        if user.id == admin.id and "ADMIN" not in body.roles:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="cannot_remove_own_admin_role")
        changes["roles"] = {"from": user.role_names, "to": body.roles}
        _set_roles(db, user, body.roles)
        record_audit(
            db,
            action=AuditAction.ROLE_CHANGED,
            user_id=admin.id,
            entity_type="user",
            entity_id=user.id,
            metadata=changes["roles"],
            ip_address=client_ip(request),
        )
    if body.profile is not None:
        if body.profile.military_id:
            clash = db.scalar(
                select(InvestigatorProfile.id).where(
                    InvestigatorProfile.military_id == body.profile.military_id,
                    InvestigatorProfile.user_id != user.id,
                )
            )
            if clash:
                raise HTTPException(status.HTTP_409_CONFLICT, detail="military_id_taken")
        if user.profile is None:
            user.profile = InvestigatorProfile(user_id=user.id, created_by=admin.id, **body.profile.model_dump())
        else:
            for key, value in body.profile.model_dump().items():
                setattr(user.profile, key, value)
        changes["profile"] = list(body.profile.model_dump(exclude_none=True).keys())
    record_audit(
        db,
        action=AuditAction.USER_UPDATED,
        user_id=admin.id,
        entity_type="user",
        entity_id=user.id,
        metadata={"fields": list(changes.keys())},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.patch("/users/{user_id}/status", response_model=UserOut)
def set_user_status(
    user_id: uuid.UUID,
    body: UserStatusUpdate,
    request: Request,
    admin: User = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
) -> UserOut:
    user = _get_user_or_404(db, user_id)
    if user.id == admin.id and not body.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="cannot_disable_self")
    user.is_active = body.is_active
    record_audit(
        db,
        action=AuditAction.USER_ENABLED if body.is_active else AuditAction.USER_DISABLED,
        user_id=admin.id,
        entity_type="user",
        entity_id=user.id,
        metadata={"username": user.username},
        ip_address=client_ip(request),
    )
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.post("/users/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def reset_password(
    user_id: uuid.UUID,
    body: PasswordResetRequest,
    request: Request,
    admin: User = Depends(require_permission("users.manage")),
    db: Session = Depends(get_db),
) -> Response:
    user = _get_user_or_404(db, user_id)
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = body.must_change_password
    record_audit(
        db,
        action=AuditAction.PASSWORD_RESET,
        user_id=admin.id,
        entity_type="user",
        entity_id=user.id,
        metadata={"username": user.username, "by_admin": True},
        ip_address=client_ip(request),
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- investigators


@router.get("/investigators", response_model=list[InvestigatorProfileOut])
def list_investigators(
    q: str | None = Query(default=None, max_length=100),
    _: User = Depends(require_permission("investigators.read", "users.manage")),
    db: Session = Depends(get_db),
) -> list[InvestigatorProfileOut]:
    stmt = (
        select(InvestigatorProfile)
        .join(User, User.id == InvestigatorProfile.user_id)
        .where(User.is_active.is_(True), User.roles.any(Role.name.in_(["INVESTIGATOR", "ADMIN"])))
    )
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(InvestigatorProfile.full_name.ilike(like), InvestigatorProfile.military_id.ilike(like)))
    return list(db.scalars(stmt.order_by(InvestigatorProfile.full_name)).all())


@router.get("/investigators/{profile_id}", response_model=InvestigatorProfileOut)
def get_investigator(
    profile_id: uuid.UUID,
    _: User = Depends(require_permission("investigators.read", "users.manage")),
    db: Session = Depends(get_db),
) -> InvestigatorProfileOut:
    profile = db.get(InvestigatorProfile, profile_id)
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="investigator_not_found")
    return profile
