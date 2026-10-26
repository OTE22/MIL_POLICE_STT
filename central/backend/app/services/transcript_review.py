"""Human review is bound to the current text, attribution and identified speakers."""
import hashlib
import json
from sqlalchemy import select
from app.models import SessionSpeaker, TranscriptSegment, Transcript, PersonIdentity
from app.services.transcript_content import speech_parts
from app.services.person_identity import resolve_identity


def _identity_fact(db, identity_id):
    identity = resolve_identity(db, db.get(PersonIdentity, identity_id)) if identity_id else None
    return [str(identity.id), identity.person_name] if identity else None


def token_for(db, transcript):
    speakers = db.scalars(select(SessionSpeaker).where(SessionSpeaker.session_id == transcript.session_id,
                                                       SessionSpeaker.recording_id == transcript.recording_id)
                          .order_by(SessionSpeaker.id)).all()
    payload = {"id": str(transcript.id), "segments": [
        [str(s.id), s.revision, speech_parts(s)] for s in transcript.segments], "speakers": [
        [str(s.id), str(s.identity_id), s.speaker_role.value, s.display_name,
         _identity_fact(db, s.identity_id)]
        for s in speakers]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def is_reviewed(db, transcript):
    return bool(transcript.review_token and transcript.review_token == token_for(db, transcript))


def require_reviewed_sources(db, sources):
    identifiers = {str(segment) for source in sources for segment in source.source_segment_ids or []}
    if not identifiers:
        return
    rows = db.scalars(select(TranscriptSegment).where(TranscriptSegment.id.in_(identifiers))).all()
    if len(rows) != len(identifiers):
        raise ValueError("html_report_source_outside_session")
    for identifier in {row.transcript_id for row in rows}:
        if not is_reviewed(db, db.get(Transcript, identifier)):
            raise ValueError("html_report_transcript_review_required")
