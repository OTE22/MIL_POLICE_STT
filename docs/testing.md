# Testing

## Test suites

| Suite | Location | What it covers | How to run |
|---|---|---|---|
| Central server (31 tests) | `central/backend/tests/` | successful login, invalid login, disabled account, admin authorization, investigator authorization, user creation/validation, role change + password reset + audit, investigation creation, investigator assignment (multiple), unauthorized resource access, status transitions, list filters + dashboard, processing token generation + claims, audio metadata validation, expired token, invalid/mismatched/forged tokens, result synchronization (state reports → result → audio upload with SHA-256 check → transcript retrieval → workstation registry → audit), duplicate result submission (idempotent), failed processing, cancelled job, result validation, transcript edit (original preserved, restore, audit), transcript edit authorization, speaker rename + audit, workstation registration | `docker compose run --rm --no-deps -e SKIP_MIGRATIONS=true -v "$PWD/central/backend:/app" --entrypoint "" backend sh -c "cd /app && python -m pytest tests -q"` (uses the isolated `military_stt_test` database) |
| Local Agent unit/integration (43 tests) | `desktop-agent/tests/` (`test_security.py`, `test_segments.py`, `test_sync.py`, `test_agent_api.py`) | token validation (valid, replay, expired, acceptance window, wrong key, wrong iss/aud/action, garbage, missing public key), localhost-only binding, CORS + Private-Network-Access headers, health/capabilities/model-status, audio validation (extension, fake WAV, empty, oversize), full job lifecycle with every state reported and synchronization (result + audio, token discarded), overlap metadata, diarization failure reported (no fallback), STT failure reported, cancellation, cleanup/retention, sync retry after network failure with backoff, idempotent duplicate submission, permanent rejection, SQLite durability across restart, segment post-processing (merge same speaker, never across another speaker, max length, split at silence, VAD trim, padding never duplicates audio, overlap marking, label normalization) | `cd desktop-agent && python -m pytest tests --ignore=tests/test_real_models.py -q` (models are replaced by test doubles; FFmpeg required) or inside the image: `docker compose run --rm agent python -m pytest tests -q` |
| Real models (agent) | `desktop-agent/tests/test_real_models.py` | VAD on real speech, **real NVIDIA Sortformer diarization A→B→A**, real Cohere Arabic transcription, combined speaker-turn transcription | `docker compose run --rm agent python -m pytest tests/test_real_models.py -v -s` (skips when a model is not provisioned) |
| Browser UI smoke (19 checks) | `scripts/ui_smoke.py` | RTL/lang, Arabic login error, dashboard, sessions list + filters, new-session form, details tabs, recording tab + local AI status panel, transcript (segments, overlap badge, audio player, search, speaker filter, click-to-seek, inline edit with original preserved), speaker mapping, activity log, RBAC redirect, logout, users page (columns, add modal, disable/enable), workstations, audit page + filter, console errors | `python scripts/ui_smoke.py --admin-password ...` (Playwright/Chromium; injects a transcript through the agent API — no model run) |
| Real full E2E (spec §81) | `scripts/e2e_browser.py` | admin login → create investigator → investigator login → agent detected → Sortformer READY → Cohere READY → create investigation → upload Arabic two-speaker recording → local processing → sync → PostgreSQL → Arabic transcript displayed → map SPEAKER_00→المحقق / SPEAKER_01→الشخص الذي تتم مقابلته → click segment seeks audio → edit segment (original intact) → audit log | `python scripts/e2e_browser.py --audio desktop-agent/tests/fixtures/conversation_ar_2spk.wav --admin-password ...` |

## Test data

`desktop-agent/tests/fixtures/conversation_ar_2spk.wav` is a 52 s Arabic conversation with
two distinct voices in the pattern A → B → A → B → A (see `fixtures/README.md`). It was
synthesized with neural TTS voices because no human multi-speaker Arabic recording was
available on the build machine. For unit acceptance, replace it with a real interview
recording and re-run `scripts/run_diarization_test.py … --expect SPEAKER_00,SPEAKER_01,SPEAKER_00`.

## Results on the build machine (2026-08-23, Windows 11, i7-8550U, 24 GB RAM, **no GPU**)

RESULTS_PLACEHOLDER
