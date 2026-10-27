"""Keep the authorized temporary verification token in memory, never in artifacts or logs."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
mint = '''
from datetime import datetime, timezone
from sqlalchemy import select
from app.config import get_settings
from app.core.security import create_access_token
from app.db.session import SessionLocal
from app.models import User
settings = get_settings()
with SessionLocal() as db:
    user = db.scalar(select(User).where(User.username == settings.bootstrap_admin_username, User.is_active.is_(True)))
    assert user and 'investigations.read_all' in user.permission_codes
    token, _ = create_access_token(user.id, user.username, {'exp': int(datetime.now(timezone.utc).timestamp()) + 120, 'auth_mode': settings.auth_mode})
    print(token)
'''
token = subprocess.check_output(['docker', 'exec', '-i', 'mstt-backend', 'python', '-'], input=mint, text=True, cwd=ROOT).strip()
environment = dict(os.environ, WORKFLOW_VERIFICATION_TOKEN=token)
subprocess.run(['docker', 'run', '--rm', '--network', 'military-stt-central_internal',
    '--add-host', 'host.docker.internal:host-gateway', '--env', 'WORKFLOW_VERIFICATION_TOKEN',
    '-v', str(ROOT / 'scripts') + ':/task:ro', '-v', str(ROOT / 'storage/test-artifacts') + ':/artifacts',
    '--entrypoint', 'python', 'military-stt/workflow-backend-test:20261026', '/task/live_workflow_browser.py'],
    cwd=ROOT, env=environment, check=True)
