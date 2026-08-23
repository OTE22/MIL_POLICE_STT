# Central server

## Configuration (`.env`, prefix `CENTRAL_`)

| Variable | Purpose |
|---|---|
| `POSTGRES_DB/USER/PASSWORD` | database credentials |
| `CENTRAL_JWT_SECRET` | HS256 secret for user sessions (≥ 48 random chars) |
| `CENTRAL_ACCESS_TOKEN_EXPIRE_MINUTES` | user JWT lifetime (default 480) |
| `CENTRAL_PROCESSING_TOKEN_ACCEPT_TTL_SECONDS` | window in which the agent must accept a job (default 600) |
| `CENTRAL_PROCESSING_TOKEN_SUBMIT_TTL_SECONDS` | window in which results/audio may be synchronized (default 86400) |
| `CENTRAL_MAX_UPLOAD_BYTES` | original-audio upload limit (default 2 GiB; nginx `client_max_body_size` 2100m) |
| `CENTRAL_BOOTSTRAP_ADMIN_*` | first administrator (created only when `users` is empty, must change password) |
| `CENTRAL_CORS_ALLOWED_ORIGINS` | only for the Vite dev server; empty in production |
| `CENTRAL_HTTP_PORT` / `CENTRAL_HTTPS_PORT` | published nginx ports (8080 / 8443) |

Processing-token keys are generated automatically into `./secrets/` on first start
(`processing_token_private.pem`, `processing_token_public.pem`). Only the public key is ever
copied to workstations.

## PostgreSQL schema (Alembic revision `8404f3cb8c30`)

```
users                 id, username(unique), password_hash(Argon2id), is_active, must_change_password,
                      last_login_at, created_by, created_at, updated_at
roles                 id, name(ADMIN|INVESTIGATOR|USER), description
permissions           id, code(unique), description
user_roles            user_id, role_id
role_permissions      role_id, permission_id
investigator_profiles id, user_id(unique), full_name, rank, military_id(unique), unit, department,
                      job_title, phone, email, location, notes, created_by, created_at, updated_at
investigation_sessions id, session_number(unique, INV-YYYY-NNNNN), title, description, location,
                      session_date, start_time, end_time, status(enum), notes,
                      expected_speaker_count, created_by, created_at, updated_at
session_investigators id, session_id, investigator_id, assignment_role(LEAD|ASSISTANT)   [unique pair]
subjects              id, session_id, subject_name, reference_number,
                      person_type(MILITARY|CIVILIAN|UNKNOWN), identity_confidence
                      (DECLARED|DOCUMENT_SEEN|VERIFIED),
                      military_id, rank, unit, department, security_branch,
                      nationality_code(ISO-3166 alpha-2), nationality_name,
                      register_number, place_of_registration, is_unregistered,   -- Lebanese civil registry
                      is_undocumented, undocumented_reason, notes
subject_documents     id, subject_id, document_type(NATIONAL_ID|CIVIL_EXTRACT|PASSPORT|
                      RESIDENCY_PERMIT|UNHCR_CARD|UNRWA_CARD|REFUGEE_TRAVEL_DOC|MILITARY_ID|
                      DRIVING_LICENSE|OTHER), document_number, issuing_country, issue_date,
                      expiry_date, notes, storage_path, original_filename, mime_type,
                      size_bytes, sha256, uploaded_by     -- 0..n documents per person
audio_recordings      id, session_id, original_filename, mime_type, size_bytes, duration_seconds,
                      sha256, source(BROWSER_RECORDING|FILE_UPLOAD), upload_status, storage_path, created_by
workstations          id, agent_id(unique), device_name, agent_version, stt_*, diarization_*,
                      processing_device, gpu_name, status, last_seen_at, registered_by
local_processing_jobs id(=job_id in the token), session_id, recording_id, workstation_id, requested_by,
                      status(REQUESTED|ACCEPTED|PROCESSING|COMPLETED|FAILED|CANCELLED), agent_state,
                      token_nonce(unique), token_issued_at, token_accept_by, token_expires_at,
                      idempotency_key, failure_stage, error_message, agent_metadata, completed_at
transcripts           id, session_id, recording_id, job_id(unique), status, language, stt_provider,
                      stt_model, stt_model_revision, diarization_provider, diarization_model,
                      diarization_model_revision, vad_model, agent_version, processing_device,
                      speaker_count, warnings, processing_metadata, created_at, completed_at
transcript_segments   id, transcript_id, sequence, speaker_label, start_seconds, end_seconds,
                      original_text (never overwritten), edited_text, confidence, is_overlap,
                      edited_by, edited_at, created_at                  [unique transcript_id+sequence]
session_speakers      id, session_id, speaker_label, display_name, speaker_role
                      (INVESTIGATOR|SUBJECT|WITNESS|OTHER|UNKNOWN), reference_number, notes
                      [unique session_id+speaker_label]
audit_logs            id, user_id, action, entity_type, entity_id, safe_metadata(jsonb), ip_address, created_at
```

All ids are UUIDs; foreign keys cascade from sessions to their children; audio files live on
disk under `storage/recordings/{session_uuid}/{recording_uuid}.{ext}` (never as BLOBs).

## Roles and permissions

| Permission | ADMIN | INVESTIGATOR | USER |
|---|:-:|:-:|:-:|
| users.manage / users.read | ✔ | | |
| investigators.read | ✔ | ✔ | |
| investigations.create | ✔ | ✔ | |
| investigations.read_all | ✔ | | |
| investigations.read_assigned (created by or assigned to me) | ✔ | ✔ | ✔ |
| investigations.update / investigations.archive | ✔ | ✔ | |
| recordings.create / processing.request | ✔ | ✔ | |
| subjects.documents.view (ID/passport scans) | ✔ | ✔ | |
| transcripts.read | ✔ | ✔ | ✔ |
| transcripts.edit / speakers.assign | ✔ | ✔ | |
| workstations.read / workstations.register | ✔ | ✔ | |
| audit.read | ✔ | | |

Every protected endpoint checks: authenticated user → account active → permission →
**resource access** (`user_can_access_session`). Sessions a user may not see return 404.

## API summary

```
POST /api/auth/login                      GET  /api/auth/me            POST /api/auth/logout
POST /api/auth/change-password
GET/POST /api/users                       GET/PUT /api/users/{id}      PATCH /api/users/{id}/status
POST /api/users/{id}/reset-password
GET /api/investigators                    GET /api/investigators/{id}
GET /api/investigations/dashboard
GET/POST /api/investigations              GET/PUT /api/investigations/{id}
GET /api/investigations/{id}/jobs         GET /api/investigations/{id}/activity
POST /api/investigations/{id}/local-processing-token
GET  /api/local-processing/public-key     GET /api/local-processing/{job_id}
POST /api/local-processing/{job_id}/cancel                       (user)
POST /api/local-processing/{job_id}/state                        (agent, processing token)
POST /api/local-processing/{job_id}/result                       (agent, idempotent)
POST /api/local-processing/{job_id}/audio                        (agent, multipart)
GET  /api/investigations/{id}/transcript  PATCH /api/transcript-segments/{id}
GET  /api/investigations/{id}/speakers    PATCH /api/investigations/{id}/speakers/{speaker_id}
GET  /api/recordings/{id}/audio
POST/GET/DELETE /api/investigations/{id}/subject-documents/{doc_id}/file
GET  /api/workstations                    POST /api/workstations/register
GET  /api/audit-logs                      GET /api/health
```

Errors return `{"detail": "<code>"}`; the frontend maps every code to an Arabic message
(`central/frontend/src/lib/i18n.ts`). Stack traces are never returned.

## Session status machine

`DRAFT → RECORDING → PROCESSING → COMPLETED | FAILED`, plus `ARCHIVED`.
`PROCESSING/COMPLETED/FAILED` transitions are driven by token issue and agent reports;
manual transitions are limited to the table in `api/investigations.py`.
