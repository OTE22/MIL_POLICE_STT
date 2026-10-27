"""Populate only missing setup facts in the explicitly requested development session via its API."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import httpx
from sqlalchemy import select
from app.config import get_settings
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import User

TARGET = '04176210-31ec-46e5-9637-c1aff1747d1b'
settings = get_settings()
assert settings.environment == 'development', 'Refusing mock data outside development'
with SessionLocal() as db:
    user = db.scalar(select(User).where(User.username == settings.bootstrap_admin_username, User.is_active.is_(True)))
    assert user and 'investigations.update' in user.permission_codes
    token = create_access_token(user.id, user.username, {'exp': int(datetime.now(timezone.utc).timestamp()) + 120,
                                                       'auth_mode': settings.auth_mode})[0]
client = httpx.Client(base_url='http://127.0.0.1:8000/api', headers={'Authorization': 'Bearer ' + token}, timeout=30)
base = '/investigations/' + TARGET


def get(path):
    response = client.get(path)
    response.raise_for_status()
    return response.json()


before = get(base)
assert before['workflow_state'] not in ('CLOSED', 'ARCHIVED'), 'Do not reopen a session implicitly'
issues = before['intake_readiness']['issues']
payload = {'expected_revision': before['revision']}
changes = []
details = {
    'father_name': 'أب تجريبي', 'mother_name': 'أم تجريبية', 'birth_year': '1990',
    'birth_place': 'بيروت — بيانات تجريبية', 'district': 'بيروت — بيانات تجريبية',
    'residence': 'عنوان تجريبي غير حقيقي — بيئة التطوير', 'phone': '0000000000',
    'family_status': 'أعزب — بيانات تجريبية', 'education': 'ثانوي — بيانات تجريبية',
    'occupation_statement': 'مهنة تجريبية — بيئة التطوير',
    'prior_record_statement': 'بيان افتراضي للتجربة فقط: لا سوابق ضمن السيناريو التجريبي، وليس تصريحاً حقيقياً.'}
subjects = []
for index, original in enumerate(before['subjects'], 1):
    row = {'participant_key': original['participant_key'], 'subject_name': original['subject_name'],
           'person_type': original['person_type'], 'security_branch': original['security_branch'],
           'military_id': original['military_id']}
    missing = {issue['field'] for issue in issues if issue['participant_key'] == original['participant_key']}
    assert not any(issue['code'] == 'participant_exception_conflict' for issue in issues
                   if issue['participant_key'] == original['participant_key']), 'Resolve factual/exception conflicts explicitly'
    if missing:
        row['statement_details'] = copy.deepcopy(original['statement_details'])
        for key in missing & details.keys():
            row['statement_details'][key] = details[key]
        if 'person_type' in missing:
            row['person_type'] = 'CIVILIAN'
        defaults = {'subject_name': f'شخص تجريبي {index}', 'security_branch': 'ARMY', 'rank': 'رقيب — تجريبي',
            'military_id': f'DEV-MOCK-{TARGET[:8]}-{index:02d}', 'unit': 'وحدة تجريبية — بيئة التطوير',
            'nationality_code': 'LB', 'register_number': f'DEV-MOCK-{TARGET[:8]}-{index:02d}',
            'caza_code': 'BEIRUT', 'place_of_registration': 'بيروت — قيد تجريبي غير حقيقي'}
        # UNKNOWN types become explicit civilian mock participants, so include newly applicable fields.
        if original['person_type'] == 'UNKNOWN' and 'person_type' in missing:
            missing.add('nationality_code')
            if not original['is_unregistered']:
                missing.update({'register_number', 'caza_code', 'place_of_registration'})
        for key in missing & defaults.keys():
            row[key] = defaults[key]
        if 'military_id' in missing and row['security_branch'] == 'OTHER':
            row['military_id'] = None
            row['field_exceptions'] = {**original['field_exceptions'], 'military_id': {'status': 'UNKNOWN',
                'reason': 'بيانات تطوير تجريبية: لا يوجد رقم عسكري موثوق لجهاز مسجل ضمن أخرى.'}}
        if 'occupation_statement' in missing and row['person_type'] == 'MILITARY':
            row['statement_details']['occupation_statement'] = ' — '.join(v for v in (
                row.get('rank') or original['rank'], row.get('unit') or original['unit'], 'تكليف تجريبي') if v)
        if 'documents' in missing:
            row['documents'] = [{'document_type': 'OTHER', 'document_number': f'DEV-MOCK-DOC-{TARGET[:8]}-{index:02d}',
                'notes': 'وثيقة افتراضية للتجربة فقط؛ لا يوجد مسح ضوئي ولا تأكيد تحقق أو توقيع.'}]
        marker = '[DEV-MOCK] القيم المضافة هنا افتراضية لاختبار سير العمل وليست بيانات أو تصريحات موثقة.'
        notes = original.get('notes') or ''
        if marker not in notes and len(notes) + len(marker) + 1 <= 4000:
            row['notes'] = (notes + '\n' + marker).strip()
        changes.append({'participant_key': original['participant_key'], 'fields': sorted(missing)})
    subjects.append(row)
if changes:
    payload['subjects'] = subjects
for issue in issues:
    if issue['participant_key'] is not None:
        continue
    key = issue['field']
    if key in ('title', 'location', 'session_date'):
        payload[key] = {'title': 'جلسة تحقيق تجريبية — بيئة التطوير', 'location': 'مكتب تحقيق تجريبي — بيئة التطوير',
                        'session_date': '2026-10-27'}[key]
    elif key == 'investigators':
        assert before['investigators'], 'An existing investigator must be chosen; do not invent an account'
        payload[key] = [{'investigator_id': investigator['id'], 'assignment_role': 'LEAD' if i == 0 else 'ASSISTANT'}
                        for i, investigator in enumerate(before['investigators'])]
marker = '[DEV-MOCK] استكمال البيانات الناقصة بقيم افتراضية بناءً على طلب المستخدم في بيئة التطوير؛ لم يتم تأكيد وثائق أو إفادات أو توقيع.'
notes = before.get('notes') or ''
if len(payload) > 1 and marker not in notes and len(notes) + len(marker) + 1 <= 8000:
    payload['notes'] = (notes + '\n' + marker).strip()
summary = {'session_id': TARGET, 'missing_before': len(issues), 'participant_changes': changes,
           'session_fields': sorted(set(payload) - {'expected_revision', 'subjects'})}
if '--apply' not in sys.argv:
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    raise SystemExit(0)
archive_before = get(base + '/reports')
backup = Path(settings.storage_root) / 'backups' / ('development-mock-intake-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
backup.mkdir(parents=True)
(backup / 'before.json').write_text(json.dumps(before, ensure_ascii=False, indent=2), encoding='utf-8')
(backup / 'archive-before.json').write_text(json.dumps(archive_before, ensure_ascii=False, indent=2), encoding='utf-8')
if len(payload) > 1:
    response = client.put(base, json=payload)
    assert response.status_code == 200, response.text
after = get(base)
assert after['intake_readiness']['ready'], after['intake_readiness']
assert {p['participant_key']: p['id'] for p in before['subjects']} == {p['participant_key']: p['id'] for p in after['subjects']}
assert [(r['id'], r['sha256']) for r in before['recordings']] == [(r['id'], r['sha256']) for r in after['recordings']]
assert get(base + '/reports')['reports'] == archive_before['reports']
for old in before['subjects']:
    current = next(p for p in after['subjects'] if p['id'] == old['id'])
    assert {d['id'] for d in old['documents']} <= {d['id'] for d in current['documents']}
summary.update(result='PASS', intake_ready=True, missing_after=0, revision=after['revision'],
               participant_ids_preserved=True, original_recordings_preserved=True, issued_reports_unchanged=True)
(backup / 'result.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False), flush=True)
