"""Real API/UI acceptance against the explicitly isolated workflow-ui services only.

Run inside the final backend image, after pytest releases the _test database.
Normal login is used; no administrator sessions are minted or live records accessed.
"""
import hashlib
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import expect, sync_playwright

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://workflow-ui-frontend").rstrip("/")
address = urlparse(BASE)
assert address.hostname == "workflow-ui-frontend" or (
    address.hostname in {"localhost", "127.0.0.1"} and address.port == 18080
), "Refusing to run synthetic acceptance against a live destination"
OUT = Path("/artifacts/workflow-browser")
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    request = context.request
    def call(method, path, body=None, token=None, expected=200):
        response = request.fetch(BASE + "/api" + path, method=method,
            data=body, headers={"Authorization": f"Bearer {token}"} if token else {})
        assert response.status == expected, f"{method} {path}: {response.status} {response.text()[:200]}"
        return response.json()
    administrator = call("POST", "/auth/login", {"username": "admin", "password": "AdminBootstrap!1"})["access_token"]
    username = "workflow_ui_" + uuid.uuid4().hex[:10]
    call("POST", "/users", {"username": username, "password": "WorkflowTest!1234", "roles": ["INVESTIGATOR"],
         "must_change_password": False, "profile": {"full_name": "محقق اختبار الواجهة", "military_id": username,
         "security_branch": "ARMY"}}, administrator, 201)
    token = call("POST", "/auth/login", {"username": username, "password": "WorkflowTest!1234"})["access_token"]
    session = call("POST", "/investigations", {"title": "اختبار تكامل المحضر / Workflow acceptance",
        "location": "غرفة الاختبار", "session_date": "2026-10-25", "start_time": "10:00"}, token, 201)
    base = f"/investigations/{session['id']}"
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE + "/login")
    page.locator("#username").fill(username)
    page.locator("#password").fill("WorkflowTest!1234")
    page.locator('button[type="submit"]').click()
    expect(page).not_to_have_url(re.compile(r"/login$"))
    page.goto(BASE + base + "/report")
    expect(page.get_by_test_id("html-report-editor")).to_be_visible()
    page.get_by_role("button", name="+ إضافة ملاحظة", exact=True).click()
    catalogue = call("GET", "/report-forms/html-statement", token=token)
    label = next(field["label"] for field in catalogue["note"]["fields"] if field["key"] == "note_text")
    page.get_by_label(label, exact=True).fill("ملاحظة اختبار واضحة. Evidence entered once and retained through issuance.")
    # SPA navigation must protect unsaved wording.
    page.once("dialog", lambda dialog: dialog.dismiss())
    page.get_by_role("link", name=session["title"], exact=True).click()
    expect(page).to_have_url(BASE + base + "/report")
    page.get_by_role("button", name="حفظ المحضر", exact=True).click()
    expect(page.get_by_role("button", name="حفظ المحضر", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="تنزيل HTML", exact=True)).to_be_enabled()
    page.get_by_role("checkbox", name="راجعت نص المحضر وإفاداته وأسماء الأشخاص ونسبة الأقوال إلى أصحابها").check()
    page.get_by_role("button", name="حفظ تأكيد المراجعة", exact=True).click()
    issue = page.get_by_role("button", name="إصدار وحفظ HTML وPDF", exact=True)
    expect(issue).to_be_enabled()
    issue.click()
    reopen = page.get_by_role("button", name="فتح مسودة تصحيح مع الاحتفاظ بالإصدارات الصادرة", exact=True)
    expect(reopen).to_be_visible(timeout=60000)
    page.get_by_role("button", name="التحقق من سلامة الملفات", exact=True).click()
    expect(page.get_by_text("الملفات سليمة وتطابق البصمات المحفوظة", exact=True)).to_be_visible()
    with page.expect_download() as downloaded:
        page.get_by_role("button", name="PDF", exact=True).click()
    pdf_path = OUT / "issued.pdf"
    downloaded.value.save_as(pdf_path)
    original_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    assert pdf_path.read_bytes().startswith(b"%PDF")
    for width, name in [(1440, "desktop"), (390, "mobile")]:
        page.set_viewport_size({"width": width, "height": 1000})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), name
        page.screenshot(path=str(OUT / f"report-{name}.png"), full_page=True)
    for target in ["IN_PROGRESS", "AWAITING_REVIEW", "REVIEWED", "CLOSED"]:
        current = call("GET", base, token=token)
        call("POST", base + "/workflow", {"expected_revision": current["revision"], "state": target,
             "reason": "Explicit synthetic acceptance action"}, token)
    page.get_by_label("سبب التصحيح وإعادة فتح المسودة", exact=True).fill("تصحيح موثّق ضمن اختبار التكامل")
    reopen.click()
    expect(page.get_by_role("button", name="+ إضافة ملاحظة", exact=True)).to_be_enabled()
    archive = call("GET", base + "/reports", token=token)
    issued_id = archive["reports"][0]["id"]
    response = request.get(BASE + "/api" + base + f"/reports/{issued_id}/file?format=pdf",
                           headers={"Authorization": f"Bearer {token}"})
    assert response.status == 200 and hashlib.sha256(response.body()).hexdigest() == original_hash
    assert call("GET", base + f"/reports/{issued_id}/verify", token=token)["ok"]
    assert not errors, errors
    browser.close()
print("PASS: normal login, real HTML editing, unsaved navigation protection, review, PDF issuance/download/verification, responsive layout, closure and correction; original issued PDF unchanged.")
