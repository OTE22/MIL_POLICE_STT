# Voice enrollment readiness review — 2026-09-19

Initial verdict: the normal API/database workflow was implemented, but production readiness was not established. The findings below describe the initial review; the remediation section records the subsequent fixes. An interactive browser was unavailable, so this is not a completed visual end-to-end acceptance test.

## Workflow

1. The local agent separates speaker turns and uses NVIDIA SpeakerNet to produce a normalized 256-dimensional vector. Configured audio limits are 2–30 seconds.
2. The central server stores the probe on a recording-specific speaker observation. An authorized operator links that speaker to an existing person UUID.
3. The enrollment dialog sends consent and metadata to the speaker enrollment endpoint. The server copies the stored vector and canonical person identity into `voice_enrollments`; it records source session/speaker, enrolling user, timestamps, and an audit event. Vectors are not returned in registry responses.
4. Subsequent probes are compared in PostgreSQL using pgvector cosine similarity against active enrollments with the same model name and dimension. Each person's best print determines their score.
5. The live threshold is 0.65 and the required lead over the next person is 0.05. Weak or ambiguous matches yield no suggestion. A score is a similarity measure, not a probability of identity.
6. An investigator must confirm the suggestion before it becomes an identity assignment. Existing recordings can be rescanned without rerunning audio inference.

## Live observations

- `/voice-enrollments` returns HTTP 200 with the deployed frontend bundle; unauthenticated registry API access returns 401.
- Eight active enrollments: all have consent and canonical identity links, all have 256 dimensions, and no source model-name mismatch was found.
- Six enrollments have no model revision; two report revision 1.16.0.
- Twelve speaker observations: seven confirmed, five with no suggestion.
- Agent identification is enabled and the configured model file exists. This does not prove a fresh real-audio inference succeeds.

## Findings before production sign-off

1. **High: model provenance is client-controlled.** `app/api/voice.py` enrolls under `body.model`, provider, duration and optional revision without enforcing the source embedding model. The candidate response does not include its model; the frontend falls back to a hardcoded model. The matcher filters model name and dimension, but not revision/provider. Derive provenance from the trusted processing result, persist it independently of suggestions, and define embedding compatibility across revisions.
2. **High: stale suggestions can be confirmed.** `decide_suggestion` writes the stored suggested name and CONFIRMED state before checking whether its enrollment still exists. Missing identity does not reject confirmation; inactive enrollment is not checked. Revalidate the active print and canonical identity before assigning anything, and invalidate pending suggestions when their supporting print is removed or disabled.
3. **High: recognition accuracy is not validated for operational recordings.** Existing documentation describes calibration using two synthetic voices and five samples. Measure false acceptance, false rejection and unknown-speaker behavior on representative held-out recordings, microphones, noise and overlapping speech before setting operational thresholds. The current audio collection loop includes overlapping segments rather than excluding them.
4. **Medium: registry fetch failures look like empty results.** `VoiceEnrollmentsPage.tsx` catches list/candidate errors by setting empty arrays. Show explicit errors and retry controls; prevent stale search responses from replacing newer results.
5. **Medium: duration is not reliable embedding provenance.** The candidate duration sums transcript speech while the agent caps embedding input at 30 seconds; enrollment stores browser-submitted duration. Persist the actual duration used by the encoder.
6. **Scale/access review remains necessary.** Registry listing is global for users with `voice.identify`, without pagination, and matching performs exact comparisons and returns all ranked identities. Confirm the intended registry visibility policy and load-test the expected gallery size. This review does not certify deployment security or recognition accuracy.

## Verification limits

All 50 targeted regression tests passed across voice matching, batch matching, enrollment candidates, identity authority, authorization and recording isolation.

The regression suite exercises synthetic embeddings through real API and PostgreSQL paths. It verifies software rules, not real-world biometric reliability. Interactive enrollment, microphone/audio capture and a new real-model inference were not verified in this review.

## Remediation

- Enrollment now copies model, revision, provider and actual embedding duration from the stored agent result. Browser metadata cannot override them. Missing source models are rejected. New probe provenance persists even when no match is found.
- Matching requires equal model, dimension, revision and provider. Unknown metadata does not match known metadata; unknown-to-unknown matching remains within the same model and dimension. No current model version is invented for historical records.
- Confirmation locks and revalidates the active supporting print before assigning the current canonical name and UUID. Removing or disabling a print invalidates pending suggestions, while retaining completed human decisions and audit history.
- Frontend failures show an error and retry control. Superseded search requests cannot replace current results. Prints missing revision/provider display a reprocessing notice.
- Agent voice extraction excludes overlapping speech, including intersections without overlap flags, and merges duplicate windows before measuring duration.
- An offline calibration evaluator is available at `scripts/evaluate_voice_thresholds.py`. It measures unknown-speaker false acceptance, known-speaker rejection and wrong-person identification separately. It rejects same-recording gallery/probe comparisons and never changes production thresholds automatically.

Validation: 68 backend regression tests, 13 agent audio/segmentation tests, two calibration evaluator tests and the frontend build passed. A real SpeakerNet inference on the repository fixture also succeeded: 256 finite dimensions with unit norm. This is a smoke test, not recognition-accuracy validation.

Migration `e9b5a3d02f71` adds independent probe provenance and invalidates pending suggestions for recomputation under the new rules. It preserves enrollment records and completed human decisions. Original agent result files were unavailable in the running agent, so historical unknown provenance could not be recovered safely. Reprocess source recordings and replace affected enrollments to establish complete provenance; do not assign guessed revisions.

Still required for production sign-off: representative real-audio calibration, live enrollment and real-recording UI acceptance, workload capacity testing and confirmation of the deployment's global voice-registry access policy. The thresholds remain 0.65/0.05 pending empirical validation.

### Review-panel follow-up — 2026-09-20

The deployed review panel now includes explanations, authorized source playback, pairwise
comparison, reasoned per-print reviews and manual same-person confirmation of selected
samples within or across groups. Confirmations preserve numerical results and vectors,
retain reviewer/time/reason history, can be reopened, and never extend to new samples
automatically. Changed covered samples require review again. Speaker cards group confirmed
canonical identities while preserving recording observations and correct session totals.

The 32 targeted backend checks, frontend production build and synthetic desktop/mobile
browser checks passed. Backend/frontend deployment health, the served UI bundle and
unauthenticated rejection of the new routes were verified. Browser checks used mocked API
responses and silent audio; they do not close the real-audio accuracy or live enrollment
acceptance items above. No new migration was needed. See [voice-review-panel.md](voice-review-panel.md)
and [testing.md](testing.md) for details and reproducible commands.

### Offline calibration input

Use one held-out recording per probe and a separate enrollment gallery. Supply compatible-model cosine scores for every candidate print, including the strongest competing identities. Use real known and unknown speakers; avoid training/calibration/test speaker leakage when evaluating generalization. Keep identifiers pseudonymous and files local.

```json
[
  {"probe_id":"p1","probe_recording_id":"test-recording-1","expected_identity":"person-a",
   "candidates":[{"identity_id":"person-a","source_recording_id":"gallery-recording-1","score":0.82}]},
  {"probe_id":"p2","probe_recording_id":"test-recording-2","expected_identity":null,
   "candidates":[{"identity_id":"person-a","source_recording_id":"gallery-recording-1","score":0.42}]}
]
```

These example scores illustrate the format only, not evidence of accuracy. Run:

```text
python scripts/evaluate_voice_thresholds.py held-out-scores.json --thresholds 0.65 0.70 0.75 0.80 --margin 0.05
```
