"""The reported bug: naming a speaker in المتحدثون never reached بصمات الأصوات.

Also covers the case that makes name-based selection unsafe: two people in one session who
share a name. Picking the second must link the SECOND person, not whoever matched first.
"""
import hashlib
import io
import json
import math
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import wave

from playwright.sync_api import expect, sync_playwright

BASE, UI = "http://localhost:8080/api", "http://localhost:8080"
ADMIN_PW, SHOTS = sys.argv[1], sys.argv[2]
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


inv, UI_USER, UI_PASSWORD = investigator_token("spk", "النقيب سامر خليل")

DIM = 256
_i = (stamp * 2) % (DIM - 2)
A = [1.0 if k == _i else 0.0 for k in range(DIM)]
B = [1.0 if k == _i + 1 else 0.0 for k in range(DIM)]

REF_A, REF_B = f"MIL-ARMY-{stamp}1", f"MIL-ARMY-{stamp}2"
SAVED = ".toast:has-text('تم حفظ بيانات المتحدث')"


def submit(title, subjects):
    s = call("POST", "/investigations", {"title": title, "subjects": subjects}, inv)[1]
    audio = wav()
    tk = call("POST", f"/investigations/{s['id']}/local-processing-token",
              {"original_filename": "i.wav", "mime_type": "audio/wav",
               "size_bytes": len(audio), "source": "FILE_UPLOAD"}, inv)[1]
    res = {"idempotency_key": f"spk-{stamp}-{title[-5:]}-0123456789", "language": "ar",
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
               "speakers": {"SPEAKER_00": {"embedding": A, "seconds": 8.0},
                            "SPEAKER_01": {"embedding": B, "seconds": 9.0}}},
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


# Two people who share a name - only الرقم المرجعي tells them apart.
session = submit(f"تشابه أسماء {stamp}", [
    {"subject_name": "أحمد محمد", "rank": "رائد", "person_type": "MILITARY",
     "security_branch": "ARMY", "military_id": f"{stamp}1"},
    {"subject_name": "أحمد محمد", "rank": "نقيب", "person_type": "MILITARY",
     "security_branch": "ARMY", "military_id": f"{stamp}2"},
])

_, detail = call("GET", f"/investigations/{session['id']}", token=inv)
refs = sorted((s["reference_number"] or "") for s in detail["subjects"])
check("both namesakes got their own derived reference", refs == sorted([REF_A, REF_B]), str(refs))

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

    pg.goto(f"{UI}/investigations/{session['id']}?tab=speakers")
    pg.wait_for_selector("[data-testid=speaker-card]", timeout=20000)
    card = pg.locator("[data-testid=speaker-card][data-label=SPEAKER_00]")

    card.locator("[data-testid=speaker-person-picker]").click()
    rows = pg.locator("[data-testid=pick-participant]")
    # Two rows, both reading أحمد محمد: they must not have been collapsed into one.
    check("both namesakes are offered separately",
          rows.filter(has_text="أحمد محمد").count() == 2,
          f"count={rows.filter(has_text='أحمد محمد').count()}")

    # Pick the SECOND one BY REFERENCE - the only thing that tells the two apart. Selecting
    # identifies immediately; there is no separate save.
    pg.locator(f'[data-testid=pick-participant][data-reference="{REF_B}"]').click()
    pg.wait_for_selector(SAVED, timeout=15000)

    sp = speakers(session["id"])["SPEAKER_00"]
    check("selecting a person gives the speaker a canonical identity", bool(sp["identity_id"]),
          str(sp["identity_id"]))
    check("the chosen namesake is the one linked, not the first match",
          sp["reference_number"] == REF_B, f"{sp['reference_number']} (wanted {REF_B})")
    # The reported bug: the chip SHOWS the rank, and the registry must not store it.
    check("the label carries the rank", (sp["display_name"] or "").startswith("نقيب"),
          sp["display_name"] or "")
    check("the canonical name is the human name alone",
          sp["identity_name"] == "أحمد محمد", sp["identity_name"] or "")
    # quote(): a raw Arabic query string is not ASCII, and urllib refuses to send it.
    _, people = call("GET", "/voice-enrollments/people?q=" + urllib.parse.quote("نقيب"), token=inv)
    check("no canonical person was created under the rank-decorated label",
          not [x for x in (people or []) if (x["person_name"] or "").startswith("نقيب")],
          str([x["person_name"] for x in (people or [])]))

    # The whole point of the report: it must now show up in بصمات الأصوات.
    pg.goto(f"{UI}/voice-enrollments")
    pg.wait_for_selector("[data-testid=tab-pending]", timeout=20000)
    pg.locator("[data-testid=tab-pending]").click()
    row = pg.locator(f'[data-testid=candidate-row][data-reference="{REF_B}"]')
    expect(row).to_be_visible(timeout=15000)
    check("the named speaker appears under بانتظار التسجيل", True)
    pg.screenshot(path=f"{SHOTS}/speaker-identity.png", full_page=True)

    # A speaker named with no reference stays without an identity, and says so.
    card1 = pg.locator("[data-testid=speaker-card][data-label=SPEAKER_01]")
    pg.goto(f"{UI}/investigations/{session['id']}?tab=speakers")
    pg.wait_for_selector("[data-testid=speaker-card]", timeout=20000)
    card1 = pg.locator("[data-testid=speaker-card][data-label=SPEAKER_01]")
    card1.locator("[data-testid=speaker-person-picker]").click()
    pg.locator("[data-testid=pick-temporary-input]").fill("شاهد بلا هوية")
    pg.locator("[data-testid=pick-temporary-save]").click()
    pg.wait_for_selector(SAVED, timeout=15000)

    sp1 = speakers(session["id"])["SPEAKER_01"]
    check("a temporary label still leaves no identity", sp1["identity_id"] is None)
    check("and it is only a label", sp1["display_name"] == "شاهد بلا هوية",
          sp1["display_name"] or "")
    expect(card1.locator("[data-testid=speaker-not-identified]")).to_be_visible(timeout=10000)
    check("the card explains why it is missing from بصمات الأصوات", True)

    # Naming someone does not identify them, so the ways of identifying stay on offer.
    card1.locator("[data-testid=speaker-person-picker]").click()
    check("إضافة شخص جديد is still offered once a label exists",
          pg.locator("[data-testid=pick-add-new]").count() == 1)
    pg.keyboard.press("Escape")

    # ---- civilians: issued a reference, and a family record identifies nobody --------
    #
    # رقم السجل lists a whole family on one إخراج قيد. Deriving from it made relatives one
    # canonical person: the second was refused when their names differed, and silently merged
    # when they matched. Both are recorded here as two people with two references.
    civil = submit(f"أقارب {stamp}", [
        {"subject_name": "علي حسن", "person_type": "CIVILIAN",
         "caza_code": "ZAHLE", "register_number": "123"},
        {"subject_name": "حسن حسن", "person_type": "CIVILIAN",
         "caza_code": "ZAHLE", "register_number": "123"},
    ])
    _, civil_detail = call("GET", f"/investigations/{civil['id']}", token=inv)
    civil_refs = {x["subject_name"]: x["reference_number"] for x in civil_detail["subjects"]}

    check("a civilian is issued a reference nobody typed",
          all((r or "").startswith("CIV-") for r in civil_refs.values()), str(civil_refs))
    check("two relatives on one رقم سجل are two people",
          civil_refs["علي حسن"] != civil_refs["حسن حسن"], str(civil_refs))
    check("the civil record is still recorded, just not identifying",
          all(x["register_number"] == "123" for x in civil_detail["subjects"]))

    pg.goto(f"{UI}/investigations/{civil['id']}?tab=speakers")
    pg.wait_for_selector("[data-testid=speaker-card]", timeout=20000)
    civil_card = pg.locator("[data-testid=speaker-card][data-label=SPEAKER_00]")
    wanted = civil_refs["علي حسن"]
    civil_card.locator("[data-testid=speaker-person-picker]").click()
    row = pg.locator(f'[data-testid=pick-participant][data-reference="{wanted}"]')
    check("the civilian is offered with their CIV reference on the row", row.count() == 1)
    row.click()
    pg.wait_for_selector(SAVED, timeout=15000)

    check("the reference the server stored is shown read-only",
          civil_card.locator("[data-testid=speaker-reference]").input_value() == wanted,
          civil_card.locator("[data-testid=speaker-reference]").input_value())

    civil_speaker = speakers(civil["id"])["SPEAKER_00"]
    check("the civilian speaker reached a canonical identity",
          bool(civil_speaker["identity_id"]), str(civil_speaker["identity_id"]))
    check("and it is the person who was clicked",
          civil_speaker["reference_number"] == wanted, civil_speaker["reference_number"] or "")

    pg.goto(f"{UI}/voice-enrollments")
    pg.wait_for_selector("[data-testid=tab-pending]", timeout=20000)
    pg.locator("[data-testid=tab-pending]").click()
    expect(pg.locator(f'[data-testid=candidate-row][data-reference="{wanted}"]')).to_be_visible(timeout=15000)
    check("the civilian appears under بانتظار التسجيل", True)
    pg.screenshot(path=f"{SHOTS}/civilian-identity.png", full_page=True)

    check("no page errors", not errs, "; ".join(errs[:2]))
    b.close()

bad = [n for n, ok in R if not ok]
print(f"\nSPEAKER IDENTITY UI: {len(R) - len(bad)}/{len(R)} checks passed")
sys.exit(1 if bad else 0)
