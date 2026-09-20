# Speaker identification (SpeakerNet-M)

> **Updated identity model:** Person reference numbers have been removed. People now use internal UUIDs. See [the current identity contract and migration](person-identity-migration.md). Reference-number descriptions below document the earlier implementation.

**Who this is for:** developers, and administrators tuning the matching thresholds.

**Enrolling a voice in practice?** Read [voice-enrollment-guide.md](voice-enrollment-guide.md).

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

   Candidates are grouped by **canonical identity** before the margin is applied, and each
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

## Who a print belongs to

Every print points at a row in the canonical person registry, keyed by الرقم المرجعي — which
is now [derived from the identifiers already recorded](subject-identity.md#الرقم-المرجعي--derived-not-typed)
rather than typed. That row is the authority for a person's **current** name and reference.

The `person_name` and `person_reference` stored on a print are a **snapshot of what was
recorded when it was taken**. They are kept as history and are never consulted for current
identity, so renaming a person updates one registry row and every print follows.

Merging two references keeps the merged row as an **alias**: it can never be recreated, and a
stale client submitting it resolves forward to the survivor.

A print whose `identity_id` is NULL is **dropped before scoring**, not merely ignored at the
end. It is biometric evidence attributed to nobody: it cannot name a speaker, so it must not
compete in the ranking either — a rival with no person behind it can only push a real match
below the margin and turn a correct answer into an abstention.

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

Check for it — note that this groups by the **identity** the prints point at, which is what
the matcher actually uses:

```sql
SELECT e.identity_id, i.person_name, count(*) AS prints
FROM voice_enrollments e JOIN person_identities i ON i.id = e.identity_id
WHERE e.is_active GROUP BY 1, 2 ORDER BY i.person_name;
```

Two rows with the same person under different `identity_id`s is the problem case.

Consolidate the identities, then re-scan. This is deliberately a manual step: the system
cannot safely decide that three reference numbers are one human.

```
POST /api/voice-enrollments/people/{identity_id}/consolidate
     { "into_identity_id": "<the surviving person>" }
```

It merges the two registry rows and repoints every print, subject and speaker in one
transaction, keeping the merged reference as an alias. It requires `voice.enroll` **and**
`investigations.read_all` (ADMIN in practice), because consolidation rewrites ownership
across sessions the caller may not be able to open.

> **Do not do this with `UPDATE voice_enrollments SET person_reference = …`.** That column is
> a historical snapshot of what was recorded the day the print was taken; matching groups by
> `identity_id`. Rewriting it consolidates nothing — the two identities go on competing and
> the matcher goes on abstaining — while looking like it worked.

## Checking one person's prints against each other — فحص البصمات الصوتية

Consolidation fixes one person split across identities. The opposite failure — **two
people's voices filed under one identity** — is worse for matching (the wrong voice matches
at ~1.0 forever) and invisible from counts alone. The per-person check makes it measurable:

```
POST /api/voice-enrollments/people/{identity_id}/biometric-check   (voice.identify)
```

The **فحص البصمات الصوتية** button on each person row of بصمات الأصوات calls it. In one
pgvector statement the server computes every pairwise cosine between that person's **active**
prints (per model/dimension/revision/provider group — incompatible prints are never compared), then links
prints that reach **عتبة اقتراح الهوية** and reports the **connected components**:

* **1 component** — every print reaches every other, directly or through siblings: coherent.
* **2+ components** — separate sets or incompatible model groups → `REVIEW_REQUIRED`.
  This is not proof of different people: recording conditions also affect similarity.
  The system never guesses which
  component is the real person; each print links to its source session so a human can listen
  and decide.

Per print it reports the best/worst similarity to a sibling, how many siblings it reaches,
its component number, and a status: `COHERENT`, `ISOLATED` (reaches none), `NEAR_DUPLICATE`
(≥ عتبة البصمة شبه المكررة — possible redundancy, requiring source review), or
`SINGLE_PRINT`. Components matter because max-similarity alone cannot see a split identity:
in A↔B = 0.84, C↔D = 0.86, cross ≈ 0.40, every print has an excellent peer — and there are
still two computed components.

The check is **advisory and read-only**: it runs only when pressed (never at enrolment,
never on page load, never registry-wide), it deactivates/deletes/merges/re-assigns nothing,
and no vector ever reaches the browser or the logs. Each run leaves one log line (see the
table below). The result also provides source A/B playback and explicit, separately saved
notes, flags, review resolution and deactivation with reasons.

**Manual same-person sets:** select 2–100 active samples within one component or across
components/model groups, then save **تأكيد وحدة الهوية** with a reason. The decision covers
only those print IDs and their reviewed update timestamps. `ACTIVE`, `STALE` and `REOPENED`
describe the human decision independently of `overall_status` and the numerical components.
No vectors, scores, matching thresholds or canonical identities are changed. New samples
do not inherit confirmation. Reopening appends a reasoned event and retains the original.
Details and API contracts: [voice-review-panel.md](voice-review-panel.md).

## Permissions and privacy

| Permission | Grants |
|---|---|
| `voice.identify` | see suggestions, confirm/reject, list enrollment metadata, run the check and read review/confirmation history |
| `voice.enroll` | create, update and delete templates; save print reviews, confirm same-person sets and reopen them |

Source listening additionally requires `transcripts.read` and access to the investigation.

Both are granted to ADMIN and INVESTIGATOR; the read-only USER role has neither.
**Embeddings are never returned to a browser** and never written to the audit log — the
API exposes only metadata, scores and names. Audit events: `VOICE_ENROLLED`,
`VOICE_ENROLLMENT_DELETED`, `VOICE_IDENTITY_SUGGESTED`, `VOICE_IDENTITY_CONFIRMED`,
`VOICE_IDENTITY_REJECTED`, with action-specific metadata. Review actions use
`VOICE_PRINT_REVIEWED`; set decisions use `VOICE_IDENTITY_SET_CONFIRMED` and
`VOICE_IDENTITY_SET_REOPENED`, recording reasons and print references without vectors.

A speaker's own embedding is stored on the speaker row so that enrolling someone later can
re-match earlier sessions without reprocessing audio.

## Using it in the application

**Speakers tab (تبويب المتحدثون)**

* One card represents each canonical person, with expandable recording observations.
  Same-name people are not merged; unidentified observations remain separate. Source
  filenames identify the observations, with `SPEAKER_*` codes in **تفاصيل المصدر**.
* Session speaking totals use the latest transcript per recording, avoiding both missing
  older recordings and double-counting reprocessing. Each observation retains its own controls.

* A pending suggestion appears above the speaker as a highlighted banner:
  `اقتراح بناءً على بصمة الصوت: <name>` with `درجة التطابق: NN%`, the disclaimer
  "هذا اقتراح آلي ولا يُعتمد إلا بعد تأكيد المحقق." and two buttons:
  **تأكيد الاقتراح** / **تجاهل الاقتراح**.
  الاسم المعروض stays **empty** until the investigator confirms.
* After a decision the banner becomes a badge: `مؤكَّد من المحقق` or `مرفوض من المحقق`.
* **تسجيل بصمة الصوت** sits next to **اختيار الشخص**, the single control that binds a
  speaker to a person. It is disabled until the speaker has **both** a canonical identity
  and a voice embedding, and the tooltip names whichever is missing. The submit button in
  the dialog stays disabled until **تم الحصول على الموافقة وتوثيقها** is ticked.
* A free-text label (**تسمية مؤقتة**) never enables enrolment: a print is filed against a
  person, not a string. The card says so plainly —
  *لن يظهر في بصمات الأصوات حتى تُحدَّد هويته*.

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

## A speaker observation belongs to ONE recording

A diarizer's `SPEAKER_00` is a cluster index local to one audio file. When a session holds
several recordings, each recording's clusters become **separate speaker rows** under the next
free session-wide label:

```
recording 1: local SPEAKER_00 -> SPEAKER_00   (identified as علي عباس, enrolled)
recording 2: local SPEAKER_00 -> SPEAKER_01   (a different human - starts غير معروف)
recording 3: local SPEAKER_00 -> SPEAKER_02   (Ali again - SUGGESTED at 0.9+, confirmed by a human)
```

This replaced a defect where all recordings shared one row per label: a person confirmed in
recording 1 was silently inherited by whoever spoke next - measured live, a voice scoring
**0.5372** against the confirmed person (a different-speaker score; same-speaker is
0.755-0.898) still displayed as them, and the row's stored voiceprint had been overwritten
with the stranger's voice. Reprocessing the *same* recording still reuses its rows
(observations are keyed on recording + source label), so re-runs never duplicate speakers.

Whether two observations are the same human is decided the same two ways as ever: biometric
suggestion above the threshold, or the investigator picking the person. Nothing is ever
inherited from "the last identified speaker".

## Matching runs inside PostgreSQL (pgvector)

All of a recording's probes are matched in **one SQL statement** against the whole eligible
gallery: `1 - (embedding <=> probe)` is the same cosine similarity as before (embeddings are
L2-normalised; pgvector stores float4, so scores agree to ~1e-4). Prints still collapse to
each person's best, identities are ranked, and the decision uses the same 0.65 threshold and
0.05 margin - the policy lives in one shared function, so the SQL path and the in-memory
reference (`best_match`, kept for the unit tests) cannot disagree.

The gallery filter is exactly: active, canonical identity present, same model, same
dimension. It is **never** filtered by session, subjects or recording - a person enrolled on
another case is still recognised here.

Every stage of the similarity workflow logs its part - and never the vectors themselves:

| Stage | Where | Logger / line |
|---|---|---|
| Speech collected per speaker | desktop agent | `speaker SPEAKER_00 embedded: 3 span(s), 14.2s speech, 14.2s used (cap 30s) -> dim=256 norm=1.0000 in 840ms` (skips say why: `no embedding for ... (speaker_id_audio_too_short) - 1 span(s), 1.4s of speech`) |
| Probe stored centrally | `app.services.voice_matching` DEBUG | `probe stored session=... recording=... speaker=SPEAKER_01 (source=SPEAKER_00) dim=256 model=...` - and skips: `human decision CONFIRMED is final` |
| The pgvector batch | `app.services.voice_matching` INFO | `voice batch: 2 probe(s) x 3 candidate identities (7 print comparison(s)) model=... threshold=0.65 margin=0.05 in 43ms` |
| The complete field | `app.services.voice_matching` DEBUG | `voice ranking probe=...: 1) <identity> 0.8412, 2) <identity> 0.5372, 3) ...` - every eligible identity, ranked |
| The verdict | `app.services.voice_matching` INFO | `voice decision ... decision=UNKNOWN best=0.5372 runner_up=- threshold=0.65 margin=0.05 prints=1 candidates=2` |
| The SQL itself | `app.sql` DEBUG | the batch statement with its duration |
| A manual print-coherence check | `app.api.voice` INFO | `biometric check identity=... person=علي عباس prints=6 components=3 status=REVIEW_REQUIRED thresholds=0.65/0.98` |

All lines carry the request id, so one grep of `storage/logs/backend.jsonl` reconstructs a
recording's entire identification story. To see the DEBUG detail on a running server, set
`app.services.voice_matching=DEBUG` in **إعدادات النظام** (and turn it back off after).

## One name, everywhere

Anything showing *who a person is* reads the canonical `person_name` from `person_identities`,
resolved through merges — the speaker picker, the speaker card, بصمات الأصوات and the registry
search alike. The enrolment-time snapshot on a print (`enrolled_person_name`) is history and is
never presented as the current answer.

The rank is deliberately outside that name. It is shown next to it where a source row carries
one, and never concatenated into stored text, because `person_identities` has no rank column
and a "MAJOR ALI" written into one screen can never match the "ALI" the registry returns.

## Failure behaviour

Identification is strictly optional. If the model is missing, fails to load, or a speaker
has less than `AGENT_SPEAKER_ID_MIN_SECONDS` of speech, that speaker simply gets no
embedding and no suggestion — the transcript is produced and synchronized exactly as
before. Nothing about diarization or transcription depends on it.

`AGENT_SPEAKER_ID_MIN_SECONDS` (default **2.0**) is measured against a speaker's **total**
speech in the session, not their longest turn: `collect_speaker_audio` concatenates all of
that speaker's spans before the check. A person who says three separate sentences of 1.5 s
each has 4.5 s and is embedded normally.

### Checking that the capability is actually present

Optional-and-silent is convenient until it hides a deployment fault, because on the speaker
card a missing *capability* and a missing *embedding* look identical. Read the model state
directly:

```bash
curl -s http://127.0.0.1:17117/model-status | python -m json.tool | grep -A 8 speaker_id
```

```json
"speaker_id": {
  "provider": "nemo_speakernet",
  "model": "nvidia/speakerverification_speakernet",
  "state": "PROVISIONED",
  "extra": { "device": "cpu", "embedding_dim": 256, "enabled": true, "min_seconds": 2.0 }
}
```

`PROVISIONED` means the file is found but not yet loaded — normal before the first job.
`READY` means loaded. `NOT_PROVISIONED` means the `.nemo` is not where the agent expects it.

**If the `speaker_id` key is absent from the response altogether**, the agent predates the
feature and must be redeployed; no amount of reprocessing will produce an embedding. The
same states are shown in the recording tab as **حالة نموذج بصمة الصوت**, beside STT and
diarization, where an agent that does not report the model at all reads **غير معروف**.

A result payload from a working agent carries a `voice_identification` block. One where the
key is **missing entirely** — as opposed to `null` — was produced by a build from before this
feature existed.
