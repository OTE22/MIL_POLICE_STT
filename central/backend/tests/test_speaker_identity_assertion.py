"""Session labels never become a canonical person name."""
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
