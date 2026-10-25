"""Exercise the investigation UI with synthetic APIs and a fake microphone.

Run after npm run build; optionally pass http://localhost to verify deployed assets.
No requests to real investigation or processing APIs are allowed through.
"""
import copy
import io
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
from urllib.parse import urlparse
import wave

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "storage/test-artifacts/investigation-workspace"
SHOTS.mkdir(parents=True, exist_ok=True)
SESSION = "04176210-31ec-46e5-9637-c1aff1747d1b"
NOW = "2026-10-25T09:00:00Z"
PERMISSIONS = ["investigations.update", "investigations.create", "investigations.archive", "recordings.create", "transcripts.edit", "speakers.assign", "voice.identify", "voice.enroll", "reports.generate"]


class PreviewHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if not Path(self.translate_path(self.path)).is_file():
            self.path = "/index.html"
        super().do_GET()

    def log_message(self, *_):
        pass


audio = io.BytesIO()
with wave.open(audio, "wb") as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(16000)
    wav.writeframes(b"\x00\x00" * 16000 * 30)
AUDIO = audio.getvalue()
speakers = [dict(id=f"speaker-{n}", session_id=SESSION, recording_id="recording-1", speaker_label=f"SPEAKER_0{n}",
                 identity_id=f"person-{n}" if n == 1 else None, identity_name="أحمد منصور" if n == 1 else None,
                 display_name="أحمد منصور" if n == 1 else "علي حسن", speaker_role="INVESTIGATOR" if n == 1 else "SUBJECT",
                 notes=None, segment_count=2, total_seconds=10, updated_at=NOW, identification_status="NONE",
                 suggested_name=None, suggested_score=None, suggested_model=None, has_voice_embedding=True) for n in (1, 2)]
segments = [dict(id=f"segment-{n}", sequence=n, speaker_label=f"SPEAKER_0{1 if n in (0, 3) else 2}",
                 start_seconds=n * 6, end_seconds=n * 6 + 5,
                 original_text=text, edited_text=None, confidence=.93, is_overlap=False, edited_by=None,
                 edited_by_name=None, edited_at=None) for n, text in enumerate([
                     "يرجى ذكر اسمك الكامل ومكان إقامتك.", "اسمي علي حسن وأقيم في بيروت.",
                     "وصلت إلى المكان صباحاً برفقة أحد زملائي.", "هل يمكنك توضيح وقت وصولك إلى المكان؟"])]
recording = dict(id="recording-1", session_id=SESSION, original_filename="تسجيل الجلسة الأولى.wav", mime_type="audio/wav",
                 size_bytes=len(AUDIO), duration_seconds=30, sha256="ab" * 32, source="FILE_UPLOAD", upload_status="UPLOADED", created_at=NOW)
session = dict(id=SESSION, title="مراجعة إفادات الجلسة", session_number="INV-2026-00128", location="غرفة التحقيق ٢",
               session_date="2026-10-25", start_time="09:00:00", end_time="09:15:00", duration_seconds=900,
               description="مراجعة أقوال المشاركين وتوثيق تسلسل الوقائع.", status="COMPLETED", notes="تُراجع الإفادات مع التسجيل الأصلي قبل إعداد المحضر.",
               created_at=NOW, updated_at=NOW, created_by="reviewer", created_by_name="أحمد منصور",
               has_transcript=True, expected_speaker_count=2, speaker_limit_warning=False, latest_job_status="COMPLETED",
               recordings=[recording], investigators=[dict(id="investigator-1", full_name="أحمد منصور", rank="نقيب", military_id="12345", unit="قسم التحقيق", assignment_role="LEAD")],
               subjects=[dict(id="subject-1", participant_key="subject:subject-1", subject_name="علي حسن", person_type="CIVILIAN", identity_confidence="DOCUMENT_SEEN", nationality_code="LB", nationality_name="لبنان", documents=[], notes=None, is_undocumented=False, is_unregistered=False, duplicate_of_sessions=[])])
model = dict(state="READY", available=True, loaded=True, model="local-model", provider="local", revision="1", error=None)
caps = dict(agent_id="test-agent", agent_version="1.0", device_name="محطة المراجعة", processing_device="cuda", gpu_name="Test GPU", cuda_available=True,
            stt=model, diarization=model, speaker_id=model, vad=model, max_speakers=4, supported_formats=["wav", "mp3", "m4a", "webm"], max_upload_bytes=2147483648,
            ready=True, loadable=True, loading=False, busy=False, central_sync_enabled=True)
state = dict(permissions=PERMISSIONS[:], audio_error=False, transcript_error=False, activity_error=False, save_error=False, agent_ready=True, job_started=False, requests=[], segments=copy.deepcopy(segments))


def fulfill(route, body, status=200):
    route.fulfill(status=status, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=json.dumps(body))


def api(route):
    path = urlparse(route.request.url).path.removeprefix("/api")
    method = route.request.method
    if path == "/auth/me":
        fulfill(route, dict(id="reviewer", username="reviewer", is_active=True, must_change_password=False, roles=["INVESTIGATOR"], permissions=state["permissions"], profile={"full_name": "أحمد منصور"}, last_login_at=None))
    elif path == f"/investigations/{SESSION}":
        fulfill(route, session)
    elif path.endswith("/transcript"):
        if state["transcript_error"]:
            fulfill(route, {"detail": "generic"}, 503)
        else:
            fulfill(route, dict(id="transcript-1", session_id=SESSION, recording_id="recording-1", job_id="job-1", status="COMPLETED", language="ar", speakers=speakers, segments=state["segments"], audio_available=True, warnings=[], created_at=NOW, completed_at=NOW, stt_model="Local Arabic transcription", diarization_model="Local speaker separation", speaker_count=2))
    elif path.endswith("/audio"):
        if state["audio_error"]:
            fulfill(route, {"detail": "generic"}, 500)
        else:
            route.fulfill(content_type="audio/wav", body=AUDIO)
    elif path.startswith("/transcript-segments/") and method == "PATCH":
        if state["save_error"]:
            fulfill(route, {"detail": "generic"}, 500)
        else:
            payload = route.request.post_data_json
            state["requests"].append((path, payload))
            segment = next(item for item in state["segments"] if item["id"] == path.rsplit("/", 1)[1])
            segment.update(edited_text=payload["edited_text"], edited_by="reviewer", edited_by_name="أحمد منصور", edited_at=NOW)
            fulfill(route, segment)
    elif path.endswith("/activity"):
        fulfill(route, {"detail": "generic"} if state["activity_error"] else dict(items=[], total=0, page=1, page_size=100), 503 if state["activity_error"] else 200)
    elif path.endswith("/jobs"):
        fulfill(route, [])
    elif path.endswith("/statement-details"):
        fulfill(route, dict(token="synthetic", session_id=SESSION, participant_key="subject:subject-1", values={}, fields=[]))
    elif path.endswith("/local-processing-token"):
        state["requests"].append((path, route.request.post_data_json))
        fulfill(route, dict(job_id="job-1", processing_token="synthetic", speaker_limit_warning=False))
    elif path == "/local-processing/job-1":
        fulfill(route, dict(id="job-1", status="COMPLETED"))
    else:
        if method != "GET":
            raise AssertionError(f"Unexpected mutation: {method} {path}")
        fulfill(route, [])


def agent(route):
    path = urlparse(route.request.url).path
    if route.request.method == "OPTIONS":
        route.fulfill(status=204, headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Private-Network": "true"})
    elif path == "/capabilities":
        fulfill(route, {**caps, "ready": state["agent_ready"], "stt": model if state["agent_ready"] else {**model, "state": "PROVISIONED"}})
    elif path == "/jobs" and route.request.method == "GET":
        fulfill(route, [])
    elif path == "/jobs" or path == "/jobs/job-1":
        state["job_started"] = True
        completed = path.endswith("job-1")
        fulfill(route, dict(job_id="job-1", session_id=SESSION, state="COMPLETED" if completed else "TRANSCRIBING", sync_state="SYNCED" if completed else "NOT_STARTED", progress=1 if completed else .6, message=None, error_code=None, error_message=None, failure_stage=None, warnings=[], speaker_count=2, segment_count=4, created_at=NOW))
    else:
        fulfill(route, {})


server = None
if len(sys.argv) > 1:
    base = sys.argv[1].rstrip("/")
else:
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(PreviewHandler, directory=str(ROOT / "central/frontend/dist")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
        context = browser.new_context(viewport={"width": 1440, "height": 1100}, permissions=["microphone"])
        context.add_init_script("sessionStorage.setItem('mstt.access_token', 'synthetic-ui-test')")
        context.route("**/api/**", api)
        context.route("**/127.0.0.1:17117/**", agent)
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))

        def open_tab(tab):
            page.goto(f"{base}/investigations/{SESSION}?tab={tab}")
            expect(page.locator(".investigation-context")).to_be_visible()
            page.evaluate("document.fonts.ready")

        def screenshot(name):
            page.evaluate("window.scrollTo(0, 0)")
            page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)

        for tab, selector in [("details", "investigation-details"), ("recording", "recording-workspace"), ("transcript", "transcript-workspace")]:
            open_tab(tab)
            expect(page.get_by_test_id(selector)).to_be_visible()
            assert "???" not in page.locator("#main-content").inner_text(), f"Broken Arabic text on {tab}"
            screenshot(f"{tab}-desktop")
            for width in (1440, 1280, 1024, 768, 390, 320):
                page.set_viewport_size({"width": width, "height": 1000})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), f"Overflow on {tab} at {width}px"
            page.set_viewport_size({"width": 390, "height": 844})
            screenshot(f"{tab}-mobile")
            page.set_viewport_size({"width": 1440, "height": 1100})
        print("PASS: Arabic text and responsive layout across three screens and six widths", flush=True)

        open_tab("details")
        expect(page.get_by_test_id("subject-summary")).to_have_count(1)
        expect(page.get_by_role("button", name="بيانات صاحب الإفادة في هذه الجلسة", exact=False)).to_be_visible()
        page.get_by_role("link", name="مراجعة النص المفرغ", exact=True).click()
        expect(page.get_by_test_id("transcript-workspace")).to_be_visible()
        expect(page.get_by_test_id("segment")).to_have_count(4)
        expect(page.get_by_test_id("speaker-turn")).to_have_count(3)
        page.get_by_role("searchbox").fill("بيروت")
        expect(page.get_by_test_id("segment")).to_have_count(2)
        page.get_by_role("button", name="مسح التصفية").click()
        page.locator(".transcript-speaker-buttons button").nth(1).click()
        expect(page.get_by_test_id("segment")).to_have_count(2)
        page.get_by_role("button", name="مسح التصفية").click()
        page.get_by_test_id("edit-segment").first.click()
        textarea = page.get_by_role("textbox", name="تعديل نص المقطع")
        textarea.fill("يرجى توضيح اسمك الكامل ومكان إقامتك.")
        state["save_error"] = True
        page.get_by_role("button", name="حفظ التصحيح", exact=True).click()
        expect(page.locator(".toast-error")).to_be_visible()
        expect(textarea).to_be_visible()
        state["save_error"] = False
        page.get_by_role("button", name="حفظ التصحيح", exact=True).click()
        expect(textarea).to_have_count(0)
        page.locator(".transcript-original summary").first.click()
        expect(page.locator(".transcript-original .orig-box")).to_contain_text(segments[0]["original_text"])
        assert state["requests"][-1] == ("/transcript-segments/segment-0", {"edited_text": "يرجى توضيح اسمك الكامل ومكان إقامتك."})
        expect(page.get_by_test_id("audio-player")).to_be_visible()
        assert page.locator(".player").bounding_box()["height"] < 180, "Audio controls must stay compact"
        page.get_by_test_id("segment").nth(1).locator(".tools button").first.click()
        assert page.get_by_test_id("audio-player").evaluate("el => el.currentTime") >= 6
        print("PASS: overview navigation, participant controls, transcript grouping/search, speaker filter, editing, original comparison, audio seek", flush=True)

        state["audio_error"] = True
        open_tab("transcript")
        expect(page.get_by_role("button", name="إعادة تحميل الصوت")).to_be_visible()
        expect(page.get_by_test_id("segment").first.locator(".tools button").first).to_be_disabled()
        state["audio_error"] = False
        page.get_by_role("button", name="إعادة تحميل الصوت").click()
        expect(page.get_by_test_id("audio-player")).to_be_visible()

        open_tab("recording")
        process = page.get_by_role("button", name="معالجة التسجيل", exact=True)
        expect(process).to_be_disabled()
        picker = page.get_by_label("اختيار ملف صوتي", exact=True)
        picker.set_input_files({"name": "invalid.txt", "mimeType": "text/plain", "buffer": b"invalid"})
        expect(page.locator(".recording-source-card [role=alert]")).to_be_visible()
        picker.set_input_files({"name": "review.wav", "mimeType": "audio/wav", "buffer": AUDIO})
        expect(page.get_by_test_id("pending-audio")).to_be_visible()
        expect(page.locator(".recording-preview")).to_be_visible()
        expect(process).to_be_enabled()
        page.get_by_role("tab", name="التفاصيل", exact=True).click()
        page.get_by_role("tab", name="التسجيل", exact=True).click()
        expect(page.get_by_test_id("pending-audio")).to_contain_text("review.wav")
        process.click()
        expect(page.get_by_role("progressbar")).to_be_visible()
        expect(page.get_by_role("link", name="مراجعة النص المفرغ", exact=True)).to_be_visible(timeout=12000)
        expect(page.get_by_test_id("pending-audio")).to_have_count(0)
        assert state["job_started"]
        print("PASS: audio failure/retry, invalid upload, preview, pending-file retention, processing and completion navigation", flush=True)

        open_tab("recording")
        page.get_by_role("button", name="تسجيل مباشر", exact=False).click()
        page.get_by_role("button", name="بدء التسجيل", exact=True).click()
        expect(page.get_by_role("button", name="إيقاف مؤقت", exact=False)).to_be_visible()
        page.get_by_role("button", name="إيقاف مؤقت", exact=False).click()
        page.get_by_role("button", name="متابعة التسجيل", exact=True).click()
        page.get_by_role("button", name="إنهاء التسجيل", exact=True).click()
        expect(page.get_by_test_id("pending-audio")).to_be_visible()
        page.get_by_role("button", name="تجاهل", exact=True).click()
        expect(page.get_by_test_id("pending-audio")).to_have_count(0)
        page.get_by_role("button", name="بدء التسجيل", exact=True).click()
        expect(page.get_by_role("button", name="إيقاف مؤقت", exact=True)).to_be_visible()
        page.get_by_role("tab", name="التفاصيل", exact=True).click()
        page.get_by_role("tab", name="التسجيل", exact=True).click()
        expect(page.get_by_test_id("pending-audio")).to_be_visible()
        expect(page.get_by_role("button", name="تسجيل مباشر", exact=False)).to_have_attribute("aria-pressed", "true")
        page.get_by_role("button", name="تجاهل", exact=True).click()
        print("PASS: synthetic microphone recording, pause/resume, stop, preview and discard", flush=True)

        state["activity_error"] = True
        open_tab("activity")
        expect(page.get_by_role("button", name="إعادة المحاولة")).to_be_visible()
        state["activity_error"] = False
        page.get_by_role("button", name="إعادة المحاولة").click()
        expect(page.locator(".activity-workspace")).to_be_visible()
        state["transcript_error"] = True
        open_tab("transcript")
        expect(page.get_by_role("button", name="إعادة المحاولة")).to_be_visible()
        state["transcript_error"] = False
        page.get_by_role("button", name="إعادة المحاولة").click()
        expect(page.get_by_test_id("transcript-workspace")).to_be_visible()
        state["permissions"] = []
        open_tab("transcript")
        expect(page.get_by_test_id("edit-segment")).to_have_count(0)
        open_tab("recording")
        expect(page.get_by_test_id("recording-source")).to_have_count(0)
        open_tab("not-a-tab")
        expect(page.get_by_test_id("investigation-guide")).to_be_visible()
        print("PASS: load-error recovery, read-only permissions, invalid-tab fallback", flush=True)
        assert not errors, errors
        browser.close()
        print(f"PASS: no browser runtime errors. Screenshots: {SHOTS}", flush=True)
finally:
    if server:
        server.shutdown()
