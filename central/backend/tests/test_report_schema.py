"""The report tables exist with the guarantees the محضر depends on.

These are structural, not behavioural: they pin the constraints that make an issued report
defensible — one draft per session, versions that never collide, a template version that
cannot be deleted out from under a document that cites it, and Q&A rows that carry their own
copy of the evidence text.
"""

import uuid

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal, engine
from app.models import (
    GeneratedReport,
    ReportDraft,
    ReportQABlock,
    ReportStatus,
    ReportTemplateVersion,
    TranscriptSourceMode,
)

from conftest import auth, create_session


def _session_id(client, investigator):
    return uuid.UUID(create_session(client, investigator["token"])["id"])


def test_all_four_report_tables_exist():
    names = set(inspect(engine).get_table_names())
    assert {
        "report_template_versions",
        "report_drafts",
        "report_qa_blocks",
        "generated_reports",
    } <= names


def test_one_draft_per_session(client, investigator):
    sid = _session_id(client, investigator)
    with SessionLocal() as db:
        db.add(ReportDraft(session_id=sid))
        db.commit()
    with SessionLocal() as db:
        db.add(ReportDraft(session_id=sid))
        with pytest.raises(IntegrityError):
            db.commit()


def test_draft_defaults_are_the_safe_ones(client, investigator):
    sid = _session_id(client, investigator)
    with SessionLocal() as db:
        draft = ReportDraft(session_id=sid)
        db.add(draft)
        db.commit()
        db.refresh(draft)
        assert draft.status is ReportStatus.DRAFT
        # Corrected text by default: a submitted report should quote the reviewed transcript.
        assert draft.transcript_source_mode is TranscriptSourceMode.CORRECTED
        # Nothing is acknowledged until a human does it.
        assert draft.unresolved_ack is False


def test_qa_blocks_keep_their_own_copy_of_the_source_text(client, investigator):
    """The report must not read through to transcript_segments at render time."""
    sid = _session_id(client, investigator)
    with SessionLocal() as db:
        draft = ReportDraft(session_id=sid)
        db.add(draft)
        db.flush()
        db.add(
            ReportQABlock(
                draft_id=draft.id,
                sequence=1,
                question_source_text="شو صار؟",
                answer_source_text="ما بعرف",
                report_question_text="ماذا حدث؟",
                report_answer_text="لا أعرف",
                source_segment_ids=[str(uuid.uuid4())],
                source_recording_ids=[str(uuid.uuid4())],
            )
        )
        db.commit()
        block = db.scalars(select(ReportQABlock).where(ReportQABlock.draft_id == draft.id)).one()
        assert block.question_source_text == "شو صار؟"
        assert block.report_question_text == "ماذا حدث؟"
        assert block.included_in_report is True
        assert block.fusha_status.value == "NOT_REQUESTED"
        assert block.llm_provenance is None


def test_qa_sequence_is_unique_within_a_draft(client, investigator):
    sid = _session_id(client, investigator)
    with SessionLocal() as db:
        draft = ReportDraft(session_id=sid)
        db.add(draft)
        db.flush()
        db.add(ReportQABlock(draft_id=draft.id, sequence=1))
        db.commit()
        db.add(ReportQABlock(draft_id=draft.id, sequence=1))
        with pytest.raises(IntegrityError):
            db.commit()


def test_report_version_is_unique_per_session(client, investigator):
    """Issuing V1 twice must be impossible - versions never collide or overwrite."""
    sid = _session_id(client, investigator)
    with SessionLocal() as db:
        db.add(
            GeneratedReport(
                session_id=sid, report_version=1, storage_path="reports/x/1.docx", docx_sha256="a" * 64
            )
        )
        db.commit()
        db.add(
            GeneratedReport(
                session_id=sid, report_version=1, storage_path="reports/x/1b.docx", docx_sha256="b" * 64
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()


def test_a_template_version_cited_by_a_report_cannot_be_deleted(client, investigator):
    """RESTRICT: the layout an issued document was printed on stays on the record."""
    sid = _session_id(client, investigator)
    with SessionLocal() as db:
        tpl = ReportTemplateVersion(
            version=99, storage_path="report-templates/t.docx", sha256="c" * 64, is_development=True
        )
        db.add(tpl)
        db.flush()
        db.add(
            GeneratedReport(
                session_id=sid,
                report_version=7,
                template_version_id=tpl.id,
                storage_path="reports/x/7.docx",
                docx_sha256="d" * 64,
            )
        )
        db.commit()
        tpl_id = tpl.id

    with SessionLocal() as db:
        db.delete(db.get(ReportTemplateVersion, tpl_id))
        with pytest.raises(IntegrityError):
            db.commit()


def test_deleting_a_draft_keeps_the_issued_report(client, investigator):
    """SET NULL, not CASCADE: a submitted document outlives the working copy."""
    sid = _session_id(client, investigator)
    with SessionLocal() as db:
        draft = ReportDraft(session_id=sid)
        db.add(draft)
        db.flush()
        report = GeneratedReport(
            session_id=sid,
            draft_id=draft.id,
            report_version=1,
            storage_path="reports/y/1.docx",
            docx_sha256="e" * 64,
        )
        db.add(report)
        db.commit()
        report_id, draft_id = report.id, draft.id

    with SessionLocal() as db:
        db.delete(db.get(ReportDraft, draft_id))
        db.commit()
        survivor = db.get(GeneratedReport, report_id)
        assert survivor is not None, "an issued report must survive its draft"
        assert survivor.draft_id is None
        assert survivor.docx_sha256 == "e" * 64


def test_deleting_a_session_removes_its_report_rows(client, investigator):
    """Reports live inside the session aggregate - the session's CASCADE reaches them."""
    token = investigator["token"]
    sid = uuid.UUID(create_session(client, token)["id"])
    with SessionLocal() as db:
        draft = ReportDraft(session_id=sid)
        db.add(draft)
        db.flush()
        db.add(ReportQABlock(draft_id=draft.id, sequence=1))
        db.commit()

    with SessionLocal() as db:
        from app.models import InvestigationSession

        db.delete(db.get(InvestigationSession, sid))
        db.commit()
        assert db.scalars(select(ReportDraft).where(ReportDraft.session_id == sid)).all() == []


def test_template_versions_are_numbered_uniquely():
    with SessionLocal() as db:
        v = 4242
        db.add(ReportTemplateVersion(version=v, storage_path="report-templates/a.docx", sha256="1" * 64))
        db.commit()
        db.add(ReportTemplateVersion(version=v, storage_path="report-templates/b.docx", sha256="2" * 64))
        with pytest.raises(IntegrityError):
            db.commit()
    with SessionLocal() as db:  # leave no stray row behind for other tests
        for row in db.scalars(select(ReportTemplateVersion).where(ReportTemplateVersion.version == 4242)).all():
            db.delete(row)
        db.commit()


def test_report_tables_do_not_touch_evidence_tables():
    """No FK from a report table may point INTO evidence in a way that could rewrite it.

    Report rows reference evidence with SET NULL / plain id columns only, so deleting or
    editing a report can never cascade into recordings, transcripts or identities.
    """
    insp = inspect(engine)
    for table in ("report_drafts", "report_qa_blocks", "generated_reports"):
        for fk in insp.get_foreign_keys(table):
            target = fk["referred_table"]
            rule = (fk.get("options") or {}).get("ondelete", "").upper()
            if target in ("transcripts", "transcript_segments", "audio_recordings", "voice_enrollments"):
                pytest.fail(f"{table} must not hold a hard FK into evidence table {target}")
            if target == "session_speakers":
                assert rule == "SET NULL", "speaker links must never cascade into speaker rows"
