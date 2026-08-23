"""Authentication endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Response, APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import client_ip, get_current_user
from app.core.security import (
    create_access_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from app.db.session import get_db
from app.models import AuditAction, User
from app.schemas.auth import ChangePasswordRequest, CurrentUserOut, LoginRequest, TokenResponse
from app.services.audit import record_audit

router = APIRouter(prefix="/auth", tags=["auth"])

# Constant-time-ish dummy hash used when the username does not exist so that
# response timing does not reveal valid usernames.
_DUMMY_HASH = hash_password("dummy-password-for-timing-equalization")


def _serialize_user(user: User) -> CurrentUserOut:
    return CurrentUserOut(
        id=user.id,
        username=user.username,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        roles=user.role_names,
        permissions=sorted(user.permission_codes),
        last_login_at=user.last_login_at,
        profile=user.profile,
    )


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.username == body.username.lower()))
    ip = client_ip(request)
    if user is None:
        verify_password(body.password, _DUMMY_HASH)
        record_audit(db, action=AuditAction.LOGIN_FAILED, user_id=None, metadata={"username": body.username[:64]}, ip_address=ip)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")
    if not verify_password(body.password, user.password_hash):
        record_audit(db, action=AuditAction.LOGIN_FAILED, user_id=user.id, metadata={"username": user.username}, ip_address=ip)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")
    if not user.is_active:
        record_audit(db, action=AuditAction.LOGIN_FAILED, user_id=user.id, metadata={"reason": "disabled"}, ip_address=ip)
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="account_disabled")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.last_login_at = datetime.now(timezone.utc)
    token, expires_at = create_access_token(user.id, user.username)
    record_audit(db, action=AuditAction.LOGIN, user_id=user.id, entity_type="user", entity_id=user.id, ip_address=ip)
    db.commit()
    return TokenResponse(access_token=token, expires_at=expires_at)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def logout(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    record_audit(db, action=AuditAction.LOGOUT, user_id=user.id, entity_type="user", entity_id=user.id, ip_address=client_ip(request))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=CurrentUserOut)
def me(user: User = Depends(get_current_user)) -> CurrentUserOut:
    return _serialize_user(user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid_credentials")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    record_audit(db, action=AuditAction.PASSWORD_RESET, user_id=user.id, entity_type="user", entity_id=user.id, metadata={"self_service": True}, ip_address=client_ip(request))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
