"""Explicit manual attestations within/across computed groups, never vector merging."""
import uuid

import pytest

from app.db.session import SessionLocal
from app.models import VoiceEnrollment
from conftest import auth
from test_batch_voice_matching import _person, _print
from test_biometric_check import _axis, _pair_vec, _check


def gallery(similarity=0.84, incompatible=False):
    with SessionLocal() as db:
        person = _person(db, "شخص تجريبي", "confirm")
        first = _print(db, person, _axis(0))
        second = _print(db, person, _pair_vec(0, similarity, 1))
        if incompatible:
            second.model_revision = "other"
        db.commit()
    return person.id, [first, second]


def payload(prints):
    return {"reason": "راجعت العينات وتحققت من صاحب الصوت", "prints": [
        {"enrollment_id": str(p.id), "expected_updated_at": p.updated_at.isoformat()} for p in prints]}


def confirm(client, token, person, prints):
    return client.post(f"/api/voice-enrollments/people/{person}/identity-confirmations",
                       headers=auth(token), json=payload(prints))


@pytest.mark.parametrize("similarity,incompatible,components", [(0.84, False, 1), (0.4, False, 2), (0.84, True, 2)])
def test_confirmation_within_across_and_incompatible_groups_changes_no_biometrics(
    client, admin_token, similarity, incompatible, components
):
    person, prints = gallery(similarity, incompatible)
    before = _check(client, admin_token, person).json()
    assert before["number_of_components"] == components
    response = confirm(client, admin_token, person, prints)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "ACTIVE"
    assert response.json()["reviewer_name"]
    after = _check(client, admin_token, person).json()
    assert after["groups"] == before["groups"]
    assert after["overall_status"] == before["overall_status"]
    assert after["number_of_components"] == components
    assert set(after["identity_confirmations"][0]["enrollment_ids"]) == {str(p.id) for p in prints}
    with SessionLocal() as db:
        for original in prints:
            stored = db.get(VoiceEnrollment, original.id)
            assert stored.updated_at == original.updated_at
            assert list(stored.embedding) == list(original.embedding)
    assert confirm(client, admin_token, person, prints).status_code == 409


def test_new_prints_do_not_inherit_confirmation_and_edits_require_review(client, admin_token):
    person, prints = gallery()
    assert confirm(client, admin_token, person, prints).status_code == 200
    with SessionLocal() as db:
        from app.models import PersonIdentity
        new = _print(db, db.get(PersonIdentity, person), _axis(0))
        db.commit()
    checked = _check(client, admin_token, person).json()
    decision = checked["identity_confirmations"][0]
    assert decision["status"] == "ACTIVE"
    assert str(new.id) not in decision["enrollment_ids"]
    with SessionLocal() as db:
        db.get(VoiceEnrollment, prints[0].id).notes = "تعديل بعد المراجعة"
        db.commit()
    assert _check(client, admin_token, person).json()["identity_confirmations"][0]["status"] == "STALE"
    assert confirm(client, admin_token, person, prints).status_code == 409


def test_reopen_keeps_original_decision_and_requires_reason_and_permission(client, admin_token, viewer):
    person, prints = gallery()
    decision = confirm(client, admin_token, person, prints).json()
    path = f"/api/voice-enrollments/people/{person}/identity-confirmations/{decision['id']}/reopen"
    assert client.post(path, headers=auth(viewer["token"]), json={"reason": "إعادة تحقق"}).status_code == 403
    assert client.post(path, headers=auth(admin_token), json={"reason": "  "}).status_code == 422
    response = client.post(path, headers=auth(admin_token), json={"reason": "توجد عينة تحتاج تحققاً إضافياً"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "REOPENED" and body["reopened_at"] and body["reopened_by_name"]
    assert body["reason"] == decision["reason"]
    assert client.post(path, headers=auth(admin_token), json={"reason": "مرة ثانية"}).status_code == 409
    assert confirm(client, admin_token, person, prints).status_code == 200
    entries = _check(client, admin_token, person).json()["identity_confirmations"]
    assert [e["status"] for e in entries] == ["ACTIVE", "REOPENED"]


def test_confirmation_rejects_invalid_selections_and_unprivileged_users(client, admin_token, viewer):
    person, prints = gallery()
    path = f"/api/voice-enrollments/people/{person}/identity-confirmations"
    assert confirm(client, viewer["token"], person, prints).status_code == 403
    assert client.post(path, json=payload(prints)).status_code == 401
    for body in [payload(prints[:1]), payload([prints[0], prints[0]]), {**payload(prints), "reason": " "},
                 {**payload(prints), "reason": "x" * 2001}]:
        assert client.post(path, headers=auth(admin_token), json=body).status_code == 422
    other, others = gallery()
    assert confirm(client, admin_token, person, [prints[0], others[0]]).status_code == 409
    assert confirm(client, admin_token, other, prints).status_code == 409
    with SessionLocal() as db:
        db.get(VoiceEnrollment, prints[0].id).is_active = False
        db.commit()
    assert confirm(client, admin_token, person, prints).status_code == 409
    assert _check(client, admin_token, person).json()["identity_confirmations"] == []


def test_deleted_print_makes_confirmation_stale_and_reopen_is_identity_scoped(client, admin_token):
    person, prints = gallery()
    decision = confirm(client, admin_token, person, prints).json()
    with SessionLocal() as db:
        db.delete(db.get(VoiceEnrollment, prints[0].id))
        db.commit()
    assert _check(client, admin_token, person).json()["identity_confirmations"][0]["status"] == "STALE"
    path = f"/api/voice-enrollments/people/{uuid.uuid4()}/identity-confirmations/{decision['id']}/reopen"
    assert client.post(path, headers=auth(admin_token), json={"reason": "اختبار"}).status_code == 404
