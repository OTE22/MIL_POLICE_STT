"""Continuous isolated acceptance with real local speech inference and browser dictation.

Only synthetic fixtures/accounts are used. Run in the backend test image with /fixtures,
/artifacts and this script mounted. A PASS requires the entire journey to finish.
"""
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

BASE = "http://workflow-ui-frontend"
AGENT = "http://workflow-ui-agent:17117"
OUT = Path("/artifacts/complete-workflow")
OUT.mkdir(parents=True, exist_ok=True)
results = []


def record(name, **details):
    results.append({"step": name, "status": "PASS", **details})
    (OUT / "journey.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("PASS:", name, flush=True)


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage",
        "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
        "--use-file-for-fake-audio-capture=/fixtures/single_speaker_ar.wav",
        "--unsafely-treat-insecure-origin-as-secure=" + BASE])
    context = browser.new_context(viewport={"width": 1600, "height": 1000}, locale="ar-LB",
                                  permissions=["microphone"], accept_downloads=True)
    context.add_init_script("localStorage.setItem('mstt.agent_url', '" + AGENT + "')")
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    request = context.request
    token = None

    def api(method, path, body=None, expected=200, bearer=None):
        response = request.fetch(BASE + "/api" + path, method=method, data=body,
            headers={"Authorization": "Bearer " + (bearer or token)} if (bearer or token) else {})
        assert response.status == expected, f"{method} {path}: {response.status} {response.text()[:1200]}"
        return response.json()

    def shot(name):
        page.screenshot(path=str(OUT / (name + ".png")), full_page=True)

    def wait_for(name, check, seconds=900):
        deadline = time.monotonic() + seconds
        last = None
        while time.monotonic() < deadline:
            last = check()
            if last:
                return last
            page.wait_for_timeout(1000)
        raise AssertionError(f"Timeout waiting for {name}: {last}")

    def field(container, label):
        return container.get_by_label(re.compile("^" + re.escape(label) + r"\s*\*?$"))

    def saved_state():
        state = api("GET", base + "/report/html")
        expect(page.locator(".report-save-state")).to_have_text("تم الحفظ", timeout=15000)
        return api("GET", base + "/report/html")

    try:
        admin = api("POST", "/auth/login", {"username": "admin", "password": "AdminBootstrap!1"})["access_token"]
        username = "journey_" + uuid.uuid4().hex[:10]
        user = api("POST", "/users", {"username": username, "password": "WorkflowTest!1234", "roles": ["INVESTIGATOR"],
            "must_change_password": False, "profile": {"full_name": "محقق تجربة المسار الكامل", "rank": "نقيب", "military_id": username, "security_branch": "ARMY"}}, 201, admin)
        page.goto(BASE + "/login")
        page.locator("#username").fill(username); page.locator("#password").fill("WorkflowTest!1234")
        page.locator('button[type="submit"]').click()
        expect(page).not_to_have_url(re.compile(r"/login$"))
        token = page.evaluate("sessionStorage.getItem('mstt.access_token')")
        page.goto(BASE + "/investigations/new")
        page.locator("#session-title").fill("اختبار كامل للتحقيق والإملاء — بيانات اصطناعية")
        page.get_by_test_id("subject-name").fill("الشخص العسكري التجريبي")
        page.get_by_test_id("person-type-MILITARY").check()
        page.locator('button[type="submit"]').click()
        expect(page).to_have_url(re.compile(r"/investigations/[a-f0-9-]{36}$"))
        base = "/investigations/" + page.url.split("/")[-1]
        session = api("GET", base)
        assert not session["intake_readiness"]["ready"]
        expect(page.get_by_role("heading", name="استكمال بيانات الأشخاص")).to_be_visible()
        api("POST", base + "/local-processing-token", {"original_filename": "attempt.wav", "mime_type": "audio/wav", "size_bytes": 1000}, 409)
        api("POST", base + "/report/html", {}, 409)
        shot("01-incomplete-draft")
        record("Incomplete draft saved; direct processing and report preparation blocked", session_id=session["id"])

        page.goto(BASE + base + "/edit")
        page.locator("#session-location").fill("غرفة الاختبارات")
        page.locator("#session-session_date").fill("2026-10-26")
        cards = page.get_by_test_id("subject-card")
        military = cards.nth(0)
        field(military, "الجهاز").select_option("ARMY")
        field(military, "الرتبة").fill("رقيب")
        military.get_by_test_id("military-id").fill("E2E-" + username)
        field(military, "الوحدة").fill("وحدة اختبار")
        page.get_by_role("button", name=re.compile("إضافة شخص")).click()
        civilian = cards.nth(1)
        civilian.get_by_test_id("subject-name").fill("الشخص المدني التجريبي")
        civilian.get_by_test_id("nationality").select_option("LB")
        civilian.get_by_test_id("register-number").fill(str(int(time.time()) % 10000000))
        civilian.get_by_test_id("caza-code").select_option("BEIRUT")
        field(civilian, "البلدة / تفاصيل محل القيد").fill("بيروت")
        values = {"father_name": "الأب التجريبي", "mother_name": "الأم التجريبية", "birth_year": "1990",
            "birth_place": "بيروت", "district": "بيروت", "residence": "عنوان اصطناعي للاختبار", "family_status": "عازب",
            "education": "ثانوي", "occupation_statement": "عمل تجريبي", "prior_record_statement": "يصرح بأنه غير محكوم سابقاً"}
        catalogue = api("GET", "/investigations/participant-requirements")["fields"]
        for card in (military, civilian):
            for definition in catalogue:
                if definition["key"] in values:
                    field(card, definition["label"]).fill(values[definition["key"]])
            card.get_by_label("حالة رقم الهاتف", exact=True).select_option("REFUSED")
            field(card, "سبب عدم توفر رقم الهاتف").fill("رفض الشخص تقديم رقم الهاتف أثناء التسجيل الأولي")
            card.get_by_role("button", name=re.compile("إضافة وثيقة")).click()
            field(card, "رقم الوثيقة").fill("DOC-" + username + ("-M" if card == military else "-C"))
        page.locator('button[type="submit"]').click()
        expect(page).to_have_url(BASE + base)
        session = api("GET", base)
        assert session["intake_readiness"]["ready"], session["intake_readiness"]
        assert len(session["subjects"]) == 2
        person_ids = [p["id"] for p in session["subjects"]]
        shot("02-complete-intake")
        record("Military and civilian intake completed once with explicit refusal and documents")

        runtime = wait_for("real models", lambda: (lambda c: c if c["ready"] else None)(request.get(AGENT + "/capabilities").json()))
        (OUT / "runtime.json").write_text(json.dumps(runtime, indent=2), encoding="utf-8")
        page.goto(BASE + base + "?tab=recording")
        page.get_by_label("اختيار ملف صوتي").set_input_files("/fixtures/conversation_ar_2spk.wav")
        process = page.get_by_role("button", name="معالجة التسجيل", exact=True)
        expect(process).to_be_enabled(timeout=20000); process.click()
        def interview_done():
            jobs = api("GET", base + "/jobs")
            if jobs and jobs[0]["status"] == "FAILED":
                raise AssertionError(jobs[0].get("error_message"))
            current = api("GET", base)
            return current if jobs and jobs[0]["status"] == "COMPLETED" and current["recordings"] and current["recordings"][0]["upload_status"] == "UPLOADED" else None
        session = wait_for("real interview processing and original upload", interview_done, 1800)
        transcript = api("GET", base + "/transcript")
        assert transcript["segments"] and transcript["stt_provider"] == "cohere_local"
        assert len(transcript["speakers"]) >= 2
        original = {s["id"]: s["original_text"] for s in transcript["segments"]}
        recording_hash = session["recordings"][0]["sha256"]
        for index, speaker in enumerate(transcript["speakers"]):
            identity = session["investigators"][0]["identity_id"] if index == 0 else session["subjects"][0]["identity_id"]
            api("PATCH", base + "/speakers/" + speaker["id"], {"identity_id": identity, "speaker_role": "INVESTIGATOR" if index == 0 else "SUBJECT"})
        for segment in transcript["segments"]:
            api("PATCH", "/transcript-segments/" + segment["id"], {"expected_revision": segment["revision"], "edited_text": segment["original_text"]})
        transcript = api("GET", base + "/transcript")
        answer = next(s for s in transcript["segments"] if s["speaker_label"] == transcript["speakers"][1]["speaker_label"])
        api("PUT", "/transcript-segments/" + answer["id"] + "/attribution", {"expected_revision": answer["revision"], "parts": [{
            "speaker_label": answer["speaker_label"], "start_seconds": answer["start_seconds"], "end_seconds": answer["end_seconds"], "text": answer["original_text"] + " تمت مراجعة هذا النص التجريبي."}]})
        assert all(original[s["id"]] == s["original_text"] for s in api("GET", base + "/transcript")["segments"])
        page.goto(BASE + base + "?tab=transcript"); shot("03-reviewed-transcript")
        record("Real local interview engine synchronized; identities and attribution reviewed; original evidence unchanged", audio_sha256=recording_hash)

        page.goto(BASE + base + "/report")
        expect(page.get_by_test_id("html-report-editor")).to_be_visible()
        page.get_by_role("button", name="إضافة إفادة", exact=True).click()
        picker = page.get_by_role("region", name="اختيار أصحاب الإفادات")
        for person in session["subjects"]:
            picker.get_by_label(person["subject_name"], exact=False).check()
        picker.get_by_role("button", name=re.compile("تجهيز الإفادات المحددة")).click()
        state = saved_state()
        statements = [b for b in state["document"]["blocks"] if b["type"] == "statement"]
        assert len(statements) == 2 and any(e["source_block_ids"] for b in statements for e in b["entries"])
        for block in statements:
            assert block["values"]["father_name"] == values["father_name"]
            page.locator(".report-outline-item > button").filter(has_text=block["values"]["statement_name"]).click()
            for index, entry in enumerate(block["entries"]):
                if not entry["answer"]:
                    page.get_by_label(f"نص الإفادة {index + 1}", exact=True).fill("إفادة يدوية تجريبية للشخص الذي لا يتوفر له تسجيل.")
        saved_state(); shot("04-multiple-statements")
        record("Multiple participants imported in one selection; registered details reused and source references retained")

        page.get_by_role("button", name="إضافة ملاحظة", exact=True).click()
        page.get_by_label("الملاحظة", exact=True).fill("ملاحظة سابقة قبل الإملاء.")
        saved_state()
        page.get_by_role("button", name="إملاء صوتي — الملاحظة", exact=True).click()
        voice = page.get_by_role("region", name="إملاء المحقق")
        voice.get_by_role("button", name="بدء التسجيل", exact=True).click()
        page.wait_for_timeout(12000)
        voice.get_by_role("button", name="إنهاء التسجيل", exact=True).click()
        voice.get_by_role("button", name="تحويل التسجيل إلى نص", exact=True).click()
        insert = voice.get_by_role("button", name="إدراج النص المراجع", exact=True)
        expect(insert).to_be_enabled(timeout=900000)
        machine = api("GET", base + "/report/dictations")[0]
        assert machine["machine_text"].strip() and machine["audio_ready"]
        voice.get_by_label("راجع النص وعدّله قبل الإدراج").fill(machine["machine_text"] + " [صياغة راجعها المحقق في الاختبار]")
        insert.click()
        wait_for("reviewed dictation accepted", lambda: api("GET", base + "/report/dictations")[0]["status"] == "ACCEPTED")
        after = api("GET", base + "/transcript")
        assert after["id"] == transcript["id"] and len(after["speakers"]) == len(transcript["speakers"])
        assert all(original[s["id"]] == s["original_text"] for s in after["segments"])
        shot("05-dictation-reviewed")
        record("Real microphone dictation reviewed and appended; no contamination of testimony or speakers")

        page.get_by_role("button", name="خلاصة التحقيق", exact=True).click()
        page.get_by_label("الوقائع", exact=True).fill(("وقائع اصطناعية موثقة لأغراض الاختبار. " * 180) + "Evidence REF-2026/A")
        page.get_by_label("الاستنتاج", exact=True).fill("استنتاج تجريبي يراجع سلامة تسلسل الوقائع والأدلة.")
        page.get_by_label("المسؤوليات", exact=True).select_option("NONE")
        page.get_by_label("الاقتراحات", exact=True).select_option("TEXT")
        page.get_by_label("نص الاقتراحات", exact=True).fill("اقتراح تجريبي بالتحقق من البيانات وتوثيق المتابعة.")
        saved_state()
        page.get_by_role("button", name="إضافة ملاحظة", exact=True).click()
        page.get_by_label("الملاحظة", exact=True).fill("ملاحظة بعد خلاصة التحقيق.")
        saved_state()
        page.get_by_role("button", name="معاينة PDF والمراجعة", exact=True).click()
        expect(page.get_by_title("معاينة PDF النهائية")).to_be_visible(timeout=60000)
        shot("06-pdf-review-long-document")
        page.get_by_role("checkbox", name="راجعت بيانات المحضر ومحتواه ونسبة الأقوال إلى أصحابها", exact=True).check()
        page.get_by_role("button", name="حفظ تأكيد المراجعة", exact=True).click()
        issue = page.get_by_role("button", name="إصدار وحفظ HTML وPDF", exact=True)
        expect(issue).to_be_enabled(timeout=20000); issue.click()
        expect(page.get_by_role("button", name="معاينة PDF والمراجعة", exact=True)).to_be_enabled(timeout=60000)
        archive = wait_for("first immutable report", lambda: (lambda a: a if a["reports"] else None)(api("GET", base + "/reports")))
        first = archive["reports"][0]
        artifacts = {}
        for fmt in ("html", "pdf"):
            response = request.get(BASE + "/api" + base + f"/reports/{first['id']}/file?format={fmt}", headers={"Authorization": "Bearer " + token})
            assert response.status == 200
            artifacts[fmt] = response.body()
            (OUT / ("issued-v1." + fmt)).write_bytes(response.body())
        assert api("GET", base + f"/reports/{first['id']}/verify")["ok"]
        record("Lead reviewed and issued long HTML/PDF with verifiable immutable hashes", pdf_sha256=hashlib.sha256(artifacts["pdf"]).hexdigest())

        for target in ("AWAITING_REVIEW", "REVIEWED", "CLOSED"):
            current = api("GET", base)
            api("POST", base + "/workflow", {"expected_revision": current["revision"], "state": target, "reason": "انتقال صريح ضمن اختبار المسار الكامل"})
        state = api("GET", base + "/report/html")
        api("POST", base + "/report/reopen", {"expected_token": state["token"], "reason": "تصحيح تجريبي موثق مع الاحتفاظ بالإصدار الأول"})
        page.goto(BASE + base + "/report")
        page.get_by_role("button", name="إضافة ملاحظة", exact=True).click()
        page.get_by_label("الملاحظة", exact=True).fill("تصحيح لاحق في الإصدار الثاني فقط.")
        saved_state()
        page.get_by_role("button", name="معاينة PDF والمراجعة", exact=True).click()
        expect(page.get_by_title("معاينة PDF النهائية")).to_be_visible(timeout=60000)
        page.get_by_role("checkbox", name="راجعت بيانات المحضر ومحتواه ونسبة الأقوال إلى أصحابها", exact=True).check()
        page.get_by_role("button", name="حفظ تأكيد المراجعة", exact=True).click()
        issue = page.get_by_role("button", name="إصدار وحفظ HTML وPDF", exact=True)
        expect(issue).to_be_enabled(timeout=20000); issue.click()
        wait_for("successor issue", lambda: len(api("GET", base + "/reports")["reports"]) == 2)
        for fmt, content in artifacts.items():
            response = request.get(BASE + "/api" + base + f"/reports/{first['id']}/file?format={fmt}", headers={"Authorization": "Bearer " + token})
            assert response.body() == content
        for width, name in [(1600, "desktop"), (390, "mobile")]:
            page.set_viewport_size({"width": width, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            shot("07-issued-" + name)
        assert [p["id"] for p in api("GET", base)["subjects"]] == person_ids
        assert not errors, errors
        record("Closure, reasoned reopening and successor issuance completed; original HTML/PDF byte-identical")
        print("COMPLETE JOURNEY PASS", flush=True)
    except Exception as exc:
        results.append({"step": "failure", "status": "FAIL", "error": str(exc), "browser_errors": errors})
        (OUT / "journey.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        shot("failure")
        (OUT / "failure.html").write_text(page.content(), encoding="utf-8")
        raise
    finally:
        browser.close()
