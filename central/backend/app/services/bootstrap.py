"""Seed roles / permissions and the bootstrap administrator."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.permissions import PERMISSIONS, ROLE_ADMIN, ROLE_DESCRIPTIONS, ROLE_PERMISSIONS
from app.core.security import hash_password
from app.models import InvestigatorProfile, Permission, Role, User

log = logging.getLogger(__name__)


def seed_roles_and_permissions(db: Session) -> None:
    existing_perms = {p.code: p for p in db.scalars(select(Permission)).all()}
    for code, description in PERMISSIONS.items():
        if code not in existing_perms:
            perm = Permission(code=code, description=description)
            db.add(perm)
            existing_perms[code] = perm
    db.flush()

    existing_roles = {r.name: r for r in db.scalars(select(Role)).all()}
    for role_name, codes in ROLE_PERMISSIONS.items():
        role = existing_roles.get(role_name)
        if role is None:
            role = Role(name=role_name, description=ROLE_DESCRIPTIONS.get(role_name))
            db.add(role)
            existing_roles[role_name] = role
        wanted = {existing_perms[c] for c in codes}
        current = set(role.permissions)
        for perm in wanted - current:
            role.permissions.append(perm)
    db.flush()


def seed_bootstrap_admin(db: Session) -> None:
    settings = get_settings()
    if db.scalar(select(User.id).limit(1)) is not None:
        return
    admin_role = db.scalar(select(Role).where(Role.name == ROLE_ADMIN))
    user = User(
        username=settings.bootstrap_admin_username,
        password_hash=hash_password(settings.bootstrap_admin_password),
        is_active=True,
        must_change_password=True,
    )
    user.roles.append(admin_role)
    db.add(user)
    db.flush()
    db.add(InvestigatorProfile(user_id=user.id, full_name=settings.bootstrap_admin_full_name, created_by=user.id))
    log.warning("Bootstrap administrator '%s' created - change the password immediately.", user.username)


def run_bootstrap(db: Session) -> None:
    seed_roles_and_permissions(db)
    seed_bootstrap_admin(db)
    db.commit()
