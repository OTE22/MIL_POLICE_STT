"""End-to-end: an unknown speaker becomes a canonical person with several voice prints.

The lifecycle this proves, in the browser:

    audio -> diarization -> SPEAKER_01 -> no voice match -> غير معروف
          -> تحديد الهوية (the SAME SubjectFields form as إضافة شخص)
          -> person recorded on the session, speaker linked
          -> appears under بانتظار التسجيل
          -> تسجيل بصمة via the existing enrolment endpoint
          -> moves to الأشخاص المسجّلون
          -> a second session suggests the SAME identity, second print
          -> one person row reading ٢ بصمات
"""
import hashlib
import io
import json
import math
import struct
import sys
import time
import urllib.error
import urllib.request
import wave

from playwright.sync_api import expect, sync_playwright

BASE, UI = "http://localhost:8080/api", "http://localhost:8080"
ADMIN_PW = sys.argv[1]
SHOTS = sys.argv[2]
R = []


def check(n, ok, d=""):
    R.append((n, ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {n} {d}")


def call(m, p, b=None, token=None):
    d = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request(BASE + p, data=d, method=m)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=60) as x:
            return x.status, (json.loads(x.read() or b"null") if x.status != 204 else None)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def wav(sec=52.0):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * 220 * i / 16000)))
                               for i in range(int(16000 * sec))))
    return buf.getvalue()


stamp = int(time.time()) % 1000000
# الرقم المرجعي is NOT chosen here. A civilian is issued CIV-* by the backend on save, so the
# value is read back after the person is created - which is the whole point: nobody types it.
REFERENCE = None
PERSON = "أحمد محمد"

def investigator_token(prefix, full_name):
    """Log in as the investigator these checks run as.

    The first argument is either an ADMIN password - a throwaway investigator is then created
    for this run - or `username:password` for an investigator that already exists. Nothing here
    needs administrator rights except creating that user, so an existing account is enough and
    avoids handing the E2E an admin credential it does not use.
    """
    if ":" in ADMIN_PW:
        username, _, password = ADMIN_PW.partition(":")
        status, body = call("POST", "/auth/login", {"username": username, "password": password})
        assert status == 200, f"investigator login failed ({status}): {body}"
        return body["access_token"], username, password

    status, body = call("POST", "/auth/login", {"username": "admin", "password": ADMIN_PW})
    assert status == 200, f"admin login failed ({status}). Pass user:password to run as an existing investigator."
    admin_token = body["access_token"]
    username = f"{prefix}{stamp}"
    call("POST", "/users", {"username": username, "password": "Investigator!2026",
                            "roles": ["INVESTIGATOR"], "must_change_password": False,
                            "profile": {"full_name": full_name}}, admin_token)
    token = call("POST", "/auth/login", {"username": username, "password": "Investigator!2026"})[1]["access_token"]
    return token, username, "Investigator!2026"


inv, UI_USER, UI_PASSWORD = investigator_token("vid", "النقيب سامر خليل")

DIM = 256
# Orthogonal per run, so prints left by other runs score 0.0 against these voices and the
# assertions do not depend on the state of the registry.
_i = (stamp * 2) % (DIM - 2)
VOICE_A = [1.0 if k == _i else 0.0 for k in range(DIM)]
VOICE_B = [1.0 if k == _i + 1 else 0.0 for k in range(DIM)]

SAVED = ".toast:has-text('تم حفظ بيانات المتحدث')"
ENROLLED = ".toast:has-text('تم تسجيل بصمة الصوت')"
IDENTIFIED = ".toast:has-text('تم تحديد هوية المتحدث')"


def submit(title, a_vec, b_vec):
    s = call("POST", "/investigations", {"title": title}, inv)[1]
    audio = wav()
    tk = call("POST", f"/investigations/{s['id']}/local-processing-token",
              {"original_filename": "i.wav", "mime_type": "audio/wav",
               "size_bytes": len(audio), "source": "FILE_UPLOAD"}, inv)[1]
    res = {"idempotency_key": f"vid-{stamp}-{title[-6:]}-0123456789", "language": "ar",
           "stt_provider": "cohere_local", "stt_model": "CohereLabs/cohere-transcribe-arabic-07-2026",
           "diarization_provider": "nvidia_sortformer",
           "diarization_model": "nvidia/diar_streaming_sortformer_4spk-v2.1",
           "agent_version": "1.0.0", "processing_device": "cpu", "speaker_count": 2,
           "warnings": [], "processing_metadata": {},
           "audio": {"duration_seconds": 52.0, "sha256": hashlib.sha256(audio).hexdigest(),
                     "size_bytes": len(audio)},
           "voice_identification": {
               "provider": "nemo_speakernet", "model": "nvidia/speakerverification_speakernet",
               "model_revision": "1.16.0", "embedding_dim": DIM, "device": "cpu",
               "speakers": {"SPEAKER_00": {"embedding": a_vec, "seconds": 8.0},
                            "SPEAKER_01": {"embedding": b_vec, "seconds": 9.0}}},
           "segments": [
               {"speaker_label": "SPEAKER_00", "start_seconds": 1.1, "end_seconds": 9.4,
                "text": "أين كنت مساء أمس؟", "is_overlap": False},
               {"speaker_label": "SPEAKER_01", "start_seconds": 11.4, "end_seconds": 22.0,
                "text": "كنت في المنزل.", "is_overlap": False}]}
    st, _ = call("POST", f"/local-processing/{tk['job_id']}/result", res, tk["processing_token"])
    assert st == 200, f"submit {st}"
    return s


def speakers(session_id):
    _, rows = call("GET", f"/investigations/{session_id}/speakers", token=inv)
    return {r["speaker_label"]: r for r in rows}


first = submit(f"جلسة أولى {stamp}", VOICE_A, VOICE_B)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1500, "height": 1100})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(f"{UI}/login")
    pg.fill("#username", UI_USER)
    pg.fill("#password", UI_PASSWORD)
    pg.click("button[type=submit]")
    pg.wait_for_url(lambda x: "/login" not in x)

    # ---- 1. no match -> the speaker stays unknown --------------------------
    sp = speakers(first["id"])
    check("unmatched speaker stays NONE (no person invented)",
          sp["SPEAKER_01"]["identification_status"] == "NONE"
          and sp["SPEAKER_01"]["display_name"] is None,
          sp["SPEAKER_01"]["identification_status"])
    check("no identity attached before a human decides", sp["SPEAKER_01"]["identity_id"] is None)

    pg.goto(f"{UI}/investigations/{first['id']}?tab=speakers")
    pg.wait_for_selector("[data-testid=speaker-card]", timeout=20000)
    card = pg.locator("[data-testid=speaker-card][data-label=SPEAKER_01]")
    check("تحديد الهوية offered for the unknown speaker",
          card.locator("[data-testid=speaker-person-picker]").count() == 1)

    # ---- 2. identify as a NEW person, using the existing subject form -------
    card.locator("[data-testid=speaker-person-picker]").click()
    pg.locator("[data-testid=pick-add-new]").click()
    modal = pg.locator(".modal")
    expect(modal).to_be_visible()
    modal.locator("[data-testid=identify-new]").click()
    # The SAME SubjectFields form as إضافة شخص: proven by its own fields being present.
    check("the existing person form is reused (نوع الشخص present)",
          modal.locator("text=نوع الشخص").count() >= 1)
    modal.locator("label:text-is('اسم الشخص') >> xpath=following::input[1]").fill(PERSON)
    # الرقم المرجعي is read-only: a civilian is issued CIV-* on save. Confirm the form says so
    # rather than offering somewhere to type one.
    check("الرقم المرجعي is not typed for a new civilian",
          modal.locator("[data-testid=reference-pending]").count() == 1)
    pg.screenshot(path=f"{SHOTS}/identity-01-form.png", full_page=True)
    modal.locator("[data-testid=identify-submit]").click()
    pg.wait_for_selector(IDENTIFIED, timeout=20000)

    sp = speakers(first["id"])
    # Whatever the backend issued is the reference from here on.
    REFERENCE = sp["SPEAKER_01"]["reference_number"]
    check("the new civilian was issued a reference", (REFERENCE or "").startswith("CIV-"), REFERENCE or "")
    check("speaker linked to a canonical identity", bool(sp["SPEAKER_01"]["identity_id"]))
    check("display name recorded", sp["SPEAKER_01"]["display_name"] == PERSON)
    check("embedding preserved by identification", sp["SPEAKER_01"]["has_voice_embedding"] is True)
    identity_id = sp["SPEAKER_01"]["identity_id"]

    _, session = call("GET", f"/investigations/{first['id']}", token=inv)
    check("person recorded on the session through the normal subject list",
          any((s.get("reference_number") or "") == REFERENCE for s in session["subjects"]))

    # ---- 3. the person is waiting to be enrolled ---------------------------
    pg.goto(f"{UI}/voice-enrollments")
    pg.wait_for_selector("[data-testid=tab-pending]", timeout=20000)
    pg.locator("[data-testid=tab-pending]").click()
    row = pg.locator(f'[data-testid=candidate-row][data-reference="{REFERENCE}"]')
    expect(row).to_be_visible(timeout=15000)
    check("identified speaker appears under بانتظار التسجيل automatically", True)
    pg.screenshot(path=f"{SHOTS}/identity-02-pending.png", full_page=True)

    row.locator("[data-testid=candidate-enroll]").click()
    dialog = pg.locator(".modal")
    expect(dialog).to_be_visible()
    check("enrol dialog prefills the canonical reference",
          dialog.locator("[data-testid=voice-enroll-reference]").input_value() == REFERENCE)
    dialog.locator("[data-testid=voice-consent]").check()
    dialog.locator("[data-testid=voice-enroll-submit]").click()
    pg.wait_for_selector(ENROLLED, timeout=20000)

    pg.locator("[data-testid=tab-people]").click()
    person = pg.locator(f'[data-testid=person-row][data-reference="{REFERENCE}"]')
    expect(person).to_be_visible(timeout=15000)
    check("person moved to الأشخاص المسجّلون", True)
    check("one print so far", "بصمة واحدة" in person.inner_text(), person.inner_text().split("\n")[0])

    # ---- 4. a second session recognises the SAME identity -------------------
    second = submit(f"جلسة ثانية {stamp}", VOICE_B, VOICE_A)   # same voice, other label
    sp2 = speakers(second["id"])
    check("the same voice is suggested in a new session",
          sp2["SPEAKER_00"]["identification_status"] == "SUGGESTED"
          and sp2["SPEAKER_00"]["suggested_name"] == PERSON,
          f"{sp2['SPEAKER_00']['identification_status']} / {sp2['SPEAKER_00']['suggested_name']}")

    pg.goto(f"{UI}/investigations/{second['id']}?tab=speakers")
    pg.wait_for_selector("[data-testid=voice-suggestion]", timeout=20000)
    pg.locator("[data-testid=voice-confirm]").first.click()
    pg.wait_for_selector(".toast:has-text('تم تأكيد الاقتراح')", timeout=15000)

    # Enrol a second print of the same person, from this other session.
    pg.goto(f"{UI}/voice-enrollments")
    pg.locator("[data-testid=tab-pending]").click()
    row2 = pg.locator(f'[data-testid=candidate-row][data-reference="{REFERENCE}"]')
    expect(row2).to_be_visible(timeout=15000)
    row2.locator("[data-testid=candidate-enroll]").click()
    dialog = pg.locator(".modal")
    expect(dialog).to_be_visible()
    check("second print reuses the same canonical reference",
          dialog.locator("[data-testid=voice-enroll-reference]").input_value() == REFERENCE)
    dialog.locator("[data-testid=voice-consent]").check()
    dialog.locator("[data-testid=voice-enroll-submit]").click()
    pg.wait_for_selector(ENROLLED, timeout=20000)

    pg.locator("[data-testid=tab-people]").click()
    rows = pg.locator(f'[data-testid=person-row][data-reference="{REFERENCE}"]')
    check("still ONE person row, not two", rows.count() == 1, f"count={rows.count()}")
    expect(rows.first).to_contain_text("بصمتان", timeout=15000)
    check("the row reads two prints for one person", True)
    pg.screenshot(path=f"{SHOTS}/identity-03-people.png", full_page=True)

    # ---- 5. both prints belong to one identity -----------------------------
    _, prints = call("GET", "/voice-enrollments?include_inactive=true", token=inv)
    mine = [r for r in prints if r["person_reference"] == REFERENCE]
    check("two prints stored", len(mine) == 2, f"count={len(mine)}")
    check("both share one canonical identity", len({r["identity_id"] for r in mine}) == 1)
    check("identity matches the one on the speaker", mine[0]["identity_id"] == identity_id)

    check("no page errors", not errs, "; ".join(errs[:2]))
    b.close()

# Leave the registry as we found it: this test creates real biometric templates.
_, all_prints = call("GET", "/voice-enrollments?include_inactive=true", token=inv)
removed = 0
for row in all_prints or []:
    if row.get("person_reference") == REFERENCE:
        st, _ = call("DELETE", f"/voice-enrollments/{row['id']}", token=inv)
        removed += 1 if st == 204 else 0
check("test prints cleaned up", removed == 2, f"removed {removed}")

bad = [n for n, ok in R if not ok]
print(f"\nVOICE IDENTITY UI: {len(R) - len(bad)}/{len(R)} checks passed")
sys.exit(1 if bad else 0)
