"""Resolve people only through this session; never search another session's facts."""
import hashlib
import json
import uuid
from app.models import PersonIdentity
from app.services.person_identity import resolve_identity


def canonical_id(db, value):
    person = resolve_identity(db, db.get(PersonIdentity, uuid.UUID(str(value)))) if value else None
    return str(person.id) if person else None


def details_token(subject):
    payload = [str(subject.session_id), str(subject.participant_key), str(subject.identity_id), subject.statement_details or {}]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def participant_values(subject):
    values = dict(subject.statement_details or {})
    values.update(statement_name=subject.subject_name or "",
                  statement_rank=subject.rank or "", statement_service_number=subject.military_id or "",
                  civil_register=" / ".join(v for v in [subject.register_number, subject.place_of_registration] if v))
    if not values.get("occupation_statement"):
        values["occupation_statement"] = " — ".join(v for v in [subject.rank, subject.unit, subject.department] if v)
    return {key: value for key, value in values.items() if value}


def options_for(db, session):
    options, represented = [], set()
    for subject in session.subjects:
        person = canonical_id(db, subject.identity_id)
        represented.add(person)
        options.append({"key": f"participant:{subject.participant_key}", "label": subject.subject_name,
                        "participant_key": str(subject.participant_key), "identity_id": person, "speaker_id": None})
    for link in session.investigators:
        person = canonical_id(db, link.investigator.identity_id)
        if person and person not in represented:
            represented.add(person)
            options.append({"key": f"person:{person}", "label": link.investigator.full_name,
                            "participant_key": None, "identity_id": person, "speaker_id": None})
    for speaker in session.speakers:
        person = canonical_id(db, speaker.identity_id)
        if person and person not in represented:
            represented.add(person)
            name = db.get(PersonIdentity, uuid.UUID(person)).person_name
            options.append({"key": f"person:{person}", "label": name,
                            "participant_key": None, "identity_id": person, "speaker_id": None})
        elif not person:
            options.append({"key": f"speaker:{speaker.id}",
                            "label": f"{speaker.display_name or speaker.speaker_label} — هوية غير مرتبطة",
                            "participant_key": None, "identity_id": None, "speaker_id": str(speaker.id)})
    return options


def resolve_selection(db, session, block):
    """Return eligible answer-speaker IDs, source person values and normalized selection."""
    participant = block.get("participant_key")
    identity = block.get("identity_id")
    speaker_id = block.get("speaker_id")
    values = {}
    if participant:
        subject = next((s for s in session.subjects if str(s.participant_key) == str(participant)), None)
        if subject is None:
            raise ValueError("html_report_participant_outside_session")
        person = canonical_id(db, subject.identity_id)
        if identity and canonical_id(db, identity) != person:
            raise ValueError("html_report_participant_identity_mismatch")
        identity = person
        values = participant_values(subject)
    elif identity:
        identity = canonical_id(db, identity)
        allowed = {o["identity_id"] for o in options_for(db, session) if o["identity_id"]}
        if not identity or identity not in allowed:
            raise ValueError("html_report_person_outside_session")
        values["statement_name"] = db.get(PersonIdentity, uuid.UUID(identity)).person_name
        for link in session.investigators:
            profile = link.investigator
            if canonical_id(db, profile.identity_id) == identity:
                values.update(statement_rank=profile.rank or "", statement_service_number=profile.military_id or "",
                              occupation_statement=" — ".join(v for v in [profile.rank, profile.unit, profile.department] if v))
                break
    speakers = {str(s.id): s for s in session.speakers}
    if speaker_id and str(speaker_id) not in speakers:
        raise ValueError("html_report_speaker_outside_session")
    if identity:
        eligible = {key for key, s in speakers.items() if canonical_id(db, s.identity_id) == identity}
        if speaker_id and str(speaker_id) not in eligible:
            raise ValueError("html_report_source_speaker_mismatch")
    else:
        eligible = {str(speaker_id)} if speaker_id else set()
        if speaker_id:
            s = speakers[str(speaker_id)]
            values["statement_name"] = s.display_name or ""
    return eligible, values, {"participant_key": str(participant) if participant else None,
                              "identity_id": identity, "speaker_id": str(speaker_id) if speaker_id else None}


def ordered_sources(draft):
    recording_order = {str(rid): i for i, rid in enumerate(draft.selected_recording_ids or [])}
    def key(qa):
        recording = min((recording_order.get(str(r), 10**9) for r in qa.source_recording_ids or []), default=10**9)
        return recording, qa.start_seconds if qa.start_seconds is not None else float("inf"), qa.sequence, str(qa.id)
    return sorted(draft.qa_blocks, key=key)
