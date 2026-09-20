import uuid
import pytest
from app.db.session import SessionLocal
from app.models import SessionSpeaker, VoiceEnrollment
from app.services.voice_matching import batch_match_voice_embeddings
from tests.conftest import auth
from tests.test_voice_matching import EMB_A, MODEL, _submit, _voice, _speakers, _enroll


def enrolled(client, token):
    session = _submit(client, token, voice=_voice(SPEAKER_00=EMB_A))
    speaker = _speakers(client, token, session['id'])['SPEAKER_00']
    response = _enroll(client, token, session['id'], speaker['id'], 'MIL-ARMY-991', 'Test person',
                       model='forged', model_revision='forged', provider='forged', sample_seconds=9999)
    assert response.status_code == 201, response.text
    return response.json()


def test_enrollment_uses_only_agent_provenance(client, investigator):
    token = investigator['token']
    row = enrolled(client, token)
    assert (row['model'], row['model_revision'], row['provider'], row['sample_seconds']) == (
        MODEL, '1.16.0', 'nemo_speakernet', 8.0)
    with SessionLocal() as db:
        stored = db.get(VoiceEnrollment, uuid.UUID(row['id']))
        assert list(stored.embedding) == EMB_A
        for revision, provider in [('other', 'nemo_speakernet'), ('1.16.0', 'other'), (None, None)]:
            result = batch_match_voice_embeddings(db, [('probe', EMB_A)], model=MODEL,
                                                 model_revision=revision, provider=provider)[0]
            assert result.decision == 'UNKNOWN'
        assert batch_match_voice_embeddings(db, [('probe', EMB_A)], model=MODEL,
            model_revision='1.16.0', provider='nemo_speakernet')[0].decision == 'SUGGESTED'


@pytest.mark.parametrize('action', ['disable', 'delete'])
def test_retired_print_invalidates_pending_suggestion(client, investigator, action):
    token = investigator['token']
    row = enrolled(client, token)
    session = _submit(client, token, voice=_voice(SPEAKER_00=EMB_A))
    speaker = _speakers(client, token, session['id'])['SPEAKER_00']
    assert speaker['identification_status'] == 'SUGGESTED'
    url = f"/api/voice-enrollments/{row['id']}"
    response = client.delete(url, headers=auth(token)) if action == 'delete' else client.patch(
        url, headers=auth(token), json={'is_active': False})
    assert response.status_code in (200, 204)
    decision = client.post(f"/api/investigations/{session['id']}/speakers/{speaker['id']}/identification",
                           headers=auth(token), json={'accept': True})
    assert decision.status_code == 409
    after = _speakers(client, token, session['id'])['SPEAKER_00']
    assert after['identification_status'] == 'NONE'
    assert after['identity_id'] is None


def test_confirmation_revalidates_print_even_without_invalidation(client, investigator):
    token = investigator['token']
    row = enrolled(client, token)
    session = _submit(client, token, voice=_voice(SPEAKER_00=EMB_A))
    speaker = _speakers(client, token, session['id'])['SPEAKER_00']
    with SessionLocal() as db:
        db.get(VoiceEnrollment, uuid.UUID(row['id'])).is_active = False
        db.commit()
    response = client.post(f"/api/investigations/{session['id']}/speakers/{speaker['id']}/identification",
                           headers=auth(token), json={'accept': True})
    assert response.status_code == 409
    assert response.json()['detail'] == 'voice_suggestion_stale'
    with SessionLocal() as db:
        assert db.get(SessionSpeaker, uuid.UUID(speaker['id'])).identity_id is None
