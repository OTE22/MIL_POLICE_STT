"""Full platform presentation audit using synthetic APIs only.

Build the frontend first. Optional URL verifies deployed assets. No real records or
credentials are used. Screenshots and axe/typography results go to test-artifacts.
"""
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "storage/test-artifacts/platform"
SHOTS.mkdir(parents=True, exist_ok=True)
SESSION = "04176210-31ec-46e5-9637-c1aff1747d1b"
NOW = "2026-10-25T09:00:00Z"
PERMISSIONS = ["users.manage", "workstations.read", "audit.read", "system.configure", "investigators.read", "reports.templates.manage", "reports.generate", "reports.read", "reports.finalize", "investigations.create", "investigations.update", "investigations.archive", "recordings.create", "transcripts.edit", "speakers.assign", "voice.identify", "voice.enroll", "voice.manage"]
profile = dict(id="profile-1", user_id="user-1", full_name="أحمد منصور", rank="نقيب", military_id="MP-012450", security_branch="ARMY", unit="قسم التحقيقات", department="الشرطة العسكرية", job_title="محقق", phone="+961 1 234 567", email="investigator@example.test", location="بيروت", created_at=NOW, updated_at=NOW)
user = dict(id="user-1", username="investigator", is_active=True, must_change_password=False, roles=["ADMIN"], permissions=PERMISSIONS, profile=profile, last_login_at=NOW, created_at=NOW)
recording = dict(id="recording-1", original_filename="تسجيل الجلسة الأولى.wav", mime_type="audio/wav", size_bytes=480000, duration_seconds=30, sha256="ab" * 32, source="FILE_UPLOAD", upload_status="UPLOADED", created_at=NOW)
session = dict(id=SESSION, title="مراجعة الإفادات والتحقق من تسلسل الوقائع", session_number="INV-2026-00128", location="غرفة التحقيق المركزية", session_date="2026-10-25", start_time="09:00:00", end_time="09:30:00", duration_seconds=1800, description="تدوين إفادات المشاركين ومراجعة الأدلة الصوتية قبل إعداد المحضر.", status="COMPLETED", revision=0, workflow_state="IN_PROGRESS", processing_summary={"COMPLETED": 1}, notes="تُراجع الإفادات مع التسجيل الأصلي.", created_at=NOW, updated_at=NOW, created_by="user-1", created_by_name="أحمد منصور", has_transcript=True, expected_speaker_count=2, speaker_limit_warning=False, latest_job_status="COMPLETED", recordings=[recording], investigators=[dict(**profile, assignment_role="LEAD")], subjects=[])
speakers = [dict(id="speaker-1", session_id=SESSION, recording_id="recording-1", recording_name=recording["original_filename"], speaker_label="SPEAKER_01", identity_id="person-1", identity_name="علي حسن", display_name="علي حسن", speaker_role="SUBJECT", notes="", segment_count=1, total_seconds=24, updated_at=NOW, identification_status="CONFIRMED", suggested_name=None, suggested_score=None, suggested_model=None, has_voice_embedding=True)]
voice = dict(id="voice-1", identity_id="person-1", person_name="علي حسن", enrolled_person_name="علي حسن", notes="عينة صوتية مسجلة", model="Local voice identification", model_revision="1", provider="local", embedding_dim=192, sample_seconds=24, source_session_id=SESSION, source_speaker_label="SPEAKER_01", consent_recorded=True, is_active=True, enrolled_by="user-1", enrolled_by_name="أحمد منصور", created_at=NOW, updated_at=NOW)
block = dict(id="statement-1", type="statement", speaker_id="speaker-1", identity_id="person-1", participant_key=None, values={"statement_name": "علي حسن", "statement_signature_role": "صاحب الإفادة"}, identity_checked=True, attestation_confirmed=False, entries=[dict(id="entry-1", question="يرجى توضيح وقت الوصول.", answer="وصلت إلى المكان صباحاً برفقة أحد زملائي.", source_block_ids=[])])
document = dict(session_id=SESSION, revision="statement-html-1", subject=session["title"], investigator_id=profile["id"], blocks=[block])
catalogue = dict(revision="statement-html-1", title="إفادة", fields=[dict(key="statement_name", label="اسم صاحب الإفادة", group="البيانات الشخصية"), dict(key="statement_signature_role", label="صفة الموقّع", group="البيانات الشخصية")], clauses=dict(heading="إفادة {statement_name}", identity="استمعنا إلى {statement_name}", place_date="بيروت في ٢٥ تشرين الأول ٢٠٢٦"), note=dict(title="ملاحظة", fields=[dict(key="note_text", label="نص الملاحظة", group="الملاحظة", multiline=True)], clauses=dict(body="{note_text}")))
draft = dict(id="draft-1", session_id=SESSION, status="DRAFT", case_subject=session["title"], token="synthetic")
config = dict(fields=[dict(key="max_speakers", group="المعالجة والتحقيق", label="عدد المتحدثين الافتراضي", description="العدد المستخدم عند إعداد جلسة جديدة.", type="int", value=4, min=1, max=12, options=None), dict(key="model", group="المعالجة والتحقيق", label="نموذج المعالجة", description="النموذج المحلي المستخدم في المعالجة.", type="select", value="local", options=["local", "standard"], min=None, max=None), dict(key="audit_enabled", group="سجل التدقيق", label="تسجيل الإجراءات", description="تسجيل الإجراءات والتغييرات في سجل التدقيق.", type="bool", value=True, min=None, max=None, options=None)])


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if not Path(self.translate_path(self.path)).is_file(): self.path = "/index.html"
        super().do_GET()
    def log_message(self, *_): pass


def api(route):
    path = urlparse(route.request.url).path.removeprefix("/api")
    if path.endswith("/report/html/preview") and route.request.method == "POST":
        route.fulfill(content_type="application/json", body=json.dumps({"html": "<!doctype html><html lang='ar' dir='rtl'><body><p>Synthetic preview for presentation audit</p></body></html>"}))
        return
    assert route.request.method == "GET", f"Unexpected mutation: {route.request.method} {path}"
    body = []
    if path == "/auth/me": body = user
    elif path == "/investigations/dashboard": body = dict(total_sessions=48, sessions_today=4, processing=3, completed=32, recent=[{**session, "lead_investigator": "نقيب أحمد منصور"}])
    elif path == "/investigations": body = dict(items=[{**session, "lead_investigator": "نقيب أحمد منصور"}], total=1, page=1, page_size=20)
    elif path == f"/investigations/{SESSION}": body = session
    elif path == "/investigators": body = [profile]
    elif path == "/users": body = dict(items=[user], total=1, page=1, page_size=200)
    elif path == "/admin/config": body = config
    elif path == "/workstations": body = [dict(id="ws-1", device_name="MP-WORKSTATION-01", agent_id="agent-01", agent_version="1.0.0", stt_model="Arabic transcription", stt_model_revision="1", diarization_model="Speaker separation", diarization_model_revision="1", processing_device="cuda", gpu_name="RTX 4090", status="ONLINE", last_seen_at=NOW, registered_by_name="أحمد منصور")]
    elif path == "/voice-enrollments": body = [voice]
    elif path == "/voice-enrollments/candidates": body = []
    elif path == "/audit-logs" or path.endswith("/activity"): body = dict(items=[dict(id="event-1", action="auth.login", username="investigator", user_id="user-1", entity_type="user", entity_id="user-1", details={}, ip_address="127.0.0.1", created_at=NOW)], total=1, page=1, page_size=50)
    elif path.endswith("/transcript"): body = dict(id="transcript-1", session_id=SESSION, recording_id="recording-1", job_id="job-1", status="COMPLETED", language="ar", speakers=speakers, segments=[dict(id="seg-1", sequence=0, speaker_label="SPEAKER_01", start_seconds=0, end_seconds=24, original_text=block["entries"][0]["answer"], edited_text=None, confidence=.93, is_overlap=False, edited_by=None, edited_by_name=None, edited_at=None)], audio_available=False, warnings=[], created_at=NOW, completed_at=NOW)
    elif path.endswith("/report/html/people"): body = dict(session_id=SESSION, options=[dict(key="person:person-1", label="علي حسن", participant_key=None, identity_id="person-1", speaker_id="speaker-1")])
    elif path.endswith("/report/html"): body = dict(token="synthetic", document=document, status="DRAFT", source_token="synthetic", sources_changed=False, source_changes=[], reviewed=False, blocked_reasons=["report_review_required"])
    elif path.endswith("/report"): body = draft
    elif path.endswith("/reports"): body = dict(reports=[], can_finalize=False, blocked_reasons=[], missing_fields=[], unresolved_speaker_labels=[], active_template_version=None, active_template_is_development=False)
    elif path == "/report-forms/html-statement": body = catalogue
    elif path == "/report-forms/note-templates": body = []
    elif path.endswith("/people"): body = []
    route.fulfill(content_type="application/json", body=json.dumps(body))


server = None
if len(sys.argv) > 1: base = sys.argv[1].rstrip("/")
else:
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(ROOT / "central/frontend/dist")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

routes = [("dashboard", "/"), ("investigations", "/investigations"), ("new-investigation", "/investigations/new"), ("edit-investigation", f"/investigations/{SESSION}/edit"), ("details", f"/investigations/{SESSION}"), ("recording", f"/investigations/{SESSION}?tab=recording"), ("transcript", f"/investigations/{SESSION}?tab=transcript"), ("speakers", f"/investigations/{SESSION}?tab=speakers"), ("activity", f"/investigations/{SESSION}?tab=activity"), ("report", f"/investigations/{SESSION}/report"), ("users", "/users"), ("workstations", "/workstations"), ("voice", "/voice-enrollments"), ("audit", "/audit"), ("settings", "/settings"), ("password", "/change-password")]
results = []
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        # Inspector-only bypass allows axe injection; deployed CSP is never modified.
        context = browser.new_context(viewport=dict(width=1440, height=1050), reduced_motion="reduce", bypass_csp=True)
        context.add_init_script("sessionStorage.setItem('mstt.access_token', 'synthetic-test-only')")
        context.route("**/api/**", api)
        context.route("http://127.0.0.1:8765/**", lambda r: r.abort())
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def audit(name, screenshot=True):
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(100)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), f"Page overflow: {name}"
            text_issues = page.evaluate("""() => [...document.querySelectorAll('body *')].filter(e => {
              const s=getComputedStyle(e); return e.getClientRects().length && s.visibility!=='hidden' && [...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim()) && parseFloat(s.fontSize)<14;
            }).map(e=>({text:e.textContent.trim().slice(0,80),size:getComputedStyle(e).fontSize,cls:e.className}))""")
            axe_file = ROOT / "storage/test-artifacts/axe.min.js"
            violations = []
            if axe_file.exists():
                page.add_script_tag(path=str(axe_file))
                violations = page.evaluate("""async () => (await axe.run(document, {runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa']}})).violations.map(v=>({id:v.id,impact:v.impact,description:v.description,nodes:v.nodes.map(n=>({target:n.target,summary:n.failureSummary}))}))""")
            result = dict(screen=name, tiny_text=text_issues, violations=violations)
            results.append(result)
            if screenshot: page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True, animations="disabled")
            print(f"AUDIT {name}: {len(text_issues)} tiny text, {len(violations)} accessibility violations", flush=True)

        for name, url in routes:
            page.set_viewport_size(dict(width=1440, height=1050))
            page.goto(base + url)
            expect(page.locator("main")).to_be_visible()
            page.wait_for_timeout(350)
            audit(name + "-desktop")
            page.set_viewport_size(dict(width=390, height=844))
            audit(name + "-mobile")
            for width in (320, 768, 1024):
                page.set_viewport_size(dict(width=width, height=1050))
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth+1"), f"Overflow {name} at {width}"

        page.set_viewport_size(dict(width=390, height=844))
        page.goto(base + "/")
        toggle = page.get_by_role("button", name="فتح القائمة الرئيسية")
        toggle.click()
        expect(page.get_by_role("dialog")).to_be_visible()
        audit("navigation-mobile")
        page.keyboard.press("Shift+Tab")
        assert page.evaluate("!!document.activeElement.closest('.sidebar')")
        page.keyboard.press("Escape")
        expect(toggle).to_be_focused()
        page.goto(base + "/users")
        page.get_by_role("button", name="إضافة مستخدم").click()
        expect(page.get_by_role("dialog")).to_be_visible()
        audit("user-modal-mobile")
        page.keyboard.press("Shift+Tab")
        assert page.evaluate("!!document.activeElement.closest('[role=dialog]')")
        page.keyboard.press("Escape")
        page.set_viewport_size(dict(width=1440, height=1050))
        page.goto(base + f"/investigations/{SESSION}?tab=speakers")
        page.get_by_test_id("speaker-person-picker").click()
        audit("speaker-picker-desktop")
        page.set_viewport_size(dict(width=390, height=844))
        audit("speaker-picker-mobile")
        page.get_by_test_id("pick-add-new").click()
        expect(page.get_by_test_id("identify-new")).to_be_visible()
        audit("identify-new-mobile")
        page.get_by_test_id("identify-existing").click()
        audit("identify-existing-mobile")
        page.keyboard.press("Escape")
        page.get_by_role("button", name="تسجيل بصمة الصوت", exact=False).click()
        audit("enrollment-mobile")
        page.keyboard.press("Escape")

        page.set_viewport_size(dict(width=1440, height=1050))
        login_context = browser.new_context(viewport=dict(width=1440, height=1050), reduced_motion="reduce", bypass_csp=True)
        page = login_context.new_page()
        page.goto(base + "/login")
        audit("login-desktop")
        page.set_viewport_size(dict(width=320, height=844))
        audit("login-mobile")
        browser.close()
        assert not errors, errors
finally:
    (SHOTS / "audit.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    if server: server.shutdown()

issues = [r for r in results if r["tiny_text"] or r["violations"]]
assert not issues, f"See {SHOTS / 'audit.json'} for {len(issues)} screens with findings"
print(f"PASS: {len(results)} screen/state audits; five viewport widths; navigation and dialog focus; no runtime errors.")
