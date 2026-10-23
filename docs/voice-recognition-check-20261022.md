# Voice recognition diagnosis and deployment — 2026-10-22

The local SpeakerNet model was ready and recent processing results were reaching
the central database. Two separate outcomes explained the reported failure:

- In the 06:35 UTC recording, one turn covered 1.10–8.56 seconds and another
  covered 1.28–2.88 seconds. Both had an overlap flag. The old extraction code
  discarded both entire turns, leaving no voice embeddings.
- In the 06:38 UTC recording, matching did run. One observation scored 0.6918
  against the configured 0.65 threshold and remained a suggestion awaiting human
  confirmation. The other scored 0.3877 and correctly received no suggestion.

The gallery contained 15 active prints: nine with current model provenance and
six older prints with no recorded revision. Unknown provenance was not fabricated,
and compatibility rules and matching thresholds were not relaxed.

## Changes

- Extract identity audio from all original diarization turns, subtract precise
  competing intervals, and intersect voice activity regions. Keep uncertain
  overlap excluded, including competing turns that yielded no transcript text.
- Store extraction diagnostics and show actionable processing warnings for short
  or overlapping speech, disabled identification, and unavailable models.
- Return matching outcome counts, including missing samples, incompatible prints,
  low similarity, ambiguity, and preserved human decisions.
- Show these counts in Arabic, explain missing samples, link pending transcript
  suggestions to the speakers tab, and refresh speaker state after enrollment.

## Verification

- 54 backend voice tests passed against the isolated test database.
- 37 agent tests passed. One lifecycle cleanup warning in that combined run did
  not recur in the focused final run: seven tests passed without warnings,
  including the updated warning cases and lifecycle test.
- Frontend type checking and production build passed.
- Offline real-model check of the original affected audio recovered 5.86 seconds
  of clean speech and a normalized 256-dimensional embedding. The wholly
  overlapping second voice still had no isolated speech. No results were uploaded
  by this check and no original audio was modified.
- Isolated browser workflow: pending suggestion notice, navigation, diagnostic
  counts, missing-sample guidance, confirmation, and name in transcript all
  verified. Test port 18081 is deliberately outside the live agent's CORS allowlist;
  live origin http://localhost was separately verified with HTTP 200 and its
  matching Access-Control-Allow-Origin header.

## Deployment and retained data

Backend, frontend, and CPU agent were rebuilt and recreated. All services are
healthy. Served frontend asset: `index-B17xQ6bN.js`. Temporary test services were
removed. Rollback images use tag `before-voice-overlap-20261022` for all three.

Live counts remained unchanged: one session, 23 speaker observations, 42
transcript segments, 15 voice prints, and two generated reports. No migration was
needed. Existing recordings were not rewritten or automatically reassigned.

For a historic observation with no embedding, rerun audio processing or make a
new clear recording; voice rematching alone only compares already stored samples.
A suggested name becomes an assigned identity only after investigator confirmation.
