"""FastAPI dependencies: current user, role and permission checks, resource access."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.logging_setup import bind_user
from app.core.security import TokenError, decode_access_token
from app.db.session import get_db
from app.models import InvestigationSession, InvestigatorProfile, SessionInvestigator, User

_bearer = HTTPBearer(auto_error=False)

# Arabic user-facing messages are produced by the frontend from these codes.
ERR_UNAUTHENTICATED = "unauthenticated"
ERR_FORBIDDEN = "forbidden"
ERR_ACCOUNT_DISABLED = "account_disabled"


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=ERR_UNAUTHENTICATED)
    try:
        payload = decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=f"token_{exc}") from exc
    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=ERR_UNAUTHENTICATED) from exc
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=ERR_UNAUTHENTICATED)
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ERR_ACCOUNT_DISABLED)
    request.state.user = user
    # Every later log record of this request - services, SQL, matching - now carries the
    # username. One hook here covers every authenticated route.
    bind_user(user.username)
    return user


def require_permission(*codes: str) -> Callable[..., User]:
    """Dependency factory: the user must hold at least one of the listed permissions."""

    def _dep(user: User = Depends(get_current_user)) -> User:
        held = user.permission_codes
        if not any(code in held for code in codes):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ERR_FORBIDDEN)
        return user

    return _dep


def require_role(*roles: str) -> Callable[..., User]:
    def _dep(user: User = Depends(get_current_user)) -> User:
        if not any(r in user.role_names for r in roles):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail=ERR_FORBIDDEN)
        return user

    return _dep


def user_can_access_session(db: Session, user: User, session: InvestigationSession) -> bool:
    """Resource-level authorization for an investigation session."""
    perms = user.permission_codes
    if "investigations.read_all" in perms:
        return True
    if "investigations.read_assigned" not in perms:
        return False
    if session.created_by == user.id:
        return True
    profile_id = db.scalar(select(InvestigatorProfile.id).where(InvestigatorProfile.user_id == user.id))
    if profile_id is None:
        return False
    assigned = db.scalar(
        select(SessionInvestigator.id).where(
            SessionInvestigator.session_id == session.id,
            SessionInvestigator.investigator_id == profile_id,
        )
    )
    return assigned is not None


def get_accessible_session(
    session_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InvestigationSession:
    session = db.get(InvestigationSession, session_id)
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="session_not_found")
    if not user_can_access_session(db, user, session):
        # Do not reveal existence of sessions the user may not see.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="session_not_found")
    return session


def client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


def accessible_sessions_stmt(db: Session, user: User):
    """Sessions this user may see, as a SELECT to compose into other queries.

    Shared by the investigation list and by the voice endpoints: an investigator must never
    discover a person, a speaker or a session through the voice area that they could not see
    through the investigations area.
    """
    stmt = select(InvestigationSession)
    if "investigations.read_all" in user.permission_codes:
        return stmt
    profile_id = db.scalar(select(InvestigatorProfile.id).where(InvestigatorProfile.user_id == user.id))
    conditions = [InvestigationSession.created_by == user.id]
    if profile_id is not None:
        conditions.append(
            InvestigationSession.id.in_(
                select(SessionInvestigator.session_id).where(SessionInvestigator.investigator_id == profile_id)
            )
        )
    return stmt.where(or_(*conditions))
