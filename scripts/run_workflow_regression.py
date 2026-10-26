"""Record actual process exit status and complete output for isolated regression checks."""
import json
import subprocess
import time
from pathlib import Path

root = Path(__file__).resolve().parents[1]
output = root / 'storage/test-artifacts/intake-final-regression.log'
command = ['docker', 'compose', '-f', 'docker-compose.yml', '-f', 'scripts/workflow-test.compose.yml',
           'run', '--rm', '--no-deps', '-v', str(root / 'central/backend') + ':/app:ro',
           '--entrypoint', 'python', 'backend', '-m', 'pytest', '-o', 'addopts=', '-q',
           '--tb=short', '--show-capture=no', '-p', 'no:cacheprovider']
started = time.monotonic()
with output.open('w', encoding='utf-8') as log:
    result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
summary = {'exit_code': result.returncode, 'elapsed_seconds': round(time.monotonic() - started, 2), 'log': str(output)}
(output.parent / 'intake-final-regression.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps(summary), flush=True)
raise SystemExit(result.returncode)
