# Testing

## Test suites

| Suite | Location | What it covers | How to run |
|---|---|---|---|
| Central server | `central/backend/tests/` | successful login, invalid login, disabled account, admin authorization, investigator authorization, user creation/validation, role change + password reset + audit, investigation creation, investigator assignment (multiple), unauthorized resource access, status transitions, list filters + dashboard, processing token generation + claims, audio metadata validation, expired token, invalid/mismatched/forged tokens, result synchronization (state reports → result → audio upload with SHA-256 check → transcript retrieval → workstation registry → audit), duplicate result submission (idempotent), failed processing, cancelled job, result validation, transcript edit (original preserved, restore, audit), transcript edit authorization, speaker rename + audit, workstation registration | `docker compose run --rm --no-deps -e SKIP_MIGRATIONS=true -v "$PWD/central/backend:/app" --entrypoint "" backend sh -c "cd /app && python -m pytest tests -q"` (uses the isolated `military_stt_test` database) |
| Voice identification | `central/backend/tests/test_voice_matching.py` | cosine bounds and dimension mismatch, **two prints of one person no longer cancel out**, a person is scored by their best print, two different people too close still abstain, below-threshold abstains, inactive/other-model enrolments ignored, re-enrolling the same person is accepted, a reference under a different name is refused, enrolling a speaker with no embedding is refused, re-match applies a voice enrolled after the session, re-match never overrides a confirmed/rejected decision, global re-match touches only undecided speakers | `docker compose run --rm --no-deps -e SKIP_MIGRATIONS=true -v "$PWD/central/backend:/app" --entrypoint "" backend sh -c "cd /app && python -m pytest tests/test_voice_matching.py -q"` |
| Local Agent unit/integration (43 tests) | `desktop-agent/tests/` (`test_security.py`, `test_segments.py`, `test_sync.py`, `test_agent_api.py`) | token validation (valid, replay, expired, acceptance window, wrong key, wrong iss/aud/action, garbage, missing public key), localhost-only binding, CORS + Private-Network-Access headers, health/capabilities/model-status, audio validation (extension, fake WAV, empty, oversize), full job lifecycle with every state reported and synchronization (result + audio, token discarded), overlap metadata, diarization failure reported (no fallback), STT failure reported, cancellation, cleanup/retention, sync retry after network failure with backoff, idempotent duplicate submission, permanent rejection, SQLite durability across restart, segment post-processing (merge same speaker, never across another speaker, max length, split at silence, VAD trim, padding never duplicates audio, overlap marking, label normalization) | `cd desktop-agent && python -m pytest tests --ignore=tests/test_real_models.py -q` (models are replaced by test doubles; FFmpeg required) or inside the image: `docker compose run --rm agent python -m pytest tests -q` |
| Real models (agent) | `desktop-agent/tests/test_real_models.py` | VAD on real speech, **real NVIDIA Sortformer diarization A→B→A**, real Cohere Arabic transcription, combined speaker-turn transcription | `docker compose run --rm agent python -m pytest tests/test_real_models.py -v -s` (skips when a model is not provisioned) |
| Browser UI smoke (19 checks) | `scripts/ui_smoke.py` | RTL/lang, Arabic login error, dashboard, sessions list + filters, new-session form, details tabs, recording tab + local AI status panel, transcript (segments, overlap badge, audio player, search, speaker filter, click-to-seek, inline edit with original preserved), speaker mapping, activity log, RBAC redirect, logout, users page (columns, add modal, disable/enable), workstations, audit page + filter, console errors | `python scripts/ui_smoke.py --admin-password ...` (Playwright/Chromium; injects a transcript through the agent API — no model run) |
| Real full E2E (spec §81) | `scripts/e2e_browser.py` | admin login → create investigator → investigator login → agent detected → Sortformer READY → Cohere READY → create investigation → upload Arabic two-speaker recording → local processing → sync → PostgreSQL → Arabic transcript displayed → map SPEAKER_00→المحقق / SPEAKER_01→الشخص الذي تتم مقابلته → click segment seeks audio → edit segment (original intact) → audit log | `python scripts/e2e_browser.py --audio desktop-agent/tests/fixtures/conversation_ar_2spk.wav --admin-password ...` |

## Test data

`desktop-agent/tests/fixtures/conversation_ar_2spk.wav` is a 52 s Arabic conversation with
two distinct voices in the pattern A → B → A → B → A (see `fixtures/README.md`). It was
synthesized with neural TTS voices because no human multi-speaker Arabic recording was
available on the build machine. For unit acceptance, replace it with a real interview
recording and re-run `desktop-agent/scripts/run_diarization_test.py … --expect SPEAKER_00,SPEAKER_01,SPEAKER_00`.

## Results on the build machine (2026-08-23, Windows 11, i7-8550U, 24 GB RAM, **no GPU**)

| Suite | Result |
|---|---|
| Central server pytest (isolated PostgreSQL `military_stt_test`) | **197 passed, 0 failed** (voice identification, the canonical person registry, civilian references, external identifiers, participant reconciliation, retiring family-keyed references, consolidation, speaker identity authorization) |
| Reference derivation and the قضاء vocabulary | **28 passed** — includes the generated frontend list matching the backend one |
| Speaker identity in the browser (the reported المتحدثون bug, rank vs canonical name, same-name people, two relatives on one رقم سجل) | **19/19 PASS** |
| Unknown speaker → identity → enrolment, end to end | **23/23 PASS** |
| Voice cycle in the browser (enrol gating, re-scan, per-person grouping) | **17/17 PASS** |
| Activity timeline (readable audit, grouped runs) | **15/15 PASS** |
| Local Agent pytest on the host (test doubles, FFmpeg) | **43 passed** |
| Local Agent pytest, source mounted over the image (2026-08-26) | **44 passed, 3 skipped** — the 3 skips are the real-model tests, which need the models mounted; the 44th is real VAD, which is bundled |
| Local Agent pytest inside the Docker image (`military-stt/desktop-agent:1.0.0-cpu`, real models mounted) | **47 passed, 0 skipped, 0 failed** in 235 s |
| Real VAD on the Arabic conversation | PASS — 10 speech regions, leading silence excluded |
| **Real NVIDIA Sortformer diarization** (`desktop-agent/scripts/run_diarization_test.py`, CPU) | **PASS** — 10 turns in 6.6 s for 52 s of audio; speaker sequence `SPEAKER_00 → SPEAKER_01 → SPEAKER_00 → SPEAKER_01 → SPEAKER_00` exactly as scripted; the same voice is regrouped under the same label each time it returns; overlap flags present; STT windows never overlap |
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

### 2026-08-27 (evening) — identity leaked across recordings in one session

Reported as "later speech keeps being assigned to the last identified person". Measured on
live data: four recordings each emitted `SPEAKER_00`, all sharing ONE row keyed on
`(session_id, speaker_label)`; the matcher correctly scored the newest voice **0.5372**
against the confirmed person and made no suggestion - and the row still displayed them,
because a non-match rightly clears only suggestion state, never a human-set identity. The
row's probe embedding had also been overwritten by each new voice, so the confirmed person's
row held a stranger's voiceprint. The matcher, thresholds and embeddings were all correct;
the defect was row reuse.

Fix: speaker observations are keyed on `(recording_id, source_label)` (migration
`f3d9c40a7e18`) with the server allocating the next free session-wide label; reprocessing the
same recording reuses its rows. Matching moved into PostgreSQL via pgvector (migration
`a9f4e21c8b55`, image `pgvector/pgvector:pg16` + one-time collation REINDEX): all probes of a
recording in one SQL statement, same 0.65/0.05 policy in one shared function. 15 new tests in
`test_speaker_identity_isolation.py` + `test_batch_voice_matching.py`, including a
query-count assertion (N speakers -> ONE gallery query), an SQL-vs-reference agreement sweep,
and a live E2E replaying the actual incident embeddings: the stranger's 0.5372 voice now
becomes a separate `SPEAKER_01` with no identity, while Ali's real print suggests علي عباس at
1.0 - suggestion only, `identity_id` still NULL until a human confirms.

### 2026-08-27 (later) — one source of truth for names

The same human rendered as **MAJOR ALI** in مُحقّقو الجلسة and **ALI** in البحث عن شخص مسجل, and
appeared in both at once. Two causes, one root: three different shapes fed three renderings.
De-duplication excluded only subjects, so an investigator passed straight through into the
registry results.

Fixed by adding `GET /investigations/{id}/people` — every person on a session in one shape,
canonical name resolved through merges, rank carried separately — and by rendering both
sections through a single `PersonRow`. The `participants`/`investigators` props and the
`Participant` type were deleted; the picker owns its own source.

Also in this round: الرقم المرجعي was removed from the subject form (it is computed), الجهاز +
الرقم العسكري became required for military subjects, and the two fields labelled *محل القيد*
were separated into **القضاء** and **البلدة / تفاصيل محل القيد**.

**A regression the suite caught.** The first version of the subject rule refused any military
subject without a serial. Two tests failed, both encoding a documented decision —
*"A soldier with no service number can be neither derived nor issued to."* An interview must be
recordable whether or not the person can be identified. The rule was narrowed to the genuinely
incoherent case: a serial with **no usable force**. Neither-given stays legal.

Verification caught three more before they shipped: the new route registered as
`/investigations/investigations/…` (the router already carries the prefix), `participant_key`
typed as `str` when it is a UUID, and `_investigator_briefs` building its response field by
field so new columns returned `null` while the database was correct.

### 2026-08-27 — investigators became registry people

Migration `b2e94c1f7a06` gives `investigator_profiles` a `security_branch`, `reference_number`
and `identity_id`, and `الجهاز` + `الرقم العسكري` became **required on every user**. Two
consequences worth knowing when a test fails here:

* `tests/conftest.py::create_user` now supplies both fields by default, deriving a UNIQUE
  `military_id` from a **stable digest of the username** — `hash()` is salted per process and
  would collide across runs in a way that reads as a flaky test.
* Identity counts are no longer constants. `test_reorder_and_unrelated_edits_never_reallocate`
  asserted exactly 2 `person_identities`; the investigator running the session is a person now,
  so it asserts a **delta** instead — which is what the test was always about.

The regression that made this worth catching: registration originally *refused* an incomplete
profile, and because the session creator is auto-assigned as lead investigator, that stopped
administrators creating sessions at all. An incomplete profile is now left unregistered and
surfaced in the picker rather than blocking the write.

### 2026-08-26 — voice prints were never produced by a real agent

Reported as a bug in **تسجيل بصمة الصوت**: a voice was recorded and transcribed, the speaker
was identified, and the button still said *لا توجد بصمة صوت لهذا المتحدث*. The button was
right. Three separate faults, each of which alone would have caused it:

1. **The deployed agent image predated the feature.** `ca1e73d` (2026-08-24) added speaker
   identification; the running image was built 2026-08-23. Proof is in the payloads the agent
   itself kept: both jobs in `/data/jobs/*/result.json` lack the `voice_identification` key
   *entirely*, while current code always emits it (`null` when there is nothing to report).
2. **`/model-status` never reported `speaker_id`.** `runtime.status()` included it, but
   `_capabilities()` in `app/api/health.py` copies keys one at a time and that commit never
   added it there. So the capability was invisible even after rebuilding — indistinguishable
   from a missing embedding, which is why the first diagnosis looked confirmed and was not.
3. **The agent test suite had been red since that same commit.** `build_runtime` in
   `tests/conftest.py` never set `runtime.speaker_id`, so every call to `/capabilities` or
   `/model-status` raised `AttributeError`. CI would have caught faults 1 and 2 on the day
   they landed.

Fixed by forwarding `speaker_id` through `_capabilities()` and building the real (unloaded)
service in the test stub. Verified: `speaker_id.state` reaches **READY** ~100 s after
`POST /models/load` on CPU, agent suite **44 passed / 3 skipped**, backend **197 passed**.

**Regression guard still missing.** No test asserts that `/capabilities` contains
`speaker_id`; the suite only proves the endpoint does not crash. A one-line assertion in
`test_health_and_capabilities` would have caught fault 2 directly and is worth adding.

Lesson worth keeping: an *optional* capability that fails silently needs a visible state, or
its absence is indistinguishable from having nothing to do. Hence
**حالة نموذج بصمة الصوت** in the recording tab.

Defects found by earlier verification rounds and fixed:

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

## Running the backend suite

The frontend tree is mounted read-only so the test that proves the generated قضاء picker still
matches the backend vocabulary can actually run:

```bash
docker compose run --rm --no-deps -e SKIP_MIGRATIONS=true   -v "$PWD/central/backend:/app" -v "$PWD/central/frontend:/frontend:ro"   --entrypoint "" backend sh -c "cd /app && python -m pytest tests -q"
```

The image must be built with `INSTALL_DEV=true` for pytest to be present; production images
deliberately omit it. A plain `docker compose build backend` defaults it to `false`, which
silently produces an image with no pytest:

```bash
INSTALL_DEV=true docker compose build backend
```

Under Git Bash on Windows, `$PWD` in a `-v` argument is rewritten by MSYS path translation and
the bind mount silently does not happen — pytest then runs against the code baked into the
image, and *appears* to pass. Use Windows-style paths with translation disabled:

```bash
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -e SKIP_MIGRATIONS=true \
  -v "C:\path\to\central\backend:/app" -v "C:\path\to\central\frontend:/frontend:ro" \
  --entrypoint "" backend sh -c "cd /app && python -m pytest tests -q"
```

## Running the agent suite

The agent image ships pytest, so the quickest check runs the local source against it. Note the
application lives at **`/agent`**, not `/app`:

```bash
MSYS_NO_PATHCONV=1 docker run --rm --entrypoint "" \
  -v "C:\path\to\desktop-agent\app:/agent/app:ro" \
  -v "C:\path\to\desktop-agent\tests:/agent/tests:ro" \
  -w /agent military-stt/desktop-agent:1.0.0-cpu \
  python -m pytest tests -q -p no:cacheprovider
```

Expect **44 passed, 3 skipped** — the skips are the real-model tests, which need the model
directory mounted as well. To include them, add `-v "C:\path\to\models:/models:ro"`.
