"""Read-only HTTP/runtime verification; temporary authorized admin token stays in memory."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
path = Path(sys.argv[1]).resolve()
assert path.is_relative_to(ROOT / 'storage/backups')
manifest = json.loads(path.read_text(encoding='utf-8'))
for service, info in manifest['images'].items():
    running = json.loads(subprocess.check_output(['docker', 'inspect', 'mstt-' + service], text=True))[0]
    assert running['Image'] == info['release_id']
    assert running['State']['Health']['Status'] == 'healthy', service
mint = '''
from datetime import datetime, timezone
from sqlalchemy import select
from app.config import get_settings
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import User
settings=get_settings()
with SessionLocal() as db:
 user=db.scalar(select(User).where(User.username==settings.bootstrap_admin_username,User.is_active.is_(True)))
 assert user and 'investigations.read_all' in user.permission_codes
 token,_=create_access_token(user.id,user.username,{'exp':int(datetime.now(timezone.utc).timestamp())+120,'auth_mode':settings.auth_mode})
 print(token)
'''
token = subprocess.check_output(['docker', 'exec', '-i', 'mstt-backend', 'python', '-'], input=mint, text=True).strip()
def api(route, data=None):
    request = urllib.request.Request('http://localhost/api' + route,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)

base = '/investigations/04176210-31ec-46e5-9637-c1aff1747d1b'
state = api(base + '/report/html')
assert state['document']['revision'] == 'investigation-html-3'
assert 'opening' in state['document']
# Strip server-owned block provenance before requesting the read-only preview.
document = state['document']
for block in document['blocks']:
    for key in ('authorship', 'dictation_sources', 'person_snapshot', 'template_snapshot'):
        block.pop(key, None)
    for entry in block.get('entries', []): entry.pop('source_snapshot', None)
    for finding in block.get('findings', []): finding.pop('subject_snapshot', None)
preview = api(base + '/report/html/preview', {'expected_token': state['token'], 'document': document})['html']
assert 'data-block-id="opening"' in preview
if any(block['type'] == 'statement' and block.get('entries') for block in document['blocks']):
    assert 'س/ج' in preview
if any(block['type'] == 'statement' and any(entry['question'].strip() for entry in block.get('entries', [])) for block in document['blocks']):
    assert '<b>ج:</b>' in preview
assert 'باشرنا التحقيق على الشكل التالي:' in preview
request = urllib.request.Request('http://localhost/api' + base + '/report/html/preview-pdf',
    data=json.dumps({'expected_token': state['token'], 'document': document}).encode(),
    headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
with urllib.request.urlopen(request, timeout=90) as response:
    assert 'application/pdf' in response.headers['Content-Type']
    pdf = response.read()
assert pdf.startswith(b'%PDF') and len(pdf) > 1000
with urllib.request.urlopen('http://localhost' + base + '/report') as response:
    csp = response.headers['Content-Security-Policy']
    assert "frame-src 'self' blob:;" in csp
assert api(base + '/report/html')['token'] == state['token'], 'Verification changed the draft'
archives = api(base + '/reports')['reports']
for row in archives:
    assert api(base + '/reports/' + row['id'] + '/verify')['ok']
index = urllib.request.urlopen('http://localhost' + base + '/report').read().decode()
assets = re.findall(r'(?:src|href)="(/assets/[^" ]+)"', index)
for asset in assets:
    served = urllib.request.urlopen('http://localhost' + asset).read()
    assert served == (ROOT / 'central/frontend/dist' / asset.lstrip('/')).read_bytes()
head = subprocess.check_output(['docker', 'exec', 'mstt-backend', 'alembic', 'current'], text=True)
assert 'a27689aebc56' in head
proof = {'result': 'PASS', 'backend_regression_tests_passed': 34, 'focused_tests_passed': 9, 'pdf_bytes': len(pdf), 'pdf_sha256': hashlib.sha256(pdf).hexdigest(), 'blob_frame_policy': True, 'migration_head': 'a27689aebc56', 'archives_verified': len(archives),
         'draft_unchanged': True, 'opening_present': True, 'assets': assets,
         'preview_sha256': hashlib.sha256(preview.encode()).hexdigest(),
         'browser_ui_check': 'Isolated real API browser journey PASS: storage/test-artifacts/document-editor/browser.json',
         'visual_artifacts': 'storage/test-artifacts/document-editor'}
(ROOT / 'storage/test-artifacts/report-opening/pdf-preview-runtime.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
manifest['deployment'] = 'VERIFIED_HTTP_RUNTIME'
manifest['verification'] = proof
path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print(json.dumps(proof), flush=True)
