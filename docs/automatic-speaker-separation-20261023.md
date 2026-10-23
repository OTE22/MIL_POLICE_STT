# Automatic speaker separation

The user confirmed that the 33.24-second sample contains two people. The saved
result from the restored four-speaker Sortformer model contains one speaker.
The local Nemotron 3 and pyannote Community-1 trials both detected two speakers
without receiving the expected count during inference. Nemotron took 3.839
seconds for diarization; pyannote took 59.325 seconds in the recorded two-thread
CPU comparison. Speaker count alone does not establish boundary accuracy.

The focused change selects the pinned Nemotron 3 model in the desktop agent.
It uses the normal upload, automatic diarization, per-speaker Arabic transcription
and result display. WhisperX and the manual attribution-review dialog are not
part of this change. Report generation and login keep the restored implementation.

The model adapter validates the checkpoint revision and speaker capacity, loads
all weights strictly, and uses the model's 264-frame speaker cache. Runtime
capabilities reflect the selected model. The provisioning script validates the
downloaded checkpoint checksum. The expected count of two is only an evaluation
assertion; it is never passed to model inference.

Build and model pins are documented in [nemotron-diarization.md](nemotron-diarization.md).
The candidate was built from `military-stt/desktop-agent:rollback-20261022` using
`scripts/build-nemotron-agent.ps1`, with output tag
`military-stt/desktop-agent:speaker-separation-20261023`.

Before-change configuration and modified files are backed up in
`storage/backups/before-speaker-separation-20261023T185726Z/`. The prior live image
remains tagged `military-stt/desktop-agent:rollback-20261022`. Original recordings
and existing transcripts are preserved; selecting a model does not rewrite them.

Validation: 69 model-selection, segment-processing, API, security and
speaker-embedding tests passed. The existing test fixture still emits its known
worker/database teardown warning. `pip check` found no broken dependencies.

The complete pipeline passed on the user's 33.24-second recording: two speakers,
14 raw turns, eight transcribed segments and no empty transcription segments.
Each speaker has a separate normalized voice embedding. Both the source and
private-copy SHA-256 checks passed, and synchronization remained disabled.
The full test took 643.39 seconds, including cold model loading; transcription
itself took 106.33 seconds. Its initial 8 GiB memory limit caused paging while
loading the existing Cohere model and was raised to 10 GiB. This is not a
representative measurement of warm production latency.

Two additional real-inference tests passed on the existing synthetic fixtures:
the A → B → A → B → A sequence retains speaker identity when each voice returns,
and a single-speaker clip remains one speaker. The first concurrent fixture run
was stopped to relieve memory pressure; the subsequent sequential run passed
both tests in 48.34 seconds. The CPU-only pin-memory warning is informational.

Reports and logs are under `storage/model-evaluation/results/`:
`full-pipeline-speaker-separation-20261023.json`,
`speaker-fixtures-20261023.xml` and `speaker-fixtures-20261023-sequential.log`.
Synthetic fixtures and the user's confirmed speaker count provide bounded
validation; exact boundary error on the real recording remains unmeasured.

The agent was activated through its normal Compose service using the updated
`1.0.0-cpu` tag, image
`sha256:55c1e029cd4f7e2795483a2ea366be05087edd46a62341413b485106f49a15d1`.
Local configuration selects the pinned Nemotron revision and 264-frame cache.
Post-activation verification reports the agent ready, with diarization,
transcription and speaker identification all `READY` and no model errors. The
central application health check and database connectivity also passed.
New processing uses the model automatically. Previously saved results keep their
original provenance and must be processed again to obtain a new result.

References: [official Nemotron model](https://huggingface.co/nvidia/Nemotron-3-Diarization),
[official Community-1 model](https://huggingface.co/pyannote/speaker-diarization-community-1).
