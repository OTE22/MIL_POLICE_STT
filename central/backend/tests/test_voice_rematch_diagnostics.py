"""Explain unsuccessful identification without weakening the matching decision."""

import math

import pytest

from tests.conftest import auth
from tests.test_voice_matching import EMB_A, EMB_B, _enroll, _speakers, _submit, _voice


def _rematch(client, token, session_id):
    response = client.post(
        f"/api/investigations/{session_id}/voice-rematch", headers=auth(token)
    )
    assert response.status_code == 200, response.text
    return response.json()


def _source(client, token, *, second_person=False):
    session = _submit(client, token, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    speakers = _speakers(client, token, session["id"])
    response = _enroll(client, token, session["id"], speakers["SPEAKER_00"]["id"],
                       "MIL-ARMY-71", "First person")
    assert response.status_code == 201, response.text
    if second_person:
        response = _enroll(client, token, session["id"], speakers["SPEAKER_01"]["id"],
                           "MIL-ARMY-72", "Second person")
        assert response.status_code == 201, response.text
    return session


def test_rematch_reports_missing_samples(client, investigator):
    token = investigator["token"]
    session = _submit(client, token)
    assert _rematch(client, token, session["id"]) == {
        "scanned": 0, "suggested": 0, "no_sample": 2,
        "no_compatible_enrollment": 0, "below_threshold": 0,
        "ambiguous": 0, "skipped_decided": 0,
    }


@pytest.mark.parametrize("incompatible_gallery", [False, True])
def test_rematch_distinguishes_missing_compatible_prints_from_low_similarity(
    client, investigator, incompatible_gallery
):
    token = investigator["token"]
    if incompatible_gallery:
        _source(client, token)
    voice = _voice(SPEAKER_00=EMB_A)
    if incompatible_gallery:
        voice["model_revision"] = "different-revision"
    session = _submit(client, token, voice=voice)
    result = _rematch(client, token, session["id"])
    assert result["scanned"] == result["no_compatible_enrollment"] == 1
    assert result["no_sample"] == 1
    assert result["suggested"] == result["below_threshold"] == result["ambiguous"] == 0
    assert _speakers(client, token, session["id"])["SPEAKER_00"]["identity_id"] is None


def test_rematch_reports_low_score_and_protects_human_decisions(client, investigator):
    token = investigator["token"]
    source = _source(client, token)
    session = _submit(client, token, voice=_voice(SPEAKER_00=EMB_A, SPEAKER_01=EMB_B))
    result = _rematch(client, token, session["id"])
    assert result["scanned"] == 2
    assert result["suggested"] == result["below_threshold"] == 1
    assert result["no_compatible_enrollment"] == result["ambiguous"] == 0

    result = _rematch(client, token, source["id"])
    assert result["skipped_decided"] == 1
    assert result["scanned"] == result["below_threshold"] == 1
    speaker = _speakers(client, token, source["id"])["SPEAKER_00"]
    assert speaker["identification_status"] == "CONFIRMED"

    # The registry-wide endpoint exposes the same diagnostics and still leaves existing
    # suggestions alone; only the two low-scoring, undecided observations are scanned.
    response = client.post("/api/voice-enrollments/rematch", headers=auth(token))
    assert response.status_code == 200, response.text
    assert response.json() == {
        "sessions": 2, "scanned": 2, "suggested": 0, "no_sample": 0,
        "no_compatible_enrollment": 0, "below_threshold": 2,
        "ambiguous": 0, "skipped_decided": 1,
    }


def test_rematch_explains_ambiguous_people_without_assigning_either(client, investigator):
    token = investigator["token"]
    _source(client, token, second_person=True)
    probe = [0.70, 0.68, math.sqrt(1 - 0.70**2 - 0.68**2)] + [0.0] * 13
    session = _submit(client, token, voice=_voice(SPEAKER_00=probe))
    result = _rematch(client, token, session["id"])
    assert result["scanned"] == result["ambiguous"] == 1
    assert result["suggested"] == result["below_threshold"] == result["no_compatible_enrollment"] == 0
    speaker = _speakers(client, token, session["id"])["SPEAKER_00"]
    assert speaker["identification_status"] == "NONE"
    assert speaker["identity_id"] is None
