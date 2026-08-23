"""Real full end-to-end browser test (spec §81) driven with Playwright (Chromium).

Workflow exercised:
  admin login → create investigator → investigator login → Local AI Agent detected →
  models READY → create investigation → upload a multi-speaker Arabic recording →
  local processing (VAD → NVIDIA diarization → Cohere STT) → synchronization →
  transcript displayed → speakers mapped → click segment seeks audio → edit one segment
  (original intact) → audit log contains the change.

Usage:
  python scripts/e2e_browser.py --audio path/to/two_speakers_ar.wav [--central http://localhost:8080]
                                [--admin-password ...] [--headed] [--screenshots DIR]
Exit code 0 only if every step above succeeded. The script never fakes an AI result:
if the agent reports a model as not ready it stops and reports exactly where.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

REPORT: list[tuple[str, str]] = []


def step(name: str, ok: bool, detail: str = "") -> None:
    REPORT.append((name, ("PASS" if ok else "FAIL") + (f" - {detail}" if detail else "")))
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")
    if not ok:
        raise SystemExit(2)


def shot(page: Page, directory: Path | None, name: str) -> None:
    if directory:
        directory.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(directory / f"{name}.png"), full_page=True)


def api(base: str, path: str, token: str | None = None, method: str = "GET", body: dict | None = None) -> tuple[int, dict | list | None]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        return e.code, json.loads(e.read() or b"null")


def login(page: Page, base: str, username: str, password: str) -> None:
    page.goto(f"{base}/login")
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("button[type=submit]")
    page.wait_for_url(lambda u: "/login" not in u, timeout=20000)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--central", default="http://localhost:8080")
    ap.add_argument("--agent", default="http://127.0.0.1:17117")
    ap.add_argument("--audio", required=True)
    ap.add_argument("--admin-user", default="admin")
    ap.add_argument("--admin-password", required=True)
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--screenshots", default=None)
    ap.add_argument("--timeout-minutes", type=float, default=60)
    args = ap.parse_args()
    base = args.central.rstrip("/")
    shots = Path(args.screenshots) if args.screenshots else None
    audio = Path(args.audio)
    assert audio.exists(), audio
    stamp = int(time.time())
    inv_user, inv_pw = f"inv{stamp % 100000}", "Investigator!2026"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        ctx = browser.new_context(viewport={"width": 1400, "height": 900}, locale="ar")
        page = ctx.new_page()
        console_errors: list[str] = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)

        # 1. Admin login
        login(page, base, args.admin_user, args.admin_password)
        if "/change-password" in page.url:
            new_pw = args.admin_password + "x"
            page.fill("input[autocomplete=current-password]", args.admin_password)
            page.fill("input[autocomplete=new-password] >> nth=0", new_pw)
            page.fill("input[autocomplete=new-password] >> nth=1", new_pw)
            page.click("button[type=submit]")
            page.wait_for_url(lambda u: "/change-password" not in u)
            args.admin_password = new_pw
        expect(page.locator("text=لوحة التحكم").first).to_be_visible()
        step("admin login", True)
        shot(page, shots, "01-dashboard-admin")

        # 2. Create investigator through the users page
        page.goto(f"{base}/users")
        page.click("text=إضافة مستخدم")
        page.fill("input[dir=ltr][pattern]", inv_user)
        page.fill("input[type=password][autocomplete=new-password]", inv_pw)
        # roles: untick INVESTIGATOR default is ticked already; ensure only INVESTIGATOR
        page.uncheck("label:has-text('مدير النظام') input") if page.is_checked("label:has-text('مدير النظام') input") else None
        page.check("label:has-text('محقق') input")
        page.uncheck("label:has-text('يجب تغيير كلمة المرور') input")
        modal = page.locator(".modal")
        modal.locator("input.input").nth(2).fill("الرائد علي حسن")  # full name (after username/password)
        labels = modal.locator(".field")
        for i in range(labels.count()):
            lab = labels.nth(i).locator("label").inner_text()
            if lab.startswith("الرتبة"):
                labels.nth(i).locator("input").fill("رائد")
            if lab.startswith("الرقم العسكري"):
                labels.nth(i).locator("input").fill(f"M-{stamp % 100000}")
        modal.locator("button[type=submit]").click()
        expect(page.locator(f"text={inv_user}")).to_be_visible(timeout=10000)
        step("create investigator", True, inv_user)
        shot(page, shots, "02-users")
        page.click("button[title='تسجيل الخروج']")
        page.wait_for_url(lambda u: "/login" in u)

        # 3. Investigator login
        login(page, base, inv_user, inv_pw)
        expect(page.locator("text=لوحة التحكم").first).to_be_visible()
        step("investigator login", True)

        # 4. Local AI Agent detected + models READY (checked through the agent API and the UI)
        caps = json.loads(urllib.request.urlopen(f"{args.agent}/capabilities", timeout=10).read())
        step("local agent detected", True, f"{caps['agent_id']} v{caps['agent_version']} device={caps['processing_device']}")
        if caps["diarization"]["state"] != "READY" or caps["stt"]["state"] != "READY":
            urllib.request.urlopen(urllib.request.Request(f"{args.agent}/models/load", method="POST"), timeout=10).read()
            deadline = time.time() + 20 * 60
            while time.time() < deadline:
                caps = json.loads(urllib.request.urlopen(f"{args.agent}/capabilities", timeout=10).read())
                if caps["diarization"]["state"] in ("READY", "ERROR", "NOT_PROVISIONED") and caps["stt"]["state"] in ("READY", "ERROR", "NOT_PROVISIONED"):
                    break
                time.sleep(5)
        step("NVIDIA diarization model READY", caps["diarization"]["state"] == "READY", f"{caps['diarization']['model']} ({caps['diarization']['state']}) {caps['diarization'].get('error') or ''}")
        step("Cohere Arabic model READY", caps["stt"]["state"] == "READY", f"{caps['stt']['model']} ({caps['stt']['state']}) {caps['stt'].get('error') or ''}")

        # 5. Create investigation via the form
        page.goto(f"{base}/investigations/new")
        page.fill("input.input >> nth=0", f"جلسة تحقيق تجريبية {stamp}")
        page.locator(".field", has_text="اسم الشخص").locator("input").fill("أحمد محمد")
        page.locator(".field", has_text="الموقع").first.locator("input").fill("بيروت")
        page.click("button[type=submit]")
        page.wait_for_url(lambda u: "/investigations/" in u and "/new" not in u, timeout=20000)
        session_id = page.url.rstrip("/").split("/")[-1].split("?")[0]
        expect(page.locator("text=مسودة").first).to_be_visible()
        step("create investigation", True, session_id)
        shot(page, shots, "03-session-details")

        # 6. Recording tab: status panel + upload file + process
        page.click("role=tab[name='التسجيل']")
        expect(page.locator("text=حالة المعالجة المحلية")).to_be_visible()
        expect(page.locator(".status-row", has_text="حالة الخدمة")).to_contain_text("جاهز", timeout=30000)
        page.set_input_files("input[type=file]", str(audio))
        expect(page.locator(".file-chip")).to_be_visible()
        shot(page, shots, "04-recording-ready")
        page.click("text=معالجة التسجيل")
        step("recording submitted to local agent", True, audio.name)

        # 7. Wait for processing (UI shows the Arabic state labels) and sync
        deadline = time.time() + args.timeout_minutes * 60
        final = None
        seen_states: set[str] = set()
        while time.time() < deadline:
            jobs = json.loads(urllib.request.urlopen(f"{args.agent}/jobs", timeout=10).read())
            mine = [j for j in jobs if j["session_id"] == session_id]
            if mine:
                j = mine[0]
                seen_states.add(j["state"])
                if j["state"] in ("FAILED", "CANCELLED") or (j["state"] == "COMPLETED" and j["sync_state"] in ("SYNCED", "SYNC_FAILED")):
                    final = j
                    break
            time.sleep(3)
        step("local processing finished", final is not None and final["state"] == "COMPLETED", f"states={sorted(seen_states)} final={(final or {}).get('state')} err={(final or {}).get('error_code')} {(final or {}).get('error_message') or ''}")
        step("result synchronized with central", final["sync_state"] == "SYNCED", final.get("last_sync_error") or "")
        shot(page, shots, "05-processing-done")

        # 8. Transcript displayed (via API first, then the UI)
        status, tok = api(base, "/api/auth/login", method="POST", body={"username": inv_user, "password": inv_pw})
        token = tok["access_token"]
        status, tr = api(base, f"/api/investigations/{session_id}/transcript", token)
        step("transcript stored in PostgreSQL", status == 200 and len(tr["segments"]) > 0, f"{len(tr['segments'])} segments, {tr['speaker_count']} speakers, stt={tr['stt_model']}@{(tr['stt_model_revision'] or '')[:10]}, diar={tr['diarization_model']}@{(tr['diarization_model_revision'] or '')[:10]}")
        sequence = []
        for s in tr["segments"]:
            if not sequence or sequence[-1] != s["speaker_label"]:
                sequence.append(s["speaker_label"])
        arabic = any(any("؀" <= ch <= "ۿ" for ch in s["original_text"]) for s in tr["segments"])
        step("Arabic transcription generated", arabic, " | ".join(s["original_text"][:40] for s in tr["segments"][:3]))
        step("speaker sequence A→B→A", sequence[:3] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"], " -> ".join(sequence))

        page.reload()
        page.click("role=tab[name='النص المفرغ']")
        expect(page.locator("[data-testid=segment]").first).to_be_visible(timeout=20000)
        expect(page.locator("[data-testid=audio-player]")).to_be_visible(timeout=30000)
        shot(page, shots, "06-transcript")
        step("Arabic transcript displayed", page.locator("[data-testid=segment]").count() == len(tr["segments"]))

        # 9. Map speakers
        page.click("role=tab[name='المتحدثون']")
        cards = page.locator("[data-testid=speaker-card]")
        expect(cards.first).to_be_visible()
        c0 = page.locator("[data-testid=speaker-card][data-label=SPEAKER_00]")
        c0.locator("input.input").first.fill("المحقق")
        c0.locator("select").select_option("INVESTIGATOR")
        c0.locator("button", has_text="تعيين الاسم").click()
        expect(page.locator(".toast", has_text="تم حفظ بيانات المتحدث")).to_be_visible()
        c1 = page.locator("[data-testid=speaker-card][data-label=SPEAKER_01]")
        c1.locator("input.input").first.fill("الشخص الذي تتم مقابلته")
        c1.locator("select").select_option("SUBJECT")
        c1.locator("button", has_text="تعيين الاسم").click()
        expect(page.locator(".toast", has_text="تم حفظ بيانات المتحدث").last).to_be_visible()
        shot(page, shots, "07-speakers")
        _, speakers = api(base, f"/api/investigations/{session_id}/speakers", token)
        names = {s["speaker_label"]: s["display_name"] for s in speakers}
        step("speakers mapped", names.get("SPEAKER_00") == "المحقق" and names.get("SPEAKER_01") == "الشخص الذي تتم مقابلته", str(names))

        # 10. Click a segment -> audio seeks
        page.click("role=tab[name='النص المفرغ']")
        expect(page.locator("[data-testid=audio-player]")).to_be_visible(timeout=30000)
        second = page.locator("[data-testid=segment]").nth(1)
        expected_start = tr["segments"][1]["start_seconds"]
        second.click()
        time.sleep(1.0)
        current = page.evaluate("document.querySelector('[data-testid=audio-player]').currentTime")
        step("click segment seeks audio", abs(current - expected_start) < 1.5, f"currentTime={current:.2f} expected≈{expected_start:.2f}")
        expect(page.locator("[data-testid=segment]").first).to_contain_text("المحقق")

        # 11. Edit one segment, original intact
        first = page.locator("[data-testid=segment]").first
        first.hover()
        first.locator("[data-testid=edit-segment]").click()
        original_text = tr["segments"][0]["original_text"]
        first.locator("textarea").fill(original_text + " (تصحيح)")
        first.locator("button", has_text="حفظ التصحيح").click()
        expect(page.locator(".toast", has_text="تم حفظ التصحيح")).to_be_visible()
        _, tr2 = api(base, f"/api/investigations/{session_id}/transcript", token)
        seg0 = tr2["segments"][0]
        step("segment edited, original text intact", seg0["original_text"] == original_text and seg0["edited_text"] == original_text + " (تصحيح)", f"edited_by={seg0['edited_by_name']}")
        shot(page, shots, "08-edited")

        # 12. Audit log
        page.click("role=tab[name='سجل النشاط']")
        expect(page.locator("[data-testid=activity]")).to_contain_text("تصحيح مقطع في النص")
        expect(page.locator("[data-testid=activity]")).to_contain_text("تعيين اسم متحدث")
        _, activity = api(base, f"/api/investigations/{session_id}/activity", token)
        actions = {e["action"] for e in activity["items"]}
        needed = {"INVESTIGATION_CREATED", "LOCAL_PROCESSING_REQUESTED", "LOCAL_PROCESSING_STARTED", "DIARIZATION_STARTED", "TRANSCRIPTION_STARTED", "LOCAL_PROCESSING_COMPLETED", "TRANSCRIPT_RECEIVED", "RECORDING_UPLOADED", "SPEAKER_RENAMED", "TRANSCRIPT_SEGMENT_EDITED"}
        step("audit trail complete", needed <= actions, f"missing={sorted(needed - actions)}")
        shot(page, shots, "09-activity")
        step("no browser console errors", not [e for e in console_errors if "favicon" not in e], "; ".join(console_errors[:3]))
        browser.close()

    print("\nE2E RESULT: ALL STEPS PASSED")
    for name, res in REPORT:
        print(f"  {res:60s} {name}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit as e:
        if e.code not in (0, None):
            print("\nE2E RESULT: FAILED")
            for name, res in REPORT:
                print(f"  {res:60s} {name}")
        raise
