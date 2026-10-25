"""Session-owned, repeatable HTML report blocks; source records are never modified."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

CATALOGUE = json.loads((Path(__file__).resolve().parents[1] / "assets/html_statement.json").read_text(encoding="utf-8"))
CATALOGUE["note"] = json.loads((Path(__file__).resolve().parents[1] / "assets/html_note.json").read_text(encoding="utf-8"))
FIELDS = {field["key"] for field in CATALOGUE["fields"]}
NOTE_FIELDS = {field["key"] for field in CATALOGUE["note"]["fields"]}


def document_for(draft):
    return (draft.official_form or {}).get("html_report") or {
        "revision": CATALOGUE["revision"], "subject": draft.case_subject or "", "investigator_id": None, "blocks": [],
    }


def token_for(draft):
    encoded = json.dumps({"draft": str(draft.id), "document": document_for(draft)}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def state_for(draft):
    return {"document": document_for(draft), "token": token_for(draft)}


def prepare_document(body, draft, session):
    """Validate references and snapshot imported source text on the server."""
    document = body.document.model_dump(mode="json")
    if document["investigator_id"] and document["investigator_id"] not in {str(i.investigator_id) for i in session.investigators}:
        raise ValueError("html_report_investigator_outside_session")
    speakers = {str(s.id) for s in session.speakers}
    sources = {str(block.id): block for block in draft.qa_blocks}
    previous = {entry["id"]: entry for block in document_for(draft)["blocks"] if block["type"] == "statement" for entry in block["entries"]}
    for block in document["blocks"]:
        if block["type"] != "statement":
            continue
        person = block["speaker_id"]
        if person and person not in speakers:
            raise ValueError("html_report_speaker_outside_session")
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
                    snapshot = {"block_id": source_id,
                        "answer_speaker_id": str(source.answer_speaker_id) if source.answer_speaker_id else None,
                        "question_source_text": source.question_source_text, "answer_source_text": source.answer_source_text,
                        "source_segment_ids": source.source_segment_ids or [], "source_recording_ids": source.source_recording_ids or [],
                        "start_seconds": source.start_seconds, "end_seconds": source.end_seconds}
                if not person or snapshot["answer_speaker_id"] != person:
                    raise ValueError("html_report_source_speaker_mismatch")
                entry["source_snapshot"].append(snapshot)
    return document
