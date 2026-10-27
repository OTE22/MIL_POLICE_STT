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
- Final continuous browser journey: completion recorded in the machine-readable artifacts below;
  deployment is guarded on successful results.
- The browser journey uses Chromium microphone capture with synthetic Arabic audio and the real
  local speech engine. It verifies software capture/inference, not physical microphone hardware.
- A prior harness run stopped because it omitted the required source-change acknowledgement.
  That failed-run evidence is retained under `complete-workflow/source-ack-test-stop`; the app
  correctly blocked approval. The harness now makes the explicit acknowledgement.

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
