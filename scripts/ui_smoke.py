"""Browser smoke test of every Arabic page + the transcript UI interactions.

This test does NOT run the AI models: it injects a transcript through the same central
API the Local Agent uses (/api/local-processing/{job}/result + /audio) and then verifies the
user interface: dashboard, sessions list/filters, new session form, details tabs, recording
tab + agent status panel, transcript viewer (playback, seek on click, search, speaker
filter, inline edit with original preserved), speaker mapping, activity log, users page,
workstations page, audit page, logout.

  python scripts/ui_smoke.py --admin-password ... [--central http://localhost:8080] [--screenshots DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import struct
import sys
import time
import urllib.request
import wave
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


def api(base: str, path: str, token: str | None = None, method: str = "GET", body: dict | None = None, raw: bytes | None = None, content_type: str | None = None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", content_type or "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        return e.code, json.loads(e.read() or b"null")


def wav_bytes(seconds: float = 22.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        frames = bytearray()
        for i in range(int(16000 * seconds)):
            f = 220 if (i // 16000) % 2 == 0 else 330
            frames += struct.pack("<h", int(6000 * math.sin(2 * math.pi * f * i / 16000)))
        wf.writeframes(bytes(frames))
    return buf.getvalue()


def multipart(field: str, filename: str, content: bytes, mime: str) -> tuple[bytes, str]:
    boundary = "----mstt" + hashlib.md5(content[:64]).hexdigest()
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{filename}\"\r\nContent-Type: {mime}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def login(page: Page, base: str, username: str, password: str) -> None:
    page.goto(f"{base}/login")
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("button[type=submit]")
    page.wait_for_url(lambda u: "/login" not in u, timeout=20000)


def shot(page: Page, d: Path | None, name: str) -> None:
    if d:
        d.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(d / f"{name}.png"), full_page=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--central", default="http://localhost:8080")
    ap.add_argument("--admin-user", default="admin")
    ap.add_argument("--admin-password", required=True)
    ap.add_argument("--screenshots", default=None)
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    base = args.central.rstrip("/")
    shots = Path(args.screenshots) if args.screenshots else None
    stamp = int(time.time()) % 1000000

    # ---- seed data through the API (admin) ----
    st, tok = api(base, "/api/auth/login", method="POST", body={"username": args.admin_user, "password": args.admin_password})
    assert st == 200, tok
    admin = tok["access_token"]
    inv_user, inv_pw = f"uinv{stamp}", "Investigator!2026"
    st, u = api(base, "/api/users", admin, "POST", {"username": inv_user, "password": inv_pw, "roles": ["INVESTIGATOR"], "must_change_password": False, "profile": {"full_name": "النقيب سامر خليل", "rank": "نقيب", "military_id": f"U-{stamp}"}})
    assert st == 201, u
    st, tok = api(base, "/api/auth/login", method="POST", body={"username": inv_user, "password": inv_pw})
    inv = tok["access_token"]
    st, s = api(base, "/api/investigations", inv, "POST", {"title": f"جلسة واجهة {stamp}", "location": "صيدا", "session_date": "2026-08-23", "subjects": [{"subject_name": "أحمد محمد"}]})
    assert st == 201, s
    audio = wav_bytes()
    st, t = api(base, f"/api/investigations/{s['id']}/local-processing-token", inv, "POST", {"original_filename": "interview.wav", "mime_type": "audio/wav", "size_bytes": len(audio), "source": "FILE_UPLOAD"})
    assert st == 200, t
    ptoken = t["processing_token"]
    for state in ("CREATED", "RECEIVING_AUDIO", "PREPROCESSING", "DIARIZING", "TRANSCRIBING", "FINALIZING"):
        api(base, f"/api/local-processing/{t['job_id']}/state", ptoken, "POST", {"state": state, "progress": 0.5, "workstation": {"agent_id": f"agent-ui-{stamp}", "device_name": "UI-DESKTOP", "agent_version": "1.0.0", "processing_device": "cpu", "stt_ready": True, "diarization_ready": True}})
    result = {
        "idempotency_key": f"ui-smoke-{stamp}-0123456789",
        "language": "ar", "stt_provider": "cohere_local", "stt_model": "CohereLabs/cohere-transcribe-arabic-07-2026", "stt_model_revision": "c3e911b42149bf7a1e53d5cef9878aee87515a23",
        "diarization_provider": "nvidia_sortformer", "diarization_model": "nvidia/diar_streaming_sortformer_4spk-v2.1", "diarization_model_revision": "fafaab5faa1617a0ca52d38dd3dc4bd636800d3d",
        "vad_model": "snakers4/silero-vad", "agent_version": "1.0.0", "processing_device": "cpu", "speaker_count": 2, "warnings": ["Processed on CPU."],
        "processing_metadata": {"note": "ui smoke (API-injected result, not a model run)"},
        "audio": {"duration_seconds": 22.0, "sha256": hashlib.sha256(audio).hexdigest(), "size_bytes": len(audio)},
        "segments": [
            {"speaker_label": "SPEAKER_00", "start_seconds": 2.0, "end_seconds": 8.0, "text": "أين كنت مساء أمس؟", "is_overlap": False},
            {"speaker_label": "SPEAKER_01", "start_seconds": 9.0, "end_seconds": 16.0, "text": "كنت في المنزل.", "is_overlap": False},
            {"speaker_label": "SPEAKER_00", "start_seconds": 16.5, "end_seconds": 21.0, "text": "هل كان معك أحد؟", "is_overlap": True},
        ],
    }
    st, r = api(base, f"/api/local-processing/{t['job_id']}/result", ptoken, "POST", result)
    assert st == 200, r
    body, ctype = multipart("file", "interview.wav", audio, "audio/wav")
    st, up = api(base, f"/api/local-processing/{t['job_id']}/audio", ptoken, "POST", raw=body, content_type=ctype)
    assert st == 201, up
    print("seeded session", s["session_number"])

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        ctx = browser.new_context(viewport={"width": 1400, "height": 900}, locale="ar")
        page = ctx.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        # Login page + RTL
        page.goto(f"{base}/login")
        check("html lang=ar dir=rtl", page.evaluate("document.documentElement.lang") == "ar" and page.evaluate("document.documentElement.dir") == "rtl")
        page.fill("#username", inv_user)
        page.fill("#password", "wrong")
        page.click("button[type=submit]")
        expect(page.locator(".alert-danger")).to_contain_text("اسم المستخدم أو كلمة المرور غير صحيحة")
        check("invalid login shows Arabic error", True)
        login(page, base, inv_user, inv_pw)

        # Dashboard
        expect(page.locator("h1", has_text="لوحة التحكم")).to_be_visible()
        for label in ("إجمالي الجلسات", "جلسات اليوم", "قيد المعالجة", "الجلسات المكتملة", "آخر الجلسات"):
            expect(page.locator(f"text={label}").first).to_be_visible()
        check("dashboard cards + recent table", page.locator("table.table tbody tr").count() >= 1)
        shot(page, shots, "ui-01-dashboard")

        # Sessions list + filters
        page.click("nav >> text=الجلسات")
        expect(page.locator("h1", has_text="الجلسات")).to_be_visible()
        page.fill("input.search", f"{stamp}")
        expect(page.locator("table.table tbody tr")).to_have_count(1, timeout=10000)
        page.select_option("select.select >> nth=0", "COMPLETED")
        expect(page.locator("table.table tbody tr")).to_have_count(1, timeout=10000)
        page.select_option("select.select >> nth=0", "DRAFT")
        expect(page.locator("td.empty")).to_be_visible(timeout=10000)
        check("sessions list search + status filter", True)
        shot(page, shots, "ui-02-sessions")

        # New session form renders all sections
        page.click("nav >> text=إنشاء جلسة جديدة")
        for sec in ("معلومات الجلسة", "المحققون", "بيانات الشخص", "الموقع والتوقيت", "ملاحظات"):
            expect(page.locator(".section-title", has_text=sec)).to_be_visible()
        page.fill("input.input >> nth=0", f"جلسة من النموذج {stamp}")
        page.click("button[type=submit]")
        page.wait_for_url(lambda u: "/investigations/" in u and "/new" not in u)
        expect(page.locator(".badge", has_text="مسودة").first).to_be_visible(timeout=15000)
        check("new session form creates a session", True)
        shot(page, shots, "ui-03-new-session")

        # Details page of the seeded session
        page.goto(f"{base}/investigations/{s['id']}")
        for tab in ("التفاصيل", "التسجيل", "النص المفرغ", "المتحدثون", "سجل النشاط"):
            expect(page.locator(f"role=tab[name='{tab}']")).to_be_visible()
        expect(page.locator("dd.mono", has_text=s["session_number"])).to_be_visible()
        check("details tab", page.locator("text=أحمد محمد").count() >= 1 and page.locator("text=مكتملة").count() >= 1)
        shot(page, shots, "ui-04-details")

        # Recording tab (agent panel renders; agent may or may not be running)
        page.click("role=tab[name='التسجيل']")
        for label in ("بدء التسجيل", "رفع ملف صوتي", "حالة الميكروفون", "حالة التسجيل", "حالة المعالجة المحلية", "حالة الخدمة", "حالة نموذج تحويل الصوت إلى نص", "حالة نموذج فصل المتحدثين", "الجهاز المستخدم", "إصدار الخدمة"):
            expect(page.locator(f"text={label}").first).to_be_visible()
        check("recording tab + local AI status panel", True)
        shot(page, shots, "ui-05-recording")

        # Transcript tab
        page.click("role=tab[name='النص المفرغ']")
        segs = page.locator("[data-testid=segment]")
        expect(segs).to_have_count(3, timeout=15000)
        expect(page.locator("[data-testid=audio-player]")).to_be_visible(timeout=30000)
        expect(segs.nth(2)).to_contain_text("تداخل في الكلام")
        check("transcript segments + overlap badge + audio player", True)
        page.fill("input[aria-label='بحث في النص']", "المنزل")
        expect(segs).to_have_count(1)
        expect(page.locator("mark")).to_contain_text("المنزل")
        page.fill("input[aria-label='بحث في النص']", "")
        page.select_option("select[aria-label='تصفية حسب المتحدث']", "SPEAKER_01")
        expect(segs).to_have_count(1)
        page.select_option("select[aria-label='تصفية حسب المتحدث']", "")
        expect(segs).to_have_count(3)
        check("transcript search + speaker filter", True)
        segs.nth(1).click()
        time.sleep(1.0)
        cur = page.evaluate("document.querySelector('[data-testid=audio-player]').currentTime")
        check("click segment seeks audio", abs(cur - 9.0) < 1.5, f"currentTime={cur:.2f}")
        first = segs.nth(0)
        first.hover()
        first.locator("[data-testid=edit-segment]").click()
        first.locator("textarea").fill("أين كنت مساء أمس يا أحمد؟")
        first.locator("button", has_text="حفظ التصحيح").click()
        expect(page.locator(".toast", has_text="تم حفظ التصحيح")).to_be_visible()
        expect(first).to_contain_text("معدّل")
        expect(first.locator(".orig-box")).to_contain_text("أين كنت مساء أمس؟")
        _, tr = api(base, f"/api/investigations/{s['id']}/transcript", inv)
        check("inline edit keeps original_text", tr["segments"][0]["original_text"] == "أين كنت مساء أمس؟" and tr["segments"][0]["edited_text"] == "أين كنت مساء أمس يا أحمد؟")
        shot(page, shots, "ui-06-transcript")

        # Speakers tab
        page.click("role=tab[name='المتحدثون']")
        c0 = page.locator("[data-testid=speaker-card][data-label=SPEAKER_00]")
        c0.locator("input.input").first.fill("المحقق")
        c0.locator("select").select_option("INVESTIGATOR")
        c0.locator("button", has_text="تعيين الاسم").click()
        expect(page.locator(".toast", has_text="تم حفظ بيانات المتحدث")).to_be_visible()
        c1 = page.locator("[data-testid=speaker-card][data-label=SPEAKER_01]")
        c1.locator("input.input").first.fill("أحمد محمد")
        c1.locator("select").select_option("SUBJECT")
        c1.locator("button", has_text="تعيين الاسم").click()
        time.sleep(0.5)
        page.click("role=tab[name='النص المفرغ']")
        expect(page.locator("[data-testid=segment]").first).to_contain_text("المحقق")
        expect(page.locator("[data-testid=segment]").nth(1)).to_contain_text("أحمد محمد")
        check("speaker mapping reflected in transcript", True)
        shot(page, shots, "ui-07-speakers")

        # Activity tab
        page.click("role=tab[name='سجل النشاط']")
        act = page.locator("[data-testid=activity]")
        for label in ("إنشاء جلسة", "طلب معالجة محلية", "بدء فصل المتحدثين", "استلام النص المفرغ", "تصحيح مقطع في النص", "تعيين اسم متحدث", "رفع التسجيل الأصلي"):
            expect(act).to_contain_text(label)
        check("activity log (Arabic audit labels)", True)
        shot(page, shots, "ui-08-activity")

        # Investigator cannot see admin pages
        page.goto(f"{base}/users")
        page.wait_for_url(lambda u: u.rstrip("/").endswith(":8080") or u.rstrip("/").endswith("/"))
        check("investigator redirected away from admin page", "/users" not in page.url)
        page.click("button[title='تسجيل الخروج']")
        page.wait_for_url(lambda u: "/login" in u)
        check("logout", True)

        # Admin pages
        login(page, base, args.admin_user, args.admin_password)
        page.click("nav >> text=إدارة المستخدمين")
        expect(page.locator("h1", has_text="إدارة المستخدمين")).to_be_visible()
        for col in ("الاسم", "اسم المستخدم", "الدور", "الرتبة", "الرقم العسكري", "الحالة", "آخر تسجيل دخول", "الإجراءات"):
            expect(page.locator("th", has_text=col).first).to_be_visible()
        page.click("text=إضافة مستخدم")
        expect(page.locator(".modal")).to_be_visible()
        page.locator(".modal button", has_text="إلغاء").click()
        row = page.locator("tr", has_text=inv_user)
        row.locator("button", has_text="تعطيل").click()
        expect(row).to_contain_text("معطّل", timeout=10000)
        row.locator("button", has_text="تفعيل").click()
        expect(row).to_contain_text("نشط", timeout=10000)
        check("users page: columns, add modal, disable/enable", True)
        shot(page, shots, "ui-09-users")
        page.click("nav >> text=حالة محطات العمل")
        expect(page.locator("td", has_text=f"agent-ui-{stamp}")).to_be_visible()
        check("workstations page lists the registered agent", True)
        shot(page, shots, "ui-10-workstations")
        page.click("nav >> text=سجل التدقيق")
        expect(page.locator("h1", has_text="سجل التدقيق")).to_be_visible()
        page.select_option("select.select >> nth=0", "SPEAKER_RENAMED")
        expect(page.locator("table.table tbody tr").first).to_contain_text("تعيين اسم متحدث")
        check("audit page + action filter", True)
        shot(page, shots, "ui-11-audit")
        # The deliberate wrong-password login produces one expected 401 resource error.
        real_errors = [e for e in errors if "favicon" not in e and "127.0.0.1:17117" not in e and "net::ERR" not in e and "401" not in e]
        check("no console/page errors (agent probe errors excluded)", not real_errors, "; ".join(real_errors[:3]))
        browser.close()

    failed = [r for r in RESULTS if not r[1]]
    print(f"\nUI SMOKE: {len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
