"""End-to-end continuity, evidence retention, concurrency and official HTML/PDF regression."""
import io
import uuid
import wave
from copy import deepcopy
from sqlalchemy import select
from app.models import Subject, SubjectDocument, TranscriptSegment, GeneratedReport, InvestigationSession
from app.db.session import SessionLocal
from conftest import auth, create_session, request_token, sample_result


def html_draft(client, token, session):
    path = f"/api/investigations/{session['id']}/report/html"
    result = client.post(path, headers=auth(token), json={})
    assert result.status_code == 200, result.text
    return path, result.json()


def test_document_partial_edit_preserves_metadata_and_validates_merged_dates(client, investigator):
    token = investigator["token"]
    session = create_session(client, token, subjects=[{"subject_name": "Document holder", "documents": [{
        "document_type": "PASSPORT", "document_number": "P123", "issue_date": "2025-01-01",
        "expiry_date": "2027-01-01", "notes": "Retain these facts"}]}])
    subject = session["subjects"][0]
    document = subject["documents"][0]
    path = f"/api/investigations/{session['id']}"
    payload = {"participant_key": subject["participant_key"], "subject_name": subject["subject_name"],
               "documents": [{"id": document["id"], "document_type": "PASSPORT", "notes": None}]}
    result = client.put(path, headers=auth(token), json={"expected_revision": session["revision"], "subjects": [payload]})
    assert result.status_code == 200, result.text
    current = result.json()
    saved = current["subjects"][0]["documents"][0]
    assert saved["document_number"] == "P123" and saved["issue_date"] == "2025-01-01"
    assert saved["notes"] is None
    payload["documents"][0]["expiry_date"] = "2024-01-01"
    assert client.put(path, headers=auth(token), json={"expected_revision": current["revision"], "subjects": [payload]}).status_code == 422
    assert client.put(path, headers=auth(token), json={"expected_revision": current["revision"], "title": "  "}).status_code == 422


def test_session_duration_totals_all_recordings(client, investigator):
    from app.models import AudioRecording
    token = investigator["token"]
    session = create_session(client, token)
    first, second = [request_token(client, token, session["id"]) for _ in range(2)]
    with SessionLocal() as db:
        recordings = db.scalars(select(AudioRecording).where(AudioRecording.session_id == uuid.UUID(session["id"]))).all()
        assert len(recordings) == 2
        recordings[0].duration_seconds = 10
        recordings[1].duration_seconds = 25
        db.commit()
    assert client.get(f"/api/investigations/{session['id']}", headers=auth(token)).json()["duration_seconds"] == 35


def test_issuance_locks_canonical_names_against_concurrent_registry_edits(client, investigator):
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError
    from app.services.workflow import lock_source_people
    session = create_session(client, investigator["token"])
    with SessionLocal() as holder:
        current = holder.get(InvestigationSession, uuid.UUID(session["id"]))
        lock_source_people(holder, current)
        identity_id = current.subjects[0].identity_id
        assert identity_id is not None
        with SessionLocal() as editor:
            editor.execute(text("SET LOCAL lock_timeout = '200ms'"))
            with pytest.raises(OperationalError):
                editor.execute(text("UPDATE person_identities SET person_name = person_name WHERE id = :id"),
                               {"id": identity_id})


def fill_note(state):
    document = deepcopy(state["document"])
    document["blocks"] = [{"id": str(uuid.uuid4()), "type": "note", "values": {
        "note_date": "2026-10-25", "note_time": "12:30", "note_text": "Reviewed evidence. \u0645\u0644\u0627\u062d\u0638\u0629",
        "closing_location": "Beirut", "closing_date": "2026-10-25"}}]
    document["blocks"].append({"id": str(uuid.uuid4()), "type": "conclusion", "values": {
        "facts": "Reviewed events and evidence", "inference": "Assessment from reviewed evidence",
        "closing_location": "Beirut", "closing_date": "2026-10-25"},
        "responsibility_mode": "NONE", "proposal_mode": "NONE", "findings": []})
    return document


def save(client, token, path, state, document):
    result = client.put(path, headers=auth(token), json={"expected_token": state["token"], "document": __import__("app.services.report_html", fromlist=["editable_document"]).editable_document(document)})
    assert result.status_code == 200, result.text
    return result.json()


def review(client, token, path, state, acknowledge=False):
    return client.post(path + "/review", headers=auth(token), json={"expected_token": state["token"],
        "expected_source_token": state["source_token"], "content_reviewed": True, "acknowledge_source_changes": acknowledge})


def test_review_precedes_issuance_and_closure_requires_official_document(client, investigator):
    token = investigator["token"]
    session = create_session(client, token)
    path, state = html_draft(client, token, session)
    state = save(client, token, path, state, fill_note(state))
    session_path = f"/api/investigations/{session['id']}"
    def move(target):
        current = client.get(session_path, headers=auth(token)).json()
        return client.post(session_path + "/workflow", headers=auth(token), json={
            "expected_revision": current["revision"], "state": target, "reason": "Explicit workflow review"})
    assert move("IN_PROGRESS").status_code == 200
    assert move("AWAITING_REVIEW").status_code == 200
    assert move("REVIEWED").status_code == 409
    assert review(client, token, path, state).status_code == 200
    assert move("REVIEWED").status_code == 200
    closed = move("CLOSED")
    assert closed.status_code == 409 and "current_report_not_issued" in closed.json()["detail"]["reasons"]


def test_issued_preview_is_frozen_and_closed_report_reopening_is_explicit(client, investigator, monkeypatch):
    from app.models import InvestigatorProfile, PersonIdentity
    from app.services import report_document
    monkeypatch.setattr(report_document, "pdf_from_html", lambda html: b"%PDF-1.7\nsynthetic archive")
    token = investigator["token"]
    session = create_session(client, token)
    path, state = html_draft(client, token, session)
    state = save(client, token, path, state, fill_note(state))
    assert review(client, token, path, state).status_code == 200
    archive_path = f"/api/investigations/{session['id']}/reports"
    result = client.post(archive_path, headers=auth(token), json={"expected_token": state["token"]})
    assert result.status_code == 201, result.text
    issued = result.json()["reports"][0]
    html = client.get(archive_path + f"/{issued['id']}/file?format=html", headers=auth(token)).content
    base = f"/api/investigations/{session['id']}"
    for target in ["IN_PROGRESS", "AWAITING_REVIEW", "REVIEWED", "CLOSED"]:
        current = client.get(base, headers=auth(token)).json()
        moved = client.post(base + "/workflow", headers=auth(token), json={"expected_revision": current["revision"],
            "state": target, "reason": "Explicit verified transition"})
        assert moved.status_code == 200, moved.text
    with SessionLocal() as db:
        profile = db.get(InvestigatorProfile, uuid.UUID(session["investigators"][0]["id"]))
        profile.full_name = "Updated canonical investigator"
        db.get(PersonIdentity, profile.identity_id).person_name = profile.full_name
        db.commit()
    preview = client.post(path + "/preview", headers=auth(token), json={
        "expected_token": state["token"], "document": fill_note(state)})
    assert preview.status_code == 200, preview.text
    assert preview.json()["html"].encode() == html
    reopened = client.post(base + "/report/reopen", headers=auth(token), json={
        "expected_token": state["token"], "reason": "   "})
    assert reopened.status_code == 422
    reopened = client.post(base + "/report/reopen", headers=auth(token), json={
        "expected_token": state["token"], "reason": "Explicit correction after closure"})
    assert reopened.status_code == 200, reopened.text
    assert client.get(base, headers=auth(token)).json()["workflow_state"] == "IN_PROGRESS"
    assert client.get(archive_path + f"/{issued['id']}/file?format=html", headers=auth(token)).content == html


def test_html_official_issue_reopen_and_immutable_artifacts(client, investigator):
    token = investigator["token"]
    session = create_session(client, token)
    path, state = html_draft(client, token, session)
    state = save(client, token, path, state, fill_note(state))
    assert "report_review_required" in state["blocked_reasons"]
    reviewed = review(client, token, path, state)
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["reviewed"] is True
    archive_path = f"/api/investigations/{session['id']}/reports"
    issued = client.post(archive_path, headers=auth(token), json={"expected_token": state["token"]})
    assert issued.status_code == 201, issued.text
    first = issued.json()["reports"][0]
    html = client.get(archive_path + f"/{first['id']}/file?format=html", headers=auth(token))
    pdf = client.get(archive_path + f"/{first['id']}/file?format=pdf", headers=auth(token))
    assert html.status_code == pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert "Reviewed evidence." in html.text
    assert client.get(archive_path + f"/{first['id']}/verify", headers=auth(token)).json()["ok"]
    assert client.put(path, headers=auth(token), json={"expected_token": state["token"], "document": fill_note(state)}).status_code == 409
    reopened = client.post(path.removesuffix('/html') + '/reopen', headers=auth(token), json={
        "expected_token": state["token"], "reason": "Correct the note"})
    assert reopened.status_code == 200, reopened.text
    newer = save(client, token, path, reopened.json(), fill_note(reopened.json()))
    assert review(client, token, path, newer).status_code == 200
    assert client.post(archive_path, headers=auth(token), json={"expected_token": newer["token"]}).status_code == 201
    assert client.get(archive_path + f"/{first['id']}/file?format=html", headers=auth(token)).content == html.content
    assert client.get(archive_path + f"/{first['id']}/file?format=pdf", headers=auth(token)).content == pdf.content


def test_upstream_changes_invalidate_review_and_stale_saves(client, investigator):
    token = investigator["token"]
    session = create_session(client, token)
    path, state = html_draft(client, token, session)
    state = save(client, token, path, state, fill_note(state))
    assert review(client, token, path, state).status_code == 200
    changed = client.put(f"/api/investigations/{session['id']}", headers=auth(token), json={
        "expected_revision": session["revision"], "location": None})
    assert changed.status_code == 200, changed.text
    assert changed.json()["location"] is None
    assert client.put(f"/api/investigations/{session['id']}", headers=auth(token), json={
        "expected_revision": session["revision"], "title": "stale"}).status_code == 409
    current = client.get(path, headers=auth(token)).json()
    assert current["sources_changed"] and not current["reviewed"]
    assert review(client, token, path, current).status_code == 409
    assert review(client, token, path, current, True).status_code == 409
    restored = client.put(f"/api/investigations/{session['id']}", headers=auth(token), json={
        "expected_revision": changed.json()["revision"], "location": "Corrected location"})
    assert restored.status_code == 200
    current = client.get(path, headers=auth(token)).json()
    assert review(client, token, path, current, True).status_code == 200


def test_participant_ids_and_documents_survive_edits_and_removal(client, investigator):
    token = investigator["token"]
    session = create_session(client, token, subjects=[{"subject_name": "Person", "documents": [{"document_type": "PASSPORT"}]}])
    subject = session["subjects"][0]
    document = subject["documents"][0]
    payload = {"participant_key": subject["participant_key"], "identity_id": subject["identity_id"],
               "subject_name": "Person", "documents": [{"id": document["id"], "document_type": "PASSPORT"}]}
    url = f"/api/investigations/{session['id']}"
    result = client.put(url, headers=auth(token), json={"expected_revision": session["revision"], "subjects": [payload]})
    assert result.status_code == 200, result.text
    assert result.json()["subjects"][0]["id"] == subject["id"]
    payload["documents"] = []
    rejected = client.put(url, headers=auth(token), json={"expected_revision": result.json()["revision"], "subjects": [payload]})
    assert rejected.status_code == 200
    assert rejected.json()["subjects"][0]["documents"][0]["id"] == document["id"]
    result = rejected
    payload["removed_document_ids"] = [document["id"]]
    result = client.put(url, headers=auth(token), json={"expected_revision": result.json()["revision"], "subjects": [payload]})
    assert result.status_code == 200, result.text
    result = client.put(url, headers=auth(token), json={"expected_revision": result.json()["revision"], "subjects": [],
                        "removed_participant_keys": [subject["participant_key"]]})
    assert result.status_code == 200, result.text
    with SessionLocal() as db:
        assert db.get(Subject, uuid.UUID(subject["id"])).removed_at
        assert db.get(SubjectDocument, uuid.UUID(document["id"])).removed_at


def test_reviewed_attribution_reaches_report_import_and_preserves_original(client, investigator):
    from app.services.report_context import build_turns
    from app.models import TranscriptSourceMode
    token = investigator["token"]
    session = create_session(client, token)
    job = request_token(client, token, session["id"])
    result = client.post(f"/api/local-processing/{job['job_id']}/result", headers=auth(job["processing_token"]), json=sample_result())
    assert result.status_code == 200, result.text
    transcript = client.get(f"/api/investigations/{session['id']}/transcript", headers=auth(token)).json()
    segment = transcript["segments"][0]
    other = transcript["segments"][1]["speaker_label"]
    parts = [{"speaker_label": other, "start_seconds": segment["start_seconds"], "end_seconds": segment["end_seconds"], "text": "Corrected attribution"}]
    url = f"/api/transcript-segments/{segment['id']}/attribution"
    result = client.put(url, headers=auth(token), json={"expected_revision": segment["revision"], "parts": parts})
    assert result.status_code == 200, result.text
    assert result.json()["original_text"] == segment["original_text"]
    assert client.put(url, headers=auth(token), json={"expected_revision": segment["revision"], "parts": parts}).status_code == 409
    with SessionLocal() as db:
        turns = build_turns(db, [uuid.UUID(transcript["recording_id"])], TranscriptSourceMode.CORRECTED)
        assert turns[0].speaker_label == other and "Corrected attribution" in turns[0].text
        original = build_turns(db, [uuid.UUID(transcript["recording_id"])], TranscriptSourceMode.ORIGINAL)
        assert original[0].speaker_label == segment["speaker_label"]
    parts[0]["speaker_label"] = "FOREIGN"
    assert client.put(url, headers=auth(token), json={"expected_revision": result.json()["revision"], "parts": parts}).status_code == 422


def test_multiple_jobs_do_not_complete_investigation_or_hide_active_job(client, investigator):
    token = investigator["token"]
    session = create_session(client, token)
    jobs = [request_token(client, token, session["id"]) for _ in range(2)]
    result = client.post(f"/api/local-processing/{jobs[0]['job_id']}/result", headers=auth(jobs[0]["processing_token"]), json=sample_result())
    assert result.status_code == 200, result.text
    current = client.get(f"/api/investigations/{session['id']}", headers=auth(token)).json()
    assert current["status"] == "PROCESSING"
    assert current["workflow_state"] == "IN_PROGRESS"
    assert current["processing_summary"]["REQUESTED"] == 1
    closure = client.post(f"/api/investigations/{session['id']}/workflow", headers=auth(token), json={
        "expected_revision": current["revision"], "state": "AWAITING_REVIEW", "reason": "Ready for review"})
    assert closure.status_code == 409


def test_processing_retry_reuses_recording_and_resolves_only_its_failure(client, investigator):
    from app.services.workflow import unresolved_processing_failures
    token = investigator["token"]
    session = create_session(client, token)
    first = request_token(client, token, session["id"])
    path = f"/api/investigations/{session['id']}/local-processing-token"
    body = {"recording_id": first["recording_id"], "original_filename": "interview.wav",
            "mime_type": "audio/wav", "size_bytes": 44 + 16000 * 2 * 3, "source": "FILE_UPLOAD"}
    assert client.post(path, headers=auth(token), json=body).status_code == 409
    failed = client.post(f"/api/local-processing/{first['job_id']}/state", headers=auth(first["processing_token"]),
                         json={"state": "FAILED", "message": "Test retry", "failure_stage": "TRANSCRIBING"})
    assert failed.status_code == 200, failed.text
    with SessionLocal() as db:
        assert unresolved_processing_failures(db, uuid.UUID(session["id"])) == 1
    assert client.post(path, headers=auth(token), json={**body, "size_bytes": body["size_bytes"] + 1}).status_code == 409
    second = client.post(path, headers=auth(token), json=body)
    assert second.status_code == 200, second.text
    retry = second.json()
    assert retry["recording_id"] == first["recording_id"] and retry["job_id"] != first["job_id"]
    result = client.post(f"/api/local-processing/{retry['job_id']}/result", headers=auth(retry["processing_token"]), json=sample_result())
    assert result.status_code == 200, result.text
    current = client.get(f"/api/investigations/{session['id']}", headers=auth(token)).json()
    assert len(current["recordings"]) == 1 and current["status"] == "COMPLETED"
    assert current["processing_summary"]["FAILED"] == current["processing_summary"]["COMPLETED"] == 1
    assert current["unresolved_processing_failures"] == 0
    with SessionLocal() as db:
        assert unresolved_processing_failures(db, uuid.UUID(session["id"])) == 0
    another = create_session(client, token)
    foreign = client.post(f"/api/investigations/{another['id']}/local-processing-token", headers=auth(token), json=body)
    assert foreign.status_code == 404


def test_html_access_and_retired_formats(client, investigator, investigator2):
    token = investigator["token"]
    session = create_session(client, token)
    path, state = html_draft(client, token, session)
    assert client.get(path, headers=auth(investigator2["token"])).status_code == 404
    assert client.get('/api/report-forms/m53', headers=auth(token)).status_code == 410
    assert client.post('/api/report-templates', headers=auth(token), json={}).status_code == 410
    document = fill_note(state)
    document["investigator_id"] = str(uuid.uuid4())
    assert client.put(path, headers=auth(token), json={"expected_token": state["token"], "document": document}).status_code == 422


def test_scan_removal_retains_bytes_and_allows_a_new_version(client, investigator):
    import base64
    token = investigator["token"]
    session = create_session(client, token, subjects=[{"subject_name": "Person", "documents": [{"document_type": "PASSPORT"}]}])
    document = session["subjects"][0]["documents"][0]
    url = f"/api/investigations/{session['id']}/subject-documents/{document['id']}"
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5ioAAAAASUVORK5CYII=")
    uploaded = client.post(url + '/file', headers=auth(token), files={"file": ("scan.png", png, "image/png")})
    assert uploaded.status_code == 201, uploaded.text
    assert client.delete(url + '/file', headers=auth(token)).status_code == 204
    historical = client.get(url + '/versions/1/file', headers=auth(token))
    assert historical.status_code == 200 and historical.content == png
    assert client.post(url + '/file', headers=auth(token), files={"file": ("next.png", png, "image/png")}).status_code == 201
    assert client.get(url + '/versions/1/file', headers=auth(token)).content == png
    current = client.get(f"/api/investigations/{session['id']}", headers=auth(token)).json()
    subject = current["subjects"][0]
    retired = client.put(f"/api/investigations/{session['id']}", headers=auth(token), json={
        "expected_revision": current["revision"], "subjects": [], "removed_participant_keys": [subject["participant_key"]]})
    assert retired.status_code == 200, retired.text
    assert client.delete(url + '/file', headers=auth(token)).status_code == 409
    assert client.get(url + '/file', headers=auth(token)).content == png
    assert client.get(url + '/versions/1/file', headers=auth(token)).content == png


def test_pdf_failure_leaves_draft_editable_and_unissued(client, investigator, monkeypatch):
    from app.services import report_document
    token = investigator["token"]
    session = create_session(client, token)
    path, state = html_draft(client, token, session)
    state = save(client, token, path, state, fill_note(state))
    assert review(client, token, path, state).status_code == 200
    def fail(_):
        raise RuntimeError("renderer unavailable")
    monkeypatch.setattr(report_document, "pdf_from_html", fail)
    result = client.post(f"/api/investigations/{session['id']}/reports", headers=auth(token), json={"expected_token": state["token"]})
    assert result.status_code == 503
    current = client.get(path, headers=auth(token)).json()
    assert current["status"] == "DRAFT"
    assert client.get(f"/api/investigations/{session['id']}/reports", headers=auth(token)).json()["reports"] == []


def test_closure_requires_current_report_and_freezes_edits(client, investigator, monkeypatch):
    from app.services import report_document
    monkeypatch.setattr(report_document, "pdf_from_html", lambda _: b"%PDF-test-artifact")
    token = investigator["token"]
    session = create_session(client, token)
    path, state = html_draft(client, token, session)
    state = save(client, token, path, state, fill_note(state))
    assert review(client, token, path, state).status_code == 200
    assert client.post(f"/api/investigations/{session['id']}/reports", headers=auth(token), json={"expected_token": state["token"]}).status_code == 201
    base = f"/api/investigations/{session['id']}"
    for target in ["IN_PROGRESS", "AWAITING_REVIEW", "REVIEWED", "CLOSED"]:
        current = client.get(base, headers=auth(token)).json()
        result = client.post(base + '/workflow', headers=auth(token), json={"expected_revision": current["revision"], "state": target, "reason": "Human review"})
        assert result.status_code == 200, result.text
    current = client.get(base, headers=auth(token)).json()
    assert client.put(base, headers=auth(token), json={"expected_revision": current["revision"], "title": "Forbidden edit"}).status_code == 409
    assert client.post(path.removesuffix('/html') + '/reopen', headers=auth(token), json={"expected_token": state["token"], "reason": "   "}).status_code == 422
    assert client.post(base + '/workflow', headers=auth(token), json={"expected_revision": current["revision"], "state": "IN_PROGRESS", "reason": "New evidence"}).status_code == 200


def test_verified_audio_hash_cannot_be_replaced_by_result_metadata(client, investigator):
    import hashlib
    token = investigator["token"]
    session = create_session(client, token)
    job = request_token(client, token, session["id"])
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
        audio.writeframes(b'\0\0' * 16000)
    data = buffer.getvalue()
    audio_url = f"/api/local-processing/{job['job_id']}/audio"
    upload = client.post(audio_url, headers=auth(job["processing_token"]), files={"file": ("recording.wav", data, "audio/wav")})
    assert upload.status_code == 201, upload.text
    result = sample_result()
    result["audio"]["sha256"] = 'b' * 64
    response = client.post(f"/api/local-processing/{job['job_id']}/result", headers=auth(job["processing_token"]), json=result)
    assert response.status_code == 409, response.text
    result["audio"]["sha256"] = hashlib.sha256(data).hexdigest()
    assert client.post(f"/api/local-processing/{job['job_id']}/result", headers=auth(job["processing_token"]), json=result).status_code == 200

    from app.models import AudioRecording
    from app.services.workflow import evidence_blockers
    from app.services.storage import absolute_path
    with SessionLocal() as db:
        current = db.get(InvestigationSession, uuid.UUID(session["id"]))
        recording = db.scalar(select(AudioRecording).where(AudioRecording.session_id == current.id))
        path = absolute_path(recording.storage_path)
        assert path is not None and not evidence_blockers(db, current, verify_hashes=True)
        path.write_bytes(data + b"changed after verification")
        assert "original_audio_integrity_failed" in evidence_blockers(db, current, verify_hashes=True)
        path.unlink()
        assert "original_audio_missing" in evidence_blockers(db, current)


def test_report_revision_rejects_stale_save_after_content_changes_back(client, investigator):
    token = investigator["token"]
    session = create_session(client, token)
    path, state = html_draft(client, token, session)
    document = fill_note(state)
    first = save(client, token, path, state, document)
    changed = {**deepcopy(document), "subject": "Temporary wording"}
    second = save(client, token, path, first, changed)
    third = save(client, token, path, second, document)
    assert third["token"] != first["token"]
    assert client.put(path, headers=auth(token), json={"expected_token": first["token"], "document": changed}).status_code == 409


def test_downstream_defaults_clear_and_explicit_overrides_keep_provenance(client, investigator):
    token = investigator["token"]
    session = create_session(client, token)
    participant = session["subjects"][0]
    path, state = html_draft(client, token, session)
    document = deepcopy(state["document"])
    document["blocks"] = [{"id": str(uuid.uuid4()), "type": "statement", "participant_key": participant["participant_key"],
        "values": {"father_name": "Explicit override", "phone": participant["statement_details"]["phone"]}, "entries": []}]
    state = save(client, token, path, state, document)
    updated = client.put(f"/api/investigations/{session['id']}", headers=auth(token), json={
        "expected_revision": session["revision"], "subjects": [{"participant_key": participant["participant_key"],
            "subject_name": participant["subject_name"], "statement_details": {**participant["statement_details"], "father_name": "Current", "phone": ""}, "field_exceptions": {"phone": {"status": "UNKNOWN", "reason": "Number no longer available"}}}]})
    assert updated.status_code == 200, updated.text
    assert client.put(path, headers=auth(token), json={"expected_token": state["token"], "document": document}).status_code == 409
    result = client.get(path, headers=auth(token)).json()
    block = result["document"]["blocks"][0]
    assert block["values"]["father_name"] == "Explicit override"
    assert "Number no longer available" in block["values"]["phone"]
    assert block["person_snapshot"]["values"]["father_name"] == "Current"
    assert "father_name" in block["person_snapshot"]["overrides"]
    assert result["sources_changed"] and result["source_changes"]
