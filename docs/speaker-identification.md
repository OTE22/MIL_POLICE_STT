# Speaker identification (SpeakerNet-M)

> Looking for the day-to-day workflow — how to enrol a voice, re-scan a session, or work
> out why a suggestion is missing? See [voice-enrollment-guide.md](voice-enrollment-guide.md).
> This document covers the model and the matching rules.

> **Scope change.** The original specification (§10, §83) excluded voice biometrics.
> This capability was added later at the customer's request. It is built as an
> **assistive suggestion that a human must confirm** — it never assigns a name by
> itself — so the manual speaker mapping required by §10 remains the authoritative act.

| | |
|---|---|
| Model | `nvidia/speakerverification_speakernet` (SpeakerNet-M) |
| Pinned revision | `1.16.0`, SHA-256 `07e9653ec9776260b6d5de92df2d1aacde798d7657f4d12937b36e22596acdb5` |
| Source | NVIDIA NGC (public, no account needed) — not Hugging Face |
| Size / runtime | 21.85 MB, NeMo `EncDecSpeakerLabelModel`, 256-dimension embeddings |
| Provider key | `AGENT_SPEAKER_ID_PROVIDER=nemo_speakernet` |
| Default | enabled (`AGENT_SPEAKER_ID_ENABLED=true`); failure is never fatal |

## What each model does

```
NVIDIA Sortformer          WHO SPOKE WHEN     anonymous SPEAKER_00 … SPEAKER_03 + timestamps
Cohere Transcribe Arabic   WHAT WAS SAID      Arabic text per speaker turn
NVIDIA SpeakerNet-M        HOW THE VOICE SOUNDS   a 256-d vector per anonymous speaker
central matching           WHO IT MIGHT BE    cosine vs enrolled voices -> a SUGGESTION
the investigator           WHO IT IS          confirms or rejects; only this writes the name
```

SpeakerNet does not replace diarization and does not produce text.

## Flow

1. **Agent (local).** After transcription, each anonymous speaker's turns are concatenated
   (longest first, capped at `AGENT_SPEAKER_ID_MAX_SECONDS`, minimum
   `AGENT_SPEAKER_ID_MIN_SECONDS`) and encoded into one L2-normalized embedding.
   Raw audio never leaves the workstation — only the vector is sent, inside the normal
   result payload (`voice_identification`).
2. **Central (arithmetic, not inference).** `services/voice_matching.py` compares the
   embedding against `voice_enrollments`, and records a suggestion on the speaker row
   when — and only when — all of these hold:
   * the enrolment was produced by the **same model** (embeddings are not comparable across models);
   * the best score ≥ `CENTRAL_VOICE_MATCH_THRESHOLD` (default **0.65**);
   * the best score beats the runner-up by ≥ `CENTRAL_VOICE_MATCH_MARGIN` (default 0.05) —
     otherwise the result is ambiguous and the system **abstains**.

   Candidates are grouped by `person_reference` **before** the margin is applied, and each
   person is represented by their best print. Several prints of one person therefore
   reinforce each other; the margin only ever separates two *different people*. Identity is
   the reference, never the display name — two people share a common name often enough that
   merging them would let the matcher confidently suggest the wrong person.
3. **Investigator.** The speakers tab shows `اقتراح: <name> (score)` with تأكيد / تجاهل.
   Confirming copies the name into `display_name` and requires `speakers.assign` — the same
   permission as typing the name by hand. Rejecting keeps the suggestion for the audit trail.

## Calibration

Measured on the reference Arabic recording (two TTS voices, 5 samples):

```
same speaker      0.755 – 0.898   (mean 0.818)
different speaker 0.343 – 0.522   (mean 0.436)
margin                    +0.232
```

The default threshold 0.65 sits in the middle of that gap. **Recalibrate on your own
recordings before operational use** — room acoustics, microphones and telephone audio all
shift these numbers. Raise the threshold to reduce false suggestions; lower it to get more
(each still requires human confirmation).

## Enrolment (creating a voice template)

* Created only from a speaker in an existing session whose identity is already established,
  through `POST /api/investigations/{id}/speakers/{speaker_id}/enroll`.
* **Consent is mandatory**: the request is refused with `consent_required` unless
  `consent_recorded` is true. The flag, the enrolling user and the source session/speaker
  are stored with the template.
* **Several prints per person are supported and encouraged** — enrol the same person again
  from a different session to cover other recording conditions. Use the *same*
  `person_reference` each time; that is what ties the prints together.
* A reference already registered under a **different** name is refused with
  `person_reference_name_mismatch`. Mis-filing a biometric template under someone else's
  identity is the one mistake this area must not make quietly.
* Deactivate (`is_active=false`) to stop future suggestions without destroying the record;
  delete to remove it entirely. Names already **confirmed** by a human are unaffected.

## Re-scanning after a later enrolment

Matching runs when the agent submits its result. A session processed **before** a person was
enrolled would therefore never receive a suggestion, however many prints are added later.
Two actions close that gap, using only embeddings already stored — no audio is reprocessed
and no model runs:

| Where | Action | Scope |
|---|---|---|
| A session's المتحدثون tab | **إعادة فحص البصمات** | that session |
| بصمات الأصوات page | **إعادة فحص الجلسات غير المحددة** | every speaker still at `NONE` |

`POST /api/investigations/{id}/voice-rematch` and `POST /api/voice-enrollments/rematch`,
both requiring `voice.identify`. **Confirmed and rejected speakers are never touched** — a
human decision stands — and every run is audited as `VOICE_REMATCH_RUN` with its counts.

A speaker whose embedding predates the recording of its producing model is skipped rather
than guessed at; embeddings are only ever compared within the model that made them.

## Consolidating a person enrolled under several references

Before multiple prints were supported, re-enrolling a person was refused, so operators
worked around it by inventing a new reference number for the same human. Those rows now
look like **different people**, and two of them scoring alike makes the matcher abstain —
suppressing suggestions for exactly the person who is best enrolled.

Check for it:

```sql
SELECT person_name, count(DISTINCT person_reference) AS refs,
       string_agg(DISTINCT person_reference, ', ') AS which
FROM voice_enrollments WHERE is_active GROUP BY 1 HAVING count(DISTINCT person_reference) > 1;
```

Consolidate onto the person's real identifier, then re-scan. This is deliberately a manual
step: the system cannot safely decide that three reference numbers are one human.

```sql
UPDATE voice_enrollments SET person_reference = '<the real ID number>'
WHERE person_name = '<the person>' AND person_reference IN ('<old-1>', '<old-2>');
```

## Permissions and privacy

| Permission | Grants |
|---|---|
| `voice.identify` | see suggestions, confirm/reject, list enrolment metadata |
| `voice.enroll` | create, update and delete voice templates |

Both are granted to ADMIN and INVESTIGATOR; the read-only USER role has neither.
**Embeddings are never returned to a browser** and never written to the audit log — the
API exposes only metadata, scores and names. Audit events: `VOICE_ENROLLED`,
`VOICE_ENROLLMENT_DELETED`, `VOICE_IDENTITY_SUGGESTED`, `VOICE_IDENTITY_CONFIRMED`,
`VOICE_IDENTITY_REJECTED`, each carrying the score, model and revision.

A speaker's own embedding is stored on the speaker row so that enrolling someone later can
re-match earlier sessions without reprocessing audio.

## Using it in the application

**Speakers tab (تبويب المتحدثون)**

* A pending suggestion appears above the speaker as a highlighted banner:
  `اقتراح بناءً على بصمة الصوت: <name>` with `درجة التطابق: NN%`, the disclaimer
  "هذا اقتراح آلي ولا يُعتمد إلا بعد تأكيد المحقق." and two buttons:
  **تأكيد الاقتراح** / **تجاهل الاقتراح**.
  الاسم المعروض stays **empty** until the investigator confirms.
* After a decision the banner becomes a badge: `مؤكَّد من المحقق` or `مرفوض من المحقق`.
* **تسجيل بصمة الصوت** next to تعيين الاسم opens the enrolment dialog. It is disabled
  until the speaker has a name, and the submit button stays disabled until
  **تم الحصول على الموافقة وتوثيقها** is ticked.

**بصمات الأصوات page** (sidebar → الإدارة, requires `voice.identify`)

Lists every template with the person, reference, model + revision, sample length, source
session, consent flag, active state and who enrolled it. Holders of `voice.enroll` can
تعطيل / تفعيل (stop or resume future suggestions) or حذف البصمة (permanent). Confirmed
names are never affected by deactivating or deleting a template.

## Provisioning

```bash
python scripts/provision_models.py --model-dir ./models --only speaker_id
```

Downloads from NGC, verifies the pinned SHA-256 and writes `MANIFEST.json`. Afterwards the
workstation runs fully offline like the other models. To disable the feature entirely:
`AGENT_SPEAKER_ID_ENABLED=false`.

## Failure behaviour

Identification is strictly optional. If the model is missing, fails to load, or a speaker
has less than `AGENT_SPEAKER_ID_MIN_SECONDS` of speech, that speaker simply gets no
embedding and no suggestion — the transcript is produced and synchronized exactly as
before. Nothing about diarization or transcription depends on it.
