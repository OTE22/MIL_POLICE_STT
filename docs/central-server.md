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

## PostgreSQL schema (Alembic revision `b2e94c1f7a06`)

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

## Logging (debugging, not audit)

The `audit_logs` table is the LEGAL record of who did what. Logging is the ENGINEERING
record of what the system did. They are separate by design.

Two sinks, same pipeline: human-readable stdout (`docker compose logs -f backend`) and
JSON-lines in **`storage/logs/backend.jsonl`** (rotating, 20 MB x 10) - on the mounted
volume, so logs **survive container recreation** and travel with the /storage backups.

Every request gets an **`X-Request-ID`** (an inbound one from the agent is honoured),
echoed in the response header and included in the 500 body. A root-logger filter stamps
that id and the authenticated username onto every record emitted while the request runs -
services, SQL warnings, voice-matching decisions - so one grep reconstructs one request:

```bash
grep '"request_id": "a1b2c3d4e5f6"' storage/logs/backend.jsonl | jq
```

Also built in: one access line per request (route TEMPLATE, status, duration, user, ip;
health polling demoted to DEBUG; uvicorn's duplicate silenced), slow-query warnings above
`CENTRAL_SLOW_QUERY_MS` (statement truncated, **parameters never logged**), and enforced
redaction - `Bearer` tokens, passwords, secrets and embedding vectors are scrubbed in the
pipeline before any formatter, in both sinks (`[redacted]` / `[vector:256]`).

| Env | Default | |
|---|---|---|
| `CENTRAL_LOG_LEVEL` | `INFO` | root level |
| `CENTRAL_LOG_LEVELS` | – | per-logger, e.g. `app.services.voice_matching=DEBUG,sqlalchemy.engine=WARNING` |
| `CENTRAL_LOG_DIR` | `<storage>/logs` | `""` disables the file sink |
| `CENTRAL_SLOW_QUERY_MS` | `200` | slow-query threshold |

**Runtime changes from the interface** — **إعدادات النظام** (admins, `system.configure`)
edits a whitelisted set live: log levels, slow-query threshold, voice threshold/margin,
session and processing-token lifetimes, and the upload cap. Changes hit the very next
request and are **ephemeral by design** - a restart re-reads `.env`, so a bad interactive
change is one restart away from undone. Secrets and boot-structural settings are not on the
whitelist and never reach the browser. Every change is logged (`app.admin`) with old value,
new value, the admin's username and the request id. Full operator guide, including WHEN
each setting takes effect: [system-settings.md](system-settings.md).

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
| voice.identify (say which human a speaker is; confirm/reject suggestions; re-scan) | ✔ | ✔ | |
| voice.enroll (create, deactivate and delete voice prints) | ✔ | ✔ | |
| subjects.reference.override (hand-assign a *derived* الرقم المرجعي) | ✔ | | |
| system.configure (change runtime settings from إعدادات النظام) | ✔ | | |
| workstations.read / workstations.register | ✔ | ✔ | |
| audit.read | ✔ | | |

### Required fields when creating a user

`username` (3–64 of `a-zA-Z0-9._-`, stored lowercase, unique), `password` (≥ 10 characters), at
least one role, `full_name`, **`military_id`** (unique) and **`security_branch`**. Everything
else on the profile — rank, unit, department, job title, phone, email, location, notes — is
optional.

Creating or updating a user requires **`الجهاز` (`security_branch`) and `الرقم العسكري`
(`military_id`)**, because an investigator is a person in the registry and those two fields are
what produce their الرقم المرجعي. `OTHER` is rejected with 422: a catch-all is not a namespace,
and two "other" forces sharing a serial would become one identity.

**`speakers.assign` and `voice.identify` are deliberately separate.** The first permits
*labelling* a voice in one session; the second permits *claiming which human it is* — a claim
that reaches the canonical person registry and, through it, the biometric prints. A speaker
PATCH that asserts an identity (sends `person_name`, or changes `reference_number`) is refused
with `identity_change_not_permitted` unless the caller holds `voice.identify`. The check runs
**before** the row is mutated, so a refusal leaves the speaker exactly as it was and creates no
canonical person.

Two operations need a second permission on top of their own:

* accepting a voice suggestion needs `voice.identify` **and** `speakers.assign`;
* consolidating two canonical people
  (`POST /voice-enrollments/people/{id}/consolidate`) needs `voice.enroll` **and**
  `investigations.read_all` — ADMIN in practice, because it rewrites ownership across sessions
  the caller may not be allowed to open.

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

### `GET /investigations/{id}/people` — one shape for everyone on a session

The single source the speaker picker renders from. Subjects and investigators are different
rows with different columns, and letting the interface flatten each one itself is what produced
the same human twice under two different names.

```json
[ { "identity_id": "…", "person_name": "ALI", "rank": "MAJOR",
    "reference_number": "MIL-ARMY-20110078", "source": "INVESTIGATOR",
    "participant_key": null, "selectable": true, "blocked_reason": null } ]
```

Three rules it enforces so the callers cannot each invent their own:

* **`person_name` is always the canonical name** from `person_identities`, resolved through any
  merge — never the snapshot stored on the source row. Rename or consolidate a person and every
  screen follows at once.
* **`rank` is carried separately and never folded into the name.** A rank is a role that changes
  with promotion while the person does not, and `person_identities` has no column for one — so a
  name with a rank baked in cannot match what بصمات الأصوات shows.
* **A row with no reference is still returned**, marked `selectable: false` with a
  `blocked_reason`. Omitting it is how a subject saved without a name vanished from
  مشاركو الجلسة while still appearing in the registry search — the same human, invisible where
  they belonged and visible where they were a stranger.

Requires `transcripts.read` and session access, like every other session-scoped route.

## Session status machine

`DRAFT → RECORDING → PROCESSING → COMPLETED | FAILED`, plus `ARCHIVED`.
`PROCESSING/COMPLETED/FAILED` transitions are driven by token issue and agent reports;
manual transitions are limited to the table in `api/investigations.py`.

## Canonical person identity

`Subject` records a person's participation in **one** session and is rebuilt on every save, so
it cannot tie the same human together across sessions. `person_identities` does exactly that
and nothing else:

| column | |
|---|---|
| `reference_normalized` | **UNIQUE** — the cross-session guarantee |
| `reference_display` | الرقم المرجعي as entered or derived |
| `person_name` | the authoritative **current** name |
| `merged_into_id` | self-FK; a merged row is kept as an alias so its reference can never be recreated |

`subjects`, `session_speakers` and `voice_enrollments` each carry a nullable `identity_id`
pointing at it. **`identity_id` is backend-owned** — resolved from الرقم المرجعي and never
accepted from a client, so nobody can attach a speaker to another person by posting a UUID.

Two sequences issue the references the system allocates: `civilian_person_reference_seq`
(`CIV-NNNNNNNN`, every civilian) and `tmp_person_reference_seq` (`TMP-YYYY-NNNNNN`, a person not
yet classified). Sequences, never `COUNT(*)+1` or `MAX()+1` — those race, and two investigators
recording people at the same moment must not receive one value. Neither is ever reset.

`person_identifiers` holds **external** identifiers — passport, إقامة, UNHCR, UNRWA — under
`UNIQUE (identifier_type, issuer_namespace, value_normalized)`. The namespace is what makes
automatic resolution safe: passport `1234567` exists in many countries, so a bare number is not
an identity. `issuer_namespace` is `''` rather than `NULL`, because a `NULL` would switch the
constraint off for exactly the agency-wide identifiers that most need it. رقم السجل is
deliberately absent — it identifies a family record, not a human.

`subjects.participant_key` identifies a **participation slot within one session**, never a
person. A save replaces the whole subject collection, so `Subject.id` is destroyed and re-minted
each time; this is the only handle that survives, and it is what stops a repeated save issuing a
second reference for the same participant. Its `UNIQUE (session_id, participant_key)` is
`DEFERRABLE INITIALLY DEFERRED`, because a rebuild deletes the old row and inserts the new one
carrying the same key inside one transaction.

A partial unique index, `uq_voice_enrollment_active_source` on
`(source_session_id, source_speaker_label, model) WHERE is_active`, is what makes concurrent
enrolment of one sample safe.
