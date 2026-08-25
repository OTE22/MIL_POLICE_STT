# بصمات الأصوات — how voice enrolment works

A practical guide to the voice registry: what a "print" is, how one gets created, what the
system does with it, and what to do when suggestions do not appear.

For the model and the maths, see [speaker-identification.md](speaker-identification.md).
For the whole recording pipeline, see [how-it-works.md](how-it-works.md).

---

## 1. What a voice print is

A print is **256 numbers** — a SpeakerNet-M embedding describing how a voice sounds. It is
not audio. You cannot listen to it, and it cannot be turned back into speech.

It exists so the system can answer one narrow question: *does this anonymous speaker sound
like someone we have met before?* The answer is always a **suggestion**. Only an
investigator pressing **تأكيد** ever writes a name onto a speaker.

```
audio  →  (on the workstation)  →  256 numbers  →  (to the server)
                                                    ↓
                                        compared with enrolled prints
                                                    ↓
                                        "اقتراح: … "  →  human confirms
```

Raw audio never leaves the desktop for this purpose, and the embedding is never sent back
to a browser or written into the audit log.

---

## 2. Where prints come from

**Only from a speaker in a session you have already identified.** There is no "upload a
voice sample" screen, and that is deliberate: every print is traceable to a real recording,
a real session, and the person who vouched for the identity.

So the order is always:

```
1. process a recording          → speakers appear as SPEAKER_00, SPEAKER_01 …
2. establish who SPEAKER_00 is  → type the name, or pick from the session's people
3. press "تسجيل بصمة الصوت"      → the print is created from that speaker's audio
```

Step 2 before step 3, always. The enrol button stays disabled until the speaker has a name.

---

## 3. Enrolling, step by step

Open a session → **المتحدثون** tab.

| Step | What you do |
|---|---|
| 1 | Set **الاسم المعروض** for the speaker and press **تعيين الاسم** |
| 2 | Press **تسجيل بصمة الصوت** on that speaker's card |
| 3 | Check the name, and fill in **الرقم المرجعي** |
| 4 | Tick the consent box |
| 5 | Press the confirm button in the dialog |

### الرقم المرجعي is the important field

This is the person's **stable identifier** — military number, civil registry number, case
reference. It is what ties a person's prints together, and it is **not** the display name.

> **Use the same رقم مرجعي every time you enrol the same person.** This is the single most
> important rule on this page. Two prints of one person filed under two different reference
> numbers look like two different people to the system, and two "different people" who sound
> alike make the matcher refuse to choose — so the person stops getting suggestions
> altogether. See §7.

### Consent is mandatory

The request is refused (`consent_required`) unless the consent box is ticked. A voice print
is biometric data. The flag, who enrolled it, and which session and speaker it came from are
all stored with the print.

---

## 4. Several prints per person — encouraged

One person **should** have more than one print. A voice recorded in a quiet room, over a
phone, or through a different microphone produces noticeably different embeddings, and more
prints mean better coverage.

To add another print: identify that person in another session and enrol them again, using
**the same رقم مرجعي**.

The matcher groups prints by reference and represents each person by their *best* print, so
extra prints can only help — they never compete with each other.

If you enter a reference that is already registered under a **different name**, the request
is refused (`person_reference_name_mismatch`). That is almost always a typo in the reference
number, and filing someone's voice under another person's identity is the one mistake this
area must not make quietly.

---

## 5. What happens after enrolment

**New recordings**: matching runs automatically when the workstation submits its result.

**Sessions already processed**: nothing happens automatically. Matching ran when those
results arrived, and a print enrolled afterwards was not there at the time. Use a re-scan:

| Where | Button | Scope |
|---|---|---|
| A session's **المتحدثون** tab | **إعادة فحص البصمات** | that one session |
| **بصمات الأصوات** page | **إعادة فحص الجلسات غير المحددة** | every speaker still "غير محدد" |

Re-scans compare embeddings already stored in the database. No audio is reprocessed, no
model runs, and it takes seconds. **A speaker you have already confirmed or rejected is
never touched.**

### What a suggestion looks like

```
اقتراح: الرائد علي حسن — درجة التطابق 81%        [تأكيد]  [تجاهل]
لا يُعتمد إلا بعد تأكيد المحقق
```

* **تأكيد** — writes the name into الاسم المعروض, marks the speaker **مؤكَّد من المحقق**.
* **تجاهل** — marks it **مرفوض**. The rejected suggestion is kept for the audit trail, and
  re-scans will not raise it again.

---

## 6. Managing the registry

The **بصمات الأصوات** page lists every print: person, reference, model, sample length,
source session, consent, status, who enrolled it, and when. Search filters by name or
reference; the checkbox shows deactivated prints too.

| Action | Effect |
|---|---|
| **تعطيل** (`is_active=false`) | Stops the print being used for future suggestions. Nothing is destroyed, and names already confirmed are unaffected. |
| **حذف** | Removes the print permanently. |

Prefer **تعطيل** over **حذف**. Deleting is permanent, and it also clears the link from any
speaker that was confirmed against that print — the identification stays confirmed, and the
audit log still records which print it was, but the live link is gone.

The embedding itself is never shown in the interface and never leaves the server.

---

## 7. When suggestions do not appear

Work down this list.

**a. Does the speaker have a print at all?**
If **تسجيل بصمة الصوت** is disabled and says *لا توجد بصمة صوت لهذا المتحدث*, that recording
was processed without the speaker-identification model. Reprocess the recording; older
sessions cannot be enrolled retroactively.

**b. Was the session processed before the person was enrolled?**
Most likely cause. Press **إعادة فحص البصمات** on the session.

**c. Is the same person enrolled under several reference numbers?**
This silently suppresses suggestions for that person — two of their own prints look like two
rival people, and the matcher abstains rather than choose. Check:

```sql
SELECT person_name, count(DISTINCT person_reference) AS refs,
       string_agg(DISTINCT person_reference, ', ') AS which
FROM voice_enrollments WHERE is_active GROUP BY 1 HAVING count(DISTINCT person_reference) > 1;
```

Consolidate onto the real identifier, then re-scan:

```sql
UPDATE voice_enrollments SET person_reference = '<the real ID number>'
WHERE person_name = '<the person>' AND person_reference IN ('<old-1>', '<old-2>');
```

**d. Do two genuinely different people sound alike?**
Then abstaining is correct. Name the speaker by hand.

**e. Is the score simply too low?**
The threshold is **0.65** (`CENTRAL_VOICE_MATCH_THRESHOLD`), calibrated on synthesised
voices. Recalibrate on your own recordings before relying on it — see the calibration
section of [speaker-identification.md](speaker-identification.md).

**f. Is the print deactivated?** Check the **بصمات الأصوات** page with *غير المفعّلة* shown.

---

## 8. Rules the system will not bend

* A voice comparison **never** writes a name. Only **تأكيد** by a person does.
* Consent is required to create a print — no exceptions.
* Prints are compared only within the model that produced them.
* When the best two *people* are too close, the system **abstains** instead of guessing.
* Re-scans never overwrite a human decision.
* Every enrolment, suggestion, confirmation, rejection, deactivation, deletion and re-scan
  is audited with who did it and when.

---

## 9. Permissions

| Permission | Grants | Roles |
|---|---|---|
| `voice.identify` | See suggestions, confirm/reject, view the registry, run a re-scan | ADMIN, INVESTIGATOR |
| `voice.enroll` | Create, deactivate and delete prints | ADMIN, INVESTIGATOR |
| `speakers.assign` | Required *in addition* to accept a suggestion — the same permission as typing a name by hand | ADMIN, INVESTIGATOR |

The read-only **USER** role has none of these and never sees voice data.

---

## 10. Privacy notes for deployment

Voice prints are biometric data and are among the most sensitive things the system holds.

* They live only in the central database, in `voice_enrollments`.
* They are never returned to a browser, never written to the audit log, and never leave the
  server.
* Deleting a person's prints does not alter transcripts or names already confirmed — those
  are historical records of what an investigator decided.
* Agree a retention policy for prints alongside the one for audio and ID scans.
