# Workflow implementation and deployment verification

Verified and deployed locally on 2026-10-26 (Asia/Beirut).

## Verification results

- **345 backend tests passed** in the production runtime, with no excluded tests. Includes real Chromium PDF issuance, immutable successor versions, bilingual long-document pagination, attribution continuity, evidence retention, processing retries, concurrent edits, ownership validation, permissions and lifecycle gates. Output: `storage/test-artifacts/workflow-production-runtime-tests.log`; process exit 0.
- TypeScript and Vite production build passed. The dashboard links to current investigation reports. HTTP origins use a cryptographically random UUID fallback when `crypto.randomUUID` is unavailable.
- Real browser acceptance passed using normal login and separate services/database: editing, unsaved navigation protection, review, issuance, PDF download/hash verification, closure, reasoned reopening, unchanged issued PDF, desktop/mobile overflow checks. Screenshots and PDF: `storage/test-artifacts/workflow-browser/`. No live investigation was modified for testing.
- Fresh installation migrated from an empty database to head. A historical migration's dependency on a removed helper was repaired by freezing its original normalization rule inside the migration.
- A restored live database migrated successfully. All original investigation and evidence columns matched before/after sorted-row SHA-256 digests. Output: `storage/test-artifacts/workflow-migration-rehearsal.log`.
- All 146 backend Python files parsed successfully; source whitespace checks passed.

## Live deployment

- Backend: `sha256:f63177f8960565d071591e83aaf49c94410a3dbab5d4d85c8814aec6c9af165f`.
- Frontend: `sha256:a5bc584d3a32d8152135d1323a7c3056167e6e0666a16599597bcf0fc9d9f52f`.
- Running containers match these images and report healthy. Nginx restarted to resolve replacement containers.
- `http://localhost/api/health` returned `status: ok`, `database: true`. Served `/assets/index-Dmws_Y6L.js` returned HTTP 200.
- Live Alembic head: `c832456a7e12`.
- Legacy reports/drafts: zero. Retired template table: absent. Six inventoried files were hash-validated and removed. HTML/PDF is the sole report generation path; retired mutation APIs explicitly return 410.

## Preservation and recovery

Post-migration comparison matched the baseline exactly for every original column in: 1 investigation, 1 assignment, 2 participants, 35 recordings, 35 jobs, 31 transcripts, 79 segments, 39 speaker observations, 4 identities, 2 identifiers, 25 enrollments and 726 audit records. There were no participant documents. The reviewed attribution overlay remains present. All 31 stored evidence files also match their backup hashes; all six inventoried legacy files are absent from active storage.

Database/file backups, removal manifest and baseline: `storage/backups/before-html-workflow-20261026/`. Earlier backups and rollback image tags ending `before-html-workflow-20261025` remain. Legacy data is removed from the active application; recovery copies are retained. After new-format records exist, use forward repair rather than a destructive downgrade.

The earlier disk-full/Docker interruption was resolved before deployment. No broad volume pruning or evidence cleanup was performed. Temporary browser services and the two databases created for rehearsal/acceptance are removed after verification.

## Practical limits

End-to-end tests used isolated databases. Live checks confirmed migration, preservation, health and assets; they did not issue a report on the user's real investigation. Recordings with absent originals, unresolved failures or invalid hashes remain blocked from official issuance until explicitly repaired. Missing evidence is never fabricated and review gates are not bypassed.

The optional local LLM runtime was unreachable at startup. HTML/PDF reporting works independently; LLM-assisted features require that separate runtime.
