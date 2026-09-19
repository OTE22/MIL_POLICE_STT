"""Phase 13: issuing the محضر — gates, snapshot, hashes, archive, verification.

The guarantees under test are the ones a submitted document rests on: it cannot be issued
while required facts are missing or a speaker is unnamed, what it contains is frozen at the
moment of issue, its bytes can be checked later, and a failure never leaves the filesystem
and the database disagreeing.
"""

import io
import uuid
import zipfile

import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import (
    GeneratedReport,
    ReportDraft,
    ReportStatus,
    SessionSpeaker,
    SpeakerRole,
    TranscriptSegment,
)
from app.services.report_storage import absolute_path, atomic_write

from conftest import ADMIN, auth, create_session, request_token, sample_result
from test_report_draft import _evidence_fingerprint


def _admin(client):
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


def _identify(client, token, session_id, label, reference, name):
    """Give a speaker a real registry identity, the way the UI does."""
    from test_voice_matching import _link_identity, _speakers

    speaker = _speakers(client, token, session_id)[label]
    res = _link_identity(client, token, session_id, speaker["id"], reference, name)
    assert res.status_code == 200, res.text


def _ready_session(client, token, *, identify=True):
    """A session whose report can actually be issued: roles, identities, header fields."""
    s = create_session(client, token)
    _submit(
        client,
        token,
        s["id"],
        [
            ("SPEAKER_00", "ما اسمك الكامل؟"),
            ("SPEAKER_01", "وليد الايوبي"),
            ("SPEAKER_00", "أين كنت مساء أمس؟"),
            ("SPEAKER_01", "كنت في المنزل طوال المساء"),
        ],
    )
    if identify:
        _identify(client, token, s["id"], "SPEAKER_00", "MIL-ARMY-51001", "علي عباس")
        _identify(client, token, s["id"], "SPEAKER_01", "MIL-ARMY-51002", "وليد الايوبي")

    # Roles LAST: the speaker PATCH that links an identity sends speaker_role explicitly,
    # and a null there resets the role to UNKNOWN - so setting roles first would lose them
    # and the Q&A builder would see no investigator to attribute questions to.
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

    client.post(f"/api/investigations/{s['id']}/report", headers=auth(token))
    client.put(
        f"/api/investigations/{s['id']}/report",
        json={"report_number": "2026/145", "case_subject": "تحقيق تجريبي", "location": "ثكنة بيروت"},
        headers=auth(token),
    )
    return s


def _archive(client, token, session_id):
    res = client.get(f"/api/investigations/{session_id}/reports", headers=auth(token))
    assert res.status_code == 200, res.text
    return res.json()


def _finalize(client, token, session_id):
    return client.post(f"/api/investigations/{session_id}/reports", headers=auth(token))


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.read("word/document.xml").decode("utf-8")


# --------------------------------------------------------------- gates


def test_a_report_without_required_fields_is_refused(client, investigator):
    t = investigator["token"]
    s = create_session(client, t)
    _submit(client, t, s["id"], [("SPEAKER_00", "كلام")])
    client.post(f"/api/investigations/{s['id']}/report", headers=auth(t))

    body = _archive(client, t, s["id"])
    assert body["can_finalize"] is False
    assert "رقم المحضر" in body["missing_fields"]

    res = _finalize(client, t, s["id"])
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert detail["code"] in ("report_missing_fields", "report_unresolved_speakers")


def test_an_unnamed_speaker_blocks_issuing_until_acknowledged(client, investigator):
    t = investigator["token"]
    s = _ready_session(client, t, identify=False)

    body = _archive(client, t, s["id"])
    assert body["can_finalize"] is False
    assert "report_unresolved_speakers" in body["blocked_reasons"]
    assert body["unresolved_speaker_labels"]

    res = _finalize(client, t, s["id"])
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "report_unresolved_speakers"

    # The acknowledgement is a deliberate, recorded act - then it may be issued.
    client.put(
        f"/api/investigations/{s['id']}/report", json={"unresolved_ack": True}, headers=auth(t)
    )
    assert _finalize(client, t, s["id"]).status_code == 201


def test_a_report_with_no_included_content_is_refused(client, investigator):
    t = investigator["token"]
    s = _ready_session(client, t)
    draft = client.get(f"/api/investigations/{s['id']}/report", headers=auth(t)).json()
    for block in draft["qa_blocks"]:
        client.post(
            f"/api/investigations/{s['id']}/report/blocks/{block['id']}/exclude",
            json={"reason": "الكل"},
            headers=auth(t),
        )
    res = _finalize(client, t, s["id"])
    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "report_no_content"


def test_issuing_requires_the_finalize_permission(client, investigator):
    """Drafting and ISSUING are separate authorities."""
    from conftest import create_user, login

    admin_token = _admin(client)
    create_user(client, admin_token, "drafter", ["USER"], full_name="مسوّد", military_id="M-5150")
    reader = login(client, "drafter", "Password!1234")
    s = _ready_session(client, investigator["token"])
    assert _finalize(client, reader, s["id"]).status_code in (403, 404)


# --------------------------------------------------------------- issuing


def test_issuing_produces_a_hashed_archived_word_document(client, investigator):
    t = investigator["token"]
    s = _ready_session(client, t)
    res = _finalize(client, t, s["id"])
    assert res.status_code == 201, res.text
    body = res.json()

    assert len(body["reports"]) == 1
    report = body["reports"][0]
    assert report["report_version"] == 1
    assert report["report_number"] == "2026/145"
    assert len(report["docx_sha256"]) == 64
    assert len(report["context_sha256"]) == 64
    assert len(report["template_sha256"]) == 64
    assert report["qa_block_count"] == 2
    assert report["size_bytes"] > 5000
    assert report["generated_by_name"]

    # The archived file is a real .docx containing the Arabic that went in.
    download = client.get(
        f"/api/investigations/{s['id']}/reports/{report['id']}/file", headers=auth(t)
    )
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    xml = _docx_text(download.content)
    assert "أين كنت مساء أمس؟" in xml
    assert "كنت في المنزل طوال المساء" in xml
    assert "2026/145" in xml
    assert "{{" not in xml and "{%" not in xml


def test_the_document_names_people_from_the_registry(client, investigator):
    t = investigator["token"]
    s = _ready_session(client, t)
    report = _finalize(client, t, s["id"]).json()["reports"][0]
    xml = _docx_text(
        client.get(f"/api/investigations/{s['id']}/reports/{report['id']}/file", headers=auth(t)).content
    )
    assert "وليد الايوبي" in xml, "the canonical registry name, not a session nickname"
    assert "SPEAKER_00" not in xml or "غير محدد" in xml


def test_the_document_discloses_excluded_recordings_and_content(client, investigator):
    """Selective inclusion must be visible ON the paper, never silent."""
    t = investigator["token"]
    s = _ready_session(client, t)
    draft = client.get(f"/api/investigations/{s['id']}/report", headers=auth(t)).json()
    client.post(
        f"/api/investigations/{s['id']}/report/blocks/{draft['qa_blocks'][0]['id']}/exclude",
        json={"reason": "اختبار الميكروفون"},
        headers=auth(t),
    )
    report = _finalize(client, t, s["id"]).json()["reports"][0]
    xml = _docx_text(
        client.get(f"/api/investigations/{s['id']}/reports/{report['id']}/file", headers=auth(t)).content
    )
    assert "اختبار الميكروفون" in xml, "the exclusion and its reason are printed"


def test_issuing_does_not_touch_the_evidence(client, investigator):
    t = investigator["token"]
    s = _ready_session(client, t)
    before = _evidence_fingerprint(s["id"])
    assert _finalize(client, t, s["id"]).status_code == 201
    assert _evidence_fingerprint(s["id"]) == before


def test_the_draft_becomes_final_and_can_no_longer_be_edited(client, investigator):
    t = investigator["token"]
    s = _ready_session(client, t)
    draft = client.get(f"/api/investigations/{s['id']}/report", headers=auth(t)).json()
    _finalize(client, t, s["id"])

    after = client.get(f"/api/investigations/{s['id']}/report", headers=auth(t)).json()
    assert after["status"] == "FINAL"
    res = client.patch(
        f"/api/investigations/{s['id']}/report/blocks/{draft['qa_blocks'][0]['id']}",
        json={"report_answer_text": "تعديل بعد الإصدار"},
        headers=auth(t),
    )
    assert res.status_code == 409
    assert res.json()["detail"] == "report_is_final"


# --------------------------------------------------------------- immutability


def test_a_later_transcript_edit_never_changes_an_issued_report(client, investigator):
    """The point of the whole snapshot design."""
    t = investigator["token"]
    s = _ready_session(client, t)
    report = _finalize(client, t, s["id"]).json()["reports"][0]
    original_sha = report["docx_sha256"]
    before = client.get(
        f"/api/investigations/{s['id']}/reports/{report['id']}/file", headers=auth(t)
    ).content

    with SessionLocal() as db:
        seg = db.scalars(select(TranscriptSegment).order_by(TranscriptSegment.sequence)).all()[-1]
        seg.edited_text = "إفادة مختلفة تماماً بعد إصدار المحضر"
        db.commit()

    after = client.get(
        f"/api/investigations/{s['id']}/reports/{report['id']}/file", headers=auth(t)
    ).content
    assert after == before, "an issued document is bytes on disk, not a live query"
    assert "إفادة مختلفة تماماً" not in _docx_text(after)

    verified = client.get(
        f"/api/investigations/{s['id']}/reports/{report['id']}/verify", headers=auth(t)
    ).json()
    assert verified["ok"] is True
    assert _archive(client, t, s["id"])["reports"][0]["docx_sha256"] == original_sha


def test_a_correction_produces_a_new_version_never_an_overwrite(client, investigator):
    t = investigator["token"]
    s = _ready_session(client, t)
    first = _finalize(client, t, s["id"]).json()["reports"][0]

    # Reopening is a deliberate, audited act - the issued version is untouched by it.
    res = client.post(f"/api/investigations/{s['id']}/report/reopen", headers=auth(t))
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "DRAFT"
    client.put(
        f"/api/investigations/{s['id']}/report",
        json={"report_number": "2026/145-مصحح"},
        headers=auth(t),
    )
    second = _finalize(client, t, s["id"]).json()["reports"][0]

    assert second["report_version"] == 2
    assert second["id"] != first["id"]
    assert second["docx_sha256"] != first["docx_sha256"]
    # Version 1 is still downloadable, unchanged.
    v1 = client.get(f"/api/investigations/{s['id']}/reports/{first['id']}/file", headers=auth(t))
    assert v1.status_code == 200
    assert "2026/145-مصحح" not in _docx_text(v1.content)


def test_the_snapshot_records_what_the_document_was_built_from(client, investigator):
    t = investigator["token"]
    s = _ready_session(client, t)
    report = _finalize(client, t, s["id"]).json()["reports"][0]
    assert report["transcript_source_mode"] == "CORRECTED"
    assert len(report["selected_recording_ids"]) == 1
    assert report["pinned_transcripts"], "the exact transcript revision is pinned on the report"
    assert len(report["pinned_transcripts"][0]["segments_sha256"]) == 64
    assert report["template_version"] is not None


# --------------------------------------------------------------- verification


def test_verification_detects_a_tampered_file(client, investigator):
    t = investigator["token"]
    s = _ready_session(client, t)
    report = _finalize(client, t, s["id"]).json()["reports"][0]

    assert client.get(
        f"/api/investigations/{s['id']}/reports/{report['id']}/verify", headers=auth(t)
    ).json() == {
        "report_id": report["id"],
        "ok": True,
        "docx_ok": True,
        "context_ok": True,
        "template_ok": True,
        "detail": "سليم",
    }

    with SessionLocal() as db:
        row = db.get(GeneratedReport, uuid.UUID(report["id"]))
        path = absolute_path(row.storage_path)
        data = bytearray(path.read_bytes())
        data[-1] ^= 0xFF  # flip one byte
        atomic_write(row.storage_path, bytes(data))

    verified = client.get(
        f"/api/investigations/{s['id']}/reports/{report['id']}/verify", headers=auth(t)
    ).json()
    assert verified["ok"] is False
    assert verified["docx_ok"] is False
    assert verified["detail"] == "غير مطابق"


def test_verification_notices_a_missing_file(client, investigator):
    t = investigator["token"]
    s = _ready_session(client, t)
    report = _finalize(client, t, s["id"]).json()["reports"][0]
    with SessionLocal() as db:
        row = db.get(GeneratedReport, uuid.UUID(report["id"]))
        absolute_path(row.storage_path).unlink()
    verified = client.get(
        f"/api/investigations/{s['id']}/reports/{report['id']}/verify", headers=auth(t)
    ).json()
    assert verified["ok"] is False and verified["detail"] == "الملف مفقود"


# --------------------------------------------------------------- consistency & access


def test_a_failed_insert_leaves_no_orphan_document(client, investigator, monkeypatch):
    """File first, row second - and if the row fails, the file goes with it.

    Driven at the service level with only the row construction sabotaged: patching
    SQLAlchemy's flush globally would poison every later test in the suite.
    """
    from app.api.report_templates import active_template
    from app.config import get_settings
    from app.services import report_finalize as finalize_module
    from app.services.report_draft import get_draft

    t = investigator["token"]
    s = _ready_session(client, t)
    session_id = uuid.UUID(s["id"])

    def explode(_data: bytes) -> str:
        raise RuntimeError("simulated database failure")

    # Fails INSIDE the try that builds the archive row - after both files are on disk, which
    # is precisely the window the cleanup exists for. `atomic_write` hashes through its own
    # module reference, so the files still get written.
    monkeypatch.setattr(finalize_module, "sha256_bytes", explode)

    with SessionLocal() as db:
        from app.models import InvestigationSession, User

        session = db.get(InvestigationSession, session_id)
        draft = get_draft(db, session_id)
        user = db.scalars(select(User)).first()
        with pytest.raises(RuntimeError, match="simulated database failure"):
            finalize_module.finalize(db, session, draft, active_template(db), user)
        db.rollback()

    monkeypatch.undo()

    # Nothing archived, and no stray official document left on disk for this session.
    with SessionLocal() as db:
        assert (
            db.scalars(select(GeneratedReport).where(GeneratedReport.session_id == session_id)).all()
            == []
        )
    reports_dir = get_settings().storage_root / "reports" / str(session_id)
    assert not reports_dir.exists() or not any(reports_dir.glob("*.docx"))

    # ...and the report can still be issued normally afterwards.
    assert _finalize(client, t, s["id"]).status_code == 201


def test_another_investigator_cannot_reach_the_archive(client, investigator, investigator2):
    s = _ready_session(client, investigator["token"])
    report = _finalize(client, investigator["token"], s["id"]).json()["reports"][0]
    other = investigator2["token"]
    assert client.get(f"/api/investigations/{s['id']}/reports", headers=auth(other)).status_code == 404
    assert (
        client.get(
            f"/api/investigations/{s['id']}/reports/{report['id']}/file", headers=auth(other)
        ).status_code
        == 404
    )


def test_a_report_id_from_another_session_is_not_reachable(client, investigator):
    t = investigator["token"]
    mine = _ready_session(client, t)
    other = _ready_session(client, t)
    foreign = _finalize(client, t, other["id"]).json()["reports"][0]
    _finalize(client, t, mine["id"])
    res = client.get(
        f"/api/investigations/{mine['id']}/reports/{foreign['id']}/file", headers=auth(t)
    )
    assert res.status_code == 404


def test_issuing_downloading_and_verifying_are_audited(client, investigator):
    t = investigator["token"]
    s = _ready_session(client, t)
    report = _finalize(client, t, s["id"]).json()["reports"][0]
    client.get(f"/api/investigations/{s['id']}/reports/{report['id']}/file", headers=auth(t))
    client.get(f"/api/investigations/{s['id']}/reports/{report['id']}/verify", headers=auth(t))

    rows = client.get("/api/audit-logs?limit=100", headers=auth(_admin(client))).json()["items"]
    actions = {r["action"] for r in rows}
    assert {"REPORT_GENERATED", "REPORT_DOWNLOADED", "REPORT_VERIFIED"} <= actions
    issued = [r for r in rows if r["action"] == "REPORT_GENERATED"][0]
    assert issued["safe_metadata"]["docx_sha256"] == report["docx_sha256"]


def test_reopening_requires_a_final_report_and_keeps_the_issued_ones(client, investigator):
    """A correction supersedes; it never edits what was already issued."""
    t = investigator["token"]
    s = _ready_session(client, t)

    # Nothing to reopen while the draft is still a draft.
    res = client.post(f"/api/investigations/{s['id']}/report/reopen", headers=auth(t))
    assert res.status_code == 409
    assert res.json()["detail"] == "report_not_final"

    issued = _finalize(client, t, s["id"]).json()["reports"][0]
    before = client.get(
        f"/api/investigations/{s['id']}/reports/{issued['id']}/file", headers=auth(t)
    ).content

    assert client.post(f"/api/investigations/{s['id']}/report/reopen", headers=auth(t)).status_code == 200

    # The issued document is byte-identical and still verifies after reopening.
    after = client.get(
        f"/api/investigations/{s['id']}/reports/{issued['id']}/file", headers=auth(t)
    ).content
    assert after == before
    assert client.get(
        f"/api/investigations/{s['id']}/reports/{issued['id']}/verify", headers=auth(t)
    ).json()["ok"] is True

    # ...and the draft is editable again, so a corrected version can be issued.
    draft = client.get(f"/api/investigations/{s['id']}/report", headers=auth(t)).json()
    assert draft["status"] == "DRAFT"
    res = client.patch(
        f"/api/investigations/{s['id']}/report/blocks/{draft['qa_blocks'][0]['id']}",
        json={"report_answer_text": "نص مصحّح"},
        headers=auth(t),
    )
    assert res.status_code == 200

    actions = {
        r["action"]
        for r in client.get("/api/audit-logs?limit=100", headers=auth(_admin(client))).json()["items"]
    }
    assert "REPORT_DRAFT_REOPENED" in actions
