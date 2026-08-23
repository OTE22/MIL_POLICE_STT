# Security

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

## Not included (by design, spec §83)

Voice biometrics / automatic speaker identification, face recognition, LLM chat, RAG,
vector databases, cloud STT, Whisper, NVIDIA ASR, central GPU inference.
