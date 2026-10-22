"""Explicit fictional UI fixture; refuses to run against a non-test database."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if not os.environ.get("CENTRAL_DATABASE_URL", "").endswith("_test"):
    raise SystemExit("Refusing to seed a non-test database")

from fastapi.testclient import TestClient
from conftest import ADMIN, auth
from app.main import app
from test_report_finalize import _ready_session
from test_report_m53 import _draft, _values, _save

with TestClient(app) as client:
    login = client.post("/api/auth/login", json=ADMIN)
    login.raise_for_status()
    token = login.json()["access_token"]
    session = _ready_session(client, token)
    draft = _draft(client, token, session["id"])
    values = _values()
    values["statement_name"] = draft["official_form"]["suggestions"]["statement_name"]
    result = _save(client, token, session["id"], draft, values=values)
    result.raise_for_status()
    print("UI_SESSION=" + session["id"])
