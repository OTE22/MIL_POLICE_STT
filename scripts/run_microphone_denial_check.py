import json
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
history = json.loads((root / 'storage/test-artifacts/complete-workflow/source-ack-test-stop/journey.json').read_text(encoding='utf-8'))
session = history[0]['session_id']
mint = '''
import uuid
from datetime import datetime, timezone
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import User, InvestigationSession
with SessionLocal() as db:
    session = db.get(InvestigationSession, uuid.UUID("SESSION_ID"))
    user = db.get(User, session.created_by)
    print(create_access_token(user.id, user.username, {'exp': int(datetime.now(timezone.utc).timestamp()) + 120})[0])
'''.replace('SESSION_ID', session)
token = subprocess.check_output(['docker', 'exec', '-i', 'military-stt-central-workflow-ui-backend-1', 'python', '-'], input=mint, text=True, cwd=root).strip()
environment = dict(os.environ, WORKFLOW_VERIFICATION_TOKEN=token, WORKFLOW_TEST_SESSION=session)
subprocess.run(['docker', 'run', '--rm', '--network', 'military-stt-central_internal', '--env', 'WORKFLOW_VERIFICATION_TOKEN', '--env', 'WORKFLOW_TEST_SESSION',
    '-v', str(root / 'scripts') + ':/task:ro', '-v', str(root / 'storage/test-artifacts') + ':/artifacts', '--entrypoint', 'python',
    'military-stt/workflow-backend-test:20261026', '/task/check_dictation_microphone_denial.py'], cwd=root, env=environment, check=True)
