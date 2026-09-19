"""One-off workspace refactor; run locally, never part of application startup."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
def edit(path, fn):
    p = ROOT / path
    p.write_text(fn(p.read_text(encoding='utf-8')), encoding='utf-8')

base = 'central/backend/app/'
# Database models and API contracts no longer carry business reference fields.
for path in ['models/person_identity.py', 'models/investigator.py', 'models/investigation.py',
             'models/transcript.py', 'models/voice.py', 'schemas/auth.py', 'schemas/investigations.py',
             'schemas/transcripts.py', 'schemas/voice.py']:
    edit(base + path, lambda s: re.sub(r'^    (?:reference_normalized|reference_display|reference_number|person_reference|enrolled_person_reference|identity_reference):.*\n', '', s, flags=re.M))
edit(base+'schemas/investigations.py', lambda s: s.replace('    participant_key: uuid.UUID | None = None', '    participant_key: uuid.UUID | None = None\n    identity_id: uuid.UUID | None = None').replace('    participant_key: uuid.UUID\n', '    participant_key: uuid.UUID\n    identity_id: uuid.UUID | None = None\n').replace(' or self.reference_number', ''))
edit(base+'schemas/transcripts.py', lambda s: s.replace('class SpeakerUpdateIn(BaseModel):', 'class SpeakerUpdateIn(BaseModel):\n    identity_id: uuid.UUID | None = None'))
edit(base+'schemas/investigations.py', lambda s: s.replace('class InvestigatorBrief(BaseModel):', 'class InvestigatorBrief(BaseModel):\n    identity_id: uuid.UUID | None = None'))

def identity_service(s):
    normalize = s[s.index('def normalize_reference'):s.index('def resolve_identity')].replace('normalize_reference', 'normalize_identifier')
    resolve = s[s.index('def resolve_identity'):s.index('def find_identity')]
    merge = s[s.index('class IdentityMergeConflict'):s.index('# ---------------------------------------------------------------------------')]
    repoint = s[s.index('def repoint_identity'):]
    repoint = re.sub(r'^        (?:subject|speaker)\.reference_number.*\n', '', repoint, flags=re.M)
    repoint = repoint.replace('from app.models import SessionSpeaker, Subject, VoiceEnrollment', 'from app.models import InvestigatorProfile, SessionSpeaker, Subject, VoiceEnrollment')
    repoint = repoint.replace('    db.flush()\n    return {', '    for profile in db.scalars(select(InvestigatorProfile).where(InvestigatorProfile.identity_id == source_id)):\n        profile.identity_id = target.id\n\n    db.flush()\n    return {')
    return '''"""Stable person UUIDs, explicit identity selection, and merge resolution."""
from __future__ import annotations
import unicodedata
import uuid
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import PersonIdentity

_ARABIC_DIGITS = {ord("٠") + i: str(i) for i in range(10)}
_ARABIC_DIGITS.update({ord("۰") + i: str(i) for i in range(10)})
MAX_ALIAS_HOPS = 16

class PersonNameRequired(Exception):
    pass

class IdentityNameMismatch(Exception):
    def __init__(self, identity, submitted_name):
        self.identity = identity
        self.existing_name = identity.person_name
        self.submitted_name = submitted_name

''' + normalize + resolve + '''def create_identity(db: Session, person_name: str) -> PersonIdentity:
    name = (person_name or "").strip()
    if not name:
        raise PersonNameRequired()
    identity = PersonIdentity(person_name=name)
    db.add(identity)
    db.flush()
    return identity

def identity_for_person(db: Session, person, *, identity_id=None, check_name=True) -> PersonIdentity:
    """Reuse an explicit UUID or scoped service number; never resolve by name."""
    from fastapi import HTTPException
    from app.services.person_identifiers import attach_identifier, find_by_identifier
    name = (getattr(person, "subject_name", None) or getattr(person, "full_name", None) or "").strip()
    branch = getattr(person, "security_branch", None)
    branch = getattr(branch, "value", branch)
    serial = (getattr(person, "military_id", None) or "").strip()
    scoped = bool(serial and branch and branch != "OTHER")
    # Serialize claims on a service number, including when the identifier is not yet present.
    # The transaction-scoped lock closes the select/insert race without merging by name.
    if scoped:
        from sqlalchemy import text
        key = f"MILITARY:{branch}:{normalize_identifier(serial)}"
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})
    identity = resolve_identity(db, db.get(PersonIdentity, identity_id)) if identity_id else None
    if identity_id and identity is None:
        raise HTTPException(404, detail="identity_not_found")
    if identity is None and scoped:
        identity = find_by_identifier(db, identifier_type="MILITARY", issuer=branch, value=serial)
        if identity and check_name and identity.person_name.strip() != name:
            raise IdentityNameMismatch(identity, name)
    if identity is None:
        identity = create_identity(db, name)
    if scoped:
        attach_identifier(db, identity=identity, identifier_type="MILITARY", issuer=branch, value=serial)
    return identity

class InvestigatorProfileIncomplete(Exception):
    def __init__(self, missing):
        self.missing = missing

def ensure_investigator_identity(db: Session, profile) -> PersonIdentity:
    if not (profile.full_name or "").strip():
        raise InvestigatorProfileIncomplete(["full_name"])
    identity = identity_for_person(db, profile, identity_id=profile.identity_id, check_name=not profile.identity_id)
    profile.identity_id = identity.id
    return identity

''' + merge + repoint
edit(base+'services/person_identity.py', identity_service)
edit(base+'services/person_identifiers.py', lambda s: s.replace('normalize_reference', 'normalize_identifier').replace('{"PASSPORT", "RESIDENCY"}', '{"PASSPORT", "RESIDENCY", "MILITARY"}').replace('metadata={"person_reference": identity.reference_display, **metadata}', 'metadata={"identity_id": str(identity.id), **metadata}'))

def investigations(s):
    s = s.replace('    ReferenceNameMismatch,\n', '').replace('    get_or_create_identity,\n    normalize_reference,', '    identity_for_person,')
    s = s.replace('reference_number=p.reference_number,', 'identity_id=p.identity_id,').replace('    "reference_number",\n', '')
    start = s.index('# References WE issue')
    end = s.index('def _apply_subjects(')
    s = s[:start] + '''class ParticipantIdentityRequired(Exception):
    """An existing participant was lost without an explicit removal."""

def _reconcile_participants(session, items, removed_keys):
    known = {sub.participant_key for sub in session.subjects}
    submitted = [i.participant_key for i in items if i.participant_key is not None]
    if not set(submitted) <= known or not removed_keys <= known:
        raise HTTPException(400, detail="unknown_participant_key")
    if len(submitted) != len(set(submitted)):
        raise HTTPException(400, detail="duplicate_participant_key")
    if removed_keys & set(submitted):
        raise HTTPException(400, detail="conflicting_participant_removal")
    if known - set(submitted) - removed_keys:
        raise ParticipantIdentityRequired()


''' + s[end:]
    s = s.replace('    from app.services.person_identity import find_identity\n', '')
    s = s.replace('    resolved_references = _resolve_references(db, session, items, user, removed_keys or set())', '    _reconcile_participants(session, items, removed_keys or set())')
    start = s.index('        reference = resolved_references[id(item)]')
    end = s.index('        for doc_in in item.documents:', start)
    s = s[:start] + '''        # A participant retains its person through edits, even if identifying details change.
        # Replacing that person requires an explicit remove/add operation.
        previous_id = carried.identity_id if carried else None
        if previous_id and item.identity_id:
            previous = resolve_identity(db, db.get(PersonIdentity, previous_id))
            proposed = resolve_identity(db, db.get(PersonIdentity, item.identity_id))
            if proposed is None or previous is None or previous.id != proposed.id:
                raise HTTPException(409, detail="participant_identity_change_not_permitted")
        identity = identity_for_person(db, item, identity_id=previous_id or item.identity_id,
                                       check_name=not bool(previous_id))
        subject.identity_id = identity.id
        attach_from_documents(db, identity=identity, documents=item.documents, user_id=user.id)
''' + s[end:]
    s = s.replace('        participant_key=subject.participant_key,', '        participant_key=subject.participant_key,\n        identity_id=subject.identity_id,')
    s = s.replace('fallback_name: str | None, fallback_ref: str | None', 'fallback_name: str | None')
    s = s.replace('return identity.id, identity.person_name, identity.reference_display', 'return identity.id, identity.person_name')
    s = s.replace('return None, (fallback_name or "").strip() or None, fallback_ref', 'return None, (fallback_name or "").strip() or None')
    s = s.replace('ident_id, name, ref = canonical(sub.identity_id, sub.subject_name, sub.reference_number)', 'ident_id, name = canonical(sub.identity_id, sub.subject_name)')
    s = s.replace('ident_id, name, ref = canonical(p.identity_id, p.full_name, p.reference_number)', 'ident_id, name = canonical(p.identity_id, p.full_name)')
    s = s.replace('                reference_number=ref,\n', '').replace('bool(ref)', 'bool(ident_id)').replace('None if ref else "no_reference"', 'None if ident_id else "no_identity"').replace('None if ref else "profile_incomplete"', 'None if ident_id else "profile_incomplete"')
    return s
edit(base+'api/investigations.py', investigations)

def transcripts(s):
    s = s.replace('from app.services.person_identity import find_identity, get_or_create_identity, normalize_reference', 'from app.services.person_identity import resolve_identity\nfrom app.models import PersonIdentity')
    s = s.replace('(pi.person_name, pi.reference_display)', 'pi.person_name').replace('                reference_number=s.reference_number,\n', '')
    s = s.replace('identities.get(s.identity_id, (None, None))[0]', 'identities.get(s.identity_id)').replace('                identity_reference=identities.get(s.identity_id, (None, None))[1],\n', '')
    start = s.index('    # Not a column. Without this pop')
    end = s.index('    record_audit(', start)
    s = s[:start] + '''    # UUID selection establishes identity and always requires voice.identify.
    data.pop("person_name", None)
    if "identity_id" in data:
        if "voice.identify" not in user.permission_codes:
            raise HTTPException(403, detail="identity_change_not_permitted")
        selected_id = data.pop("identity_id")
        identity = resolve_identity(db, db.get(PersonIdentity, selected_id)) if selected_id else None
        if identity is None:
            raise HTTPException(404, detail="identity_not_found")
        allowed = [sub.identity_id for sub in session.subjects]
        allowed.extend(link.investigator.identity_id for link in session.investigators)
        resolved_ids = {p.id for value in allowed if value is not None
                        if (p := resolve_identity(db, db.get(PersonIdentity, value))) is not None}
        if identity.id not in resolved_ids:
            raise HTTPException(400, detail="person_not_in_session")
        speaker.identity_id = identity.id
        speaker.display_name = identity.person_name
    for key, value in data.items():
        if key == "speaker_role":
            speaker.speaker_role = SpeakerRole(value) if value is not None else SpeakerRole.UNKNOWN
        else:
            setattr(speaker, key, value.strip() if isinstance(value, str) else value)

''' + s[end:]
    return s
edit(base+'api/transcripts.py', transcripts)

def voice(s):
    s = s.replace('    get_or_create_identity,\n', '').replace('    normalize_reference,\n', '')
    s = s.replace('PersonIdentity.person_name.ilike(like) | PersonIdentity.reference_display.ilike(like)', 'PersonIdentity.person_name.ilike(like)')
    s = s.replace('            | VoiceEnrollment.person_reference.ilike(like)\n', '')
    s = s.replace(' or "person_reference" in data', '')
    s = s.replace('{"person_name": identity.person_name, "person_reference": identity.reference_display}', '{"person_name": identity.person_name}')
    s = s.replace('{"person_name": source.person_name, "person_reference": source.reference_display}', '{"person_name": source.person_name}')
    start = s.index('        new_reference =')
    end = s.index('    if "is_active" in data', start)
    s = s[:start] + '''        if not new_name:
            raise HTTPException(400, detail="person_name_required")
        identity.person_name = new_name
        affected = [e.id for e in db.scalars(
            select(VoiceEnrollment).where(VoiceEnrollment.identity_id == identity.id)
        ).all()]

''' + s[end:]
    s = s.replace('"identity_after": {"person_name": identity.person_name,\n                                   "person_reference": identity.reference_display}', '"identity_after": {"person_name": identity.person_name}')
    s = re.sub(r'^.*(?:person_reference=|enrolled_person_reference=|speaker.reference_number =|person_reference = identity.reference_display|"person_reference":).*\n', '', s, flags=re.M)
    return s
edit(base+'api/voice.py', voice)
edit(base+'services/voice_matching.py', lambda s: re.sub(r'^.*"person_reference":.*\n', '', s, flags=re.M))

def main(s):
    s = s.replace('ParticipantReferenceRequired, ReferenceChangeRequired', 'ParticipantIdentityRequired').replace('PersonNameRequired, ReferenceNameMismatch', 'PersonNameRequired, IdentityNameMismatch')
    s = s.replace('"held_by_reference": exc.held_by.reference_display if exc.held_by else None', '"held_by_identity_id": str(exc.held_by.id) if exc.held_by else None')
    start = s.index('    @app.exception_handler(ParticipantReferenceRequired)')
    end = s.index('    @app.exception_handler(PersonNameRequired)', start)
    s = s[:start] + '''    @app.exception_handler(ParticipantIdentityRequired)
    async def _participant_identity_required(_: Request, exc: ParticipantIdentityRequired) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "participant_identity_required"})

''' + s[end:]
    s = s.replace(', "person_reference": exc.reference', '').replace('ReferenceNameMismatch', 'IdentityNameMismatch').replace('person_reference_name_mismatch', 'person_identity_name_mismatch').replace('"person_reference": exc.reference', '"identity_id": str(exc.identity.id)')
    return s
edit(base+'main.py', main)

# Newly generated reports omit reference-number placeholders. Historical artifacts stay immutable.
edit(base+'services/report_context.py', lambda s: re.sub(r'^.*(?:reference: str|reference=identity.reference_display).*\n', '', s, flags=re.M))
edit(base+'services/report_finalize.py', lambda s: re.sub(r'^.*"(?:reference|question_speaker_reference|answer_speaker_reference|investigator_reference|subject_reference)":.*\n', '', s, flags=re.M))
