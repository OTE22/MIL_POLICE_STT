"""Back up the live database and prove additive migrations on a restored copy."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
manifest_path = Path(sys.argv[1]).resolve()
assert manifest_path.is_relative_to(ROOT / 'storage/backups')
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
out = manifest_path.parent
database = 'workflow_rehearsal_' + manifest['created_at'].lower() + '_test'
dump = '/tmp/' + database + '.dump'


def run(args, **kwargs):
    return subprocess.check_output(args, cwd=ROOT, text=True, **kwargs)


run(['docker', 'exec', 'mstt-postgres', 'sh', '-c', 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$1"', 'sh', dump])
run(['docker', 'cp', 'mstt-postgres:' + dump, str(out / 'database.dump')])
run(['docker', 'exec', 'mstt-postgres', 'sh', '-c', 'createdb -U "$POSTGRES_USER" "$1"', 'sh', database])
run(['docker', 'exec', 'mstt-postgres', 'sh', '-c', 'pg_restore -U "$POSTGRES_USER" --exit-on-error --no-owner --no-acl -d "$1" "$2"', 'sh', database, dump])
info = json.loads(run(['docker', 'inspect', 'mstt-backend']))[0]
environment = dict(os.environ)
runtime = dict(item.split('=', 1) for item in info['Config']['Env'])
runtime['CENTRAL_DATABASE_URL'] = runtime['CENTRAL_DATABASE_URL'].rsplit('/', 1)[0] + '/' + database
environment.update(runtime)
command = ['docker', 'run', '--rm', '--network', 'military-stt-central_internal',
           '--volumes-from', 'mstt-backend:ro', '-v', str(ROOT / 'scripts') + ':/task:ro']
for key in runtime:
    if key.startswith('CENTRAL_'):
        command += ['--env', key]
command += ['--entrypoint', 'python', manifest['images']['backend']['release'], '/task/verify_workflow_migration.py']
with (out / 'migration-rehearsal.log').open('w', encoding='utf-8') as log:
    subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
manifest['migration_rehearsal'] = {'result': 'PASS', 'database': database,
    'database_backup_sha256': hashlib.sha256((out / 'database.dump').read_bytes()).hexdigest()}
manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print('Migration rehearsal PASS; original columns and row counts unchanged', flush=True)
