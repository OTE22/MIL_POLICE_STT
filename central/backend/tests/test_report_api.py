"""Phase 7 (backend half): the composer's endpoints.

Permission and session access are checked BEFORE anything is written, the draft is created
once and reused, and every Q&A operation leaves the transcript exactly as it found it.
"""

import uuid

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import SessionSpeaker, SpeakerRole, TranscriptSegment

from conftest import ADMIN, auth, create_session, request_token, sample_result
from test_report_draft import _evidence_fingerprint


def _login(client):
    return client.post("/api/auth/login", json=ADMIN).json()["access_token"]


def _submit(client, token, session_id, turns):
    tok = request_token(client, token, session_id)
    body = sample_result()
    body["segments"] = [
        {
            "speaker_label": label,
            "start_seconds": 1.0 + 3 * i,
            "end_seconds": 2.0 + 3 * i,
            "text": text,
            "is_overlap": False,
        }
        for i, (label, text) in enumerate(turns)
    ]
    body["speaker_count"] = len({label for label, _ in turns})
    res = client.post(
        f"/api/local-processing/{tok['job_id']}/result",
        json=body,
        headers=auth(tok["processing_token"]),
    )
    assert res.status_code == 200, res.text


def _interview(client, token):
    s = create_session(client, token)
    _submit(
        client,
        token,
        s["id"],
        [
            ("SPEAKER_00", "ما اسمك؟"),
            ("SPEAKER_01", "علي عباس"),
            ("SPEAKER_00", "أين كنت مساء أمس؟"),
            ("SPEAKER_01", "كنت في المنزل"),
        ],
    )
    with SessionLocal() as db:
        sid = uuid.UUID(s["id"])
        for label, role in (("SPEAKER_00", SpeakerRole.INVESTIGATOR), ("SPEAKER_01", SpeakerRole.SUBJECT)):
            row = db.scalar(
                select(SessionSpeaker).where(
                    SessionSpeaker.session_id == sid, SessionSpeaker.speaker_label == label
                )
            )
            row.speaker_role = role
        db.commit()
    return s


def _create(client, token, session_id):
    res = client.post(f"/api/investigations/{session_id}/report", headers=auth(token))
    assert res.status_code in (200, 201), res.text
    return res.json()


# --------------------------------------------------------------------- access


def test_a_draft_needs_authentication_and_permission(client, investigator):
    s = _interview(client, investigator["token"])
    assert client.post(f"/api/investigations/{s['id']}/report").status_code == 401
    # A read-only USER may look at a report but never create one.
    from conftest import create_user, login

    admin_token = _login(client)
    create_user(client, admin_token, "ro_reports", ["USER"], full_name="مراقب", military_id="M-7788")
    ro = login(client, "ro_reports", "Password!1234")
    assert client.post(f"/api/investigations/{s['id']}/report", headers=auth(ro)).status_code in (403, 404)


def test_a_session_the_user_cannot_open_hides_its_report(client, investigator, investigator2):
    s = _interview(client, investigator["token"])
    _create(client, investigator["token"], s["id"])
    res = client.get(f"/api/investigations/{s['id']}/report", headers=auth(investigator2["token"]))
    assert res.status_code == 404, "a session you cannot see must not leak through its report"


def test_getting_a_draft_before_it_exists_is_404(client, investigator):
    s = _interview(client, investigator["token"])
    res = client.get(f"/api/investigations/{s['id']}/report", headers=auth(investigator["token"]))
    assert res.status_code == 404
    assert res.json()["detail"] == "report_draft_not_found"


def test_a_session_with_no_transcript_cannot_start_a_report(client, investigator):
    s = create_session(client, investigator["token"])
    res = client.post(f"/api/investigations/{s['id']}/report", headers=auth(investigator["token"]))
    assert res.status_code == 409
    assert res.json()["detail"] == "report_no_transcripts"


# --------------------------------------------------------------------- creation


def test_creating_a_draft_builds_the_qa_and_lists_the_material(client, investigator):
    s = _interview(client, investigator["token"])
    body = _create(client, investigator["token"], s["id"])

    assert body["status"] == "DRAFT"
    assert body["transcript_source_mode"] == "CORRECTED"
    assert [(b["report_question_text"], b["report_answer_text"]) for b in body["qa_blocks"]] == [
        ("ما اسمك؟", "علي عباس"),
        ("أين كنت مساء أمس؟", "كنت في المنزل"),
    ]
    assert len(body["recordings"]) == 1 and body["recordings"][0]["selected"] is True
    assert {sp["speaker_label"] for sp in body["speakers"]} == {"SPEAKER_00", "SPEAKER_01"}
    # The header fields nobody has filled in yet are reported in Arabic.
    assert "رقم المحضر" in body["missing_fields"]
    assert body["stale"] == []
    assert body["report_version_count"] == 0


def test_opening_the_composer_twice_reuses_one_draft(client, investigator):
    s = _interview(client, investigator["token"])
    first = _create(client, investigator["token"], s["id"])
    second = _create(client, investigator["token"], s["id"])
    assert first["id"] == second["id"]


def test_creating_a_draft_does_not_touch_the_evidence(client, investigator):
    s = _interview(client, investigator["token"])
    before = _evidence_fingerprint(s["id"])
    _create(client, investigator["token"], s["id"])
    assert _evidence_fingerprint(s["id"]) == before


# --------------------------------------------------------------------- editing


def test_header_fields_save_and_clear_the_missing_list(client, investigator):
    t = investigator["token"]
    s = _interview(client, t)
    _create(client, t, s["id"])
    res = client.put(
        f"/api/investigations/{s['id']}/report",
        json={
            "report_number": "2026/145",
            "case_subject": "تحقيق تجريبي",
            "location": "ثكنة بيروت",
            "report_date": "2026-08-29",
            "closing_text": "خُتم المحضر",
        },
        headers=auth(t),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["report_number"] == "2026/145"
    assert body["missing_fields"] == []
    assert body["closing_text"] == "خُتم المحضر"


def test_editing_a_block_changes_the_report_not_the_transcript(client, investigator):
    t = investigator["token"]
    s = _interview(client, t)
    draft = _create(client, t, s["id"])
    before = _evidence_fingerprint(s["id"])
    block = draft["qa_blocks"][0]

    res = client.patch(
        f"/api/investigations/{s['id']}/report/blocks/{block['id']}",
        json={"report_question_text": "ما هو اسمك الكامل؟"},
        headers=auth(t),
    )
    assert res.status_code == 200, res.text
    updated = res.json()["qa_blocks"][0]
    assert updated["report_question_text"] == "ما هو اسمك الكامل؟"
    assert updated["question_source_text"] == "ما اسمك؟", "the source copy is untouched"
    assert _evidence_fingerprint(s["id"]) == before


def test_exclude_and_restore_round_trip(client, investigator):
    t = investigator["token"]
    s = _interview(client, t)
    draft = _create(client, t, s["id"])
    block_id = draft["qa_blocks"][0]["id"]

    res = client.post(
        f"/api/investigations/{s['id']}/report/blocks/{block_id}/exclude",
        json={"reason": "اختبار الميكروفون"},
        headers=auth(t),
    )
    assert res.status_code == 200, res.text
    excluded = [b for b in res.json()["qa_blocks"] if b["id"] == block_id][0]
    assert excluded["included_in_report"] is False
    assert excluded["exclusion_reason"] == "اختبار الميكروفون"
    assert excluded["answer_source_text"], "the evidence text is still there"

    res = client.post(
        f"/api/investigations/{s['id']}/report/blocks/{block_id}/restore", headers=auth(t)
    )
    restored = [b for b in res.json()["qa_blocks"] if b["id"] == block_id][0]
    assert restored["included_in_report"] is True


def test_merge_and_split_through_the_api(client, investigator):
    t = investigator["token"]
    s = _interview(client, t)
    draft = _create(client, t, s["id"])
    first, second = draft["qa_blocks"][0]["id"], draft["qa_blocks"][1]["id"]

    res = client.post(
        f"/api/investigations/{s['id']}/report/blocks/{first}/merge",
        json={"with_block_id": second},
        headers=auth(t),
    )
    assert res.status_code == 200, res.text
    merged = res.json()["qa_blocks"]
    assert len(merged) == 1
    assert [b["sequence"] for b in merged] == [1]

    res = client.post(
        f"/api/investigations/{s['id']}/report/blocks/{merged[0]['id']}/split",
        json={"answer_head": "علي عباس.", "answer_tail": "كنت في المنزل."},
        headers=auth(t),
    )
    assert res.status_code == 200, res.text
    blocks = res.json()["qa_blocks"]
    assert len(blocks) == 2
    assert [b["sequence"] for b in blocks] == [1, 2]
    assert blocks[0]["report_answer_text"] == "علي عباس."
    assert blocks[1]["report_answer_text"] == "كنت في المنزل."


def test_a_block_from_another_session_is_not_reachable(client, investigator):
    t = investigator["token"]
    mine = _interview(client, t)
    other = _interview(client, t)
    _create(client, t, mine["id"])
    other_draft = _create(client, t, other["id"])
    foreign_block = other_draft["qa_blocks"][0]["id"]

    res = client.patch(
        f"/api/investigations/{mine['id']}/report/blocks/{foreign_block}",
        json={"report_answer_text": "لا"},
        headers=auth(t),
    )
    assert res.status_code == 404


# --------------------------------------------------------------------- selection & staleness


def test_selecting_recordings_rebuilds_the_dialogue(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)
    _submit(client, t, s["id"], [("SPEAKER_00", "من التسجيل الأول")])
    _submit(client, t, s["id"], [("SPEAKER_00", "من التسجيل الثاني")])
    draft = _create(client, t, s["id"])
    assert len(draft["qa_blocks"]) == 2

    keep = draft["recordings"][0]["id"]
    res = client.put(
        f"/api/investigations/{s['id']}/report",
        json={"selected_recording_ids": [keep]},
        headers=auth(t),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["qa_blocks"]) == 1
    assert "من التسجيل الأول" in body["qa_blocks"][0]["report_answer_text"]
    assert [r["selected"] for r in body["recordings"]] == [True, False]


def test_an_empty_or_unknown_recording_selection_is_refused(client, investigator):
    t = investigator["token"]
    s = _interview(client, t)
    _create(client, t, s["id"])
    assert (
        client.put(
            f"/api/investigations/{s['id']}/report",
            json={"selected_recording_ids": []},
            headers=auth(t),
        ).status_code
        == 422
    )
    res = client.put(
        f"/api/investigations/{s['id']}/report",
        json={"selected_recording_ids": [str(uuid.uuid4())]},
        headers=auth(t),
    )
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "report_recording_not_available"


def test_switching_to_the_original_text_requotes_the_report(client, investigator):
    t = investigator["token"]
    s = _interview(client, t)
    with SessionLocal() as db:
        seg = db.scalars(select(TranscriptSegment).order_by(TranscriptSegment.sequence)).all()[0]
        seg.edited_text = "سؤال مصحح؟"
        db.commit()

    draft = _create(client, t, s["id"])
    assert draft["qa_blocks"][0]["report_question_text"] == "سؤال مصحح؟"

    res = client.put(
        f"/api/investigations/{s['id']}/report",
        json={"transcript_source_mode": "ORIGINAL"},
        headers=auth(t),
    )
    assert res.status_code == 200, res.text
    assert res.json()["qa_blocks"][0]["report_question_text"] == "ما اسمك؟"


def test_a_later_transcript_edit_marks_the_draft_stale_without_changing_it(client, investigator):
    t = investigator["token"]
    s = _interview(client, t)
    draft = _create(client, t, s["id"])
    printed = [(b["report_question_text"], b["report_answer_text"]) for b in draft["qa_blocks"]]

    with SessionLocal() as db:
        seg = db.scalars(select(TranscriptSegment).order_by(TranscriptSegment.sequence)).all()[0]
        seg.edited_text = "نص مختلف بعد المسودة"
        db.commit()

    body = client.get(f"/api/investigations/{s['id']}/report", headers=auth(t)).json()
    assert [(b["report_question_text"], b["report_answer_text"]) for b in body["qa_blocks"]] == printed
    assert body["stale"] and body["stale"][0]["reason"] == "segments_edited"

    # ...and only an explicit refresh adopts the new text.
    res = client.post(f"/api/investigations/{s['id']}/report/refresh", headers=auth(t))
    assert res.status_code == 200, res.text
    refreshed = res.json()
    assert refreshed["qa_blocks"][0]["report_question_text"] == "نص مختلف بعد المسودة"
    assert refreshed["stale"] == []


# --------------------------------------------------------------------- unresolved speakers


def test_unresolved_speakers_are_reported_for_the_composer_to_show(client, investigator):
    t = investigator["token"]
    s = _interview(client, t)
    body = _create(client, t, s["id"])
    # Nobody has been identified yet, so both voices are flagged.
    assert set(body["unresolved_speaker_labels"]) == {"SPEAKER_00", "SPEAKER_01"}
    assert all(not sp["resolved"] for sp in body["speakers"])
    assert all("غير محدد الهوية" in sp["report_name"] for sp in body["speakers"])
    assert body["unresolved_ack"] is False

    res = client.put(
        f"/api/investigations/{s['id']}/report", json={"unresolved_ack": True}, headers=auth(t)
    )
    assert res.status_code == 200
    assert res.json()["unresolved_ack"] is True


# --------------------------------------------------------------------- audit


def test_report_work_is_audited(client, investigator):
    t = investigator["token"]
    s = _interview(client, t)
    draft = _create(client, t, s["id"])
    client.post(
        f"/api/investigations/{s['id']}/report/blocks/{draft['qa_blocks'][0]['id']}/exclude",
        json={"reason": "تحية"},
        headers=auth(t),
    )
    actions = {
        row["action"]
        for row in client.get("/api/audit-logs?limit=100", headers=auth(_login(client))).json()["items"]
    }
    assert "REPORT_DRAFT_CREATED" in actions
    assert "REPORT_QA_EXCLUDED" in actions
