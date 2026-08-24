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

| Suite | Result |
|---|---|
| Central server pytest (isolated PostgreSQL `military_stt_test`) | **31 passed, 0 failed** |
| Local Agent pytest on the host (test doubles, FFmpeg) | **43 passed** |
| Local Agent pytest inside the Docker image (`military-stt/desktop-agent:1.0.0-cpu`, real models mounted) | **47 passed, 0 skipped, 0 failed** in 235 s |
| Real VAD on the Arabic conversation | PASS — 10 speech regions, leading silence excluded |
| **Real NVIDIA Sortformer diarization** (`scripts/run_diarization_test.py`, CPU) | **PASS** — 10 turns in 6.6 s for 52 s of audio; speaker sequence `SPEAKER_00 → SPEAKER_01 → SPEAKER_00 → SPEAKER_01 → SPEAKER_00` exactly as scripted; the same voice is regrouped under the same label each time it returns; overlap flags present; STT windows never overlap |
| Voice identification API (real SpeakerNet embeddings) | **31/31 PASS** — enrol/consent/duplicate, suggestion, abstain on a different voice, confirm/reject, RBAC, audit, deletion |
| Voice identification UI (`voice_ui.py`, Playwright) | **20/20 PASS** — enrol dialog (consent-gated), suggestion banner with score, `display_name` NOT auto-filled, confirm/reject, registry page, deactivate |
| Browser UI smoke (`scripts/ui_smoke.py`) | **18/18 functional checks PASS** (console check excludes the intentional wrong-password 401) |
| **Real Cohere Arabic transcription** (`scripts/run_transcription_test.py`, CPU) | **PASS** — model loaded in 46.1 s, transcribed 11.6 s of audio in 10.9 s (**RTFx 1.1**). Output: `كانت في المنزل طوال المساء. وصلت من العمل في السادسة والنصف وتناولت العشاء مع عائلتي ثم شاهدت التلفاز.` — matches the scripted line (one inflection difference: `كانت` vs `كنت`) |
| **Real combined speaker-turn transcription** (`test_speaker_turn_transcription_combined`) | **PASS** — 10 segments, every investigator question attributed to `SPEAKER_00` and every answer to `SPEAKER_01`, A→B→A→B→A intact (full transcript below) |
| **Browser E2E (spec §81)** (`scripts/e2e_browser.py`) with the real agent container and real models | **PASS — ALL 19 STEPS PASSED**: admin login → create investigator (UI) → investigator login → agent detected (`agent-5ce0…`, CPU) → NVIDIA diarization READY → Cohere Arabic READY → create investigation → upload 52 s two-speaker Arabic recording → local processing → sync → PostgreSQL (10 segments, 2 speakers, both model revisions recorded) → Arabic transcript displayed → speakers mapped (`SPEAKER_00→المحقق`, `SPEAKER_01→الشخص الذي تتم مقابلته`) → click segment seeks audio (4.56 s exact) → segment edited with `original_text` intact → complete audit trail → zero console errors |
| Agent ↔ central over HTTPS (`https://host.docker.internal:8443`, self-signed, verification disabled for the dev pilot) | PASS (`/api/health` 200 from inside the container) |
| Browser ↔ agent on loopback (CORS + Private-Network-Access) | PASS — the recording tab shows حالة الخدمة: جاهز, CPU, version, device name, model states |

Raw diarization output (CPU, "very high latency" streaming preset):

```
  1.12 ->  3.52  SPEAKER_00      24.00 -> 26.72  SPEAKER_00      42.32 -> 43.04  SPEAKER_00
  4.56 ->  9.44  SPEAKER_00      27.76 -> 30.88  SPEAKER_00      44.00 -> 45.84  SPEAKER_00
 11.44 -> 13.60  SPEAKER_01      32.88 -> 40.32  SPEAKER_01      46.80 -> 50.48  SPEAKER_00
 14.64 -> 22.00  SPEAKER_01
speaker sequence: SPEAKER_00 -> SPEAKER_01 -> SPEAKER_00 -> SPEAKER_01 -> SPEAKER_00   RESULT: PASS
```

Combined result — NVIDIA answering *who spoke when*, Cohere answering *what was said*:

```
SPEAKER_00   1.1– 3.4   أين كنت مساء أمس يا أحمد؟
SPEAKER_00   4.6– 9.4   أريد أن تخبرني بالتفصيل عن كل ما فعلته بعد الساعة السابعة.
SPEAKER_01  11.4–13.6   كانت في المنزل طوال المساء
SPEAKER_01  14.6–22.0   وصلت من العمل في السادسة والنصف وتناولت العشاء مع عائلتي ثم شاهدت التلفاز
SPEAKER_00  24.0–26.7   هل كان معك أحد آخر في المنزل؟
SPEAKER_00  27.8–30.8   وهل يستطيع أحد أن يؤكد ما تقوله؟
SPEAKER_01  32.9–40.3   نعم كانت زوجتي وأولادي معي وجاء أخي في الساعة التاسعة وبقي حتى منتصف الليل
SPEAKER_00  42.3–43.0   حسنا
SPEAKER_00  44.0–45.8   سنتحقق من ذلك.
SPEAKER_00  46.8–50.5   هل غادرت المنزل في أي وقت خلال تلك الليلة؟
```

Model provisioning: the gated Cohere weights (4,131,862,976 bytes) were verified against the
pinned revision's SHA-256 `404ff5dccd66b1985a06059b9d5ed970a676761c0821f9c10756db6e4a1910a5`
before being renamed into place and written into `MANIFEST.json`. Both models load in
**~1 min 47 s** on CPU and stay resident.

Defects found by this verification round and fixed:

* the status panel reported `PROVISIONED` / `LOADING` as **تعذر تشغيل النموذج** ("failed to
  run"), so a healthy agent that had simply not loaded its models yet looked like a crash;
* `<input pattern="[a-zA-Z0-9._-]{3,64}">` threw `Invalid regular expression` under the HTML
  `v` flag, silently disabling client-side username validation;
* a model whose files appeared after a failed check kept a stale "model files missing" error.

Environment note: on this 11.6 GB Docker VM, loading a **second** copy of the 4 GB STT model
while the agent already held one resident exhausted the WSL2 VM and terminated the engine.
Run one model instance at a time on constrained hosts (stop the agent before the isolated
model tests), or give the VM more memory.

Environment notes: no GPU on the build machine, so all inference ran on CPU inside Docker
(`AGENT_COMPUTE=cpu`). Other projects' containers (≈ 6.5 GB RAM) had to be stopped to give
the model enough memory; production workstations should have ≥ 16 GB RAM or a CUDA GPU.

