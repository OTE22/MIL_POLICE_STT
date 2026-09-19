"""Enrollment uses the selected person's UUID and never creates or renames a person."""
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
