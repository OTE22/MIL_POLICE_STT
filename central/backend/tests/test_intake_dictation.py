"""Expanded intake/report/voice boundary checks; synthetic sync is not real-engine proof."""
import hashlib
import io
import uuid
import wave
import pytest
from copy import deepcopy
from sqlalchemy import select, func
from app.db.session import SessionLocal
from app.models import AudioRecording, Transcript, SessionSpeaker, LocalProcessingJob, Subject
from app.services.report_html import editable_document
from conftest import auth, create_session, sample_result


def draft(client, token, session):
    path = f"/api/investigations/{session['id']}/report/html"
    response = client.post(path, headers=auth(token))
    assert response.status_code == 200, response.text
    state = response.json()
    document = state["document"]
    document["blocks"] = [
        {"id": str(uuid.uuid4()), "type": "note", "values": {"note_text": "Existing note", "closing_date": "2026-10-26", "closing_location": "Beirut"}},
        {"id": str(uuid.uuid4()), "type": "conclusion", "values": {"facts": "Evidence reviewed", "inference": "Assessment", "closing_date": "2026-10-26", "closing_location": "Beirut"},
         "responsibility_mode": "NONE", "proposal_mode": "NONE", "findings": []}]
    response = client.put(path, headers=auth(token), json={"expected_token": state["token"], "document": document})
    assert response.status_code == 200, response.text
    return path, response.json()


def wav_bytes():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000)
        output.writeframes(b"\0\0" * 48000)
    return stream.getvalue()


def start(client, token, session, state, **overrides):
    body = {"expected_token": state["token"], "block_id": state["document"]["blocks"][0]["id"],
        "field": "note_text", "original_filename": "dictation.wav", "mime_type": "audio/wav",
        "size_bytes": len(wav_bytes()), "source": "BROWSER_RECORDING"}
    body.update(overrides)
    return client.post(f"/api/investigations/{session['id']}/report/dictations", headers=auth(token), json=body)


def test_incomplete_draft_persists_but_new_work_is_blocked(client, investigator):
    token = investigator["token"]
    session = create_session(client, token, subjects=[{"subject_name": "Incomplete", "person_type": "MILITARY"}])
    assert session["intake_readiness"]["ready"] is False
    issues = session["intake_readiness"]["issues"]
    assert {"father_name", "prior_record_statement", "rank", "unit", "military_id", "security_branch"} <= {i["field"] for i in issues}
    assert all(i["participant_key"] == session["subjects"][0]["participant_key"] for i in issues)
    base = f"/api/investigations/{session['id']}"
    for suffix, body in [("/report/html", {}), ("/local-processing-token", {
        "original_filename": "new.wav", "mime_type": "audio/wav", "size_bytes": 1000})]:
        result = client.post(base + suffix, headers=auth(token), json=body)
        assert result.status_code == 409, result.text
        assert result.json()["detail"]["code"] == "participant_details_incomplete"


def test_exceptions_are_validated_stamped_and_never_written_into_facts(client, investigator):
    token = investigator["token"]
    session = create_session(client, token, subjects=[{"subject_name": "Recorded designation", "person_type": "CIVILIAN"}])
    person = session["subjects"][0]
    exceptions = {i["field"]: {"status": "REFUSED", "reason": "Declined during intake", "by": "forged"}
                  for i in session["intake_readiness"]["issues"] if i["participant_key"]}
    base = f"/api/investigations/{session['id']}"
    def save(values):
        return client.put(base, headers=auth(token), json={"expected_revision": session["revision"], "subjects": [
            {"participant_key": person["participant_key"], "subject_name": person["subject_name"], "field_exceptions": values}]})
    invalid = deepcopy(exceptions); invalid["birth_year"]["reason"] = 123
    assert save(invalid).status_code == 422
    invalid = deepcopy(exceptions); invalid["father_name"]["status"] = "NOT_APPLICABLE"
    assert save(invalid).status_code == 422
    result = save(exceptions)
    assert result.status_code == 200, result.text
    assert result.json()["intake_readiness"]["ready"]
    saved = result.json()["subjects"][0]
    assert saved["statement_details"] == {}
    assert saved["field_exceptions"]["father_name"]["by"] == investigator["user"]["id"]
    assert saved["field_exceptions"]["father_name"]["at"]
    assert saved["id"] == person["id"]


def test_dictation_never_creates_testimony_and_requires_explicit_acceptance(client, investigator):
    token = investigator["token"]
    session = create_session(client, token)
    path, state = draft(client, token, session)
    result = start(client, token, session, state)
    assert result.status_code == 200, result.text
    issued = result.json()
    voicepath = path.removesuffix("/html") + "/dictations"
    refreshed = client.get(path, headers=auth(token)).json()
    assert "report_dictation_pending" in refreshed["blocked_reasons"]
    payload = sample_result(); payload["audio"]["sha256"] = hashlib.sha256(wav_bytes()).hexdigest()
    result_path = f"/api/local-processing/{issued['job_id']}"
    synced = client.post(result_path + "/result", headers=auth(issued["processing_token"]), json=payload)
    assert synced.status_code == 200, synced.text
    assert synced.json()["transcript_id"] is None
    assert client.post(result_path + "/result", headers=auth(issued["processing_token"]), json=payload).json()["duplicate"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Transcript)) == 0
        assert db.scalar(select(func.count()).select_from(SessionSpeaker)) == 0
        assert db.scalar(select(AudioRecording).where(AudioRecording.id == uuid.UUID(issued["recording_id"]))).purpose == "REPORT_DICTATION"
    session_view = client.get(f"/api/investigations/{session['id']}", headers=auth(token)).json()
    assert session_view["recordings"] == [] and session_view["processing_summary"] == {}
    row = client.get(voicepath, headers=auth(token)).json()[0]
    accept_body = {"expected_token": state["token"], "expected_text_token": row["text_token"], "text": "Reviewed dictation", "mode": "APPEND"}
    assert client.post(voicepath + f"/{row['id']}/accept", headers=auth(token), json=accept_body).status_code == 409
    uploaded = client.post(result_path + "/audio", headers=auth(issued["processing_token"]), files={"file": ("dictation.wav", wav_bytes(), "audio/wav")})
    assert uploaded.status_code == 201, uploaded.text
    accepted = client.post(voicepath + f"/{row['id']}/accept", headers=auth(token), json=accept_body)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["document"]["blocks"][0]["values"]["note_text"] == "Existing note\nReviewed dictation"
    assert "report_dictation_pending" not in accepted.json()["blocked_reasons"]
    duplicate = client.post(voicepath + f"/{row['id']}/accept", headers=auth(token), json=accept_body)
    assert duplicate.status_code == 200 and duplicate.json()["token"] == accepted.json()["token"]
    assert client.post(path, headers=auth(token)).status_code == 200


def test_dictation_cannot_target_fixed_words_or_another_session(client, investigator, investigator2):
    token = investigator["token"]
    session = create_session(client, token)
    _, state = draft(client, token, session)
    assert start(client, token, session, state, field="attestation").status_code == 422
    assert start(client, token, session, state, block_id=str(uuid.uuid4())).status_code == 409
    assert start(client, investigator2["token"], session, state).status_code == 404


@pytest.mark.parametrize("destination", ["proposals", "finding", "inference"])
def test_conclusion_dictation_appends_to_selected_field_only(client, investigator, destination):
    token = investigator["token"]
    session = create_session(client, token)
    path, state = draft(client, token, session)
    document = editable_document(state["document"])
    conclusion = document["blocks"][1]
    finding_id = str(uuid.uuid4())
    conclusion.update(responsibility_mode="FINDINGS", proposal_mode="TEXT", findings=[{
        "id": finding_id, "participant_key": session["subjects"][0]["participant_key"],
        "unidentified_subject": "", "text": "Existing responsibility", "references": {
            "participants": [], "recordings": [], "documents": [], "blocks": [document["blocks"][0]["id"]]}}])
    conclusion["values"]["proposals"] = "Existing proposals"
    conclusion["values"]["inference"] = "Existing inference"
    saved = client.put(path, headers=auth(token), json={"expected_token": state["token"], "document": document})
    assert saved.status_code == 200, saved.text
    state = saved.json()
    field = "finding:" + finding_id if destination == "finding" else destination
    result = start(client, token, session, state, block_id=conclusion["id"], field=field)
    assert result.status_code == 200, result.text
    issued = result.json()
    payload = sample_result(); payload["audio"]["sha256"] = hashlib.sha256(wav_bytes()).hexdigest()
    result_path = f"/api/local-processing/{issued['job_id']}"
    assert client.post(result_path + "/result", headers=auth(issued["processing_token"]), json=payload).status_code == 200
    assert client.post(result_path + "/audio", headers=auth(issued["processing_token"]), files={"file": ("dictation.wav", wav_bytes(), "audio/wav")}).status_code == 201
    voicepath = path.removesuffix("/html") + "/dictations"
    row = client.get(voicepath, headers=auth(token)).json()[0]
    assert row["field"] == field and row["block_id"] == conclusion["id"]
    accepted = client.post(voicepath + f"/{row['id']}/accept", headers=auth(token), json={
        "expected_token": state["token"], "expected_text_token": row["text_token"], "text": "Reviewed addition", "mode": "APPEND"})
    assert accepted.status_code == 200, accepted.text
    blocks = accepted.json()["document"]["blocks"]
    assert blocks[0]["values"]["note_text"] == "Existing note"
    assert blocks[1]["values"]["proposals"] == "Existing proposals" + ("\nReviewed addition" if destination == "proposals" else "")
    assert blocks[1]["values"]["inference"] == "Existing inference" + ("\nReviewed addition" if destination == "inference" else "")
    assert blocks[1]["findings"][0]["text"] == "Existing responsibility" + ("\nReviewed addition" if destination == "finding" else "")
    assert blocks[1]["findings"][0]["references"] == conclusion["findings"][0]["references"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Transcript)) == 0
        assert db.scalar(select(func.count()).select_from(SessionSpeaker)) == 0


def test_batch_statements_and_conclusion_reference_scope(client, investigator):
    token = investigator["token"]
    session = create_session(client, token)
    path, state = draft(client, token, session)
    key = session["subjects"][0]["participant_key"]
    response = client.post(path + "/prepare-statements", headers=auth(token), json={"expected_token": state["token"], "participant_keys": [key]})
    assert response.status_code == 200, response.text
    block = response.json()["blocks"][0]
    assert block["values"]["prior_record_statement"] == session["subjects"][0]["statement_details"]["prior_record_statement"]
    document = editable_document(state["document"])
    document["blocks"][1]["references"]["recordings"] = [str(uuid.uuid4())]
    response = client.put(path, headers=auth(token), json={"expected_token": state["token"], "document": document})
    assert response.status_code == 422


def test_transcript_review_is_explicit_revision_bound_and_required_for_import(client, investigator, investigator2):
    from report_test_helpers import _interview, _create
    token = investigator["token"]
    session = _interview(client, token)
    base = f"/api/investigations/{session['id']}"
    prepared = _create(client, token, session["id"])
    transcript = client.get(base + "/transcript", headers=auth(token)).json()
    assert transcript["reviewed"]
    options = client.get(base + "/transcripts", headers=auth(token)).json()
    assert options[0]["id"] == transcript["id"] and options[0]["reviewed"]
    selected_path = base + "/transcript?recording_id=" + transcript["recording_id"]
    assert client.get(selected_path, headers=auth(token)).json()["id"] == transcript["id"]
    assert client.get(base + "/transcript?recording_id=" + str(uuid.uuid4()), headers=auth(token)).status_code == 404
    assert client.get(selected_path, headers=auth(investigator2["token"])).status_code == 404
    selection = {"speaker_id": prepared["qa_blocks"][0]["answer_speaker_id"]}
    assert client.post(base + "/report/html/statement-preview", headers=auth(token), json=selection).status_code == 200
    segment = transcript["segments"][1]
    edited = client.patch(f"/api/transcript-segments/{segment['id']}", headers=auth(token), json={
        "expected_revision": segment["revision"], "edited_text": "Reviewed correction"})
    assert edited.status_code == 200
    current = client.get(base + "/transcript", headers=auth(token)).json()
    assert not current["reviewed"] and current["segments"][1]["original_text"] == segment["original_text"]
    review_path = base + f"/transcripts/{transcript['id']}/review"
    assert client.post(review_path, headers=auth(token), json={"expected_token": transcript["current_review_token"]}).status_code == 409
    assert client.post(review_path, headers=auth(investigator2["token"]), json={"expected_token": current["current_review_token"]}).status_code == 404
    blocked = client.post(base + "/report/html/statement-preview", headers=auth(token), json=selection)
    assert blocked.status_code == 422 and blocked.json()["detail"] == "html_report_transcript_review_required"
    assert client.post(review_path, headers=auth(token), json={"expected_token": current["current_review_token"]}).status_code == 200
    # Direct edits of fixed template wording are not a review action; imports retain original evidence.
    assert client.get(base + "/transcript", headers=auth(token)).json()["reviewed"]


def test_dictation_destination_change_and_dismissal_preserve_machine_result(client, investigator):
    token = investigator["token"]
    session = create_session(client, token)
    path, state = draft(client, token, session)
    issued = start(client, token, session, state).json()
    voicepath = path.removesuffix("/html") + "/dictations"
    initial = client.get(voicepath, headers=auth(token)).json()[0]
    document = editable_document(state["document"])
    document["blocks"][0]["values"]["note_text"] = "New wording while dictation is processing"
    changed = client.put(path, headers=auth(token), json={"expected_token": state["token"], "document": document})
    assert changed.status_code == 200
    row = client.get(voicepath, headers=auth(token)).json()[0]
    assert row["destination_changed"] and row["text_token"] != initial["text_token"]
    assert client.post(voicepath + f"/{row['id']}/dismiss", headers=auth(token), json={"reason": "   "}).status_code == 422
    assert client.post(voicepath + f"/{row['id']}/dismiss", headers=auth(token), json={"reason": "Investigator discarded duplicate narration"}).status_code == 200
    payload = sample_result()
    result = client.post(f"/api/local-processing/{issued['job_id']}/result", headers=auth(issued["processing_token"]), json=payload)
    assert result.status_code == 200
    row = client.get(voicepath, headers=auth(token)).json()[0]
    assert row["status"] == "DISMISSED" and row["machine_text"]
    assert client.get(path, headers=auth(token)).json()["document"]["blocks"][0]["values"]["note_text"] == "New wording while dictation is processing"


def test_every_recording_remains_reviewable_and_speakers_resolve_merged_identity(client, investigator):
    from report_test_helpers import _interview, _submit
    from app.models import PersonIdentity
    token = investigator['token']
    session = _interview(client, token)
    base = f"/api/investigations/{session['id']}"
    first = client.get(base + '/transcript', headers=auth(token)).json()
    _submit(client, token, session['id'], [('SPEAKER_00', 'Another question'), ('SPEAKER_01', 'Another answer')])
    second = client.get(base + '/transcript', headers=auth(token)).json()
    assert second['id'] != first['id'] and not second['reviewed']
    rows = client.get(base + '/transcripts', headers=auth(token)).json()
    assert len(rows) == 2 and rows[0]['id'] == second['id']
    selected = client.get(base + '/transcript?recording_id=' + first['recording_id'], headers=auth(token)).json()
    assert selected['id'] == first['id'] and selected['reviewed']
    with SessionLocal() as db:
        survivor = PersonIdentity(person_name='Canonical surviving person')
        db.add(survivor); db.flush()
        old = PersonIdentity(person_name='Historical alias', merged_into_id=survivor.id)
        db.add(old); db.flush()
        speaker = db.scalar(select(SessionSpeaker).where(SessionSpeaker.recording_id == uuid.UUID(first['recording_id'])))
        speaker.identity_id = old.id
        survivor_id = str(survivor.id)
        speaker_id = str(speaker.id)
        db.commit()
    selected = client.get(base + '/transcript?recording_id=' + first['recording_id'], headers=auth(token)).json()
    speaker = next(row for row in selected['speakers'] if row['id'] == speaker_id)
    assert speaker['identity_id'] == survivor_id and speaker['identity_name'] == 'Canonical surviving person'
    assert not selected['reviewed']


def test_canonical_changes_update_only_untouched_unreviewed_draft_facts(client, investigator):
    from conftest import update_session
    token = investigator["token"]
    session = create_session(client, token)
    path, state = draft(client, token, session)
    person = session["subjects"][0]
    block = client.post(path + "/statement-preview", headers=auth(token), json={"participant_key": person["participant_key"]}).json()
    document = editable_document(state["document"])
    document["blocks"].insert(0, {**block, "values": {**block["values"], "education": "Explicit report override"}})
    saved = client.put(path, headers=auth(token), json={"expected_token": state["token"], "document": editable_document(document)})
    assert saved.status_code == 200, saved.text
    current = saved.json()
    result = update_session(client, path.removesuffix("/report/html"), headers=auth(token), json={"subjects": [{
        "participant_key": person["participant_key"], "subject_name": person["subject_name"],
        "statement_details": {**person["statement_details"], "father_name": "Corrected father", "education": "Updated education"}}]})
    assert result.status_code == 200, result.text
    changed = client.get(path, headers=auth(token)).json()
    assert changed["token"] != current["token"]
    assert changed["document"]["blocks"][0]["values"]["father_name"] == "Corrected father"
    assert changed["document"]["blocks"][0]["values"]["education"] == "Explicit report override"
    # A reviewed draft is frozen even when the source is corrected later.
    from app.models import ReportDraft
    with SessionLocal() as db:
        row = db.scalar(select(ReportDraft).where(ReportDraft.session_id == uuid.UUID(session["id"])))
        row.official_form = {**row.official_form, "html_review": {"token": "prior-reviewed-version"}}
        db.commit()
    result = update_session(client, path.removesuffix("/report/html"), headers=auth(token), json={"subjects": [{
        "participant_key": person["participant_key"], "subject_name": person["subject_name"],
        "statement_details": {**person["statement_details"], "father_name": "Later correction"}}]})
    assert result.status_code == 200
    final = client.get(path, headers=auth(token)).json()
    assert final["document"]["blocks"][0]["values"]["father_name"] == "Corrected father"
    assert final["sources_changed"] and not final["reviewed"]
