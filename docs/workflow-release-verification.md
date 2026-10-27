# Investigation intake and voice reporting release

## Changes

- One participant requirements catalogue and canonical statement-details structure, with separately
  audited exceptions. Incomplete drafts remain saveable; new processing and report preparation
  require readiness. Existing uploads and results can recover.
- Explicit transcript review tied to text, attribution, and resolved identities. Each recording
  remains selectable for review. Imports require reviewed current sources.
- Registered people can be selected together for statements. Untouched draft facts follow canonical
  corrections, while report overrides and reviewed wording are preserved. Updated source wording
  requires comparison and explicit acceptance.
- Serialized autosave, conflict reconciliation, an A4 outline/editor/preview workspace, arbitrary
  notes, and one consolidated conclusion.
- Assigned-investigator dictation for notes and conclusion fields. Original audio, machine text,
  accepted wording, authorship, and destination are retained. Dictation bypasses diarization and
  identity matching and does not create testimony or speaker rows.
- Lead approval and HTML/PDF issuance remain explicit. Source-change acknowledgement is required.
  Closure, reasoned reopening, and successor reports preserve immutable issued files.

## Verification and deployment record

- Frontend: TypeScript and Vite production build passed.
- Agent: 35 security, synchronization, API, and dictation tests passed; unhandled worker-thread
  warnings were treated as errors.
- Migration rehearsal: live database backup restored into a separate `_test` database and upgraded
  to `f165789dab45`. Existing columns and row counts in every existing table matched before/after.
- Backend: 353 regression tests passed, followed by 9 focused intake/dictation tests including
  the final per-recording review and merged-identity display checks.
- Final continuous browser journey: PASS from incomplete draft through real speech processing,
  multi-person import, upstream correction/comparison/acceptance, interrupted and concurrent saves,
  all dictation fields, lead approval/issuance, closure, reopening, and successor issuance. The first
  issued HTML and PDF remained byte-for-byte unchanged. The generated report spans seven A4 pages.
- The browser journey uses Chromium microphone capture with synthetic Arabic audio and the real
  local speech engine. It verifies software capture/inference, not physical microphone hardware.
- Additional browser recovery checks passed for native unavailable capture and an explicitly
  simulated `NotAllowedError`. Both showed actionable guidance and created no dictation or report
  changes; this does not claim a physical device permission-denial test.
- A prior harness run stopped because it omitted the required source-change acknowledgement.
  That failed-run evidence is retained under `complete-workflow/source-ack-test-stop`; the app
  correctly blocked approval. The harness now makes the explicit acknowledgement.
- Coordinated deployment: backend, frontend, and agent are healthy on the exact packaged image IDs.
  Live migration head is `f165789dab45`; HTTP/HTTPS index and asset bytes match the production build.
- Live browser: details, transcript, speakers, and report pages PASS with no browser exceptions or
  attempted mutations. Initial verification correctly identified incomplete setup. At the user's
  subsequent request, 24 missing requirements across two existing participants were populated with
  marked development mock values. Readiness now passes; original entries, participant IDs, recordings,
  and issued reports are preserved. Mock document references do not confirm verification or signing.

Evidence:

- `storage/test-artifacts/intake-final-regression.json` and corresponding full log.
- `storage/test-artifacts/agent-final-regression.json`.
- `storage/test-artifacts/complete-workflow/journey.json`, runtime versions, screenshots, HTML/PDF.
- `storage/backups/workflow-release-20261026T212923Z/release.json`: exact runtime image IDs,
  source hashes, retained rollback images, migration rehearsal and backup hashes.
- `storage/test-artifacts/live-workflow/verification.json`: read-only post-deployment browser checks.

The backup covers the live database, evidence/report/document storage, logs, and agent data.
Disposable test/model-evaluation folders and other backups are excluded. Database migrations are
additive; new-format records require forward repair rather than destructive downgrade.
