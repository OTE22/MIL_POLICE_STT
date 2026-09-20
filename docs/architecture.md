# Architecture

**Who this is for:** developers, and anyone evaluating the design. It explains the shape of
the system rather than how to use it.

## 1. Two parts, one workflow

| Part | Runs | Owns |
|---|---|---|
| **Central server** (Docker Compose) | One LAN server | authentication, users/roles/permissions, investigator profiles, sessions, subjects, audio storage, transcripts, segments, speaker mappings, workstation registry, audit log, configuration |
| **Local AI Agent** (one per investigator desktop) | Windows service / systemd / Docker | audio validation, FFmpeg preprocessing, VAD, NVIDIA diarization, Cohere Arabic STT, segment post-processing, durable result synchronization |

The AI never depends on one central GPU: every desktop processes its own recordings.
Authoritative business data lives centrally; the agent is not a second backend.

## 2. Investigation workflow

```
Investigator logs in (JWT)
   └─ creates an investigation session (metadata, investigators, subject)
        └─ opens "التسجيل": records in the browser (MediaRecorder) or uploads WAV/MP3/M4A/WEBM
             └─ frontend  POST /api/investigations/{id}/local-processing-token
                  central validates permission + resource access, creates recording + job rows,
                  signs a short-lived ES256 processing token
             └─ frontend  POST http://127.0.0.1:17117/jobs  (token + audio)
                  agent verifies the token (public key), stores the original, queues the job
             └─ agent pipeline:  PREPROCESSING → DIARIZING → TRANSCRIBING → FINALIZING → SYNCING
                  progress reported to central (/state) and polled by the frontend (/jobs/{id})
             └─ agent  POST /api/local-processing/{job}/result   (idempotent, retried)
                       POST /api/local-processing/{job}/audio    (original file, SHA-256 checked)
                  central stores transcript + segments + anonymous speakers, session → COMPLETED
   └─ investigator opens "النص المفرغ": plays audio, clicks segments to seek, corrects text
        (original_text is never overwritten), maps SPEAKER_00 → المحقق, SPEAKER_01 → أحمد محمد
   └─ every action is written to audit_logs
```

## 3. AI responsibility separation

```
NVIDIA Sortformer   =  WHO SPOKE WHEN   (anonymous SPEAKER_00 … SPEAKER_03, timestamps, overlap)
Cohere Transcribe   =  WHAT WAS SAID    (Arabic text for each speaker turn)
segment_service     =  combines them    (speaker + start + end + text + is_overlap)
```

NVIDIA ASR is never used. Cohere never identifies speakers. The separately added SpeakerNet
voice-print workflow can suggest an identity; only a human confirms the assignment.
The central server compares compatible embeddings using pgvector, without AI inference.
Manual same-person confirmations across selected prints preserve the vectors and computed
groups. See [speaker-identification.md](speaker-identification.md) and
[voice-review-panel.md](voice-review-panel.md).

## 4. Local pipeline

```
Original audio (never modified, SHA-256 recorded)
  → validation: extension, MIME, magic bytes, size, ffprobe readability, duration
  → FFmpeg: WAV 16 kHz mono PCM processing copy
  → Silero VAD: speech regions (configurable thresholds)
  → NVIDIA Sortformer: speaker turns (streaming config "very high latency" preset)
  → segment_service: trim to VAD, drop tiny fragments, merge same-speaker turns (never across
    another speaker), split long turns at silences, add clamped context padding
  → Cohere Transcribe Arabic: one inference per segment window
  → result.json (structured transcript + model revisions + processing metadata)
  → durable SQLite outbox → central FastAPI → PostgreSQL
```

## 5. Central Docker services

| Service | Image | Role |
|---|---|---|
| `postgres` | postgres:16-alpine | data; also creates `<db>_test` for the isolated test-suite |
| `backend` | military-stt/central-backend | FastAPI + Alembic migrations on start + bootstrap admin |
| `frontend` | military-stt/central-frontend | nginx serving the built React app (static, no CDN) |
| `nginx` | nginx:1.27-alpine | reverse proxy: `/api/` → backend, `/` → frontend, TLS on 443 |

No Redis, no Celery, no message broker: the only background work is local on the desktops.

## 6. Trust boundaries

* Browser ↔ central: HTTPS, user JWT (HS256, server secret).
* Browser ↔ agent: loopback only (`127.0.0.1:17117`), CORS restricted to the central
  frontend origin, Private-Network-Access preflight header, no cookies.
* Agent ↔ central: processing token (ES256 signed by the central private key; the desktop
  only has the public key), one token per job, nonce replay protection, acceptance window.
* Workstation secrets: none. The agent stores only job tokens (scoped to one job) until the
  job is synchronized.
