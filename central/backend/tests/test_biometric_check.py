"""The manual فحص البصمات الصوتية: advisory, per-person, connected components, changes nothing.

Same synthetic-unit-vector approach as test_batch_voice_matching: exact cosines, values far
from the thresholds so float4 representation error can never flip a verdict.
"""

import math
import uuid

from app.config import get_settings
from app.db.session import SessionLocal
from app.models import VoiceEnrollment

from conftest import ADMIN, auth
from test_batch_voice_matching import DIM, MODEL, _person, _print


def _login(client):
    return client.post("/api/auth/login", json=ADMIN).json()["access_token"]


def _axis(i: int) -> list[float]:
    v = [0.0] * DIM
    v[i] = 1.0
    return v


def _pair_vec(base_axis: int, cos: float, ortho_axis: int) -> list[float]:
    """Unit vector with an exact cosine against _axis(base_axis)."""
    v = [0.0] * DIM
    v[base_axis] = cos
    v[ortho_axis] = math.sqrt(1 - cos**2)
    return v


def _check(client, token, identity_id):
    return client.post(
        f"/api/voice-enrollments/people/{identity_id}/biometric-check", headers=auth(token)
    )


def _no_number_lists(node):
    """No value anywhere in the payload may be a list of numbers - that is a vector."""
    if isinstance(node, dict):
        for v in node.values():
            _no_number_lists(v)
    elif isinstance(node, list):
        assert not (node and all(isinstance(x, (int, float)) for x in node)), (
            "a numeric array leaked into the biometric-check response"
        )
        for v in node:
            _no_number_lists(v)


# ---------------------------------------------------------------------------- basic shapes


def test_unknown_person_is_404_and_no_token_is_401(client):
    token = _login(client)
    assert _check(client, token, uuid.uuid4()).status_code == 404
    res = client.post(f"/api/voice-enrollments/people/{uuid.uuid4()}/biometric-check")
    assert res.status_code == 401


def test_person_with_no_active_prints_reports_no_prints(client):
    with SessionLocal() as db:
        p = _person(db, "بلا بصمات", "MIL-ARMY-Q0")
        _print(db, p, _axis(0), active=False)  # an INACTIVE print must not count
        db.commit()
    body = _check(client, _login(client), p.id).json()
    assert body["overall_status"] == "NO_PRINTS"
    assert body["total_active_prints"] == 0
    assert body["number_of_components"] == 0
    assert body["groups"] == []


def test_single_print_is_reported_as_single_print(client):
    with SessionLocal() as db:
        p = _person(db, "بصمة واحدة", "MIL-ARMY-Q1")
        _print(db, p, _axis(0))
        db.commit()
    body = _check(client, _login(client), p.id).json()
    assert body["overall_status"] == "SINGLE_PRINT"
    assert body["number_of_components"] == 1
    [group] = body["groups"]
    [pr] = group["prints"]
    assert pr["status"] == "SINGLE_PRINT"
    assert pr["peer_similarity_max"] is None
    assert pr["coherent_peer_count"] == 0


def test_two_coherent_prints_are_one_component(client):
    with SessionLocal() as db:
        p = _person(db, "منسجم", "MIL-ARMY-Q2")
        _print(db, p, _axis(0))
        _print(db, p, _pair_vec(0, 0.84, 1))
        db.commit()
    body = _check(client, _login(client), p.id).json()
    assert body["overall_status"] == "COHERENT"
    assert body["number_of_components"] == 1
    statuses = [pr["status"] for pr in body["groups"][0]["prints"]]
    assert statuses == ["COHERENT", "COHERENT"]
    for pr in body["groups"][0]["prints"]:
        assert abs(pr["peer_similarity_max"] - 0.84) < 1e-3
        assert pr["coherent_peer_count"] == 1


def test_two_incoherent_prints_are_two_components_and_review_required(client):
    with SessionLocal() as db:
        p = _person(db, "غير منسجم", "MIL-ARMY-Q3")
        _print(db, p, _axis(0))
        _print(db, p, _pair_vec(0, 0.40, 1))  # different-speaker band
        db.commit()
    body = _check(client, _login(client), p.id).json()
    assert body["overall_status"] == "REVIEW_REQUIRED"
    assert body["number_of_components"] == 2
    prints = body["groups"][0]["prints"]
    assert [pr["status"] for pr in prints] == ["ISOLATED", "ISOLATED"]
    assert prints[0]["component_id"] != prints[1]["component_id"]


def test_split_identity_two_internally_coherent_groups(client):
    """The spec's own example: A~B 0.84, C~D 0.86, cross ~0 -> 2 components, review."""
    with SessionLocal() as db:
        p = _person(db, "هوية منقسمة", "MIL-ARMY-Q4")
        a = _print(db, p, _axis(0))
        b = _print(db, p, _pair_vec(0, 0.84, 1))
        c = _print(db, p, _axis(2))
        d = _print(db, p, _pair_vec(2, 0.86, 3))
        db.commit()
        ids = {str(a.id): "A", str(b.id): "B", str(c.id): "C", str(d.id): "D"}
    body = _check(client, _login(client), p.id).json()
    assert body["overall_status"] == "REVIEW_REQUIRED"
    assert body["number_of_components"] == 2
    component_of = {
        ids[pr["enrollment_id"]]: pr["component_id"] for pr in body["groups"][0]["prints"]
    }
    assert component_of["A"] == component_of["B"]
    assert component_of["C"] == component_of["D"]
    assert component_of["A"] != component_of["C"]
    # Every print DOES have a coherent peer - max-similarity alone would call this healthy.
    assert all(pr["coherent_peer_count"] == 1 for pr in body["groups"][0]["prints"])
    assert all(pr["status"] == "COHERENT" for pr in body["groups"][0]["prints"])


def test_near_duplicate_pair_is_flagged_but_not_review_required(client):
    """Near-duplicates waste coverage but are the SAME voice - advisory flag, no alarm."""
    with SessionLocal() as db:
        p = _person(db, "شبه مكرر", "MIL-ARMY-Q5")
        _print(db, p, _axis(0))
        _print(db, p, _pair_vec(0, 0.995, 1))
        db.commit()
    body = _check(client, _login(client), p.id).json()
    assert body["overall_status"] == "COHERENT"
    assert body["number_of_components"] == 1
    assert [pr["status"] for pr in body["groups"][0]["prints"]] == [
        "NEAR_DUPLICATE",
        "NEAR_DUPLICATE",
    ]


def test_inactive_prints_are_excluded_from_the_analysis(client):
    with SessionLocal() as db:
        p = _person(db, "بينهم معطلة", "MIL-ARMY-Q6")
        _print(db, p, _axis(0))
        _print(db, p, _pair_vec(0, 0.84, 1))
        _print(db, p, _axis(2), active=False)  # would be a second component if counted
        db.commit()
    body = _check(client, _login(client), p.id).json()
    assert body["overall_status"] == "COHERENT"
    assert body["total_active_prints"] == 2
    assert body["number_of_components"] == 1


def test_incompatible_models_are_grouped_separately_and_never_compared(client):
    with SessionLocal() as db:
        p = _person(db, "نموذجان", "MIL-ARMY-Q7")
        _print(db, p, _axis(0))
        _print(db, p, _pair_vec(0, 0.84, 1))
        _print(db, p, _axis(0), model="other/model")  # identical vector, other model
        db.commit()
    body = _check(client, _login(client), p.id).json()
    assert len(body["groups"]) == 2
    by_model = {g["model"]: g for g in body["groups"]}
    assert by_model[MODEL]["component_count"] == 1
    assert by_model["other/model"]["component_count"] == 1
    [other] = by_model["other/model"]["prints"]
    # Identical to a MODEL print, but cross-model similarity is meaningless - never computed.
    assert other["status"] == "SINGLE_PRINT"
    assert other["peer_similarity_max"] is None
    # Two groups that cannot be verified against each other -> a human must look.
    assert body["number_of_components"] == 2
    assert body["overall_status"] == "REVIEW_REQUIRED"


# ---------------------------------------------------------------------- advisory guarantees


def test_the_check_modifies_absolutely_nothing(client):
    with SessionLocal() as db:
        p = _person(db, "لا تعديل", "MIL-ARMY-Q8")
        _print(db, p, _axis(0))
        _print(db, p, _pair_vec(0, 0.40, 1))  # incoherent on purpose
        db.commit()
        before = {
            e.id: (e.is_active, e.identity_id, e.person_name)
            for e in db.query(VoiceEnrollment).filter_by(identity_id=p.id)
        }
    assert _check(client, _login(client), p.id).json()["overall_status"] == "REVIEW_REQUIRED"
    with SessionLocal() as db:
        after = {
            e.id: (e.is_active, e.identity_id, e.person_name)
            for e in db.query(VoiceEnrollment).filter_by(identity_id=p.id)
        }
    assert after == before


def test_no_vectors_in_the_response(client):
    with SessionLocal() as db:
        p = _person(db, "بلا متجهات", "MIL-ARMY-Q9")
        _print(db, p, _axis(0))
        _print(db, p, _pair_vec(0, 0.84, 1))
        db.commit()
    res = _check(client, _login(client), p.id)
    assert '"embedding":' not in res.text
    _no_number_lists(res.json())


# ------------------------------------------------------------------ thresholds are the live ones


def test_raising_the_match_threshold_splits_a_previously_coherent_pair(client):
    with SessionLocal() as db:
        p = _person(db, "حساس للعتبة", "MIL-ARMY-QA")
        _print(db, p, _axis(0))
        _print(db, p, _pair_vec(0, 0.84, 1))
        db.commit()
    token = _login(client)
    assert _check(client, token, p.id).json()["overall_status"] == "COHERENT"
    original = get_settings().voice_match_threshold
    try:
        res = client.put(
            "/api/admin/config",
            json={"values": {"voice_match_threshold": 0.90}},
            headers=auth(token),
        )
        assert res.status_code == 200, res.text
        body = _check(client, token, p.id).json()
        assert body["coherence_threshold"] == 0.90
        assert body["overall_status"] == "REVIEW_REQUIRED"
        assert body["number_of_components"] == 2
    finally:
        client.put(
            "/api/admin/config",
            json={"values": {"voice_match_threshold": original}},
            headers=auth(token),
        )


def test_lowering_the_near_duplicate_threshold_flags_more_pairs(client):
    with SessionLocal() as db:
        p = _person(db, "حساس للتكرار", "MIL-ARMY-QB")
        _print(db, p, _axis(0))
        _print(db, p, _pair_vec(0, 0.94, 1))
        db.commit()
    token = _login(client)
    assert all(
        pr["status"] == "COHERENT"
        for pr in _check(client, token, p.id).json()["groups"][0]["prints"]
    )
    original = get_settings().voice_near_duplicate_threshold
    try:
        res = client.put(
            "/api/admin/config",
            json={"values": {"voice_near_duplicate_threshold": 0.93}},
            headers=auth(token),
        )
        assert res.status_code == 200, res.text
        body = _check(client, token, p.id).json()
        assert body["near_duplicate_threshold"] == 0.93
        assert all(pr["status"] == "NEAR_DUPLICATE" for pr in body["groups"][0]["prints"])
    finally:
        client.put(
            "/api/admin/config",
            json={"values": {"voice_near_duplicate_threshold": original}},
            headers=auth(token),
        )


def test_near_duplicate_threshold_must_stay_above_the_match_threshold(client):
    """0.90 near-dup with a 0.92 match threshold would call one pair both 'duplicate' and
    'incoherent'. The save is refused as a whole - neither value applies."""
    token = auth(_login(client))
    before = (get_settings().voice_match_threshold, get_settings().voice_near_duplicate_threshold)
    res = client.put(
        "/api/admin/config",
        json={"values": {"voice_match_threshold": 0.92, "voice_near_duplicate_threshold": 0.90}},
        headers=token,
    )
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "near_duplicate_must_exceed_match_threshold"
    assert (
        get_settings().voice_match_threshold,
        get_settings().voice_near_duplicate_threshold,
    ) == before
