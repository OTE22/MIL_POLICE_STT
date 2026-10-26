"""Build application-only images from the exact running runtimes; do not deploy."""
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
STAMP = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
OUT = ROOT / 'storage' / 'backups' / ('workflow-release-' + STAMP)
OUT.mkdir(parents=True)
manifest = {'created_at': STAMP, 'backup_directory': str(OUT), 'images': {}}
if len(sys.argv) > 1:
    existing = Path(sys.argv[1]).resolve()
    assert existing.is_relative_to(ROOT / 'storage/backups')
    manifest = json.loads(existing.read_text(encoding='utf-8'))
    OUT = existing.parent
    STAMP = manifest['created_at']


def run(args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


for service, container, folder, repository, suffix in [
    ('backend', 'mstt-backend', 'central/backend', 'military-stt/central-backend', ''),
    ('frontend', 'mstt-frontend', 'central/frontend', 'military-stt/central-frontend', ''),
    ('agent', 'mstt-agent', 'desktop-agent', 'military-stt/desktop-agent', '-cpu'),
]:
    image_id = run(['docker', 'inspect', '-f', '{{.Image}}', container])
    rollback = repository + ':rollback-' + STAMP + suffix
    release = repository + ':workflow-' + STAMP + suffix
    run(['docker', 'image', 'tag', image_id, rollback])
    with (OUT / (service + '-build.log')).open('w', encoding='utf-8') as log:
        subprocess.run(['docker', 'build', '--pull=false', '-f', folder + '/Dockerfile.release',
                        '--build-arg', 'BASE_IMAGE=' + rollback, '-t', release, folder],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    manifest['images'][service] = {'previous_id': image_id, 'rollback': rollback, 'release': release,
                                  'release_id': run(['docker', 'image', 'inspect', '-f', '{{.Id}}', release])}
    print(service + ' image built', flush=True)
    (OUT / 'release.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
sources = {}
for folder in ('central/backend/app', 'central/backend/alembic', 'desktop-agent/app', 'central/frontend/dist'):
    for path in sorted((ROOT / folder).rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            sources[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
manifest['source_hashes'] = sources
(OUT / 'release.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print(str(OUT / 'release.json'), flush=True)
