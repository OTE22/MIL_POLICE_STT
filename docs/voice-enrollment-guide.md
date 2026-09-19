# بصمات الأصوات — how voice enrolment works

> **Updated identity model:** Person reference numbers have been removed. People now use internal UUIDs. See [the current identity contract and migration](person-identity-migration.md). Reference-number descriptions below document the earlier implementation.

**Who this is for:** investigators who enrol voices, and anyone wondering why a name was
or was not suggested. Practical throughout; no technical knowledge needed.

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
2. establish who SPEAKER_00 is  → اختيار الشخص → pick the person
3. press "تسجيل بصمة الصوت"      → the print is created from that speaker's audio
```

Step 2 before step 3, always.

**A name is not an identity.** The enrol button needs *both* of these, and says which one is
missing:

| Missing | The button says |
|---|---|
| The speaker has no canonical person | *حدِّد هوية المتحدث أولاً — البصمة تُربط بشخص، لا باسم فقط.* |
| The recording carries no voice data | *لا توجد بصمة صوت لهذا المتحدث — تحقق من حالة نموذج بصمة الصوت في الوكيل، ثم أعد معالجة التسجيل.* |

A free-text label such as *المتحدث الأول* is legal and useful, but it establishes nobody, so
it never enables enrolment. Only picking a person does.

---

## 3. Enrolling, step by step

Open a session → **المتحدثون** tab.

| Step | What you do |
|---|---|
| 1 | Press **اختيار الشخص** on the speaker's card |
| 2 | Pick the person — from **مشاركو الجلسة**, or **البحث عن شخص مسجل**, or **إضافة شخص جديد** |
| 3 | Press **تسجيل بصمة الصوت** on that speaker's card |
| 4 | Check the name and الرقم المرجعي, both already filled in |
| 5 | Tick the consent box |
| 6 | Press the confirm button in the dialog |

**اختيار الشخص is the only way to identify a speaker.** It replaced a free-text box, three
look-alike chips and two separate buttons that each established identity through a different
door. It offers five choices, and each states what it will do:

| Section | What picking it does |
|---|---|
| **مشاركو الجلسة** | A subject recorded on this session — linked immediately |
| **مُحقّقو الجلسة** | An investigator running it — linked immediately |
| **البحث عن شخص مسجل** | The canonical registry — recorded on the session, then linked |
| **إضافة شخص جديد** | Opens the person form — created, then linked |
| **تسمية مؤقتة** | A label only. Offered **only while nobody has been identified** |

**The name you see is the same everywhere.** بصمات الأصوات, the speaker card and the picker
all show the canonical `person_name` from the registry, so a person renamed or consolidated
reads correctly in every screen at once. A **rank is shown beside the name, never inside it** —
ranks change with promotion, the registry has no column for one, and a name with a rank baked
in could never match what the voice registry returns.

**Investigators are enrollable like anyone else.** They speak in the interviews they run, so
they are registry people: assigning one to a session registers them under
`MIL-<BRANCH>-<serial>`, and from there they are identified and voice-enrolled by the same
steps as a subject. Enrol the investigator once and every session they run can suggest them.

An investigator whose profile lacks `الجهاز` or `الرقم العسكري` has no reference yet and is shown
**disabled** with what is missing — complete it in **إدارة المستخدمين**.

تسمية مؤقتة disappears once the speaker *is* someone: a working label on an identified
speaker would be a way to quietly disagree with the registry.

Picking a person resolves through **الرقم المرجعي**, never the displayed name — two people in
one session may share a rank and a name, so each row carries its person, not its string.

### الرقم المرجعي is the important field

**You never type it, and you never see an empty box for it.** Picking a person fills it in.
A soldier gets `MIL-<الجهاز>-<الرقم العسكري>`, derived from what you already entered;
everyone else is **issued** `CIV-*` when the person is saved. That is what
stops one soldier arriving as `MIL-4471`, `MIL 4471` and `4471`.

A UNHCR or UNRWA card no longer becomes the reference. The card can be reissued, corrected or
replaced, and the person must survive that — so it is recorded as an **external identifier**
that helps find them instead. محل القيد and رقم السجل identify a **family record**, not a
person, so they identify nobody. See [subject-identity.md](subject-identity.md) for why.

It is the person's **stable identifier**, not their display name — it is what ties their prints
together across sessions.

> **One person, one رقم مرجعي.** Two prints filed under two different reference numbers look
> like two different people, and two "different people" who sound alike make the matcher refuse
> to choose — so the person stops getting suggestions altogether. Derivation is what normally
> prevents this; if you override the value, the derived one is still reserved against the same
> person, so nobody else can claim it. See §7.

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

The matcher groups prints by **canonical identity** (`identity_id` in the person registry)
and represents each person by their *best* print, so extra prints can only help — they never
compete with each other.

Grouping by identity rather than by the reference stored on the print matters: `person_name`
and `person_reference` on a print are a **snapshot of what was recorded the day it was taken**.
Rename or merge a person and the prints follow automatically, because the identity they point
at is the authority — not the text they carry.

If you enter a reference that is already registered under a **different name**, the request
is refused (`person_reference_name_mismatch`). That is almost always a typo in the reference
number, and filing someone's voice under another person's identity is the one mistake this
area must not make quietly.

### فحص البصمات الصوتية — checking that a person's prints agree

More prints only help **when they are all really the same voice**. A print enrolled from the
wrong speaker sits under the person forever and makes that other voice match at ~100%. To
find this, every person row on **بصمات الأصوات** has a **فحص البصمات الصوتية** button
(anyone who can view the page can run it):

* It runs **only when you press it** — never at enrolment, never on page load, and only for
  that one person.
* The server compares the person's **active prints with each other** (one pgvector cosine
  query; prints from a different model or dimension are grouped and reported separately —
  they are never compared across groups).
* Prints that match at or above **عتبة اقتراح الهوية** (the same threshold the matcher uses,
  from إعدادات النظام) are linked; the linked sets are the **المجموعات الصوتية**. One group
  = healthy. **More than one group = تحتاج مراجعة**: internally-coherent sets that do not
  match each other usually mean two different voices were enrolled under one person.
* Per print you see the highest similarity to a sibling and a status: **منسجمة** (has a
  matching sibling), **شبه مكررة** (above عتبة البصمة شبه المكررة — same sample twice, adds
  no coverage), **معزولة** (matches none of the siblings), or **بصمة واحدة**.

The check is **advisory only**. It never deletes, deactivates, merges, or re-assigns
anything, and it never decides which group is the real person — listen to the source
recordings (each print links to its session) and use the existing تعطيل/حذف controls
yourself. Both thresholds live in **إعدادات النظام**; changing them there changes the next
check immediately.

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
| **فحص البصمات الصوتية** | Measures whether the person's active prints agree with each other and reports — changes nothing (see §4). |

Prefer **تعطيل** over **حذف**. Deleting is permanent, and it also clears the link from any
speaker that was confirmed against that print — the identification stays confirmed, and the
audit log still records which print it was, but the live link is gone.

The embedding itself is never shown in the interface and never leaves the server.

---

## 7. When suggestions do not appear

Work down this list.

**a. Does the speaker have a voice embedding at all?**

If **تسجيل بصمة الصوت** is disabled and says *لا توجد بصمة صوت لهذا المتحدث*, that recording
was processed without a working speaker-identification model. There are two different causes
and **they need opposite fixes**, so check which one you have before doing anything:

Open the session's **التسجيل** tab and read **حالة نموذج بصمة الصوت** in the agent panel:

| Badge | Meaning | What to do |
|---|---|---|
| **جاهز** | The model is loaded | The recording predates it — reprocess the recording |
| **النموذج غير محمّل** | Provisioned, not yet loaded | Normal before the first job; it loads on demand |
| **النموذج غير مثبّت** | The `.nemo` file is not where the agent expects it | Provision it — see below |
| **غير معروف** | **The agent does not report this model at all** | Its build predates the feature — redeploy the agent |
| **تعذر تشغيل النموذج** | It tried and failed | `docker compose logs agent` |

> **Reprocessing does not help when the badge is غير معروف or النموذج غير مثبّت.** The agent has
> nothing to compute an embedding with, so it will produce exactly the same nothing. This is
> the single most misleading failure in this area: a missing *capability* and a missing
> *embedding* look identical on the speaker card.

From a terminal, the same answer:

```bash
curl -s http://127.0.0.1:17117/model-status | python -m json.tool | grep -A 8 speaker_id
```

`"state": "READY"` after a job means it is working. If the `speaker_id` key is **absent from
the response entirely**, the agent is running a build from before voice identification
existed — redeploy it with `deploy/deploy-edge.sh`.

Older sessions processed without the model cannot be enrolled retroactively unless you
reprocess the audio.

**b. Was the session processed before the person was enrolled?**
Most likely cause. Press **إعادة فحص البصمات** on the session.

**c. Was the person ever identified?**
A speaker with a name but no identity is not enrollable and shows
*لن يظهر في بصمات الأصوات حتى تُحدَّد هويته* on its card. Press **اختيار الشخص** and pick the
person (or add them).

Note that this needs the `voice.identify` permission. Someone who holds only `speakers.assign`
can label a voice but cannot say which human it is, and the picker offers them **مشاركو
الجلسة** and **تسمية مؤقتة** only.

**d. Is the same person enrolled under several reference numbers?**
This silently suppresses suggestions for that person — two of their own prints look like two
rival people, and the matcher abstains rather than choose. Check:

```sql
SELECT person_name, count(DISTINCT person_reference) AS refs,
       string_agg(DISTINCT person_reference, ', ') AS which
FROM voice_enrollments WHERE is_active GROUP BY 1 HAVING count(DISTINCT person_reference) > 1;
```

Consolidate the **identities**, then re-scan. Do **not** edit `voice_enrollments` by hand:
since matching groups by `identity_id`, rewriting the `person_reference` column changes only a
historical snapshot and consolidates nothing — the two identities still compete, and the
matcher still abstains. It would look like it worked.

Use the endpoint, which merges the identities and repoints every print, subject and speaker:

```
POST /api/voice-enrollments/people/{identity_id}/consolidate
     { "into_identity_id": "<the surviving person>" }
```

It requires `voice.enroll` **and** `investigations.read_all`, so in practice ADMIN only:
consolidation rewrites ownership across sessions the caller may not be allowed to open, so
being able to enrol a voice must not confer it. The merged reference survives as an **alias** —
it can never be recreated, and a stale client submitting it resolves forward to the survivor.

**e. Do two genuinely different people sound alike?**
Then abstaining is correct. Name the speaker by hand.

**f. Is the score simply too low?**
The threshold is **0.65** (`CENTRAL_VOICE_MATCH_THRESHOLD`), calibrated on synthesised
voices. Recalibrate on your own recordings before relying on it — see the calibration
section of [speaker-identification.md](speaker-identification.md).

**g. Is the print deactivated?** Check the **بصمات الأصوات** page with *غير المفعّلة* shown.

---

## 8. Rules the system will not bend

* A voice comparison **never** writes a name. Only **تأكيد** by a person does.
* Consent is required to create a print — no exceptions.
* Prints are compared only within the model that produced them.
* When the best two *people* are too close, the system **abstains** instead of guessing.
* Re-scans never overwrite a human decision.
* **فحص البصمات الصوتية is advisory only.** It never deletes, deactivates, merges or
  re-assigns anything, and it never decides which group of prints is the real person.
* Every enrolment, suggestion, confirmation, rejection, deactivation, deletion and re-scan
  is audited with who did it and when.

---

## 9. Permissions

| Permission | Grants | Roles |
|---|---|---|
| `voice.identify` | See suggestions, confirm/reject, view the registry, run a re-scan, run **فحص البصمات الصوتية** | ADMIN, INVESTIGATOR |
| `voice.enroll` | Create, deactivate and delete prints | ADMIN, INVESTIGATOR |
| `speakers.assign` | Label a speaker: الاسم المعروض, الصفة, ملاحظات. Required *in addition* to accept a suggestion | ADMIN, INVESTIGATOR |

**Labelling and identifying are different authorities.** `speakers.assign` says *you may name
the voices in this session*. `voice.identify` says *you may declare which human this is* — a
claim that reaches the canonical registry and, through it, the biometric prints.

The split is enforced on the server, not just in the interface: a speaker PATCH that asserts a
person (`person_name`, or a changed `reference_number`) is refused with
`identity_change_not_permitted` unless the caller holds `voice.identify`. The check runs
**before** the speaker row is touched, so a refusal leaves it exactly as it was — hiding the
option in the picker would otherwise leave the endpoint open to anyone who can call it.

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
