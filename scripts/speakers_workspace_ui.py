"""Browser regression checks for the speaker review workspace.

Uses synthetic API responses in the browser; never changes investigation records.
Run after building central/frontend. Optional first argument tests deployed assets.
"""
import copy
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "storage/test-artifacts/speaker-workspace"
SHOTS.mkdir(parents=True, exist_ok=True)
SESSION = "04176210-31ec-46e5-9637-c1aff1747d1b"
NOW = "2026-10-25T09:00:00Z"
PERMISSIONS = ["speakers.assign", "voice.identify", "voice.enroll", "investigations.update", "investigations.create", "reports.generate", "investigations.archive", "recordings.create"]


class PreviewHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if not Path(self.translate_path(self.path)).is_file():
            self.path = "/index.html"
        super().do_GET()

    def log_message(self, *_):
        pass


def speaker(number, identity=None, name=None, embedding=True):
    return dict(id=f"sample-{number}", session_id=SESSION, recording_id="recording-1",
                recording_name="تسجيل الجلسة الأولى.wav", speaker_label=f"SPEAKER_{number:02}",
                display_name=name, identity_name=name if identity else None, identity_id=identity,
                speaker_role="INVESTIGATOR" if identity else "UNKNOWN", notes=None,
                segment_count=12 + number, total_seconds=85 + number * 20, updated_at=NOW,
                identification_status="UNIDENTIFIED", suggested_name=None, suggested_score=None,
                suggested_model=None, has_voice_embedding=embedding)


original = [speaker(1, embedding=False), speaker(2), speaker(3, "person-a", "علي حسن"),
            speaker(4, "person-a", "علي حسن"), speaker(5, "person-b", "علي حسن")]
original[1].update(identification_status="SUGGESTED", suggested_name="سامر خليل", suggested_score=.84)
session = dict(id=SESSION, session_number="INV-2026-00128", title="مراجعة إفادات الجلسة",
               description=None, location="غرفة التحقيق ٢", session_date="2026-10-25", start_time=None,
               end_time=None, status="COMPLETED", notes=None, expected_speaker_count=4,
               speaker_limit_warning=False, created_by="reviewer", created_by_name="أحمد منصور",
               created_at=NOW, updated_at=NOW, investigators=[], subjects=[], recordings=[],
               latest_job_status="COMPLETED", has_transcript=True, duration_seconds=650)
state = {"speakers": copy.deepcopy(original), "permissions": PERMISSIONS[:], "patches": [], "transcript_error": False, "fail_save": False}


def api(route):
    path = urlparse(route.request.url).path.removeprefix("/api")
    status = 200
    body = {}
    if path == "/auth/me":
        body = dict(id="reviewer", username="reviewer", is_active=True, must_change_password=False,
                    roles=["INVESTIGATOR"], permissions=state["permissions"], last_login_at=None,
                    profile={"full_name": "أحمد منصور"})
    elif path == f"/investigations/{SESSION}":
        body = {**session, "has_transcript": bool(state["speakers"]) or state["transcript_error"]}
    elif path.endswith("/transcript"):
        if state["transcript_error"]:
            status, body = 503, {"detail": "generic"}
        else:
            body = dict(id="transcript-1", session_id=SESSION, recording_id="recording-1", job_id="job-1",
                        status="COMPLETED", language="ar", speakers=state["speakers"], segments=[dict(
                            id="source-segment", sequence=0, speaker_label="SPEAKER_02", start_seconds=0,
                            end_seconds=4, original_text="هذه إفادة تجريبية للتحقق من اسم المتحدث.", edited_text=None,
                            is_overlap=False, confidence=.9, edited_by=None, edited_by_name=None, edited_at=None)],
                        audio_available=False, warnings=[], created_at=NOW, completed_at=NOW)
    elif "/speakers/" in path and route.request.method == "PATCH":
        if state["fail_save"]:
            status, body = 500, {"detail": "generic"}
        else:
            payload = route.request.post_data_json
            state["patches"].append(payload)
            body = next(s for s in state["speakers"] if s["id"] == path.split("/")[-1])
            body.update(payload)
    elif path.endswith("/identification"):
        body = next(s for s in state["speakers"] if s["id"] == path.split("/")[-2])
        body.update(identity_id="person-c", identity_name="سامر خليل", display_name="سامر خليل", identification_status="CONFIRMED")
    elif path.endswith("/people"):
        body = []
    elif path.endswith("/activity"):
        body = dict(items=[], total=0, page=1, page_size=100)
    elif path.endswith("/voice-rematch"):
        body = dict(suggested=0, scanned=1, no_sample=1, no_compatible_enrollment=0, below_threshold=0, ambiguous=0, skipped_decided=4)
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


server = None
if len(sys.argv) > 1:
    base = sys.argv[1].rstrip("/")
else:
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(PreviewHandler, directory=str(ROOT / "central/frontend/dist")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
url = f"{base}/investigations/{SESSION}?tab=speakers"

try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
        context.add_init_script("sessionStorage.setItem('mstt.access_token', 'synthetic-ui-test');")
        context.route("**/api/**", api)
        context.route("**/127.0.0.1:17117/**", lambda route: route.abort())
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def open_page():
            page.goto(url)
            expect(page.get_by_test_id("speaker-workspace")).to_be_visible()
            page.evaluate("document.fonts.ready")

        def queue(index):
            return page.get_by_test_id("speaker-person-group").nth(index)

        def check_no_overflow(width):
            page.set_viewport_size({"width": width, "height": 1100})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), f"Horizontal overflow at {width}px"
            expect(page.get_by_test_id("speaker-person-picker")).to_be_visible()

        open_page()
        expect(page.get_by_test_id("speaker-person-group")).to_have_count(4)
        expect(page.get_by_test_id("speaker-card")).to_have_count(1)
        expect(page.get_by_test_id("speaker-suggestion-summary")).to_be_visible()
        expect(page.get_by_test_id("voice-suggestion")).to_be_visible()
        expect(page.get_by_test_id("speaker-card")).to_have_attribute("data-label", "SPEAKER_02")
        expect(queue(0)).to_contain_text("قد يكون: سامر خليل")
        page.screenshot(path=str(SHOTS / "suggestions-desktop.png"), full_page=True)
        check_no_overflow(390)
        page.screenshot(path=str(SHOTS / "suggestions-mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1100})
        page.get_by_test_id("review-voice-suggestions").click()
        expect(page.get_by_test_id("speaker-person-group")).to_have_count(1)
        page.get_by_role("button", name="الكل", exact=False).click()
        page.get_by_role("searchbox").fill("سامر خليل")
        expect(page.get_by_test_id("speaker-person-group")).to_have_count(1)
        page.get_by_role("searchbox").fill("")
        queue(1).click()
        expect(page.locator("progress")).to_have_attribute("value", "3")
        expect(page.get_by_test_id("speaker-save")).to_be_disabled()
        expect(page.get_by_test_id("voice-enroll")).to_be_disabled()
        expect(page.get_by_test_id("speaker-voice-sample-missing")).to_be_visible()
        page.screenshot(path=str(SHOTS / "desktop.png"), full_page=True)

        page.get_by_role("textbox", name="ملاحظات", exact=True).fill("ملاحظة مراجعة محفوظة بين العينات")
        page.get_by_role("combobox", name="الصفة", exact=True).select_option("WITNESS")
        queue(0).click()
        expect(page.get_by_test_id("voice-suggestion")).to_be_visible()
        queue(1).click()
        expect(page.get_by_role("textbox", name="ملاحظات", exact=True)).to_have_value("ملاحظة مراجعة محفوظة بين العينات")
        expect(page.get_by_role("combobox", name="الصفة", exact=True)).to_have_value("WITNESS")
        state["fail_save"] = True
        page.get_by_test_id("speaker-save").click()
        expect(page.locator(".toast-error")).to_be_visible()
        expect(page.get_by_test_id("speaker-save")).to_be_enabled()
        state["fail_save"] = False
        page.get_by_test_id("speaker-save").click()
        expect(page.get_by_test_id("speaker-save")).to_be_disabled()
        assert state["patches"] == [{"speaker_role": "WITNESS", "notes": "ملاحظة مراجعة محفوظة بين العينات"}]
        print("PASS: draft retention, failed-save recovery, role/notes payload, and save state", flush=True)

        page.get_by_role("button", name="محددون", exact=False).click()
        expect(page.get_by_test_id("speaker-person-group")).to_have_count(2)
        expect(page.get_by_role("button", name="العينة 2", exact=True)).to_be_visible()
        page.get_by_role("button", name="العينة 2", exact=True).click()
        expect(page.get_by_test_id("speaker-card")).to_have_attribute("data-label", "SPEAKER_04")
        expect(page.get_by_test_id("voice-enroll")).to_be_enabled()
        page.get_by_test_id("speaker-person-picker").click()
        expect(page.get_by_role("dialog")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog")).to_have_count(0)
        page.get_by_role("searchbox").fill("لا يوجد هذا الاسم")
        expect(page.get_by_test_id("speaker-person-group")).to_have_count(0)
        page.get_by_role("button", name="إظهار الجميع", exact=True).click()
        expect(page.get_by_test_id("speaker-person-group")).to_have_count(4)
        page.get_by_role("searchbox").fill("SPEAKER_05")
        expect(page.get_by_test_id("speaker-person-group")).to_have_count(1)
        page.get_by_role("searchbox").fill("")
        print("PASS: filters, source search, no-results recovery, identity grouping, and picker", flush=True)

        page.get_by_test_id("review-voice-suggestions").click()
        page.get_by_test_id("voice-confirm").click()
        expect(page.locator(".speaker-detail-heading h3")).to_have_text("سامر خليل")
        expect(page.locator("progress")).to_have_attribute("value", "4")
        expect(page.get_by_test_id("speaker-card")).to_have_attribute("data-label", "SPEAKER_02")
        expect(page.get_by_test_id("speaker-person-group").filter(has_text="سامر خليل")).to_have_count(1)
        expect(page.get_by_test_id("speaker-suggestion-summary")).to_have_count(0)
        page.get_by_role("button", name="العينة التالية", exact=True).click()
        expect(page.get_by_test_id("speaker-card")).to_have_attribute("data-label", "SPEAKER_01")
        print("PASS: confirmed suggestion, selection after regrouping, progress, next pending sample", flush=True)

        page.get_by_role("tab", name="النص المفرغ", exact=False).click()
        expect(page.locator(".speaker-turn h4")).to_have_text("سامر خليل")
        expect(page.locator(".speaker-turn-heading")).not_to_contain_text("SPEAKER_02")
        page.get_by_role("tab", name="المتحدثون", exact=False).click()
        print("PASS: confirmed canonical name replaces source label in speaker queue and transcript", flush=True)

        page.locator(".speaker-matching-tools summary").click()
        page.get_by_test_id("voice-rematch").click()
        expect(page.get_by_test_id("voice-rematch-result")).to_be_visible()
        print("PASS: voice rematch and persistent result summary", flush=True)

        for width in (1440, 1280, 1024, 768, 390, 320):
            check_no_overflow(width)
        page.set_viewport_size({"width": 390, "height": 844})
        open_page()
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(SHOTS / "mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1100})
        tab = page.get_by_role("tab", name="المتحدثون", exact=False)
        tab.focus()
        page.keyboard.press("ArrowLeft")
        expect(page.get_by_role("tab", name="سجل النشاط", exact=False)).to_have_attribute("aria-selected", "true")
        page.keyboard.press("ArrowRight")
        expect(page.get_by_test_id("speaker-workspace")).to_be_visible()
        print("PASS: responsive layout at six widths and RTL keyboard tab navigation", flush=True)

        state["permissions"] = []
        state["speakers"] = copy.deepcopy(original)
        open_page()
        expect(page.get_by_test_id("speaker-suggestion-summary")).to_have_count(0)
        expect(page.get_by_test_id("speaker-workspace")).not_to_contain_text("سامر خليل")
        expect(page.get_by_test_id("speaker-person-picker")).to_be_disabled()
        expect(page.get_by_test_id("speaker-save")).to_have_count(0)
        expect(page.get_by_test_id("voice-enroll")).to_have_count(0)
        state["permissions"] = PERMISSIONS[:]
        state["speakers"] = [s for s in state["speakers"] if s["identity_id"]]
        open_page()
        expect(page.locator("progress")).to_have_attribute("value", str(len(state["speakers"])))
        expect(page.locator(".speaker-guidance.is-complete")).to_be_visible()
        page.screenshot(path=str(SHOTS / "completed.png"), full_page=True)
        state["speakers"] = []
        open_page()
        expect(page.get_by_role("link", name="الانتقال إلى التسجيل", exact=False)).to_be_visible()
        expect(page.locator("progress")).to_have_count(0)
        state["transcript_error"] = True
        page.goto(url)
        expect(page.get_by_role("button", name="إعادة المحاولة", exact=True)).to_be_visible()
        state["transcript_error"] = False
        state["speakers"] = copy.deepcopy(original)
        page.get_by_role("button", name="إعادة المحاولة", exact=True).click()
        expect(page.get_by_test_id("speaker-workspace")).to_be_visible()
        print("PASS: read-only permissions, completed, empty, load-error and retry states", flush=True)
        assert not errors, errors
        browser.close()
        print(f"PASS: no browser runtime errors. Screenshots: {SHOTS}", flush=True)
finally:
    if server:
        server.shutdown()
