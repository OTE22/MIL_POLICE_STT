"""The pgvector batch matcher: one SQL operation, global gallery, shared decision policy.

Synthetic unit vectors with exact cosine relationships - no models, no audio. pgvector holds
float4, so scores agree with the analytic values to ~1e-4; every asserted decision sits far
from the 0.65 / 0.05 boundaries so representation error can never flip a verdict.
"""

import math
import uuid

from sqlalchemy import event

from app.db.session import SessionLocal, engine
from app.models import PersonIdentity, VoiceEnrollment
from app.services.voice_matching import (
    DECISION_AMBIGUOUS,
    DECISION_SUGGESTED,
    DECISION_UNKNOWN,
    batch_match_voice_embeddings,
)

DIM = 16
MODEL = "nvidia/speakerverification_speakernet"

ALI = [1.0] + [0.0] * (DIM - 1)
GEORGES = [0.0, 0.0, 1.0] + [0.0] * (DIM - 3)


def _vec(cos_vs_ali: float, ortho_axis: int = 1) -> list[float]:
    """A unit vector with an exact cosine against ALI, orthogonal to everything else."""
    v = [0.0] * DIM
    v[0] = cos_vs_ali
    v[ortho_axis] = math.sqrt(1 - cos_vs_ali**2)
    return v


def _person(db, name: str, reference: str) -> PersonIdentity:
    identity = PersonIdentity(
        reference_normalized=reference.upper(),
        reference_display=reference,
        person_name=name,
    )
    db.add(identity)
    db.flush()
    return identity


def _print(db, identity, embedding, *, model=MODEL, active=True, identity_id="use") -> VoiceEnrollment:
    enr = VoiceEnrollment(
        identity_id=identity.id if identity_id == "use" else None,
        person_name=identity.person_name if identity else "بلا هوية",
        person_reference=identity.reference_display if identity else "X-NONE",
        embedding=embedding,
        embedding_dim=len(embedding),
        model=model,
        is_active=active,
        consent_recorded=True,
    )
    db.add(enr)
    db.flush()
    return enr


def test_several_probes_matched_in_one_batch_with_one_gallery_query():
    with SessionLocal() as db:
        ali = _person(db, "علي عباس", "MIL-ARMY-B1")
        georges = _person(db, "جورج حداد", "MIL-ARMY-B2")
        _print(db, ali, ALI)
        _print(db, georges, GEORGES)
        db.commit()

        statements: list[str] = []

        def _capture(conn, cursor, statement, parameters, context, executemany):
            if "voice_enrollments" in statement:
                statements.append(statement)

        event.listen(engine, "before_cursor_execute", _capture)
        try:
            results = batch_match_voice_embeddings(
                db,
                [("p1", _vec(0.9)), ("p2", GEORGES), ("p3", _vec(0.2))],
                model=MODEL,
            )
        finally:
            event.remove(engine, "before_cursor_execute", _capture)

    by_key = {r.key: r for r in results}
    assert by_key["p1"].decision == DECISION_SUGGESTED
    assert by_key["p1"].identity_id == ali.id
    assert abs(by_key["p1"].score - 0.9) < 1e-4
    assert by_key["p2"].decision == DECISION_SUGGESTED
    assert by_key["p2"].identity_id == georges.id
    assert by_key["p3"].decision == DECISION_UNKNOWN
    # N probes, ONE statement touching the gallery - the point of batching.
    assert len(statements) == 1, f"expected one gallery query, saw {len(statements)}"


def test_the_gallery_is_global_not_scoped_to_any_session():
    """An enrolled person who is on NO session and NO subject list is still a candidate."""
    with SessionLocal() as db:
        outsider = _person(db, "مايا خوري", "MIL-ARMY-B3")
        _print(db, outsider, GEORGES)
        db.commit()
        [res] = batch_match_voice_embeddings(db, [("p", GEORGES)], model=MODEL)
    assert res.decision == DECISION_SUGGESTED
    assert res.identity_id == outsider.id
    assert abs(res.score - 1.0) < 1e-4


def test_multiple_prints_of_one_person_score_by_their_best_print():
    with SessionLocal() as db:
        ali = _person(db, "علي عباس", "MIL-ARMY-B4")
        _print(db, ali, _vec(0.77, ortho_axis=1))
        best = _print(db, ali, _vec(0.84, ortho_axis=2))
        _print(db, ali, _vec(0.80, ortho_axis=3))
        db.commit()
        [res] = batch_match_voice_embeddings(db, [("p", ALI)], model=MODEL)
    assert res.decision == DECISION_SUGGESTED
    assert abs(res.score - 0.84) < 1e-4
    assert res.enrollment_id == best.id
    assert res.print_count == 3
    # One person is ONE candidate: their other prints are not a fabricated runner-up.
    assert res.runner_up_identity_id is None


def test_below_threshold_is_unknown():
    with SessionLocal() as db:
        ali = _person(db, "علي عباس", "MIL-ARMY-B5")
        _print(db, ali, ALI)
        db.commit()
        [res] = batch_match_voice_embeddings(db, [("p", _vec(0.5372))], model=MODEL)
    assert res.decision == DECISION_UNKNOWN
    assert abs(res.score - 0.5372) < 1e-4  # the score is still reported for the logs


def test_two_close_people_are_ambiguous_not_top1():
    with SessionLocal() as db:
        ali = _person(db, "علي عباس", "MIL-ARMY-B6")
        georges = _person(db, "جورج حداد", "MIL-ARMY-B7")
        _print(db, ali, ALI)
        _print(db, georges, GEORGES)
        db.commit()
        # cos(probe, ALI)=0.70 and cos(probe, GEORGES)=0.68: both pass 0.65, gap 0.02 < 0.05.
        probe = [0.70, math.sqrt(1 - 0.70**2 - 0.68**2), 0.68] + [0.0] * (DIM - 3)
        [res] = batch_match_voice_embeddings(db, [("p", probe)], model=MODEL)
    assert res.decision == DECISION_AMBIGUOUS
    assert abs(res.score - 0.70) < 1e-4
    assert abs(res.runner_up_score - 0.68) < 1e-4
    assert {res.identity_id, res.runner_up_identity_id} == {ali.id, georges.id}


def test_empty_gallery_is_unknown_with_no_scores():
    with SessionLocal() as db:
        [res] = batch_match_voice_embeddings(db, [("p", ALI)], model=MODEL)
    assert res.decision == DECISION_UNKNOWN
    assert res.score is None and res.runner_up_score is None and res.print_count == 0


def test_ineligible_prints_are_excluded():
    """Wrong model, wrong dimension, inactive, and identity-less prints never compete."""
    with SessionLocal() as db:
        ali = _person(db, "علي عباس", "MIL-ARMY-B8")
        _print(db, ali, ALI, model="someone/other-model")            # wrong model
        _print(db, ali, ALI + [0.0] * 16)                            # wrong dimension (32)
        _print(db, ali, ALI, active=False)                           # inactive
        _print(db, ali, ALI, identity_id=None)                       # attributed to nobody
        db.commit()
        [res] = batch_match_voice_embeddings(db, [("p", ALI)], model=MODEL)
    assert res.decision == DECISION_UNKNOWN, "every print in the gallery was ineligible"
    assert res.score is None


def test_probes_of_different_dimensions_share_one_batch():
    """The contract allows 16-1024 dims; each probe only meets prints of its own dimension."""
    big = [1.0] + [0.0] * 31
    with SessionLocal() as db:
        ali = _person(db, "علي عباس", "MIL-ARMY-B9")
        wide = _person(db, "سعاد نصر", "MIL-ARMY-B10")
        _print(db, ali, ALI)
        _print(db, wide, big)
        db.commit()
        results = batch_match_voice_embeddings(db, [("small", ALI), ("wide", big)], model=MODEL)
    by_key = {r.key: r for r in results}
    assert by_key["small"].identity_id == ali.id
    assert by_key["wide"].identity_id == wide.id
    assert by_key["small"].decision == by_key["wide"].decision == DECISION_SUGGESTED


def test_the_sql_path_agrees_with_the_reference_implementation():
    """pgvector and best_match must produce the same verdicts from the same gallery."""
    from app.services.voice_matching import best_match

    with SessionLocal() as db:
        ali = _person(db, "علي عباس", "MIL-ARMY-B11")
        georges = _person(db, "جورج حداد", "MIL-ARMY-B12")
        prints = [_print(db, ali, _vec(1.0)), _print(db, georges, GEORGES)]
        db.commit()
        for cos in (0.9, 0.66, 0.64, 0.5372, 0.0):
            probe = _vec(cos)
            [sql_res] = batch_match_voice_embeddings(db, [("p", probe)], model=MODEL)
            py_res = best_match(probe, prints, model=MODEL, threshold=0.65, margin=0.05)
            if sql_res.decision == DECISION_SUGGESTED:
                assert py_res is not None and py_res.enrollment.identity_id == sql_res.identity_id
                assert abs(py_res.score - sql_res.score) < 1e-4
            else:
                assert py_res is None
