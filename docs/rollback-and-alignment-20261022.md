# Diarization rollback and Arabic alignment evaluation

October 23 follow-up: after the user clarified that automatic separation of two
people is the priority, a focused Nemotron model update was validated and
activated. See [automatic-speaker-separation-20261023.md](automatic-speaker-separation-20261023.md).
The rollback and WhisperX evaluation below describe the earlier state.

The user selected restoring the code before today's diarization/review changes,
while retaining the report and login features. There is no October 21 Git commit.
The selected source baseline is `8df46a7bb691d93a1984ca0acb88f6e731970a51`,
committed October 22 at 09:55 Beirut time.

## Restored application

39 tracked files were restored to that baseline. 28 added feature/evaluation
files were archived locally. Report generation, LDAP/local login and existing
speaker identity features remain in the baseline. The experimental review
dialog and Nemotron runtime selection were removed from the running application.
The agent again uses `nvidia/diar_streaming_sortformer_4spk-v2.1`.

Migration `b7c3a1d8e902` is retained solely for database compatibility. Its columns
and the existing attribution review are preserved; the restored application does
not use them. No schema downgrade or database restore was performed.

Backup: `storage/backups/before-rollback-20261022T190759Z/` contains 497 verified
code/artifact files in `working-code.zip`, per-file SHA-256 hashes, the Git diff,
database dump (archive catalog verified), previous agent configuration and image
IDs. `archived-changes/` preserves the removed files. The database and local
configuration backup are private and ignored by Git.

Rebuilt and deployed image digests:

- Backend: `sha256:4abe93c3ae90e6065e3d4a69e537e8260db953ca087a3bf9140f625718d53960`
- Frontend: `sha256:1788e58ed40673f3f69eb357c62645af926235006abb616290062ecf20b1b959`
- Agent: `sha256:4b59d60d46ec1b12eaad7c826b3819275180b1a60b97c096287ac6b6037dfc7b`

The previous images retain the tag `before-rollback-20261022`. The restored
images also retain the tag `rollback-20261022` and are selected through the
usual `1.0.0` / `1.0.0-cpu` tags.

Validation: frontend type check and production build passed; 56 backend tests
passed against the isolated test database (login, LDAP, M53 reports, transcript
processing and report finalization); 50 agent tests passed. Backend tests emitted
read-only cache warnings. The restored agent test fixtures emitted one existing
worker/database teardown warning; no production database failure was observed.
All three services are healthy. The agent loaded all models successfully.
Port 80 serves the restored `index-DfsSHwW2.js` asset, without the attribution
review dialog and with the report form present.

Before/after database counts were identical: 29 recordings, 25 transcripts,
52 source segments, 2 issued reports, 30 speaker observations and 1 attribution
review. Original evidence and reviewed data were not rewritten.

## Isolated alignment trial

The trial uses WhisperX 3.8.6 alignment with the public Arabic checkpoint
`jonatasgrosman/wav2vec2-large-xlsr-53-arabic` at revision
`af46c2d8531b8dcbb5e23b952f739b372c2e5d2d`. The checkpoint SHA-256 is
`a0b26f6d9d3edfde1784aef863c192a8cc1e438a23b45910ab648531ebe1857b`.

This evaluates an additional alignment stage, not a new transcription engine:
the existing Arabic text is aligned to audio and matched to the saved Nemotron
turns for the same recording. Source hashes are checked; all inputs are mounted
read-only and inference runs without networking or central synchronization.
The saved Nemotron result is an evaluation input, not the restored live model.

`scripts/whisperx-alignment.Dockerfile` uses the official release's alignment
source at commit `3ccc17b8de34f305300f8a3fd3c9f76ba820c0d0` in a separate image,
with the original BSD license and per-file hashes. It installs NLTK 3.9.2. Existing
input utterance spans replace sentence-tokenizer inference; CTC alignment itself
uses the unchanged official implementation. The full WhisperX ASR/diarization CLI is not
installed as a supported runtime: unused Faster-Whisper/CTranslate2/CUDA packages
are omitted. The restored agent's packages are unchanged.

`scripts/run-whisperx-alignment.ps1` writes private results under the ignored
`storage/model-evaluation/results/` directory. It never uploads or replaces a
production transcript. Missing word times and speaker ties remain explicit;
words are not silently discarded or forced onto the nearest speaker. Eight
regression tests cover speaker changes, missing times, silence, overlap,
duplicate turns, invalid intervals and JSON export of NumPy numeric scalars.

The isolated runtime image is built:
`sha256:adcb4fb4f893a977d38c0a261bc9503c94da3d4f42fe85581415d3ffbdc0b2f4`.
Its real WhisperX CTC code passed a synthetic-emissions integration check,
producing two timed Arabic words and splitting them automatically by speaker.

The model download completed and passed checksum verification. The first real
run encountered a NumPy integer JSON-export error after inference; this is fixed
and covered by regression tests. The PowerShell runner also now checks Docker's
exit code without treating harmless redirected model progress as a fatal error.

The real trial completed October 23 at 21:52 Beirut time. On the 33.24-second
recording, with two CPU threads and a 4 GB container limit:

- All 51 existing transcript words were preserved and received alignment times.
- 50 words received speaker assignments, covering two saved Nemotron speakers.
- One timed word fell outside the supplied speaker turns and remains unassigned.
- The output contains five text runs, including the unassigned word.
- Model loading took 8.543 seconds; alignment took 20.739 seconds. These timings
  exclude the earlier transcription and diarization work and container startup.
- Input hashes remained unchanged; no production transcript was updated.

Results are in `storage/model-evaluation/results/whisperx-arabic-alignment.json`.
The continuation status is `completed` in `alignment-trial-status.json`; retry
logs are alongside it. All eight alignment tests pass in the isolated image.

These are coverage and runtime measurements, not measured timing or speaker
accuracy. Alignment only uses existing text within its supplied utterance spans;
it cannot recover speech omitted by that transcript. No manually labelled
reference boundaries were supplied. WhisperX remains an isolated trial and has
not replaced the restored production engine.
