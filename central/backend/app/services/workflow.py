"""Investigation lifecycle is independent of processing job success or failure."""
from sqlalchemy import select, func
from fastapi import HTTPException
from app.models import LocalProcessingJob, AudioRecording, ReportDraft, ReportStatus

ACTIVE_JOBS = {"REQUESTED", "ACCEPTED", "PROCESSING"}
TRANSITIONS = {
    "DRAFT": {"IN_PROGRESS", "ARCHIVED"},
    "IN_PROGRESS": {"AWAITING_REVIEW", "ARCHIVED"},
    "AWAITING_REVIEW": {"IN_PROGRESS", "REVIEWED"},
    "REVIEWED": {"IN_PROGRESS", "CLOSED"},
    "CLOSED": {"IN_PROGRESS", "ARCHIVED"},
    "ARCHIVED": {"IN_PROGRESS"},
}


def processing_summary(db, session_id):
    return {getattr(state, "value", state): count for state, count in db.execute(
        select(LocalProcessingJob.status, func.count()).join(AudioRecording, AudioRecording.id == LocalProcessingJob.recording_id).where(LocalProcessingJob.session_id == session_id, AudioRecording.purpose == "INTERVIEW")
        .group_by(LocalProcessingJob.status)).all()}


def unresolved_processing_failures(db, session_id):
    # A successful retry resolves the failure for that recording; cancelling a retry
    # does not erase it. All original job rows remain available in the audit/history.
    from app.models import JobStatus
    latest = db.execute(select(LocalProcessingJob.recording_id, LocalProcessingJob.status).join(AudioRecording, AudioRecording.id == LocalProcessingJob.recording_id)
        .where(LocalProcessingJob.session_id == session_id,
               LocalProcessingJob.status.in_([JobStatus.FAILED, JobStatus.COMPLETED]), AudioRecording.purpose == "INTERVIEW")
        .distinct(LocalProcessingJob.recording_id)
        .order_by(LocalProcessingJob.recording_id, LocalProcessingJob.created_at.desc(), LocalProcessingJob.id.desc())).all()
    return sum(state == JobStatus.FAILED for _, state in latest)


def evidence_blockers(db, session, *, verify_hashes=False):
    reasons = []
    if any(count for state, count in processing_summary(db, session.id).items() if state in ACTIVE_JOBS):
        reasons.append("active_processing_jobs")
    if unresolved_processing_failures(db, session.id):
        reasons.append("unresolved_processing_failures")
    recordings = db.scalars(select(AudioRecording).where(AudioRecording.session_id == session.id, AudioRecording.purpose == "INTERVIEW")).all()
    from app.services.storage import absolute_path
    for recording in recordings:
        path = absolute_path(recording.storage_path) if recording.storage_path else None
        if path is None or not recording.sha256:
            reasons.append("original_audio_missing")
        elif verify_hashes:
            import hashlib
            try:
                with path.open("rb") as audio:
                    if hashlib.file_digest(audio, "sha256").hexdigest() != recording.sha256:
                        reasons.append("original_audio_integrity_failed")
            except OSError:
                reasons.append("original_audio_missing")
    if not session.investigators or sum(i.assignment_role.value == "LEAD" for i in session.investigators) != 1:
        reasons.append("exactly_one_lead_required")
    return list(dict.fromkeys(reasons))


def guard_mutation(session):
    if session.workflow_state in {"CLOSED", "ARCHIVED"}:
        raise HTTPException(409, detail="reopen_investigation_before_editing")


def evidence_changed(session):
    guard_mutation(session)
    if session.workflow_state in {"REVIEWED", "AWAITING_REVIEW"}:
        session.workflow_state = "IN_PROGRESS"
    session.revision += 1


def transition(db, session, target, user):
    if target not in TRANSITIONS.get(session.workflow_state, set()):
        raise HTTPException(409, detail="invalid_workflow_transition")
    if target in {"IN_PROGRESS", "AWAITING_REVIEW", "REVIEWED", "CLOSED"} and session.workflow_state not in {"CLOSED", "ARCHIVED"}:
        from app.services.participant_requirements import require_ready
        require_ready(session)
    if target in {"REVIEWED", "CLOSED"} and "reports.finalize" not in user.permission_codes:
        raise HTTPException(403, detail="forbidden")
    if target == "ARCHIVED" and "investigations.archive" not in user.permission_codes:
        raise HTTPException(403, detail="forbidden")
    if target in {"AWAITING_REVIEW", "REVIEWED", "CLOSED"}:
        reasons = evidence_blockers(db, session, verify_hashes=target in {"REVIEWED", "CLOSED"})
        draft = db.scalar(select(ReportDraft).where(ReportDraft.session_id == session.id))
        if target == "CLOSED":
            if draft is None or draft.status != ReportStatus.FINAL:
                reasons.append("current_report_not_issued")
            elif (draft.official_form or {}).get("issued_source_token") != source_token(db, session):
                reasons.append("report_sources_changed")
        elif draft is None:
            reasons.append("report_draft_not_found")
        else:
            from app.services.report_finalize import content_blockers, review_token
            from app.services.report_html import document_for
            reasons.extend(content_blockers(session, document_for(draft)))
            if target == "REVIEWED" and ((draft.official_form or {}).get("html_review") or {}).get("token") != review_token(db, session, draft):
                reasons.append("report_review_required")
        if reasons:
            raise HTTPException(409, detail={"code": "workflow_not_ready", "reasons": reasons})
    if target == "ARCHIVED" and any(processing_summary(db, session.id).get(state, 0) for state in ACTIVE_JOBS):
        raise HTTPException(409, detail="active_processing_jobs")
    from app.models import SessionStatus
    if target == "ARCHIVED":
        session.status = SessionStatus.ARCHIVED
    elif session.workflow_state == "ARCHIVED":
        session.status = SessionStatus.DRAFT
    session.workflow_state = target
    session.revision += 1


def source_snapshot(db, session):
    from app.models import PersonIdentity, SessionSpeaker, Transcript, TranscriptSourceMode
    from app.services.report_context import pin_transcripts
    from app.services.person_identity import resolve_identity
    recording_ids = list(db.scalars(select(AudioRecording.id).where(AudioRecording.session_id == session.id, AudioRecording.purpose == "INTERVIEW")
                                    .order_by(AudioRecording.created_at, AudioRecording.id)).all())
    people = {}
    def person(identity_id):
        identity = resolve_identity(db, db.get(PersonIdentity, identity_id)) if identity_id else None
        if identity:
            people[str(identity.id)] = identity.person_name
        return str(identity.id) if identity else None
    subjects = [{"key": str(s.participant_key), "person": person(s.identity_id),
                 "facts": {c.name: getattr(s, c.name) for c in s.__table__.columns if c.name not in {"created_at", "updated_at"}},
                 "documents": [{c.name: getattr(d, c.name) for c in d.__table__.columns} for d in s.documents]}
                for s in session.subjects if s.removed_at is None]
    investigators = [{"id": str(i.investigator_id), "role": i.assignment_role,
                      "person": person(i.investigator.identity_id),
                      "profile": {c.name: getattr(i.investigator, c.name) for c in i.investigator.__table__.columns}}
                     for i in session.investigators]
    speakers = [{"id": str(s.id), "person": person(s.identity_id), "label": s.speaker_label,
                 "role": s.speaker_role, "display_name": s.display_name} for s in
                db.scalars(select(SessionSpeaker).where(SessionSpeaker.session_id == session.id).order_by(SessionSpeaker.id))]
    value = {"session": {k: getattr(session, k) for k in ("id", "title", "location", "session_date", "start_time", "end_time")},
             "subjects": sorted(subjects, key=lambda s: s["key"]), "investigators": sorted(investigators, key=lambda i: i["id"]),
             "speakers": speakers, "people": people,
             "recordings": [{"id": str(r.id), "sha256": r.sha256, "stored": bool(r.storage_path), "duration": str(r.duration_seconds)}
                            for r in db.scalars(select(AudioRecording).where(AudioRecording.session_id == session.id, AudioRecording.purpose == "INTERVIEW").order_by(AudioRecording.id))],
             "transcripts": pin_transcripts(db, recording_ids, TranscriptSourceMode.CORRECTED)}
    import json
    return json.loads(json.dumps(value, default=str))


def source_token(db, session):
    import hashlib, json
    return hashlib.sha256(json.dumps(source_snapshot(db, session), sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def lock_source_people(db, session):
    """Freeze shared registry facts until issuance commits, including merge targets.

    Session edits already serialize on the session row. Registry/profile edits span
    sessions, so they need their own shared locks while HTML/PDF are being archived.
    """
    from app.models import InvestigatorProfile, PersonIdentity, SessionSpeaker
    profiles = list(db.scalars(select(InvestigatorProfile).where(
        InvestigatorProfile.id.in_([link.investigator_id for link in session.investigators]))
        .order_by(InvestigatorProfile.id).with_for_update(read=True, of=InvestigatorProfile)
        .execution_options(populate_existing=True)))
    pending = {subject.identity_id for subject in session.subjects if subject.removed_at is None}
    pending.update(profile.identity_id for profile in profiles)
    pending.update(db.scalars(select(SessionSpeaker.identity_id).where(SessionSpeaker.session_id == session.id)))
    locked = set()
    while pending - locked - {None}:
        identities = list(db.scalars(select(PersonIdentity).where(PersonIdentity.id.in_(pending - locked - {None}))
            .order_by(PersonIdentity.id).with_for_update(read=True, of=PersonIdentity)
            .execution_options(populate_existing=True)))
        locked.update(pending)
        pending = {identity.merged_into_id for identity in identities if identity.merged_into_id}
