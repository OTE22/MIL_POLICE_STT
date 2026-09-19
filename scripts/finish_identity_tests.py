from pathlib import Path
import re
ROOT = Path(__file__).resolve().parents[1] / 'central/backend/tests'
def edit(name, fn):
    p = ROOT / name
    p.write_text(fn(p.read_text(encoding='utf-8')), encoding='utf-8')

edit('test_participant_reconciliation.py', lambda s: re.sub(r'(\[[^\n]*?\]\["identity_id"\])\.startswith\("TMP-"\)', r'bool(\1)', s.replace('reference_number', 'identity_id').replace('participant_reference_required', 'participant_identity_required')))
edit('test_processing_and_transcripts.py', lambda s: s.replace('["reference_number"]', '["identity_id"]').replace('civilian_ref.startswith("CIV-")', 'bool(civilian_ref)').replace('"reference_number": civilian_ref', '"identity_id": civilian_ref'))

def candidates(s):
    s = s.replace('    _enroll,', '    _enroll,\n    _link_identity,')
    start = s.index('    current = client.get', s.index('def _identify'))
    end = s.index('\n\ndef _ref()', start)
    s = s[:start] + '''    res = _link_identity(client, token, session["id"], speaker_id, reference, name)
    assert res.status_code == 200, res.text
    return res.json()
''' + s[end:]
    s = s.replace('assert rows[0]["person_reference"] == reference', 'assert rows[0]["identity_id"]')
    s = s.replace('r["person_reference"] == reference', 'r["person_name"] == "أحمد محمد"')
    s = s.replace('p["person_reference"] == reference', 'p["person_name"] == "الرائد علي حسن"')
    s = s.replace('people?q={reference}', 'people?q=الرائد علي حسن')
    s = s.replace('from app.services.person_identity import find_identity, merge_identities', 'from app.services.person_identity import merge_identities\n    from app.services.person_identifiers import find_by_identifier\n    def find_identity(db, reference):\n        return find_by_identifier(db, identifier_type="MILITARY", issuer="ARMY", value=reference.removeprefix("MIL-ARMY-"))')
    s = re.sub(r'^.*assert speaker.reference_number.*\n', '', s, flags=re.M)
    s = s.replace('assert subject is not None and subject.reference_number == survivor.reference_display', 'assert subject is not None and subject.identity_id == survivor.id')
    s = s.replace('assert after["identity_reference"] == reference', 'assert after["identity_id"]')
    s = s.replace('    assert res.json()["identity_id"] != victim["identity_id"], "a client-supplied identity_id must be ignored"', '    assert res.json()["detail"] == "person_not_in_session"')
    # The arbitrary UUID case is now explicitly refused instead of ignored.
    s = s.replace('    assert res.status_code == 200, res.text\n    assert res.json()["detail"] == "person_not_in_session"', '    assert res.status_code == 400, res.text\n    assert res.json()["detail"] == "person_not_in_session"')
    return s
edit('test_voice_candidates.py', candidates)

# Retain the existing permission fixture; rewrite its cases against the UUID contract.
p = ROOT/'test_speaker_identity_authorization.py'
s = p.read_text(encoding='utf-8')
s = s[:s.index('def test_re_sending_an_unchanged_reference')]
s += '''def test_uuid_selection_requires_voice_identify(client, labeller):
    t = labeller["token"]
    s, speaker = _session_with_speaker(client, t)
    subject = s["subjects"][0]
    res = _patch(client, t, s["id"], speaker["id"], identity_id=subject["identity_id"])
    assert res.status_code == 403
    assert res.json()["detail"] == "identity_change_not_permitted"

def test_role_and_notes_preserve_an_existing_identity(client, labeller):
    from app.models import SessionSpeaker
    t = labeller["token"]
    s, speaker = _session_with_speaker(client, t)
    identity_id = s["subjects"][0]["identity_id"]
    with SessionLocal() as db:
        db.get(SessionSpeaker, uuid.UUID(speaker["id"])).identity_id = uuid.UUID(identity_id)
        db.commit()
    res = _patch(client, t, s["id"], speaker["id"], notes="ملاحظة", speaker_role="WITNESS")
    assert res.status_code == 200
    assert res.json()["identity_id"] == identity_id

def test_retired_reference_cannot_bypass_permission(client, labeller):
    t = labeller["token"]
    s, speaker = _session_with_speaker(client, t)
    res = _patch(client, t, s["id"], speaker["id"], reference_number="MIL-ARMY-4471")
    assert res.status_code == 422
'''
p.write_text(s, encoding='utf-8')

(ROOT/'test_speaker_identity_assertion.py').write_text('''"""Session labels never become a canonical person name."""
from tests.conftest import auth, create_session
from tests.test_uuid_person_identity import speaker_for

def test_label_and_notes_do_not_rename_person(client, admin_token):
    s = create_session(client, admin_token)
    url = f"/api/investigations/{s['id']}/speakers/{speaker_for(s)}"
    identity_id = s["subjects"][0]["identity_id"]
    assert client.patch(url, headers=auth(admin_token), json={"identity_id": identity_id}).status_code == 200
    res = client.patch(url, headers=auth(admin_token), json={"display_name": "الرائد أحمد محمد", "notes": "note"})
    assert res.status_code == 200
    assert res.json()["identity_name"] == "أحمد محمد"
    assert res.json()["display_name"] == "الرائد أحمد محمد"
    assert res.json()["identity_id"] == identity_id

def test_label_alone_does_not_create_person(client, admin_token):
    s = create_session(client, admin_token)
    res = client.patch(f"/api/investigations/{s['id']}/speakers/{speaker_for(s)}",
                       headers=auth(admin_token), json={"display_name": "الرائد علي حسن"})
    assert res.status_code == 200
    assert res.json()["identity_id"] is None
''', encoding='utf-8')

(ROOT/'test_enrollment_identity_authority.py').write_text('''"""Enrollment uses the selected person's UUID and never creates or renames a person."""
import uuid
from app.db.session import SessionLocal
from app.models import PersonIdentity
from app.services.person_identity import create_identity, merge_identities
from tests.conftest import auth, create_session
from tests.test_uuid_person_identity import speaker_for

def test_unidentified_speaker_cannot_be_enrolled(client, admin_token):
    s = create_session(client, admin_token)
    res = client.post(f"/api/investigations/{s['id']}/speakers/{speaker_for(s)}/enroll",
                      headers=auth(admin_token), json={"model":"test", "consent_recorded":True})
    assert res.status_code == 400
    assert res.json()["detail"] == "speaker_identity_required"

def test_enrollment_follows_merge_alias_without_changing_name(client, admin_token):
    s = create_session(client, admin_token)
    speaker_id = speaker_for(s)
    url = f"/api/investigations/{s['id']}/speakers/{speaker_id}"
    source_id = s["subjects"][0]["identity_id"]
    assert client.patch(url, headers=auth(admin_token), json={"identity_id":source_id}).status_code == 200
    with SessionLocal() as db:
        target = create_identity(db, "الاسم الصحيح")
        merge_identities(db, uuid.UUID(source_id), target.id)
        db.commit()
        target_id = str(target.id)
    res = client.post(url + "/enroll", headers=auth(admin_token),
                      json={"model":"test", "consent_recorded":True, "person_name":"اسم خاطئ"})
    assert res.status_code == 201
    assert res.json()["person_name"] == "الاسم الصحيح"
    assert res.json()["identity_id"] == target_id
''', encoding='utf-8')

(ROOT/'test_subject_identity_lifecycle.py').write_text('''"""Correcting person details preserves UUID identity rather than switching references."""
from tests.conftest import auth, create_session

def test_military_details_can_be_corrected_without_splitting_person(client, admin_token):
    s = create_session(client, admin_token, subjects=[{"subject_name":"علي", "person_type":"MILITARY", "military_id":"4471", "security_branch":"ARMY"}])
    person = s["subjects"][0]
    res = client.put(f"/api/investigations/{s['id']}", headers=auth(admin_token),
                     json={"subjects":[{**person, "military_id":"4472"}]})
    assert res.status_code == 200, res.text
    assert res.json()["subjects"][0]["identity_id"] == person["identity_id"]

def test_identifier_conflict_rolls_back_whole_save(client, admin_token):
    s = create_session(client, admin_token, subjects=[
        {"subject_name":"علي", "person_type":"MILITARY", "military_id":"4471", "security_branch":"ARMY"},
        {"subject_name":"حسن", "person_type":"MILITARY", "military_id":"4472", "security_branch":"ARMY"}])
    people = s["subjects"]
    res = client.put(f"/api/investigations/{s['id']}", headers=auth(admin_token),
                     json={"subjects":[{**people[0], "notes":"must roll back"}, {**people[1], "military_id":"4471"}]})
    assert res.status_code == 409
    after = client.get(f"/api/investigations/{s['id']}", headers=auth(admin_token)).json()["subjects"]
    assert all(p["notes"] is None for p in after)
    assert {p["identity_id"] for p in after} == {p["identity_id"] for p in people}
''', encoding='utf-8')
