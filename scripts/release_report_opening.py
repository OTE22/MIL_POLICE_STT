"""Build/rehearse or deploy the opening release, retaining backups and rollback images."""
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
def run(args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()

if sys.argv[1] == 'prepare':
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out = ROOT / 'storage/backups' / ('report-opening-' + stamp)
    out.mkdir(parents=True)
    manifest = {'created_at': stamp, 'images': {}}
    for service in ('backend', 'frontend'):
        previous = run(['docker', 'inspect', '-f', '{{.Image}}', 'mstt-' + service])
        repository = 'military-stt/central-' + service
        rollback, release = repository + ':rollback-' + stamp, repository + ':opening-' + stamp
        run(['docker', 'tag', previous, rollback])
        folder = 'central/' + service
        with (out / (service + '-build.log')).open('w', encoding='utf-8') as log:
            subprocess.run(['docker', 'build', '--pull=false', '-f', folder + '/Dockerfile.release', '--build-arg',
                            'BASE_IMAGE=' + rollback, '-t', release, folder], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        manifest['images'][service] = {'previous_id': previous, 'rollback': rollback, 'release': release,
                                      'release_id': run(['docker', 'image', 'inspect', '-f', '{{.Id}}', release])}
    path = out / 'release.json'
    path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    subprocess.run([sys.executable, 'scripts/rehearse_workflow_release.py', str(path)], cwd=ROOT, check=True)
    print(str(path), flush=True)
elif sys.argv[1] == 'deploy':
    path = Path(sys.argv[2]).resolve()
    assert path.is_relative_to(ROOT / 'storage/backups')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    assert manifest['migration_rehearsal']['result'] == 'PASS'
    out = path.parent
    for service, info in manifest['images'].items():
        assert run(['docker', 'inspect', '-f', '{{.Image}}', 'mstt-' + service]) == info['previous_id']
    run(['docker', 'compose', 'stop', 'backend'])
    try:
        dump = '/tmp/opening-' + manifest['created_at'] + '.dump'
        run(['docker', 'exec', 'mstt-postgres', 'sh', '-c', 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$1"', 'sh', dump])
        run(['docker', 'cp', 'mstt-postgres:' + dump, str(out / 'database-final.dump')])
        with tarfile.open(out / 'storage.tar.gz', 'w:gz') as archive:
            for item in (ROOT / 'storage').iterdir():
                if item.name not in ('backups', 'test-artifacts', 'workflow-e2e', 'test-tools', 'model-evaluation'):
                    archive.add(item, arcname=item.name)
        manifest['backups'] = {name: hashlib.sha256((out / name).read_bytes()).hexdigest()
                               for name in ('database-final.dump', 'storage.tar.gz')}
        path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    except Exception:
        run(['docker', 'compose', 'start', 'backend'])
        raise
    for service, info in manifest['images'].items():
        run(['docker', 'tag', info['release'], 'military-stt/central-' + service + ':1.0.0'])
    run(['docker', 'compose', 'up', '-d', '--no-build', '--no-deps', 'backend', 'frontend'])
    run(['docker', 'exec', 'mstt-nginx', 'nginx', '-s', 'reload'])
    manifest['deployment'] = 'APPLIED_PENDING_RUNTIME_VERIFICATION'
    path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Release applied; runtime verification remains required', flush=True)
else:
    raise SystemExit('Use prepare or deploy <manifest>')
