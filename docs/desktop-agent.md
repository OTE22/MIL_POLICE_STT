# Local AI Agent (desktop-agent/)

## Structure

```
desktop-agent/app/
├── main.py                 FastAPI app, loopback guard, CORS + Private-Network-Access middleware
├── config.py               AGENT_* settings, pinned model revisions, MAX_SUPPORTED_SPEAKERS = 4
├── api/health.py           GET /health /capabilities /model-status, POST /models/load
├── api/jobs.py             POST /jobs, GET /jobs, GET /jobs/{id}, POST /jobs/{id}/cancel, POST /jobs/sync/run
├── security/token_validation.py   ES256 verification with the central public key + nonce store
├── audio/ffmpeg_service.py        ffprobe / ffmpeg wrappers
├── audio/preprocessing.py         validation, SHA-256, 16 kHz mono copy
├── ai/types.py                    SpeechRegion, SpeakerTurn, TranscriptSegment, ModelInfo
├── ai/device.py                   CUDA detection, device/dtype resolution
├── ai/vad_service.py              Silero VAD
├── ai/diarization_service.py      DiarizationService interface + NvidiaSortformerDiarizationService
├── ai/transcription_service.py    TranscriptionService interface + CohereLocalTranscriptionService
├── ai/speaker_id_service.py       SpeakerNet-M embeddings (optional; never fatal)
├── ai/segment_service.py          turn post-processing + STT windows (pure functions)
├── ai/model_files.py              MANIFEST.json integrity checks
├── ai/runtime.py                  resident models, lazy / background loading
├── jobs/store.py                  SQLite: jobs, outbox state, job tokens, nonces
├── jobs/pipeline.py               the state machine for one job
├── jobs/job_manager.py            queue (1 worker), cleanup, workstation identity
└── sync/central_client.py, sync/sync_worker.py   durable synchronization with retries
```

The agent is intentionally small: no users, no sessions, no business rules — those live
centrally. It only processes authorized jobs and reports back.

## API

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness: agent id, version, device name, uptime |
| `GET /capabilities` / `GET /model-status` | device (cuda/cpu, GPU name), FFmpeg, **STT / diarization / VAD / speaker_id** model state (`NOT_PROVISIONED, PROVISIONED, LOADING, READY, ERROR`), max speakers, formats, readiness, busy flag, central sync enabled, public key installed |
| `POST /models/load` | trigger background model loading (warm-up); returns the full `runtime.status()` |

`ready` deliberately means **STT and diarization only**. Speaker identification is optional,
so an agent with no `speaker_id` model is still `ready: true` and transcribes normally — check
the `speaker_id` block itself to know whether voice prints will be produced. An agent whose
response has **no `speaker_id` key at all** predates the feature and needs redeploying.
| `POST /jobs` (multipart: `processing_token`, `file`) | validates the token, stores the original audio, queues the job → `202 { job_id, state … }` |
| `GET /jobs/{id}` | state, sync_state, progress, message, error_code/message, failure_stage, speaker/segment counts, warnings |
| `POST /jobs/{id}/cancel` | cooperative cancellation (checked between stages and segments) |
| `GET /jobs`, `POST /jobs/sync/run` | job list; force an immediate sync retry |

Errors: `{"detail": {"code": "...", "message": "..."}}` — codes such as `token_invalid`,
`token_expired`, `token_replay`, `unsupported_audio`, `empty_file`, `file_too_large`,
`stt_model_missing`, `diarization_model_missing`, `public_key_missing`, `agent_processing`.

## Job states (spec §50) and Arabic labels

| State | Arabic |
|---|---|
| CREATED | تم إنشاء المهمة |
| RECEIVING_AUDIO | جارٍ استقبال التسجيل |
| PREPROCESSING | جارٍ تجهيز التسجيل |
| DIARIZING | جارٍ فصل المتحدثين |
| TRANSCRIBING | جارٍ تحويل الصوت إلى نص |
| FINALIZING | جارٍ تجهيز النتائج |
| SYNCING | جارٍ حفظ النتائج |
| COMPLETED / FAILED / CANCELLED | مكتمل / فشلت المعالجة / تم الإلغاء |

Each transition is persisted in SQLite and reported (best effort) to
`POST /api/local-processing/{job}/state`, which produces the central audit events
`LOCAL_PROCESSING_STARTED`, `DIARIZATION_STARTED/COMPLETED/FAILED`,
`TRANSCRIPTION_STARTED/COMPLETED/FAILED`, `LOCAL_PROCESSING_FAILED/CANCELLED`.

## Model lifecycle

```
agent starts → (AGENT_PRELOAD_MODELS=true: load in background)
first job    → load VAD + Sortformer + Cohere if not loaded
models stay resident → reused by every following job (single worker keeps memory bounded)
```

`AGENT_VERIFY_MODEL_INTEGRITY` = `none | size | full` checks every provisioned file against
`MANIFEST.json` (size, or SHA-256 for `full`) before loading.

## Synchronization (spec §58–59)

After FINALIZING the job is `COMPLETED` with `sync_state = WAITING_TO_SYNC`. The sync worker:

1. `POST /result` with the structured transcript, model revisions, processing metadata,
   audio metadata (SHA-256, duration) and the workstation descriptor.
   `idempotency_key` (generated once per job) makes retries safe: the central server returns
   `duplicate: true` with the same transcript id instead of creating a second transcript.
2. `POST /audio` with the original file (unless `AGENT_CENTRAL_UPLOAD_AUDIO=false`).
   The central server verifies the SHA-256 announced in step 1.
3. `sync_state = SYNCED`, the job token is deleted locally.

Network failures → `WAITING_TO_SYNC` with exponential backoff (5 s … 10 min, forever by
default); permanent rejections (token expired, job cancelled centrally, conflicting result)
→ `SYNC_FAILED` and no further retries. Results survive agent restarts (SQLite + result.json).

## Temporary files

`AGENT_DATA_DIR/jobs/{job_uuid}/` holds `original.<ext>`, `processing_16k_mono.wav`
(deleted right after finalization) and `result.json`. Directories of finished jobs are
removed after `AGENT_TEMP_RETENTION_HOURS` (72 h) — never before the job is synchronized.
Job ids are validated as UUIDs and paths are resolved inside the jobs directory
(no path traversal).

## Binding

`AGENT_BIND_HOST=127.0.0.1` is enforced; any other address aborts start-up unless
`AGENT_ALLOW_NON_LOOPBACK_BIND=true` is set by an administrator (the Docker image sets it
because the container port is published only on `127.0.0.1` of the host).
