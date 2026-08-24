"""Browser verification of the voice-cycle fixes: enrol gating and the re-scan buttons."""
import hashlib, io, json, math, struct, sys, time, urllib.error, urllib.request, wave
from playwright.sync_api import sync_playwright, expect

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
admin = call("POST", "/auth/login", {"username": "admin", "password": ADMIN_PW})[1]["access_token"]
u = f"cyc{stamp}"
call("POST", "/users", {"username": u, "password": "Investigator!2026", "roles": ["INVESTIGATOR"],
                        "must_change_password": False, "profile": {"full_name": "الرائد علي حسن"}}, admin)
inv = call("POST", "/auth/login", {"username": u, "password": "Investigator!2026"})[1]["access_token"]

DIM = 256
# Every run picks its OWN pair of orthogonal basis vectors. Enrolments left in the shared
# registry by other runs are therefore exactly 0.0 similar to this run's voices, so the
# assertions below do not depend on the state of the database.
_i = (stamp * 2) % (DIM - 2)
A = [1.0 if k == _i else 0.0 for k in range(DIM)]
B = [1.0 if k == _i + 1 else 0.0 for k in range(DIM)]

SAVED = ".toast:has-text('تم حفظ بيانات المتحدث')"
ENROLLED = ".toast:has-text('تم تسجيل بصمة الصوت')"
SCANNED = ".toast:has-text('تم الفحص')"


def submit(title, voice=True):
    s = call("POST", "/investigations", {"title": title}, inv)[1]
    a = wav()
    tk = call("POST", f"/investigations/{s['id']}/local-processing-token",
              {"original_filename": "i.wav", "mime_type": "audio/wav",
               "size_bytes": len(a), "source": "FILE_UPLOAD"}, inv)[1]
    res = {"idempotency_key": f"cyc-{stamp}-{title[-6:]}-0123456789", "language": "ar",
           "stt_provider": "cohere_local", "stt_model": "CohereLabs/cohere-transcribe-arabic-07-2026",
           "diarization_provider": "nvidia_sortformer",
           "diarization_model": "nvidia/diar_streaming_sortformer_4spk-v2.1",
           "agent_version": "1.0.0", "processing_device": "cpu", "speaker_count": 2,
           "warnings": [], "processing_metadata": {},
           "audio": {"duration_seconds": 52.0, "sha256": hashlib.sha256(a).hexdigest(), "size_bytes": len(a)},
           "segments": [
               {"speaker_label": "SPEAKER_00", "start_seconds": 1.1, "end_seconds": 9.4,
                "text": "أين كنت مساء أمس؟", "is_overlap": False},
               {"speaker_label": "SPEAKER_01", "start_seconds": 11.4, "end_seconds": 22.0,
                "text": "كنت في المنزل.", "is_overlap": False}]}
    if voice:
        res["voice_identification"] = {
            "provider": "nemo_speakernet", "model": "nvidia/speakerverification_speakernet",
            "model_revision": "1.16.0", "embedding_dim": DIM, "device": "cpu",
            "speakers": {"SPEAKER_00": {"embedding": A, "seconds": 8.0},
                         "SPEAKER_01": {"embedding": B, "seconds": 9.0}}}
    st, _ = call("POST", f"/local-processing/{tk['job_id']}/result", res, tk["processing_token"])
    assert st == 200, f"submit {st}"
    return s


# s_noemb: no embeddings at all. s_early: processed BEFORE anyone is enrolled.
s_noemb = submit(f"بدون بصمة {stamp}", voice=False)
s_early = submit(f"قبل التسجيل {stamp}")
s_src = submit(f"مصدر البصمة {stamp}")
s_src2 = submit(f"عينة ثانية {stamp}")

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page(viewport={"width": 1500, "height": 1000})
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(f"{UI}/login")
    pg.fill("#username", u)
    pg.fill("#password", "Investigator!2026")
    pg.click("button[type=submit]")
    pg.wait_for_url(lambda x: "/login" not in x)

    # ---- 1. enrol must stay disabled when there is NO embedding -------------
    pg.goto(f"{UI}/investigations/{s_noemb['id']}?tab=speakers")
    pg.wait_for_selector("[data-testid=speaker-card]", timeout=20000)
    c0 = pg.locator("[data-testid=speaker-card][data-label=SPEAKER_00]")
    c0.locator("[data-testid=speaker-name]").fill("شخص بلا بصمة")
    c0.locator("button", has_text="تعيين الاسم").click()
    pg.wait_for_selector(SAVED, timeout=10000)
    btn = c0.locator("[data-testid=voice-enroll]")
    check("named speaker with NO embedding: enrol stays disabled", btn.is_disabled())
    check("tooltip explains the missing embedding",
          "لا توجد بصمة صوت" in (btn.get_attribute("title") or ""), btn.get_attribute("title") or "")
    check("re-scan hidden when no speaker has an embedding",
          pg.locator("[data-testid=voice-rematch]").count() == 0)

    # ---- 2. enrol from a session that HAS embeddings ------------------------
    pg.goto(f"{UI}/investigations/{s_src['id']}?tab=speakers")
    pg.wait_for_selector("[data-testid=speaker-card]", timeout=20000)
    c0 = pg.locator("[data-testid=speaker-card][data-label=SPEAKER_00]")
    c0.locator("[data-testid=speaker-name]").fill("الرائد علي حسن")
    c0.locator("button", has_text="تعيين الاسم").click()
    pg.wait_for_selector(SAVED, timeout=10000)
    check("with an embedding, enrol becomes enabled",
          not c0.locator("[data-testid=voice-enroll]").is_disabled())
    c0.locator("[data-testid=voice-enroll]").click()
    m = pg.locator(".modal")
    m.locator("input.input").nth(1).fill(f"MIL-{stamp}")
    m.locator("[data-testid=voice-consent]").check()
    m.locator("[data-testid=voice-enroll-submit]").click()
    pg.wait_for_selector(ENROLLED, timeout=15000)
    check("enrolled from the UI", True)

    # ---- 3. a SECOND print of the SAME voice, from another session ----------
    # Deliberately the same speaker's voice: enrolling a DIFFERENT voice under one
    # person_reference would (correctly) make that other voice match the person too.
    pg.goto(f"{UI}/investigations/{s_src2['id']}?tab=speakers")
    pg.wait_for_selector("[data-testid=speaker-card]", timeout=20000)
    c1 = pg.locator("[data-testid=speaker-card][data-label=SPEAKER_00]")
    c1.locator("[data-testid=speaker-name]").fill("الرائد علي حسن")
    c1.locator("button", has_text="تعيين الاسم").click()
    pg.wait_for_selector(SAVED, timeout=10000)
    c1.locator("[data-testid=voice-enroll]").click()
    m = pg.locator(".modal")
    m.locator("input.input").nth(1).fill(f"MIL-{stamp}")
    m.locator("[data-testid=voice-consent]").check()
    m.locator("[data-testid=voice-enroll-submit]").click()
    pg.wait_for_selector(ENROLLED, timeout=15000)
    check("a second print of the same person is accepted (was 409 before)", True)

    # ---- 4. the earlier session stays NONE until re-scanned -----------------
    _, sp = call("GET", f"/investigations/{s_early['id']}/speakers", token=inv)
    a0 = next(x for x in sp if x["speaker_label"] == "SPEAKER_00")
    check("session processed before enrolment is still unidentified",
          a0["identification_status"] == "NONE", a0["identification_status"])

    pg.goto(f"{UI}/investigations/{s_early['id']}?tab=speakers")
    pg.wait_for_selector("[data-testid=voice-rematch]", timeout=20000)
    pg.locator("[data-testid=voice-rematch]").click()
    pg.wait_for_selector(SCANNED, timeout=20000)
    _, sp = call("GET", f"/investigations/{s_early['id']}/speakers", token=inv)
    a0 = next(x for x in sp if x["speaker_label"] == "SPEAKER_00")
    b0 = next(x for x in sp if x["speaker_label"] == "SPEAKER_01")
    check("re-scan produced a suggestion for the matching voice",
          a0["identification_status"] == "SUGGESTED" and a0["suggested_name"] == "الرائد علي حسن",
          f"{a0['identification_status']} / {a0['suggested_name']}")
    check("two prints of the same person did NOT cancel out",
          a0["suggested_score"] is not None and float(a0["suggested_score"]) >= 0.65,
          str(a0["suggested_score"]))
    check("the other voice stays unidentified",
          b0["identification_status"] == "NONE", b0["identification_status"])
    expect(pg.locator("[data-testid=voice-suggestion]").first).to_be_visible(timeout=15000)
    check("suggestion banner rendered after the re-scan", True)
    pg.screenshot(path=f"{SHOTS}/voice-rematch.png", full_page=True)

    # ---- 5. global re-scan from the enrolments page -------------------------
    pg.goto(f"{UI}/voice-enrollments")
    pg.wait_for_selector("[data-testid=voice-rematch-all]", timeout=20000)
    pg.locator("[data-testid=voice-rematch-all]").click()
    pg.wait_for_selector(SCANNED, timeout=30000)
    check("global re-scan runs from the enrolments page", True)

    check("no page errors", not errs, "; ".join(errs[:2]))
    b.close()

# Leave the shared registry as we found it: this test creates real biometric templates.
_, rows = call("GET", f"/voice-enrollments?q=MIL-{stamp}", token=inv)
removed = 0
for row in rows or []:
    if row.get("person_reference") == f"MIL-{stamp}":
        st, _ = call("DELETE", f"/voice-enrollments/{row['id']}", token=inv)
        removed += 1 if st == 204 else 0
check("test enrolments cleaned up", removed == len(
    [r for r in (rows or []) if r.get("person_reference") == f"MIL-{stamp}"]), f"removed {removed}")

bad = [n for n, ok in R if not ok]
print(f"\nVOICE CYCLE UI: {len(R) - len(bad)}/{len(R)} checks passed")
sys.exit(1 if bad else 0)
