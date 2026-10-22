"""Create fictional recognition UI samples only in the isolated test database."""
import os
import sys
from pathlib import Path

if not os.environ.get("CENTRAL_DATABASE_URL", "").endswith("_test"):
    raise SystemExit("Refusing to seed a non-test database")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app
from tests.conftest import ADMIN
from tests.test_voice_matching import EMB_A, _enroll, _speakers, _submit, _voice

with TestClient(app) as client:
    login = client.post("/api/auth/login", json=ADMIN)
    login.raise_for_status()
    token = login.json()["access_token"]
    source = _submit(client, token, voice=_voice(SPEAKER_00=EMB_A))
    speaker = _speakers(client, token, source["id"])["SPEAKER_00"]
    response = _enroll(client, token, source["id"], speaker["id"], "MIL-ARMY-7891", "Voice UI sample")
    response.raise_for_status()
    target = _submit(client, token, voice=_voice(SPEAKER_00=EMB_A))
    print("VOICE_UI_SESSION=" + target["id"])
