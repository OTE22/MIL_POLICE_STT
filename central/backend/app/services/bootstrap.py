"""Seed roles / permissions and the bootstrap administrator."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.permissions import PERMISSIONS, ROLE_ADMIN, ROLE_DESCRIPTIONS, ROLE_PERMISSIONS
from app.core.security import hash_password
from app.db.base import utcnow
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


def seed_development_report_template(db: Session) -> None:
    """Put a WORKING محضر template in place on a fresh install - marked as development.

    The organisation's approved .docx arrives later through the admin upload page. Until it
    does, this stand-in lets the composer, the renderer and the tests function, and it is
    flagged `is_development` so production refuses to issue an official report on it.
    """
    from app.models import ReportTemplateVersion, TemplateValidationStatus
    from app.services.report_dev_template import build_dev_template
    from app.services.report_renderer import validate_template
    from app.services.report_storage import atomic_write, template_relative_path

    if db.scalar(select(ReportTemplateVersion).limit(1)) is not None:
        return  # a template history already exists; never overwrite it

    data = build_dev_template()
    result = validate_template(data)
    if not result.ok:
        # Loud, but not fatal: the server still runs and an admin can upload a real one.
        log.error("bundled development report template failed validation: %s", result.message)
        return

    template = ReportTemplateVersion(
        version=1,
        storage_path="",
        sha256="",
        original_filename="development_investigation_report.docx",
        validation_status=TemplateValidationStatus.VALID,
        validation_message=result.message,
        is_development=True,
        is_active=True,
        activated_at=utcnow(),
        notes="نموذج تطويري غير معتمد - يُستبدل برفع القالب الرسمي",
    )
    db.add(template)
    db.flush()
    rel, size, digest = atomic_write(template_relative_path(template.id), data)
    template.storage_path, template.size_bytes, template.sha256 = rel, size, digest
    db.flush()
    log.warning(
        "Seeded the DEVELOPMENT report template (v1). Upload the approved .docx before "
        "issuing official reports - production will refuse to finalize on this one."
    )


def run_bootstrap(db: Session) -> None:
    seed_roles_and_permissions(db)
    seed_bootstrap_admin(db)
    try:
        seed_development_report_template(db)
    except Exception as exc:  # a template problem must never stop the server booting
        log.error("report template seeding skipped: %s", exc.__class__.__name__)
        db.rollback()
    db.commit()
