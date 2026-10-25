"""Read-only smoke check of the deployed report editor and its real API dependencies.

Uses a two-minute server-signed session for the existing active bootstrap account.
Requires local Docker execution access; does not print tokens or report content.
Does not create, edit, or delete investigation/report records.
"""
import json
from pathlib import Path
import subprocess
import sys

from playwright.sync_api import expect, sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost").rstrip("/")
SESSION = sys.argv[2] if len(sys.argv) > 2 else "04176210-31ec-46e5-9637-c1aff1747d1b"
ROOT = Path(__file__).resolve().parents[1]

token = subprocess.check_output([
    "docker", "compose", "exec", "-T", "backend", "python", "-c",
    "import os,time; from sqlalchemy import select; from app.db.session import SessionLocal; "
    "from app.models import User; from app.core.security import create_access_token; "
    "from app.config import get_settings; db=SessionLocal(); "
    "user=db.scalar(select(User).where(User.username==os.environ.get('CENTRAL_BOOTSTRAP_ADMIN_USERNAME','admin'))); "
    "assert user is not None and user.is_active, 'Active local smoke-check account unavailable'; "
    "print(create_access_token(user.id,user.username,{'auth_mode':get_settings().auth_mode,'exp':int(time.time())+120})[0]); db.close()",
], cwd=ROOT, text=True).strip()

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    headers = {"Authorization": f"Bearer {token}"}
    dependencies = [
        f"/investigations/{SESSION}/report/html",
        "/report-forms/html-statement",
        f"/investigations/{SESSION}/report/html/people",
        "/report-forms/note-templates",
    ]
    for path in dependencies:
        response = context.request.get(f"{BASE}/api{path}", headers=headers)
        assert response.status == 200, f"Report dependency {path} returned {response.status}"
        payload = response.json()
        if path.endswith("/report/html"):
            assert payload["document"]["session_id"] == SESSION
        elif path.endswith("/people"):
            assert payload["session_id"] == SESSION
            assert isinstance(payload["options"], list)
        elif path.endswith("/note-templates"):
            assert isinstance(payload, list)
        print(f"PASS: live report dependency {path} -> 200", flush=True)

    context.add_init_script("sessionStorage.setItem('mstt.access_token', " + json.dumps(token) + ");")
    page = context.new_page()
    errors = []
    failed_requests = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("response", lambda response: failed_requests.append(f"{response.status} {response.url.split('?')[0]}")
            if response.status >= 400 and response.url.startswith(BASE + "/api/") else None)
    page.goto(f"{BASE}/investigations/{SESSION}/report", wait_until="networkidle")
    editor = page.get_by_test_id("html-report-editor")
    expect(editor).to_be_visible()
    expect(editor.locator(".html-report-workspace")).to_be_visible()
    expect(editor.locator(".alert-danger")).to_have_count(0)
    expect(editor.get_by_role("button", name="+ إضافة إفادة", exact=True)).to_be_visible()
    expect(editor.get_by_role("button", name="+ إضافة ملاحظة", exact=True)).to_be_visible()
    assert not errors, errors
    assert not failed_requests, failed_requests
    print("PASS: deployed report editor loads with real APIs; no API or browser errors", flush=True)
    browser.close()
