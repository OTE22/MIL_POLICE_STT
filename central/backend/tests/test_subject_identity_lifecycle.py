"""Correcting person details preserves UUID identity rather than switching references."""
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
    people = sorted(s["subjects"], key=lambda person: person["military_id"])
    res = client.put(f"/api/investigations/{s['id']}", headers=auth(admin_token),
                     json={"subjects":[{**people[0], "notes":"must roll back"}, {**people[1], "military_id":"4471"}]})
    assert res.status_code == 409
    after = client.get(f"/api/investigations/{s['id']}", headers=auth(admin_token)).json()["subjects"]
    assert all(p["notes"] is None for p in after)
    assert {p["identity_id"] for p in after} == {p["identity_id"] for p in people}
