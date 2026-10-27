"""Deploy only a tested release, with consistent database/evidence backups and rollback images."""
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
path = Path(sys.argv[1]).resolve()
assert path.is_relative_to(ROOT / 'storage/backups')
manifest = json.loads(path.read_text(encoding='utf-8'))
out = path.parent
assert manifest['migration_rehearsal']['result'] == 'PASS'
checks = ROOT / 'storage/test-artifacts'
assert json.loads((checks / 'intake-final-regression.json').read_text())['exit_code'] == 0
assert json.loads((checks / 'agent-final-regression.json').read_text())['exit_code'] == 0
assert json.loads((checks / 'intake-targeted-regression.json').read_text())['exit_code'] == 0
journey = json.loads((checks / 'complete-workflow/journey.json').read_text(encoding='utf-8'))
assert len(journey) >= 10 and all(row['status'] == 'PASS' for row in journey)
assert 'successor' in journey[-1]['step']
for name, expected in manifest['source_hashes'].items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, 'Unpackaged change: ' + name


def run(args, cwd=ROOT):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()


def health(container, expected):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        info = json.loads(run(['docker', 'inspect', container]))[0]
        assert info['Image'] == expected, 'Unexpected runtime image: ' + container
        state = info['State']
        if state.get('Health', {}).get('Status') == 'healthy':
            return
        if state['Status'] in ('exited', 'dead'):
            raise RuntimeError(container + ' stopped unexpectedly')
        time.sleep(2)
    raise TimeoutError(container + ' did not become healthy')


with urllib.request.urlopen('http://127.0.0.1:17117/jobs', timeout=10) as response:
    jobs = json.load(response)
assert all(row['state'] in ('COMPLETED', 'FAILED', 'CANCELLED') for row in jobs), 'Live agent has unfinished work'
for service, container in [('backend', 'mstt-backend'), ('frontend', 'mstt-frontend'), ('agent', 'mstt-agent')]:
    assert run(['docker', 'inspect', '-f', '{{.Image}}', container]) == manifest['images'][service]['previous_id'], 'Runtime changed since release preparation'

run(['docker', 'compose', 'stop', 'backend'])
run(['docker', 'compose', 'stop', 'agent'], cwd=ROOT / 'desktop-agent')
try:
    dump = '/tmp/workflow-final-' + manifest['created_at'] + '.dump'
    run(['docker', 'exec', 'mstt-postgres', 'sh', '-c', 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$1"', 'sh', dump])
    run(['docker', 'cp', 'mstt-postgres:' + dump, str(out / 'database-final.dump')])
    run(['docker', 'exec', 'mstt-postgres', 'sh', '-c', 'pg_restore --list "$1" >/dev/null', 'sh', dump])
    with tarfile.open(out / 'storage.tar.gz', 'w:gz') as archive:
        for item in (ROOT / 'storage').iterdir():
            if item.name not in ('backups', 'test-artifacts', 'workflow-e2e', 'test-tools', 'model-evaluation'):
                archive.add(item, arcname=item.name)
    with tarfile.open(out / 'agent-data.tar.gz', 'w:gz') as archive:
        archive.add(ROOT / 'desktop-agent/data', arcname='data')
    for name in ('storage.tar.gz', 'agent-data.tar.gz'):
        with tarfile.open(out / name) as archive:
            assert archive.getmembers(), 'Empty backup: ' + name
    manifest['final_backups'] = {name: {'bytes': (out / name).stat().st_size,
        'sha256': hashlib.sha256((out / name).read_bytes()).hexdigest()}
        for name in ('database-final.dump', 'storage.tar.gz', 'agent-data.tar.gz')}
    manifest['backup_scope'] = 'Live database, recording/report/document storage, logs and complete agent data; excludes disposable test/model-evaluation folders and other backups.'
    path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
except Exception:
    # No new-format writes have occurred; restart the unchanged application after a backup failure.
    run(['docker', 'compose', 'start', 'backend'])
    run(['docker', 'compose', 'start', 'agent'], cwd=ROOT / 'desktop-agent')
    raise
print('Database and evidence backups verified', flush=True)
for service, tag in [('backend', 'military-stt/central-backend:1.0.0'),
                     ('frontend', 'military-stt/central-frontend:1.0.0'),
                     ('agent', 'military-stt/desktop-agent:1.0.0-cpu')]:
    run(['docker', 'image', 'tag', manifest['images'][service]['release'], tag])
run(['docker', 'compose', 'up', '-d', '--no-build', '--no-deps', 'backend', 'frontend'])
health('mstt-backend', manifest['images']['backend']['release_id'])
health('mstt-frontend', manifest['images']['frontend']['release_id'])
run(['docker', 'exec', 'mstt-nginx', 'nginx', '-s', 'reload'])
run(['docker', 'compose', 'up', '-d', '--no-build', '--no-deps', 'agent'], cwd=ROOT / 'desktop-agent')
health('mstt-agent', manifest['images']['agent']['release_id'])
manifest['deployment'] = {'state': 'HEALTHY_PENDING_BROWSER_VERIFICATION',
    'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()}
path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print('Backend, frontend and agent are healthy on the release images', flush=True)
