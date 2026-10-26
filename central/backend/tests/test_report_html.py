"""Repeatable statements, source provenance, session permissions and legacy coexistence."""
import uuid
from copy import deepcopy

from app.db.session import SessionLocal
from app.models import ReportDraft, ReportStatus
from conftest import auth, create_session
from report_test_helpers import _interview, _create
from test_report_draft import _evidence_fingerprint


def _block(name="شخص تجريبي"):
    return {"id": str(uuid.uuid4()), "type": "statement", "speaker_id": None,
            "values": {"statement_name": name}, "identity_checked": False, "attestation_confirmed": False,
            "entries": [{"id": str(uuid.uuid4()), "question": "سؤال", "answer": "جواب", "source_block_ids": []}]}


def _setup(client, investigator):
    token = investigator["token"]
    session = _interview(client, token)
    draft = _create(client, token, session["id"])
    path = f"/api/investigations/{session['id']}/report/html"
    state = client.get(path, headers=auth(token)).json()
    return token, session, draft, path, state


def _note(text="لم ترد نتيجة الفحص بعد."):
    return {"id": str(uuid.uuid4()), "type": "note", "values": {
        "note_date": "24/10/2026", "note_time": "13:30", "note_text": text,
        "closing_location": "مكان تجريبي", "closing_date": "24/10/2026",
        "clerk_name": "كاتب تجريبي", "investigator_name": "محقق تجريبي"}}


def _save(client, token, path, state, document):
    return client.put(path, headers=auth(token), json={"expected_token": state["token"], "document": document})


def test_multiple_statements_save_reorder_and_preserve_evidence(client, investigator):
    token, session, draft, path, state = _setup(client, investigator)
    before = _evidence_fingerprint(session["id"])
    document = {**state["document"], "subject": "محضر تجريبي", "blocks": [_block("الأول"), _block("الثاني"), _block("الثالث")]}
    result = _save(client, token, path, state, document)
    assert result.status_code == 200, result.text
    saved = result.json()
    assert [b["values"]["statement_name"] for b in saved["document"]["blocks"]] == ["الأول", "الثاني", "الثالث"]
    document["blocks"].reverse()
    assert _save(client, token, path, saved, document).status_code == 200
    restored = client.get(path, headers=auth(token)).json()
    assert [b["values"]["statement_name"] for b in restored["document"]["blocks"]] == ["الثالث", "الثاني", "الأول"]
    assert _evidence_fingerprint(session["id"]) == before


def test_html_draft_rejects_foreign_access_stale_save_and_duplicate_ids(client, investigator, investigator2):
    token, _, _, path, state = _setup(client, investigator)
    assert client.get(path).status_code == 401
    assert client.get(path, headers=auth(investigator2["token"])).status_code == 404
    document = {**state["document"], "blocks": [_block()]}
    assert _save(client, investigator2["token"], path, state, document).status_code == 404
    assert _save(client, token, path, state, document).status_code == 200
    assert _save(client, token, path, state, document).status_code == 409
    current = client.get(path, headers=auth(token)).json()
    duplicate = {**document, "blocks": [document["blocks"][0], document["blocks"][0]]}
    assert _save(client, token, path, current, duplicate).status_code == 422
    document["investigator_id"] = str(uuid.uuid4())
    assert _save(client, token, path, current, document).status_code == 422
    document["investigator_id"] = None
    document["blocks"][0]["speaker_id"] = str(uuid.uuid4())
    assert _save(client, token, path, current, document).status_code == 422


def test_imports_get_server_source_snapshots_and_cannot_change_person(client, investigator):
    token, session, draft, path, state = _setup(client, investigator)
    qa = draft["qa_blocks"][0]
    block = _block()
    block["speaker_id"] = qa["answer_speaker_id"]
    block["entries"][0]["source_block_ids"] = [qa["id"]]
    document = {**state["document"], "blocks": [block, _note()]}
    result = _save(client, token, path, state, document)
    assert result.status_code == 200, result.text
    snapshot = result.json()["document"]["blocks"][0]["entries"][0]["source_snapshot"][0]
    assert snapshot["source_segment_ids"] == qa["source_segment_ids"]
    assert snapshot["answer_source_text"] == qa["answer_source_text"]
    assert snapshot["start_seconds"] == qa["start_seconds"]
    state = result.json()
    refreshed = client.post(path + "/refresh-sources", headers=auth(token), json={"expected_token": state["token"]})
    assert refreshed.status_code == 200, refreshed.text
    state = refreshed.json()
    # Refresh replaces legacy QA rows; the imported HTML statement retains its evidence snapshot.
    preserved = _save(client, token, path, state, document)
    assert preserved.status_code == 200, preserved.text
    assert preserved.json()["document"]["blocks"][0]["entries"][0]["source_snapshot"][0] == snapshot
    state = preserved.json()
    block["speaker_id"] = qa["question_speaker_id"]
    assert _save(client, token, path, state, document).status_code == 422
    block["speaker_id"] = qa["answer_speaker_id"]
    block["entries"][0]["source_block_ids"] = [str(uuid.uuid4())]
    assert _save(client, token, path, state, document).status_code == 422
    block["entries"][0]["source_snapshot"] = [{"answer_source_text": "forged"}]
    assert _save(client, token, path, state, document).status_code == 422


def test_blank_mask_has_variables_and_does_not_inherit_the_sample_case(client, investigator):
    response = client.get("/api/report-forms/html-statement", headers=auth(investigator["token"]))
    assert response.status_code == 200
    template = response.json()
    assert "{statement_name}" in template["clauses"]["heading"]
    assert "{prior_record_statement}" in template["clauses"]["identity"]
    assert "نايف" not in response.text and "1981" not in response.text
    assert len(template["fields"]) == 21


def test_manual_html_report_can_start_without_audio_and_is_idempotent(client, investigator):
    token = investigator["token"]
    session = create_session(client, token)
    path = f"/api/investigations/{session['id']}/report/html"
    first = client.post(path, headers=auth(token))
    assert first.status_code == 200, first.text
    assert client.post(path, headers=auth(token)).json() == first.json()
    document = {**first.json()["document"], "blocks": [_block("إفادة يدوية")]}
    assert _save(client, token, path, first.json(), document).status_code == 200


def test_mixed_notes_and_statements_save_reorder_remove_and_restore(client, investigator):
    token, session, draft, path, state = _setup(client, investigator)
    before = _evidence_fingerprint(session["id"])
    # Existing statement-only drafts remain readable and editable after adding notes.
    statement = _block()
    first_save = _save(client, token, path, state, {**state["document"], "blocks": [statement]})
    assert first_save.status_code == 200
    state = first_save.json()
    first, second = _note(), _note("ملاحظة ثانية مستقلة.")
    document = {**state["document"], "blocks": [first, statement, second]}
    result = _save(client, token, path, state, document)
    assert result.status_code == 200, result.text
    assert result.json()["document"]["blocks"][0]["values"] == first["values"]
    assert result.json()["document"]["blocks"][2]["values"] == second["values"]
    assert result.json()["document"]["blocks"][0]["authorship"]["created_by"] == investigator["user"]["id"]
    state = result.json()
    # Re-saving exercises prior-source collection when existing blocks include notes.
    document["blocks"] = [second, first, statement]
    document["blocks"][1]["values"]["note_text"] = "تعديل الملاحظة الأولى."
    result = _save(client, token, path, state, document)
    assert result.status_code == 200, result.text
    assert result.json()["document"]["blocks"][0]["values"]["note_text"] == "ملاحظة ثانية مستقلة."
    state = result.json()
    document["blocks"] = [first, statement]
    result = _save(client, token, path, state, document)
    assert result.status_code == 200
    document["blocks"].insert(0, second)
    result = _save(client, token, path, result.json(), document)
    assert result.status_code == 200
    restored = client.get(path, headers=auth(token)).json()["document"]["blocks"]
    assert [b["id"] for b in restored] == [second["id"], first["id"], statement["id"]]
    assert _evidence_fingerprint(session["id"]) == before


def test_note_only_report_rejects_wrong_fields_sources_and_duplicate_ids(client, investigator):
    token, _, _, path, state = _setup(client, investigator)
    note = _note()
    document = {**state["document"], "blocks": [note]}
    result = _save(client, token, path, state, document)
    assert result.status_code == 200
    state = result.json()
    stored = client.get(path, headers=auth(token)).json()["document"]["blocks"]
    assert len(stored) == 1 and stored[0]["id"] == note["id"] and stored[0]["values"] == note["values"]
    for bad_note in [
        {**note, "speaker_id": str(uuid.uuid4())},
        {**note, "entries": []},
        {**note, "source_snapshot": []},
        {**note, "type": "unknown"},
        {**note, "values": {"statement_name": "اسم"}},
        {**note, "values": {"note_text": "x" * 40001}},
        {**note, "values": {"note_text": "نص\u202e"}},
    ]:
        invalid = {**document, "blocks": [bad_note]}
        assert _save(client, token, path, state, invalid).status_code == 422
    assert _save(client, token, path, state, {**document, "blocks": [note, deepcopy(note)]}).status_code == 422
    statement = _block()
    statement["entries"][0]["id"] = note["id"]
    assert _save(client, token, path, state, {**document, "blocks": [note, statement]}).status_code == 422
    assert client.get(path, headers=auth(token)).json() == state


def test_note_catalogue_has_seven_blank_variables(client, investigator):
    response = client.get("/api/report-forms/html-statement", headers=auth(investigator["token"]))
    assert response.status_code == 200
    template = response.json()["note"]
    assert len(template["fields"]) == 7
    assert "{note_text}" in template["clauses"]["body"]
    assert "{note_date}" in template["clauses"]["body"]
    assert "{note_time}" in template["clauses"]["body"]
    assert "اسكندر" not in response.text and "البندقية" not in response.text
