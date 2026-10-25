"""Session-owned, repeatable HTML report blocks; source records are never modified."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from app.services.report_people import resolve_selection, ordered_sources
from app.services import note_templates

CATALOGUE = json.loads((Path(__file__).resolve().parents[1] / "assets/html_statement.json").read_text(encoding="utf-8"))
CATALOGUE["note"] = json.loads((Path(__file__).resolve().parents[1] / "assets/html_note.json").read_text(encoding="utf-8"))
FIELDS = {field["key"] for field in CATALOGUE["fields"]}
NOTE_FIELDS = {field["key"] for field in CATALOGUE["note"]["fields"]}


def document_for(draft):
    document = (draft.official_form or {}).get("html_report") or {
        "revision": CATALOGUE["revision"], "subject": draft.case_subject or "", "investigator_id": None, "blocks": [],
    }
    return {**document, "session_id": str(draft.session_id)}


def token_for(draft):
    encoded = json.dumps({"draft": str(draft.id), "document": document_for(draft)}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def state_for(draft):
    return {"document": document_for(draft), "token": token_for(draft)}


def source_snapshot(source, session):
    return {"block_id": str(source.id), "session_id": str(session.id),
            "answer_speaker_id": str(source.answer_speaker_id) if source.answer_speaker_id else None,
            "question_source_text": source.question_source_text, "answer_source_text": source.answer_source_text,
            "source_segment_ids": source.source_segment_ids or [], "source_recording_ids": source.source_recording_ids or [],
            "start_seconds": source.start_seconds, "end_seconds": source.end_seconds}


def statement_preview(db, draft, session, selection):
    if draft.session_id != session.id:
        raise ValueError("html_report_wrong_session")
    eligible, values, normalized = resolve_selection(db, session, selection)
    # Session/report context only; never today's date substituted for an event date.
    values["closing_location"] = draft.location or session.location or ""
    values["closing_date"] = str(draft.report_date or session.session_date or "")
    entries = [{"id": str(uuid.uuid4()), "question": qa.report_question_text or "", "answer": qa.report_answer_text or "",
                "source_block_ids": [str(qa.id)], "source_snapshot": [source_snapshot(qa, session)]}
               for qa in ordered_sources(draft) if qa.included_in_report and str(qa.answer_speaker_id) in eligible]
    return {"id": str(uuid.uuid4()), "type": "statement", **normalized, "values": values,
            "identity_checked": False, "attestation_confirmed": False, "entries": entries}


def prepare_document(body, draft, session, db):
    """Validate references and snapshot imported source text on the server."""
    document = body.document.model_dump(mode="json")
    if draft.session_id != session.id or document.get("session_id") not in (None, str(session.id)):
        raise ValueError("html_report_wrong_session")
    document["session_id"] = str(session.id)
    if document["investigator_id"] and document["investigator_id"] not in {str(i.investigator_id) for i in session.investigators}:
        raise ValueError("html_report_investigator_outside_session")
    if document["clerk_id"] and document["clerk_id"] not in {str(i.investigator_id) for i in session.investigators}:
        raise ValueError("html_report_clerk_outside_session")
    sources = {str(block.id): block for block in draft.qa_blocks}
    old_blocks = {block["id"]: block for block in document_for(draft)["blocks"]}
    previous = {entry["id"]: entry for block in document_for(draft)["blocks"] if block["type"] == "statement" for entry in block["entries"]}
    for block in document["blocks"]:
        old = old_blocks.get(block["id"], {})
        if block["type"] == "note":
            template_id = block.get("template_id")
            if template_id:
                template = old.get("template_snapshot") if old.get("template_id") == template_id else None
                template = template or note_templates.get_template(db, template_id)
                if template is None:
                    raise ValueError("html_report_note_template_not_found")
                block["template_snapshot"] = template
                block["values"]["note_text"] = note_templates.render(template, block["template_values"])
            else:
                if block["template_values"]:
                    raise ValueError("html_report_note_template_required")
                block.pop("template_id", None)
                block.pop("template_values", None)
            continue
        eligible, person_values, normalized = resolve_selection(db, session, block)
        block.update(normalized)
        if block.get("participant_key") or block.get("identity_id"):
            unchanged = all(old.get(key) == block.get(key) for key in normalized)
            block["person_snapshot"] = old.get("person_snapshot") if unchanged else None
            block["person_snapshot"] = block["person_snapshot"] or {
                "session_id": str(session.id), **normalized, "values": person_values}
        else:
            block.pop("participant_key", None)
            block.pop("identity_id", None)
        for entry in block["entries"]:
            entry["source_snapshot"] = []
            prior = previous.get(entry["id"], {})
            prior_sources = {s["block_id"]: s for s in prior.get("source_snapshot", [])}
            for source_id in entry["source_block_ids"]:
                if source_id in prior_sources:
                    snapshot = prior_sources[source_id]
                else:
                    source = sources.get(source_id)
                    if source is None:
                        raise ValueError("html_report_source_outside_draft")
                    snapshot = source_snapshot(source, session)
                if snapshot.get("session_id", str(session.id)) != str(session.id):
                    raise ValueError("html_report_source_outside_session")
                if snapshot["answer_speaker_id"] not in eligible:
                    raise ValueError("html_report_source_speaker_mismatch")
                entry["source_snapshot"].append(snapshot)
    return document
