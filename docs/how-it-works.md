# How the system works

This document follows **one recording** from the microphone to the finished Arabic
transcript, naming the real files and functions at each step. Read
[architecture.md](architecture.md) first for the shape; this one explains the mechanism.

---

## 0. The one idea the whole design rests on

Three different models each answer exactly one question, and none of them is allowed to
answer another model's question:

| Question | Answered by | Where it runs |
|---|---|---|
| **من تكلّم ومتى؟** *(who spoke when)* | NVIDIA Sortformer | investigator's desktop |
| **ماذا قيل؟** *(what was said)* | Cohere Transcribe Arabic | investigator's desktop |
| **كيف يبدو هذا الصوت؟** *(what does this voice sound like)* | NVIDIA SpeakerNet-M | investigator's desktop |
| **من هو هذا الشخص؟** *(who is this person)* | **the investigator** | central web UI |

Sortformer never produces text. Cohere never decides who is speaking. SpeakerNet never
assigns a name — it only proposes one that a human must confirm. The central server never
runs a model at all; it stores, authorises and audits.

Everything else in the system exists to make that separation safe, offline and auditable.

---

## 1. Two programs, one workflow

```
┌─────────────────────── CENTRAL SERVER (one per unit, Docker) ───────────────────────┐
│  nginx ──▶ frontend (React, Arabic RTL, static)                                     │
│        └─▶ backend (FastAPI)  ──▶  PostgreSQL                                       │
│                                └─▶  /storage  (original audio, ID scans)            │
│  Owns: users, roles, sessions, subjects, transcripts, speakers, voice templates,     │
│        workstation registry, audit log. Runs NO AI.                                 │
└───────────────────────────────────┬─────────────────────────────────────────────────┘
                                    │  HTTPS (LAN)
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
   DESKTOP 01                  DESKTOP 02                  DESKTOP 03
   Local AI Agent on 127.0.0.1:17117 — FFmpeg · Silero VAD · Sortformer · Cohere · SpeakerNet
   Runs ALL the AI. Reachable only from that machine's own browser.
```

The agent is deliberately *not* a second backend: it has no users, no sessions and no
business rules. It accepts an authorised job, processes audio, and reports back.

---

## 2. Following one recording, step by step

### Step 1 — The investigator creates a session

`POST /api/investigations` → `central/backend/app/api/investigations.py`

A session number is generated (`INV-2026-00042`), investigators are assigned, and the
interviewed person is recorded (see [subject-identity.md](subject-identity.md)).
Status: **DRAFT**.

### Step 2 — Recording or uploading audio

The browser records with `MediaRecorder` (`components/recording/Recorder.tsx`) or takes a
file. Nothing is uploaded yet — the audio is held in the browser.

### Step 3 — The frontend asks permission to process

`POST /api/investigations/{id}/local-processing-token`

The central server checks the user is authenticated, active, holds `processing.request`
and can access *this* session. It then:

1. creates an `audio_recordings` row (`PENDING`) and a `local_processing_jobs` row,
2. mints a **short-lived ES256 token** (`core/processing_tokens.py`) containing
   `job_id, session_id, recording_id, user_id, jti (nonce), iat, nbf, accept_by, exp,
   allowed_action=process_recording` — and **no secrets**,
3. moves the session to **PROCESSING**.

Two independent clocks live in that token:

* `accept_by` (**10 min**) — how long the agent may *start* the job;
* `exp` (**24 h**) — how long results may still be *synchronised* after a network outage.

The private signing key never leaves the central server. Workstations hold only the
public key.

### Step 4 — The browser hands the audio to the local agent

`POST http://127.0.0.1:17117/jobs` with the token + the audio blob.

`desktop-agent/app/security/token_validation.py` verifies, in order: signature (public
key), issuer, audience, `nbf`/`exp`, `allowed_action`, `accept_by`, and finally that the
**nonce has never been seen on this workstation** (SQLite `nonces` table) — replaying a
token is refused with `token_replay`.

A random web page cannot do this: it is not in the agent's CORS allow-list and it cannot
obtain a token.

### Step 5 — The local pipeline

`desktop-agent/app/jobs/pipeline.py`. Each stage reports its state to the central server,
which turns them into audit events and drives the Arabic progress display.

```
CREATED → RECEIVING_AUDIO → PREPROCESSING → DIARIZING → TRANSCRIBING → FINALIZING → SYNCING → COMPLETED
```

**PREPROCESSING** — `audio/preprocessing.py`
Validates extension, MIME, size, **magic bytes** (the filename is never trusted),
readability and duration via `ffprobe`. Computes SHA-256 of the original. FFmpeg then makes
a **16 kHz mono 16-bit PCM** working copy. *The original is never modified.*

**DIARIZING** — `ai/vad_service.py` + `ai/diarization_service.py`
Silero VAD finds speech regions, so silence never reaches the STT model. Sortformer then
answers *who spoke when*, producing turns like `0.00 5.12 speaker_0`. Post-processing:

* `parse_nemo_segments` normalises labels → `SPEAKER_00`…
* `relabel_by_first_appearance` — `SPEAKER_00` is always whoever spoke first
* `mark_overlaps` — turns of different speakers overlapping ≥ 0.2 s get `is_overlap=true`

**Grouping is the key property**: when the first speaker talks again after the second, the
model returns the *same* label. That is what makes it diarization rather than mere
speaker-change detection.

**TRANSCRIBING** — `ai/segment_service.py` + `ai/transcription_service.py`
Turns are shaped into good STT inputs (pure functions, fully unit-tested):

1. `trim_to_vad` — clip to actual speech
2. `drop_tiny` — discard fragments < 0.3 s
3. `merge` — join consecutive same-speaker fragments ≤ 0.7 s apart, **never across another
   speaker**
4. `split_long` — cut > 28 s turns at the widest internal silence
5. `build_windows` — add 0.3 s of context each side, **clamped to half the gap** to the
   neighbouring segment, so two windows can never contain the same audio → no duplicated
   words. Overlapping speech is the one deliberate exception: both speakers keep their own
   window and are flagged, because hiding a voice would misattribute speech.

Cohere then transcribes each window. Speaker attribution comes *only* from diarization;
the text comes *only* from Cohere.

**FINALIZING** — one embedding per speaker (SpeakerNet), then `result.json` is written
containing segments, model names **and pinned revisions**, device, timings and warnings.

### Step 6 — Synchronisation (survives network loss)

`sync/sync_worker.py`. The result is durable on disk *before* any network call.

```
POST /api/local-processing/{job}/result   ← transcript + embeddings + provenance
POST /api/local-processing/{job}/audio    ← the original file; central re-checks SHA-256
```

`idempotency_key` makes retries safe: a repeat returns `duplicate: true` and the *same*
transcript id instead of creating a second one. Network failures retry with exponential
backoff (5 s → 10 min, forever by default); permanent rejections stop retrying. A finished
transcript is never lost because the central server was unreachable.

### Step 7 — The central server stores it

`api/processing.py::submit_result` writes the transcript, its segments (ordered by time),
and creates a `session_speakers` row per anonymous label. Then it calls the voice matcher
(below) and sets the session to **COMPLETED**.

### Step 8 — The investigator reads and corrects

The **النص المفرغ** tab plays the original audio, and clicking a segment seeks the player to
that timestamp. Editing writes `edited_text` — **`original_text` is never overwritten**, so
the AI output and the human correction both survive, with who changed it and when.

---

## 3. How a speaker gets a name

Three independent routes, in increasing order of assistance:

**a. Typing it.** Free text in الاسم المعروض.

**b. Suggested from the session** (`components/transcript/SpeakersPanel.tsx`).
The people already recorded in this جلسة — assigned investigators and listed subjects —
appear as one-click chips. Picking one fills the الصفة too, but never overrides a role the
investigator set deliberately. No AI involved.

**c. Suggested from the voice** (SpeakerNet-M).

```
agent  : one 256-d embedding per anonymous speaker   (the model runs locally)
         ↓ sent with the result — raw audio never leaves the workstation
central: cosine similarity vs voice_enrollments      (arithmetic, not inference)
         ↓ writes a SUGGESTION only
UI     : "اقتراح: الرائد علي حسن — درجة التطابق 81%"   [تأكيد] [تجاهل]
         ↓ تأكيد   ← the ONLY path to display_name
```

The matcher **abstains** rather than guesses: no suggestion below **0.65**, and none when
the two best *people* are within **0.05** of each other. Candidates are grouped by
`person_reference` first, so several prints of one person reinforce each other instead of
looking like rivals. Embeddings are only compared within the model that produced them.
Measured separation on the reference Arabic recording: same speaker **0.755–0.898**,
different speakers **0.343–0.522**.

Matching runs when the result is submitted, and again whenever an investigator asks for a
re-scan — needed because a voice enrolled *after* a session was processed would otherwise
never reach it. A re-scan never touches a speaker a human has already confirmed or
rejected.

Full detail, including consent and calibration:
[speaker-identification.md](speaker-identification.md).

---

## 4. Why it stays trustworthy

**Nothing is destroyed.** The original audio (SHA-256 verified end to end), the original
transcript text, and every rejected suggestion are all retained.

**Every AI output carries its provenance.** Each transcript records the STT model *and
revision*, the diarization model *and revision*, the VAD model, the agent version and the
processing device. Two years later you can say exactly which software produced a line.

**The machine never decides identity.** `display_name` is written only by a human action.

**Everything is audited.** Login, user changes, session changes, every processing stage,
transcript edits, speaker renames, document views, voice enrolments and every
confirm/reject — with the actor, the time and sanitised metadata. Passwords, tokens, keys
and biometric embeddings are stripped before anything is written
(`services/audit.py`).

**Failures are explicit.** If a model is missing or fails, the job fails with an Arabic
message and the recording is **never** sent to any external service — there is no cloud
fallback, no Whisper, no central inference.

---

## 5. Security in one page

| Boundary | Protection |
|---|---|
| User → central | Argon2id passwords, JWT HS256 (8 h), RBAC + per-session resource checks; sessions you may not see return **404**, not 403 |
| Browser → agent | loopback only (`127.0.0.1`), CORS restricted to the central origin, Private-Network-Access preflight, no cookies |
| Agent → central | ES256 job token, one job, nonce replay-protected, two expiry windows; private key never on a workstation |
| Uploads | allow-listed types, magic-byte sniffing, size caps, sanitised names, UUID paths inside the storage root, SHA-256 |
| ID scans | separate `subjects.documents.view` permission; PDFs always `attachment`; token never in a URL |
| Voice templates | separate `voice.enroll` / `voice.identify`; consent mandatory; embeddings never sent to a browser or the audit log |

Details: [security.md](security.md).

---

## 6. Offline operation

After one-time provisioning the workstation needs **no Internet at all**:

| Model | Source | Size |
|---|---|---|
| `CohereLabs/cohere-transcribe-arabic-07-2026` | Hugging Face (**gated** — accept the licence, `HF_TOKEN` for the download only) | 4.13 GB |
| `nvidia/diar_streaming_sortformer_4spk-v2.1` | Hugging Face | 471 MB |
| `nvidia/speakerverification_speakernet` | NVIDIA NGC (public) | 21.85 MB |
| Silero VAD | bundled inside the `silero-vad` wheel | — |

Every model directory carries a `MANIFEST.json` with the pinned revision and a SHA-256 per
file, verified before loading. Fonts, JS and CSS are bundled — no CDN. Models are loaded
lazily on first use and stay resident.
See [offline-provisioning.md](offline-provisioning.md).

---

## 7. Known limits

* **Four speakers.** Sortformer 4spk supports at most four. The session form warns above
  that, and a transcript that hits the limit carries a warning.
* **CPU is slow.** Measured on a CPU-only laptop: models load in ~1 min 47 s, transcription
  runs at roughly real time (RTFx 1.1). A CUDA GPU is strongly recommended for production.
* **Voice threshold needs local calibration.** 0.65 was measured on synthesised voices;
  recalibrate on real interview recordings before operational use.
* **Overlapping speech** is flagged, not separated — no source separation in this version.
* **A restart during processing fails that job**; it is not resumed. The recording is
  intact, so it can simply be processed again.
