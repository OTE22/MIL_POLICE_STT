# Security

**Who this is for:** administrators and anyone reviewing the system before approving it.
It states what is protected, how, and what is deliberately NOT included.

## Authentication and sessions

* Passwords: Argon2id (`argon2-cffi`, t=3, m=64 MiB, p=2); rehashed transparently when
  parameters change; never logged; login timing equalized for unknown users.
* User sessions: JWT HS256 (`CENTRAL_JWT_SECRET`), 8 h default expiry, `jti`, stored in
  `sessionStorage` (cleared when the tab closes). 401 → the frontend returns to the login page.
* Bootstrap admin must change the password at first login; admins can reset passwords with
  `must_change_password`.
* Disabled accounts cannot log in (403 `account_disabled`) and existing tokens stop working.

## Authorization

Every endpoint: authenticated → active → permission (`require_permission`) → resource
(`user_can_access_session`). Frontend button hiding is cosmetic only. Sessions outside the
user's scope answer 404 to avoid leaking existence.

## Local processing authorization (spec §16)

```
frontend ──POST /investigations/{id}/local-processing-token──▶ central
            (user JWT; permission processing.request; resource check)
central  ── ES256-signed JWT ────────────────────────────────▶ frontend ──▶ agent
            claims: iss, aud, sub, jti(nonce), iat, nbf, exp, accept_by,
                    job_id, session_id, recording_id, user_id, session_number,
                    allowed_action=process_recording        (no secrets)
agent    verifies signature with the central PUBLIC key, iss/aud, nbf/exp,
         allowed_action, accept_by (≤ 10 min), nonce never seen before (SQLite)
agent    uses the same token as Bearer for /state, /result, /audio until `exp` (24 h);
         central re-verifies signature + job_id + nonce on every call
```

Two windows: `accept_by` keeps the authorization to *start* a job short-lived; `exp` bounds
how long results may still be synchronized after a network outage. The private signing key
(`secrets/processing_token_private.pem`) exists only on the central server; workstations
receive `central_public_key.pem` at provisioning time (`GET /api/local-processing/public-key`
publishes it; optional TOFU fetch for pilots via `AGENT_CENTRAL_PUBLIC_KEY_AUTO_FETCH`).

## Browser ↔ Local Agent (spec §17)

* The agent binds to `127.0.0.1:17117` (start-up aborts otherwise unless an administrator
  overrides; Docker publishes on the host loopback only).
* CORS allow-list = the central frontend origin(s) (`AGENT_ALLOWED_ORIGINS`); no credentials;
  only `GET/POST/OPTIONS`.
* Chrome/Edge **Private Network Access / Local Network Access**: the preflight response
  carries `Access-Control-Allow-Private-Network: true`; newer Chrome versions additionally show
  a one-time permission prompt which the UI explains
  ("قد يطلب المتصفح الإذن للاتصال بالخدمة المحلية…"). No browser flags are disabled.
* Mixed content: loopback (`http://127.0.0.1`) is a *potentially trustworthy origin*, so an
  HTTPS central page may call it; the CSP `connect-src` allows exactly those URLs.
* A random web page cannot use the agent: it is not in the CORS allow-list and it cannot
  obtain a processing token.

## Identity documents (subject ID / passport scans)

* Stored like the audio originals: streamed to disk, **never modified**, SHA-256 recorded,
  format verified by **magic bytes** (JPEG / PNG / WEBP / PDF only), 20 MiB cap, path
  resolved inside the storage root (`storage/subject-documents/{session}/{document}.ext`).
* Gated by a **dedicated permission** `subjects.documents.view` (ADMIN + INVESTIGATOR) *in
  addition to* resource access to the session — reading a transcript does not expose ID scans,
  and the read-only USER role never sees them.
* Uploading or deleting additionally requires `investigations.update`.
* A scan cannot be silently replaced: re-uploading over an existing file returns 409, so the
  original stays as recorded until it is explicitly deleted.
* **PDFs are always served as `attachment`** (never rendered inline in the app origin);
  images are served `inline` with `nosniff` and `no-store`.
* Every upload, view and deletion is audited (`SUBJECT_DOCUMENT_UPLOADED/_VIEWED/_DELETED`)
  with the SHA-256 and document type, never the file content.
* The frontend fetches scans with an authenticated request and opens an object URL, so the
  access token never appears in a URL, browser history or server log.

## Uploads and storage

* Allow-listed extensions/MIME, magic-byte sniffing, streaming size limits, sanitized file
  names, UUID-based storage paths resolved inside the storage root (path-traversal safe),
  SHA-256 of the original verified centrally against the agent's announcement.
* Originals are never modified; transcripts keep `original_text` forever.
* Temporary files on desktops are cleaned after the retention period, never before sync.

## Transport

* nginx terminates TLS (`central/nginx/certs/cert.pem|key.pem`; self-signed generator for
  pilots, organisation certificates for production; HTTP→HTTPS redirect can be enabled).
* Security headers: CSP (self only + loopback agent), `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, HSTS on 443,
  `Cache-Control: no-store` on API responses.
* Agent → central: HTTPS with certificate verification (`AGENT_CENTRAL_CA_BUNDLE` for a
  private CA; `AGENT_CENTRAL_VERIFY_TLS=false` only for LAN pilots).

## Audit

Append-only `audit_logs` with user, action, entity, sanitized metadata and client IP for
every event listed in spec §69. Keys containing `password`, `token`, `secret`, `key`,
`authorization` are stripped by `services/audit.py` before persisting.

## Arabic formalization (optional AI) and the production boundary

The محضر may offer a Modern-Standard-Arabic rewording of a question or answer. Three rules
make that safe, and all three are code, not configuration:

* **Production never contacts a cloud provider.** The hosted-provider class refuses to
  construct when `CENTRAL_ENVIRONMENT=production` — the guard is in its constructor, so no
  code path can reach it, and every fallback rung on the production ladder is local.
* **The API key is a secret file.** It is read from an operator-provisioned path
  (`secrets/nvidia_api_key`, mode 0600, gitignored) and never enters the settings table, an
  API response, an audit entry or a log line. A development machine without one simply
  reports formalization unavailable.
* **A model never writes the report.** Suggestions are stored beside the text; only a human
  decision (اعتماد / تعديل / رفض) changes what is printed. There is no code path from model
  output to an official document without a person.

Development installs may use a hosted model, and only with **synthetic or anonymised** text.
That is an operational rule the code cannot enforce, so the deployment script states it and
the composer's provenance records which provider produced each suggestion.

## Issued reports

An issued محضر is stored under `storage/reports/`, hashed three ways (document, rendering
context, template version) and never overwritten — a correction becomes a new version.
Verification recomputes the hashes and answers سليم / غير مطابق. This is **integrity
verification, not a digital signature**: it proves the archived bytes are unchanged, and it
says nothing about a copy edited after download. For submission, re-download from the archive
and verify before filing.

Report templates are admin-supplied content and are treated as untrusted: macros, external
relationships, zip bombs, path traversal inside the archive and template-injection attempts
are all refused, Jinja runs sandboxed over a plain-dict context, and a template that fails
validation can never become the active official form.

## Not included (by design, spec §83)

Automatic identity assignment, face recognition, LLM chat, RAG, cloud STT, Whisper,
NVIDIA ASR and central GPU inference remain outside this workflow. Voice-print assistance
and pgvector storage were added after the original specification; a human still confirms
identity assignments.

Voice-review reads require `voice.identify`. Source playback additionally requires
`transcripts.read` and access to the source investigation. Notes, flags, deactivation,
same-person set confirmation and reopening require `voice.enroll`. Each decision records
the operator, reason and time. Confirmation validates the active print IDs, canonical owner
and reviewed timestamps; duplicate or stale submissions are refused. The append-only audit
stores print IDs and timestamps, never embedding vectors. See
[voice-review-panel.md](voice-review-panel.md).
