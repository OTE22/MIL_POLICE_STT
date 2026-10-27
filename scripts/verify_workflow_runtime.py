"""Verify release image IDs, live migration head, localhost assets and agent compatibility."""
import datetime
import hashlib
import json
from pathlib import Path
import re
import ssl
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
manifest_path = Path(sys.argv[1]).resolve()
assert manifest_path.is_relative_to(ROOT / 'storage/backups')
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
result = {'result': 'PASS', 'images': {}, 'assets': {}}
for service, container in [('backend', 'mstt-backend'), ('frontend', 'mstt-frontend'), ('agent', 'mstt-agent')]:
    info = json.loads(subprocess.check_output(['docker', 'inspect', container], text=True))[0]
    assert info['Image'] == manifest['images'][service]['release_id']
    assert info['State']['Health']['Status'] == 'healthy'
    result['images'][service] = info['Image']
head = subprocess.check_output(['docker', 'exec', 'mstt-backend', 'python', '-c',
    "import os,psycopg; c=psycopg.connect(os.environ['CENTRAL_DATABASE_URL'].replace('postgresql+psycopg://','postgresql://')); print(c.execute('SELECT version_num FROM alembic_version').fetchone()[0])"], text=True).strip()
assert head == 'f165789dab45'
result['migration_head'] = head
for base in ('http://localhost', 'https://localhost'):
    with urllib.request.urlopen(base, context=ssl._create_unverified_context(), timeout=20) as response:
        actual = response.read()
    assert actual == (ROOT / 'central/frontend/dist/index.html').read_bytes()
    result[base] = 'PASS'
index = (ROOT / 'central/frontend/dist/index.html').read_text(encoding='utf-8')
for asset in re.findall(r'(?:src|href)="(/assets/[^\"]+)"', index):
    with urllib.request.urlopen('http://localhost' + asset, timeout=20) as response:
        actual = response.read()
    expected = ROOT / 'central/frontend/dist' / asset.lstrip('/')
    assert actual == expected.read_bytes()
    result['assets'][asset] = hashlib.sha256(actual).hexdigest()
with urllib.request.urlopen('http://127.0.0.1:17117/capabilities', timeout=20) as response:
    capabilities = json.load(response)
assert capabilities['report_dictation'] is True
result['agent_report_dictation'] = True
browser = json.loads((ROOT / 'storage/test-artifacts/live-workflow/verification.json').read_text())
assert browser['result'] == 'PASS' and not browser['mutations_attempted']
out = ROOT / 'storage/test-artifacts/live-workflow/runtime.json'
out.write_text(json.dumps(result, indent=2), encoding='utf-8')
manifest['deployment'] = {'state': 'VERIFIED', 'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                          'browser_verification': 'PASS', 'runtime_verification': 'PASS'}
manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print('Runtime verification PASS: release images, migration head, HTTP/HTTPS assets, agent dictation compatibility', flush=True)
