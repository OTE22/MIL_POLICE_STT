"""Person lifecycle after retiring generated reference numbers."""
import uuid

import pytest
from sqlalchemy import inspect, select

from app.db.session import SessionLocal, engine
from app.models import PersonIdentity, SessionSpeaker, Subject, VoiceEnrollment
from app.services.person_identity import create_identity, merge_identities, repoint_identity, resolve_identity
from tests.conftest import auth, create_session


def speaker_for(session):
    with SessionLocal() as db:
        speaker = SessionSpeaker(session_id=uuid.UUID(session['id']), speaker_label='SPEAKER_00',
                                 voice_embedding=[1.0] + [0.0] * 15, voice_embedding_model='test')
        db.add(speaker)
        db.commit()
        return str(speaker.id)


def test_reference_columns_and_sequences_are_gone():
    from sqlalchemy import text
    inspector = inspect(engine)
    for table, removed in {
        'person_identities': {'reference_normalized', 'reference_display'},
        'subjects': {'reference_number'}, 'session_speakers': {'reference_number'},
        'investigator_profiles': {'reference_number'}, 'voice_enrollments': {'person_reference'},
    }.items():
        assert not removed & {c['name'] for c in inspector.get_columns(table)}
    with engine.connect() as db:
        assert db.execute(text("SELECT to_regclass('civilian_person_reference_seq')")).scalar() is None
        assert db.execute(text("SELECT to_regclass('tmp_person_reference_seq')")).scalar() is None


def test_same_names_are_distinct_and_resave_preserves_ids(client, admin_token):
    s = create_session(client, admin_token, subjects=[{'subject_name': 'علي حسن'}, {'subject_name': 'علي حسن'}])
    original = {p['participant_key']: p['identity_id'] for p in s['subjects']}
    assert len(set(original.values())) == 2
    assert all('reference_number' not in p for p in s['subjects'])
    response = client.put(f"/api/investigations/{s['id']}", headers=auth(admin_token),
                          json={'subjects': list(reversed(s['subjects']))})
    assert response.status_code == 200, response.text
    assert {p['participant_key']: p['identity_id'] for p in response.json()['subjects']} == original


def test_explicit_identity_reused_across_sessions(client, admin_token):
    first = create_session(client, admin_token)
    identity_id = first['subjects'][0]['identity_id']
    second = create_session(client, admin_token, subjects=[{'subject_name': 'أحمد محمد', 'identity_id': identity_id}])
    assert second['subjects'][0]['identity_id'] == identity_id


@pytest.mark.parametrize('person_type', ['CIVILIAN', 'UNKNOWN', 'MILITARY'])
def test_people_without_documents_can_be_identified(client, admin_token, person_type):
    s = create_session(client, admin_token, subjects=[{'subject_name': 'شخص', 'person_type': person_type}])
    assert s['subjects'][0]['identity_id']
    people = client.get(f"/api/investigations/{s['id']}/people", headers=auth(admin_token)).json()
    assert next(p for p in people if p['source'] == 'SUBJECT')['selectable']


def test_military_numbers_reuse_person_only_within_force(client, admin_token):
    def subject(branch, serial='٤٤٧١', name='علي حسن'):
        return {'subject_name': name, 'person_type': 'MILITARY', 'security_branch': branch, 'military_id': serial}
    first = create_session(client, admin_token, subjects=[subject('ARMY')])
    second = create_session(client, admin_token, subjects=[subject('ARMY', '4471')])
    other = create_session(client, admin_token, subjects=[subject('ISF')])
    assert first['subjects'][0]['identity_id'] == second['subjects'][0]['identity_id']
    assert first['subjects'][0]['identity_id'] != other['subjects'][0]['identity_id']
    response = client.post('/api/investigations', headers=auth(admin_token),
                           json={'title': 'conflict', 'subjects': [subject('ARMY', name='شخص آخر')]})
    assert response.status_code == 409


def test_lost_participant_and_identity_swap_are_refused(client, admin_token):
    s = create_session(client, admin_token)
    url = f"/api/investigations/{s['id']}"
    response = client.put(url, headers=auth(admin_token), json={'subjects': [{'subject_name': 'أحمد محمد'}]})
    assert response.status_code == 409
    other = create_session(client, admin_token)['subjects'][0]['identity_id']
    response = client.put(url, headers=auth(admin_token), json={'subjects': [{**s['subjects'][0], 'identity_id': other}]})
    assert response.status_code == 409
    response = client.put(url, headers=auth(admin_token), json={'subjects': [], 'removed_participant_keys': [s['subjects'][0]['participant_key']]})
    assert response.status_code == 200


def test_unknown_uuid_is_not_created(client, admin_token):
    response = client.post('/api/investigations', headers=auth(admin_token),
                           json={'title': 'bad', 'subjects': [{'subject_name': 'شخص', 'identity_id': str(uuid.uuid4())}]})
    assert response.status_code == 404


def test_retired_reference_payload_is_rejected(client, admin_token):
    response = client.post('/api/investigations', headers=auth(admin_token),
                           json={'title': 'stale', 'subjects': [{'subject_name': 'شخص', 'reference_number': 'CIV-1'}]})
    assert response.status_code == 422


def test_identity_selection_requires_voice_permission(client, admin_token, investigator):
    from app.models import Role, Permission, User
    token = investigator['token']
    s = create_session(client, token)
    speaker_id = speaker_for(s)
    with SessionLocal() as db:
        user = db.get(User, uuid.UUID(investigator['user']['id']))
        role = db.scalar(select(Role).where(Role.name == 'UUID_LABELLER')) or Role(name='UUID_LABELLER')
        role.permissions = list(db.scalars(select(Permission).where(Permission.code.in_([
            'speakers.assign', 'investigations.read_assigned', 'transcripts.read',
        ]))).all())
        user.roles = [role]
        db.commit()
    url = f"/api/investigations/{s['id']}/speakers/{speaker_id}"
    assert client.patch(url, headers=auth(token), json={'notes': 'allowed'}).status_code == 200
    assert client.patch(url, headers=auth(token), json={'identity_id': s['subjects'][0]['identity_id']}).status_code == 403


def test_speaker_selection_and_enrollment_use_uuid(client, admin_token):
    s = create_session(client, admin_token)
    speaker_id = speaker_for(s)
    url = f"/api/investigations/{s['id']}/speakers/{speaker_id}"
    identity_id = s['subjects'][0]['identity_id']
    linked = client.patch(url, headers=auth(admin_token), json={'identity_id': identity_id})
    assert linked.status_code == 200, linked.text
    assert linked.json()['identity_id'] == identity_id
    assert 'reference_number' not in linked.json()
    enrollment = client.post(url + '/enroll', headers=auth(admin_token), json={'model': 'test-model', 'consent_recorded': True})
    assert enrollment.status_code == 201, enrollment.text
    assert enrollment.json()['identity_id'] == identity_id
    assert 'person_reference' not in enrollment.json()
    renamed = client.patch('/api/voice-enrollments/' + enrollment.json()['id'], headers=auth(admin_token),
                           json={'person_name': 'اسم مصحح', 'apply_to_person': True})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()['identity_id'] == identity_id
    assert renamed.json()['enrolled_person_name'] == 'أحمد محمد'


def test_speaker_cannot_select_person_outside_session(client, admin_token):
    s = create_session(client, admin_token)
    other = create_session(client, admin_token)['subjects'][0]['identity_id']
    response = client.patch(f"/api/investigations/{s['id']}/speakers/{speaker_for(s)}", headers=auth(admin_token), json={'identity_id': other})
    assert response.status_code == 400


def test_merge_preserves_voiceprints_participants_and_stale_ids(client, admin_token):
    s = create_session(client, admin_token)
    source_id = uuid.UUID(s['subjects'][0]['identity_id'])
    with SessionLocal() as db:
        target = create_identity(db, 'الاسم المصحح')
        db.add(VoiceEnrollment(identity_id=source_id, person_name='أحمد محمد', embedding=[1.0]*16,
                               embedding_dim=16, model='test', consent_recorded=True))
        db.flush()
        merged, target = merge_identities(db, source_id, target.id)
        repoint_identity(db, source_id=merged.id, target=target)
        db.commit()
        assert resolve_identity(db, db.get(PersonIdentity, source_id)).id == target.id
        assert db.scalar(select(Subject).where(Subject.session_id == uuid.UUID(s['id']))).identity_id == target.id
        assert db.scalar(select(VoiceEnrollment)).identity_id == target.id
        target_id = str(target.id)
    saved = client.put(f"/api/investigations/{s['id']}", headers=auth(admin_token), json={'subjects': s['subjects']})
    assert saved.status_code == 200, saved.text
    assert saved.json()['subjects'][0]['identity_id'] == target_id
