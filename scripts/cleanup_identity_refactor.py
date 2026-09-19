from pathlib import Path
import re
ROOT = Path(__file__).resolve().parents[1]
def edit(path, fn):
    p = ROOT / path
    p.write_text(fn(p.read_text(encoding='utf-8')), encoding='utf-8')

def docs(s):
    s = re.sub(r'    """Follow merged_into_id.*?    """', '    """Follow merged UUIDs to the surviving person."""', s, count=1, flags=re.S)
    s = re.sub(r'    Merged rows are never deleted: retaining.*?    Concurrency is the hard part\.', '    Merged UUIDs remain resolvable for stale clients.\n\n    Concurrency is the hard part.', s, count=1, flags=re.S)
    s = s.replace('def normalize_identifier(reference: str | None)', 'def normalize_identifier(value: str | None)')
    start = s.index('    """Canonical form of a reference number.')
    end = s.index('    if reference is None:', start)
    s = s[:start] + '    """Fold case, whitespace and digit scripts in external document/service numbers."""\n' + s[end:]
    s = s.replace('if reference is None:', 'if value is None:').replace('normalize("NFKC", reference)', 'normalize("NFKC", value)')
    s = s.replace('    Current-state rows also take the survivor\'s reference, so a stale payload cannot keep\n    re-submitting one that has been merged away. Enrolment snapshots are left alone - they\n    record what was true when the print was taken.', '    Enrollment name snapshots remain unchanged. Stale UUIDs follow the merge alias.')
    return s
edit('central/backend/app/services/person_identity.py', docs)
edit('central/backend/app/models/person_identity.py', lambda s: re.sub(r'^""".*?"""', '"""Stable person UUIDs shared by sessions, investigators and voiceprints.\n\nMerged rows remain as UUID aliases so stale selections resolve to the surviving person.\n"""', s, count=1, flags=re.S).replace('    # The cross-session guarantee. Normalization rule lives in services/person_identity.py.\n', '').replace('    # The reference exactly as an investigator typed it, for display.\n', ''))
for path in ['models/transcript.py','models/voice.py','models/investigator.py','models/investigation.py']:
    edit('central/backend/app/'+path, lambda s: s.replace('    # Canonical person this row refers to. Backend-owned: resolved from the reference\n    # number, never accepted from a client.', '    # Canonical person UUID. Changes require an authorized identity-selection workflow.'))
edit('central/backend/app/models/voice.py', lambda s: s.replace('under one person_reference', 'under one identity_id').replace('    # Stable identifier for the person: military id, case reference, registry number…\n', ''))
edit('central/backend/app/schemas/transcripts.py', lambda s: s[:s.index('    # The canonical human name, rank EXCLUDED')] if '    # The canonical human name, rank EXCLUDED' in s else s)
edit('central/backend/app/schemas/transcripts.py', lambda s: s.replace('    # Canonical identity. Serialized outbound only - SpeakerUpdateIn deliberately has no\n    # identity_id, so a client can never attach a speaker to another person by UUID.', '    # Canonical person. Selecting this UUID requires voice.identify and session membership.'))
edit('central/backend/app/api/transcripts.py', lambda s: s.replace('    data.pop("person_name", None)\n', ''))
edit('central/frontend/src/lib/audit-format.ts', lambda s: s.replace('`${s(m.person_name)} · ${fieldLabel("person_reference")} ${s(m.person_reference)}`', 's(m.person_name)').replace('  person_reference: "الرقم المرجعي",\n', '').replace('["person_name", "person_reference"]', '["person_name"]'))
edit('central/frontend/src/lib/format.ts', lambda s: s.replace('`reference_number` is the only identity key', '`identity_id` is the identity key'))
edit('central/frontend/src/components/voice/EnrollDialog.tsx', lambda s: s.replace('/** الرقم المرجعي — the canonical identity key. */', '/** Internal person UUID; never displayed or typed. */').replace('The name and الرقم المرجعي are shown for confirmation only.', 'The name is shown for confirmation only.'))

# Shared test helpers use service numbers to set up people and UUIDs to link speakers.
def matching(s):
    s = s.replace('        person_reference=reference,\n', '')
    s = s.replace('assert match.enrollment.person_reference == "MIL-ARMY-1"', 'assert match.enrollment.identity_id == _identity_of("MIL-ARMY-1")')
    start = s.index('    current = client.get', s.index('def _link_identity'))
    end = s.index('\n\ndef _enroll', start)
    s = s[:start] + '''    current = client.get(f"/api/investigations/{session_id}", headers=auth(token)).json()
    subjects = current.get("subjects") or []
    serial = reference.removeprefix("MIL-ARMY-")
    person = next((p for p in subjects if p.get("military_id") == serial and p.get("security_branch") == "ARMY"), None)
    if person is None:
        res = client.put(f"/api/investigations/{session_id}",
                         json={"subjects": subjects + [_subject_for(reference, name)]}, headers=auth(token))
        if res.status_code >= 400:
            return res
        person = next(p for p in res.json()["subjects"] if p.get("military_id") == serial)
    return client.patch(f"/api/investigations/{session_id}/speakers/{speaker_id}",
                        json={"display_name": name, "identity_id": person["identity_id"], "speaker_role": "SUBJECT"},
                        headers=auth(token))
''' + s[end:]
    s = s.replace('        "person_reference": reference,\n', '').replace('person_reference_name_mismatch', 'person_identity_name_mismatch')
    s = s.replace('r["person_reference"] == reference', 'r["person_name"] in ("الرائد علي حسن", "علي حسن")')
    return s
edit('central/backend/tests/test_voice_matching.py', matching)
edit('central/backend/tests/test_subjects.py', lambda s: s.replace('"subject_name", "reference_number",', '"subject_name", "identity_id",'))
edit('central/backend/tests/test_person_identifiers.py', lambda s: s.replace('from app.services.person_identity import allocate_civilian_reference, get_or_create_identity', 'from app.services.person_identity import create_identity').replace('get_or_create_identity(db, allocate_civilian_reference(db), name)', 'create_identity(db, name)').replace('assert found.reference_display.startswith("CIV-")', 'assert found.id == person.id'))
edit('central/backend/tests/test_subject_identifiers_flow.py', lambda s: s.replace('from app.services.person_identity import find_identity', 'import uuid\nfrom app.models import PersonIdentity').replace('identity = find_identity(db, reference)', 'identity = db.get(PersonIdentity, uuid.UUID(reference))').replace('reference_number', 'identity_id').replace('held_by_reference', 'held_by_identity_id').replace('found.reference_display == reference', 'str(found.id) == reference').replace('    assert reference.startswith("CIV-"), "the card is evidence, not the canonical reference"', '    assert uuid.UUID(reference)'))
edit('central/backend/tests/test_remove_person_references_migration.py', lambda s: s.replace('import importlib\n', '').replace("    migration = importlib.import_module('alembic.versions.d8a4f2c91e60_remove_person_references') if False else None\n", ''))
edit('scripts/reset_demo_data.sh', lambda s: s.replace('SET identity_id = NULL, reference_number = NULL', 'SET identity_id = NULL'))
