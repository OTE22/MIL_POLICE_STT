from __future__ import annotations

from tests.conftest import auth, create_session


def test_create_investigation_defaults_creator_as_lead(client, investigator):
    s = create_session(client, investigator["token"])
    assert s["session_number"].startswith("INV-") and s["status"] == "DRAFT"
    assert s["investigators"][0]["full_name"] == "الرائد علي حسن" and s["investigators"][0]["assignment_role"] == "LEAD"
    assert s["subjects"][0]["subject_name"] == "أحمد محمد"
    assert s["speaker_limit_warning"] is False


def test_session_number_generation_and_uniqueness(client, investigator):
    a = create_session(client, investigator["token"])
    b = create_session(client, investigator["token"])
    assert a["session_number"] != b["session_number"]
    res = client.post("/api/investigations", json={"title": "x", "session_number": a["session_number"]}, headers=auth(investigator["token"]))
    assert res.status_code == 409 and res.json()["detail"] == "session_number_taken"


def test_speaker_limit_warning(client, investigator):
    s = create_session(client, investigator["token"], expected_speaker_count=6)
    assert s["speaker_limit_warning"] is True


def test_investigator_assignment_multiple(client, investigator, investigator2, admin_token):
    p1 = investigator["user"]["profile"]["id"]
    p2 = investigator2["user"]["profile"]["id"]
    s = create_session(
        client,
        investigator["token"],
        investigators=[{"investigator_id": p1, "assignment_role": "LEAD"}, {"investigator_id": p2, "assignment_role": "ASSISTANT"}],
    )
    roles = {i["full_name"]: i["assignment_role"] for i in s["investigators"]}
    assert roles == {"الرائد علي حسن": "LEAD", "النقيب سامر": "ASSISTANT"}
    # Assigned assistant can read it, list shows lead investigator
    res = client.get(f"/api/investigations/{s['id']}", headers=auth(investigator2["token"]))
    assert res.status_code == 200
    listing = client.get("/api/investigations", headers=auth(investigator2["token"])).json()
    assert listing["total"] == 1 and listing["items"][0]["lead_investigator"] == "الرائد علي حسن"
    # Unknown investigator rejected
    res = client.post("/api/investigations", json={"title": "x", "investigators": [{"investigator_id": "00000000-0000-0000-0000-000000000000"}]}, headers=auth(investigator["token"]))
    assert res.status_code == 400


def test_unauthorized_resource_access(client, investigator, investigator2, viewer):
    s = create_session(client, investigator["token"])
    # another investigator not assigned -> 404 (existence not revealed)
    assert client.get(f"/api/investigations/{s['id']}", headers=auth(investigator2["token"])).status_code == 404
    assert client.put(f"/api/investigations/{s['id']}", json={"title": "hack"}, headers=auth(investigator2["token"])).status_code == 404
    assert client.get("/api/investigations", headers=auth(investigator2["token"])).json()["total"] == 0
    # viewer cannot create
    assert client.post("/api/investigations", json={"title": "x"}, headers=auth(viewer["token"])).status_code == 403
    # viewer cannot request processing even if assigned
    assert client.post(f"/api/investigations/{s['id']}/local-processing-token", json={"original_filename": "a.wav", "mime_type": "audio/wav", "size_bytes": 10}, headers=auth(viewer["token"])).status_code in (403, 404)


def test_update_investigation_and_status_transitions(client, investigator):
    s = create_session(client, investigator["token"])
    res = client.put(f"/api/investigations/{s['id']}", json={"title": "عنوان محدث", "location": "طرابلس", "status": "RECORDING", "subjects": []}, headers=auth(investigator["token"]))
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "عنوان محدث" and body["status"] == "RECORDING" and body["subjects"] == []
    # invalid transition RECORDING -> COMPLETED by hand
    res = client.put(f"/api/investigations/{s['id']}", json={"status": "COMPLETED"}, headers=auth(investigator["token"]))
    assert res.status_code == 409
    # archive then processing token refused
    res = client.put(f"/api/investigations/{s['id']}", json={"status": "ARCHIVED"}, headers=auth(investigator["token"]))
    assert res.status_code == 200 and res.json()["status"] == "ARCHIVED"
    res = client.post(f"/api/investigations/{s['id']}/local-processing-token", json={"original_filename": "a.wav", "mime_type": "audio/wav", "size_bytes": 10}, headers=auth(investigator["token"]))
    assert res.status_code == 409 and res.json()["detail"] == "session_archived"


def test_list_filters_and_dashboard(client, investigator, admin_token):
    create_session(client, investigator["token"], title="جلسة الصباح", session_date="2026-08-01")
    create_session(client, investigator["token"], title="جلسة المساء", session_date="2026-08-23", location="صيدا")
    res = client.get("/api/investigations?q=المساء", headers=auth(investigator["token"])).json()
    assert res["total"] == 1 and res["items"][0]["location"] == "صيدا"
    res = client.get("/api/investigations?date_from=2026-08-10", headers=auth(investigator["token"])).json()
    assert res["total"] == 1
    res = client.get("/api/investigations?status=DRAFT&page_size=1", headers=auth(investigator["token"])).json()
    assert res["total"] == 2 and len(res["items"]) == 1
    dash = client.get("/api/investigations/dashboard", headers=auth(admin_token)).json()
    assert dash["total_sessions"] == 2 and len(dash["recent"]) == 2


def test_activity_log_for_session(client, investigator):
    s = create_session(client, investigator["token"])
    client.put(f"/api/investigations/{s['id']}", json={"notes": "ملاحظة"}, headers=auth(investigator["token"]))
    res = client.get(f"/api/investigations/{s['id']}/activity", headers=auth(investigator["token"]))
    assert res.status_code == 200
    actions = [e["action"] for e in res.json()["items"]]
    assert "INVESTIGATION_CREATED" in actions and "INVESTIGATION_UPDATED" in actions
