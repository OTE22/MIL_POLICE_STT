"""Browser acceptance with synthetic fixtures; never reads or writes real investigations.

Run against `npm run preview -- --host 127.0.0.1 --port 5174` after a frontend build.
"""
import io
import json
import wave
from pathlib import Path

from playwright.sync_api import sync_playwright, expect

BASE = "http://127.0.0.1:5174"
OUT = Path("storage/test-artifacts/voice-review")
STAMP = "2026-09-20T10:00:00Z"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    reviews = []
    confirmations = []
    flagged = False
    prints = [dict(id=f"print-{i}", identity_id="person-1", person_name="شخص تجريبي",
                   notes=None, model="test-model", model_revision="1", provider="test",
                   embedding_dim=16, sample_seconds=8, source_session_id="session-1",
                   source_speaker_label=f"SPEAKER_0{i}", consent_recorded=True,
                   is_active=True, created_at=STAMP, updated_at=STAMP) for i in range(3)]
    speakers = [dict(id=f"speaker-{i}", session_id="session-1", speaker_label=f"SPEAKER_0{i}",
                     recording_id=f"recording-{i}", recording_name=f"تسجيل {i+1}.wav",
                     display_name="شخص تجريبي" if i < 3 else None,
                     identity_name="شخص تجريبي" if i < 3 else None,
                     identity_id="person-1" if i < 2 else "person-2" if i == 2 else None,
                     speaker_role="SUBJECT" if i < 3 else "UNKNOWN", notes=None,
                     segment_count=3, total_seconds=8, updated_at=STAMP,
                     identification_status="CONFIRMED" if i < 3 else "NONE",
                     suggested_name=None, suggested_score=None, has_voice_embedding=True)
                for i in range(5)]
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
        wav.writeframes(b"\0\0" * 16000 * 8)

    def respond(route):
        nonlocal flagged
        path = route.request.url.split("/api", 1)[1].split("?", 1)[0]
        if path == "/auth/me":
            payload = dict(id="tester", username="test", roles=["ADMIN"], is_active=True,
                           must_change_password=False, profile=None,
                           permissions=["voice.identify", "voice.enroll", "transcripts.read", "speakers.assign", "investigations.read_all"])
        elif path == "/voice-enrollments": payload = prints
        elif path.endswith("/biometric-check"):
            rows = [dict(enrollment_id=p["id"], created_at=STAMP, updated_at=p["updated_at"],
                         source_session_id=p["source_session_id"], source_speaker_label=p["source_speaker_label"],
                         model=p["model"], embedding_dim=16, sample_seconds=8, peer_similarity_max=.4,
                         peer_similarity_min=.4, coherent_peer_count=0, component_id=2 if i == 1 else 1,
                         status="ISOLATED", review_status="FLAGGED" if flagged and i == 0 else "NONE")
                    for i, p in enumerate(prints)]
            payload = dict(identity_id="person-1", person_name="شخص تجريبي", total_active_prints=3,
                           number_of_components=2, overall_status="REVIEW_REQUIRED", coherence_threshold=.65,
                           near_duplicate_threshold=.98, groups=[dict(model="test-model", embedding_dim=16,
                           model_revision="1", provider="test", component_count=2, prints=rows,
                           pairs=[dict(first_id="print-0", second_id="print-1", similarity=.4),
                                  dict(first_id="print-0", second_id="print-2", similarity=.84)])],
                           identity_confirmations=confirmations)
        elif path.endswith("/identity-confirmations"):
            data = route.request.post_data_json
            ids = [p["enrollment_id"] for p in data["prints"]]
            assert len(ids) == 2 and len(set(ids)) == 2
            entry = dict(id=f"confirmation-{len(confirmations)}", enrollment_ids=ids, reason=data["reason"],
                         reviewer_name="مراجع تجريبي", created_at=STAMP, status="ACTIVE",
                         reopened_at=None, reopened_reason=None, reopened_by_name=None)
            confirmations.insert(0, entry)
            payload = entry
        elif path.endswith("/reopen"):
            entry = next(c for c in confirmations if c["id"] == path.split("/")[-2])
            entry.update(status="REOPENED", reopened_at=STAMP, reopened_by_name="مراجع تجريبي",
                         reopened_reason=route.request.post_data_json["reason"])
            payload = entry
        elif path.endswith("/reviews"):
            if route.request.method == "POST":
                data = route.request.post_data_json
                assert data["reason"] == "مراجعة تجريبية" and data["action"] == "FLAG"
                flagged = True
                prints[0]["updated_at"] = "2026-09-20T11:00:00Z"
                entry = dict(id="review-1", enrollment_id="print-0", action="FLAG", reason=data["reason"], reviewer_name="مراجع تجريبي", created_at=STAMP)
                reviews.insert(0, entry)
                payload = entry
            else: payload = reviews
        elif path.endswith("/source"):
            payload = dict(recording_id="audio-1", transcript_id="transcript-1", segments=[dict(start_seconds=1, end_seconds=6)])
        elif path.endswith("/audio"):
            route.fulfill(status=200, content_type="audio/wav", body=buffer.getvalue()); return
        elif path == "/investigations/session-1":
            payload = dict(id="session-1", title="جلسة تجريبية", session_number="TEST", status="COMPLETED", has_transcript=True)
        elif path.endswith("/transcript"):
            payload = dict(id="transcript-1", recording_id="audio-1", speakers=speakers, segments=[], audio_available=True)
        else: payload = []
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1050}, locale="ar-LB")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/api/**", respond)
        page.add_init_script("sessionStorage.setItem('mstt.access_token', 'synthetic-test-token')")
        page.goto(BASE + "/voice-enrollments")
        page.get_by_test_id("person-bio-check").click()
        expect(page.get_by_test_id("bio-print-row")).to_have_count(3)
        page.get_by_role("button", name="استماع ومقارنة").first.click()
        expect(page.locator("audio")).to_have_count(2)
        page.wait_for_function("[...document.querySelectorAll('audio')].every(a => a.readyState >= 1)")
        page.get_by_role("button", name="تشغيل المقطع المحدد").first.click()
        page.get_by_role("button", name="تشغيل المقطع المحدد").nth(1).click()
        assert page.locator("audio").first.evaluate("audio => audio.paused")
        page.get_by_role("button", name="إغلاق المقارنة").click()
        page.get_by_role("button", name="وضع علامة للمراجعة").first.click()
        expect(page.get_by_role("button", name="حفظ المراجعة")).to_be_disabled()
        page.locator("textarea").fill("مراجعة تجريبية")
        page.get_by_role("button", name="حفظ المراجعة").click()
        expect(page.get_by_text("تم حفظ الإجراء في سجل المراجعة.")).to_be_visible()
        expect(page.get_by_text("بانتظار المراجعة", exact=True)).to_be_visible()
        expect(page.get_by_text("مراجعة تجريبية", exact=True)).to_be_visible()
        # Confirm two samples within one computed group.
        page.get_by_role("button", name="تحديد المجموعة 1.1", exact=True).click()
        form = page.get_by_test_id("identity-confirmation-form")
        expect(form.locator("li")).to_have_count(2)
        expect(form.get_by_role("button", name="تأكيد أن العينات للشخص نفسه")).to_be_disabled()
        form.locator("textarea").fill("تحققت من عينتين داخل المجموعة")
        form.get_by_role("button", name="تأكيد أن العينات للشخص نفسه").click()
        expect(page.get_by_test_id("identity-confirmation")).to_have_count(1)
        assert set(confirmations[0]["enrollment_ids"]) == {"print-0", "print-2"}
        # Confirm across computed groups; selections do not silently expand.
        page.get_by_role("checkbox", name="تحديد العينة 1", exact=True).check()
        page.get_by_role("checkbox", name="تحديد العينة 2", exact=True).check()
        form.locator("textarea").fill("تحققت من الصوت عبر المجموعتين")
        form.get_by_role("button", name="تأكيد أن العينات للشخص نفسه").click()
        expect(page.get_by_test_id("identity-confirmation")).to_have_count(2)
        assert set(confirmations[0]["enrollment_ids"]) == {"print-0", "print-1"}
        decision = page.get_by_test_id("identity-confirmation").first
        expect(decision.get_by_text("نفس الشخص — مؤكّد يدوياً", exact=True)).to_be_visible()
        decision.get_by_role("button", name="إعادة فتح المراجعة", exact=True).click()
        expect(decision.get_by_role("button", name="تأكيد إعادة الفتح")).to_be_disabled()
        decision.locator("textarea").fill("إعادة تحقق إضافية")
        decision.get_by_role("button", name="تأكيد إعادة الفتح").click()
        expect(decision.get_by_text("أُعيد فتح المراجعة", exact=True)).to_be_visible()
        page.screenshot(path=str(OUT / "review-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUT / "review-mobile.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 1050})
        page.goto(BASE + "/investigations/session-1?tab=speakers")
        expect(page.get_by_test_id("speaker-person-group")).to_have_count(4)
        first_group = page.get_by_test_id("speaker-person-group").first
        expect(first_group.locator("details").first).not_to_have_attribute("open", "")
        first_group.locator("summary").first.click()
        expect(first_group.get_by_test_id("speaker-card")).to_have_count(2)
        expect(first_group.get_by_text("تسجيل 1.wav", exact=False)).to_be_visible()
        assert not first_group.get_by_text("SPEAKER_00", exact=True).is_visible()
        page.screenshot(path=str(OUT / "speakers-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(OUT / "speakers-mobile.png"), full_page=True)
        assert not errors, errors
        browser.close()
    print("PASS: review/save/history, A/B audio, person grouping, source details and mobile overflow; no browser errors.")


if __name__ == "__main__":
    main()
