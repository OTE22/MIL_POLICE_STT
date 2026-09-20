import uuid
from app.db.session import SessionLocal
from app.models import SessionSpeaker, IdentificationStatus
from app.services.voice_matching import apply_voice_identification
from tests.conftest import auth
from tests.test_voice_matching import _submit, _voice, _speakers, _enroll, _link_identity, EMB_A


def pending(client, token):
    source = _submit(client, token, voice=_voice(SPEAKER_00=EMB_A))
    speaker = _speakers(client, token, source['id'])['SPEAKER_00']
    response = _enroll(client, token, source['id'], speaker['id'], 'MIL-ARMY-991', 'Person B')
    assert response.status_code == 201
    target = _submit(client, token, voice=_voice(SPEAKER_00=EMB_A))
    probe = _speakers(client, token, target['id'])['SPEAKER_00']
    assert probe['identification_status'] == 'SUGGESTED'
    return target, probe


def test_manual_selection_cancels_old_suggestion_and_survives_rematch(client, investigator):
    token = investigator['token']
    target, probe = pending(client, token)
    response = _link_identity(client, token, target['id'], probe['id'], 'MIL-ARMY-992', 'Person A')
    assert response.status_code == 200
    chosen = response.json()
    assert chosen['identity_name'] == 'Person A'
    assert chosen['identification_status'] == 'CONFIRMED'
    assert chosen['suggested_name'] is None
    assert chosen['suggested_score'] is None
    decision = client.post(f"/api/investigations/{target['id']}/speakers/{probe['id']}/identification",
                           headers=auth(token), json={'accept': True})
    assert decision.status_code == 409
    rematch = client.post(f"/api/investigations/{target['id']}/voice-rematch", headers=auth(token))
    assert rematch.status_code == 200
    assert rematch.json()['suggested'] == 0
    after = _speakers(client, token, target['id'])['SPEAKER_00']
    assert after['identity_id'] == chosen['identity_id']
    with SessionLocal() as db:
        stored = db.get(SessionSpeaker, uuid.UUID(probe['id']))
        assert stored.decided_by is not None and stored.decided_at is not None
        assert stored.suggested_enrollment_id is None
        # Legacy manually linked rows also remain protected, even before this fix.
        stored.identification_status = IdentificationStatus.NONE
        db.commit()
    assert client.post(f"/api/investigations/{target['id']}/voice-rematch", headers=auth(token)).json()['suggested'] == 0
    with SessionLocal() as db:
        stored = db.get(SessionSpeaker, uuid.UUID(probe['id']))
        stored.voice_embedding = None
        db.flush()
        assert apply_voice_identification(db, session_id=stored.session_id,
            recording_id=stored.recording_id, label_map={stored.source_label: stored.speaker_label},
            voice=_voice(**{stored.source_label: EMB_A}), user_id=None) == 0
        assert stored.voice_embedding == EMB_A
        assert str(stored.identity_id) == chosen['identity_id']


def test_confirmation_returns_identity_needed_for_immediate_enrollment(client, investigator):
    token = investigator['token']
    target, probe = pending(client, token)
    endpoint = f"/api/investigations/{target['id']}/speakers/{probe['id']}"
    confirmed = client.post(endpoint + '/identification', headers=auth(token), json={'accept': True})
    assert confirmed.status_code == 200
    data = confirmed.json()
    assert data['identity_id']
    assert data['identity_name'] == data['display_name'] == 'Person B'
    assert data['speaker_role'] == 'SUBJECT'
    enrollment = client.post(endpoint + '/enroll', headers=auth(token), json={'consent_recorded': True})
    assert enrollment.status_code == 201, enrollment.text
    assert enrollment.json()['identity_id'] == data['identity_id']
