"""Subject identity classification and identity-document handling."""

from __future__ import annotations

import hashlib
import struct
import zlib

from tests.conftest import auth, create_session


def png_bytes(w: int = 24, h: int = 24) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x80\x40\x20" * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


MILITARY = {
    "subject_name": "الرائد سامر",
    "person_type": "MILITARY",
    "security_branch": "ARMY",
    "rank": "رائد",
    "military_id": "M-7788",
    "unit": "الفوج الأول",
    "identity_confidence": "VERIFIED",
    "documents": [{"document_type": "MILITARY_ID", "document_number": "MIL-1"}],
}
LEBANESE = {
    "subject_name": "أحمد محمد",
    "person_type": "CIVILIAN",
    "nationality_code": "LB",
    "register_number": "REG-55",
    "place_of_registration": "بعبدا/الحدث",
    "identity_confidence": "DOCUMENT_SEEN",
    "documents": [
        {"document_type": "NATIONAL_ID", "document_number": "ID-100"},
        {"document_type": "PASSPORT", "document_number": "LP-200", "expiry_date": "2020-01-01"},
    ],
}
SYRIAN = {
    "subject_name": "فاطمة",
    "person_type": "CIVILIAN",
    "nationality_code": "SY",
    "documents": [{"document_type": "UNHCR_CARD", "document_number": "UN-9", "issuing_country": "لبنان"}],
}
# Even someone who refuses to identify themselves is recorded under a name the OPERATOR
# writes. The system never invents one - that is the whole distinction.
UNIDENTIFIED = {"subject_name": "مجهول الهوية", "person_type": "UNKNOWN",
                "is_undocumented": True, "undocumented_reason": "REFUSED"}


def test_person_types_and_lebanese_fields(client, investigator):
    s = create_session(client, investigator["token"], subjects=[MILITARY, LEBANESE, SYRIAN, UNIDENTIFIED])
    subjects = {x["person_type"] + (x["nationality_code"] or ""): x for x in s["subjects"]}
    assert len(s["subjects"]) == 4
    mil = subjects["MILITARY"]
    assert mil["security_branch"] == "ARMY" and mil["rank"] == "رائد" and mil["identity_confidence"] == "VERIFIED"
    leb = subjects["CIVILIANLB"]
    assert leb["register_number"] == "REG-55" and leb["place_of_registration"] == "بعبدا/الحدث"
    assert len(leb["documents"]) == 2
    assert any(d["is_expired"] for d in leb["documents"] if d["document_type"] == "PASSPORT")
    assert subjects["CIVILIANSY"]["documents"][0]["document_type"] == "UNHCR_CARD"
    unk = subjects["UNKNOWN"]
    assert unk["is_undocumented"] is True and unk["undocumented_reason"] == "REFUSED"


def test_unidentified_person_needs_no_data(client, investigator):
    """An interview with an unidentified person must always be recordable (spec §33)."""
    s = create_session(client, investigator["token"], subjects=[
        {"subject_name": "مجهول الهوية", "person_type": "UNKNOWN", "is_undocumented": True}])
    assert len(s["subjects"]) == 1 and s["subjects"][0]["person_type"] == "UNKNOWN"

    # §33 still holds - the interview is recordable - but the person is recorded under a name
    # the operator chose. A row with no name at all is now a validation error rather than being
    # silently dropped: silence is what let a nameless subject reach the registry and be filed
    # under its own reference number.
    res = client.post("/api/investigations", json={
        "title": "بلا اسم", "location": "بيروت", "session_date": "2026-08-27",
        "start_time": "10:00", "expected_speaker_count": 1,
        "subjects": [{"person_type": "CIVILIAN"}],
    }, headers=auth(investigator["token"]))
    assert res.status_code == 422, res.text


def test_document_scan_upload_download_and_hash(client, investigator):
    s = create_session(client, investigator["token"], subjects=[LEBANESE])
    doc = s["subjects"][0]["documents"][0]
    png = png_bytes()
    res = client.post(
        f"/api/investigations/{s['id']}/subject-documents/{doc['id']}/file",
        files={"file": ("id.png", png, "image/png")},
        headers=auth(investigator["token"]),
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["sha256"] == hashlib.sha256(png).hexdigest()
    assert body["has_file"] is True and body["uploaded_by_name"] == "الرائد علي حسن"

    # The original is evidence: it is returned byte-for-byte and cannot be silently replaced.
    got = client.get(
        f"/api/investigations/{s['id']}/subject-documents/{doc['id']}/file", headers=auth(investigator["token"])
    )
    assert got.status_code == 200 and got.content == png
    assert got.headers["x-content-type-options"] == "nosniff"
    again = client.post(
        f"/api/investigations/{s['id']}/subject-documents/{doc['id']}/file",
        files={"file": ("id.png", png, "image/png")},
        headers=auth(investigator["token"]),
    )
    assert again.status_code == 409 and again.json()["detail"] == "document_file_exists"


def test_document_upload_validation(client, investigator):
    s = create_session(client, investigator["token"], subjects=[LEBANESE])
    doc_id = s["subjects"][0]["documents"][0]["id"]
    url = f"/api/investigations/{s['id']}/subject-documents/{doc_id}/file"
    h = auth(investigator["token"])
    # Executable rejected by extension/MIME
    assert client.post(url, files={"file": ("x.exe", b"MZ\x90\x00", "application/octet-stream")}, headers=h).status_code == 400
    # A file claiming to be a PNG but without PNG magic bytes is rejected
    res = client.post(url, files={"file": ("x.png", b"definitely not a png", "image/png")}, headers=h)
    assert res.status_code == 400 and res.json()["detail"] == "unsupported_document_type"
    # Empty file
    assert client.post(url, files={"file": ("x.png", b"", "image/png")}, headers=h).status_code == 400
    # A real PDF is accepted and served as an attachment (never inline)
    pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"
    ok = client.post(url, files={"file": ("scan.pdf", pdf, "application/pdf")}, headers=h)
    assert ok.status_code == 201 and ok.json()["mime_type"] == "application/pdf"
    got = client.get(url, headers=h)
    assert "attachment" in got.headers["content-disposition"]


def test_document_access_requires_dedicated_permission(client, investigator, investigator2, viewer, admin_token):
    s = create_session(client, investigator["token"], subjects=[LEBANESE])
    doc_id = s["subjects"][0]["documents"][0]["id"]
    url = f"/api/investigations/{s['id']}/subject-documents/{doc_id}/file"
    client.post(url, files={"file": ("id.png", png_bytes(), "image/png")}, headers=auth(investigator["token"]))
    # USER role has no subjects.documents.view permission
    assert client.get(url, headers=auth(viewer["token"])).status_code in (403, 404)
    # Another investigator has the permission but no access to this session
    assert client.get(url, headers=auth(investigator2["token"])).status_code == 404
    assert client.get(url).status_code == 401
    assert client.get(url, headers=auth(admin_token)).status_code == 200


def test_editing_a_session_preserves_uploaded_scans(client, investigator):
    s = create_session(client, investigator["token"], subjects=[LEBANESE])
    subject = s["subjects"][0]
    doc_id = subject["documents"][0]["id"]
    client.post(
        f"/api/investigations/{s['id']}/subject-documents/{doc_id}/file",
        files={"file": ("id.png", png_bytes(), "image/png")},
        headers=auth(investigator["token"]),
    )
    keys = [
        # participant_key: the handle the form round-trips so the server knows this is the
        # SAME participant being edited rather than a new one claiming their reference.
        "participant_key",
        "subject_name", "identity_id", "person_type", "military_id", "rank", "unit", "department",
        "security_branch", "nationality_code", "nationality_name", "register_number", "place_of_registration",
        "is_unregistered", "is_undocumented", "undocumented_reason", "identity_confidence", "notes",
    ]
    doc_keys = ["id", "document_type", "document_number", "issuing_country", "issue_date", "expiry_date", "notes"]
    fresh = client.get(f"/api/investigations/{s['id']}", headers=auth(investigator["token"])).json()["subjects"][0]
    payload = {k: fresh[k] for k in keys}
    payload["subject_name"] = "أحمد محمد علي"
    payload["documents"] = [{k: d[k] for k in doc_keys} for d in fresh["documents"]]
    res = client.put(f"/api/investigations/{s['id']}", json={"subjects": [payload]}, headers=auth(investigator["token"]))
    assert res.status_code == 200
    updated = res.json()["subjects"][0]
    assert updated["subject_name"] == "أحمد محمد علي"
    kept = [d for d in updated["documents"] if d["id"] == doc_id]
    assert len(kept) == 1 and kept[0]["has_file"] is True, "the uploaded scan must survive an edit"


def test_duplicate_document_number_warns_without_blocking(client, investigator):
    first = create_session(client, investigator["token"], subjects=[LEBANESE])
    second = create_session(client, investigator["token"], subjects=[LEBANESE])
    assert second["subjects"][0]["duplicate_of_sessions"] == [first["session_number"]]


def test_document_deletion_and_audit(client, investigator, admin_token):
    s = create_session(client, investigator["token"], subjects=[LEBANESE])
    doc_id = s["subjects"][0]["documents"][0]["id"]
    url = f"/api/investigations/{s['id']}/subject-documents/{doc_id}/file"
    h = auth(investigator["token"])
    client.post(url, files={"file": ("id.png", png_bytes(), "image/png")}, headers=h)
    client.get(url, headers=h)
    assert client.delete(url, headers=h).status_code == 204
    assert client.get(url, headers=h).status_code == 404

    logs = client.get("/api/audit-logs?entity_type=subject_document", headers=auth(admin_token)).json()
    actions = {e["action"] for e in logs["items"]}
    assert {"SUBJECT_DOCUMENT_UPLOADED", "SUBJECT_DOCUMENT_VIEWED", "SUBJECT_DOCUMENT_DELETED"} <= actions
    uploaded = next(e for e in logs["items"] if e["action"] == "SUBJECT_DOCUMENT_UPLOADED")
    assert uploaded["safe_metadata"]["sha256"] and "content" not in str(uploaded["safe_metadata"])


def test_subject_validation(client, investigator):
    bad_nationality = {**LEBANESE, "nationality_code": "LEB"}
    res = client.post(
        "/api/investigations", json={"title": "x", "subjects": [bad_nationality]}, headers=auth(investigator["token"])
    )
    assert res.status_code == 422
    bad_doc = {"subject_name": "سمير", "person_type": "CIVILIAN", "documents": [{"document_type": "NOT_A_TYPE"}]}
    res = client.post("/api/investigations", json={"title": "x", "subjects": [bad_doc]}, headers=auth(investigator["token"]))
    assert res.status_code == 422
