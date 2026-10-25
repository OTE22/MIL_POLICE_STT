# Workflow implementation and verification status

Last checked: 2026-10-25.

## Verified

- Frontend TypeScript and Vite production build passed, including the unsaved-report navigation guard.
- Frontend HTML report payload regression passed: server-owned snapshots are stripped; wording, order and source references remain.
- Earlier targeted backend checks passed for attribution revisions, participant identity preservation, concurrent processing jobs, access controls and report source handling. These are partial checks, not a complete acceptance result.
- The recovered broad regression run completed with 336 passed and two failures, with one official-issuance test excluded. One failure was the older runtime lacking Playwright; the other was an outdated test using the pre-refresh report token. The latter test now reads the new token after refresh. Both require verification in the final runtime. Raw output: `storage/test-artifacts/workflow-regression.log`.
- All 144 backend Python source files passed syntax parsing before the final integrity refinements.
- A database dump and report/document backups exist under `storage/backups/before-html-workflow-20261025/`. The legacy-file manifest records six exact files and hashes for post-migration removal.

## Not yet verified or applied

- Final refinements are undergoing targeted regression checks; the broad run above predates those refinements.
- Actual Chromium PDF issuance, long-document pagination and browser workflow acceptance remain pending.
- The final backend image build result is unconfirmed.
- No live workflow migrations, legacy database purge or manifest-based legacy file purge have been applied during this task.
- The running application must not be described as updated until image deployment, migration head, health and end-to-end behavior are checked.

## Deployment blocker

The host C: drive reached zero free bytes. Python compilation and Docker's own logging failed with disk-full errors; Docker API calls timed out. Normal Docker Desktop restart timed out. Removing the disposable `.venv-test` environment recovered about 2.3 GB; a forced Docker Desktop restart succeeded and containers resumed. Dangling-image pruning reclaimed 0 B. Backend/frontend rebuilding and the isolated regression suite subsequently resumed; deployment is still pending.

Recover disk capacity, restore Docker, rerun the interrupted regression suite and PDF checks, rebuild current source, then deploy backend/frontend together. Apply the versioned legacy-retirement migrations and the manifest-based file purge only after these checks. Preserve investigation evidence, backups and rollback images.
