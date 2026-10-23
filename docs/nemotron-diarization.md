# Optional Nemotron 3 diarization runtime

The default agent still selects `nvidia/diar_streaming_sortformer_4spk-v2.1`
(four anonymous speakers). An administrator can select the verified
`nvidia/Nemotron-3-Diarization` checkpoint (up to eight anonymous speakers).
Neither model identifies a person's name. SpeakerNet voiceprints and confirmed
enrollments remain the separate identity workflow.

## Pinned artifacts

| Artifact | Pin |
| --- | --- |
| Nemotron model revision | `f667ed73aee57d40cc39428eb768b4fd87a0a29e` |
| Checkpoint SHA-256 | `867c53f552998f772e5b5e5c082962ae85ee7ca5669c2bc17d7f615133d4e96d` |
| Official NeMo source | `NVIDIA-NeMo/Speech@16b0ff2584c6355c53cbd6c28f0f431a76b24956` |
| Lhotse | `2.0.0a6` |
| Lhotse wheel SHA-256 | `15145bd072a3d6c5f6b52b07e40f0425f7189ec3a409fedd416c04331422cac3` |

The released NeMo 3.0.0 runtime lacks this checkpoint's rotary attention
implementation. The pinned source snapshot still reports package version
3.0.0, so the image also records `NEMO_SOURCE_REVISION`. Both diarization
checkpoints use strict loading; incomplete weights fail instead of being
accepted. The adapter validates checkpoint capacity and manifest identity.

## Build and select

From the repository root, run `scripts/build-nemotron-agent.ps1`. It checks a
clean pinned official source checkout, verifies the Lhotse wheel checksum, and
builds `military-stt/desktop-agent:nemotron-candidate`. The build installs the
whole NeMo package and Lhotse without resolving or upgrading other dependencies.
It does not select a model or restart the live agent. Supply `-BaseImage` and
`-Image` to use different base/output tags; build the normal agent image first
when a base image is not available.

Provision the checkpoint using the candidate runtime's provisioning script:

```sh
python scripts/provision_models.py --model-dir /models --only diarization --diarization-model nvidia/Nemotron-3-Diarization
```

Deploy the candidate image using the normal service deployment process, with:

```dotenv
AGENT_DIARIZATION_MODEL=nvidia/Nemotron-3-Diarization
AGENT_DIARIZATION_MODEL_REVISION=f667ed73aee57d40cc39428eb768b4fd87a0a29e
AGENT_DIARIZATION_SPEAKER_CACHE_LEN=264
```

The revision and cache overrides may be empty; configuration then selects the
model's pinned defaults. Unknown models and mutable revision names are rejected.
Keep the previous image and four-speaker model for rollback. Selecting a model
in the environment alone cannot add missing runtime support or model files.

## Evaluate without central writes

`scripts/evaluate_agent_pipeline.py` exercises the actual VAD, diarization,
Arabic transcription, and speaker embeddings in the image. Run it with the
original audio and models mounted read-only, a writable results directory,
`PYTHONPATH=/agent`, and Docker `--network none`:

```sh
python /tools/evaluate_agent_pipeline.py /input/original.webm --models /models --output /results/full-pipeline.json --expected-speakers 2 --cpu-threads 2
```

The evaluator copies audio into private temporary storage, uses a temporary
SQLite database, disables synchronization, and verifies the original hash. Its
report contains boundaries, counts, model provenance, and embedding dimensions
and norms; it omits transcript text and voiceprint vectors. A passing count on
one recording establishes that case and runtime compatibility. Measuring
general speaker-attribution accuracy requires human-annotated recordings and
separate evaluation of boundary errors, overlaps, and transcription quality.

Official sources: [model card](https://huggingface.co/nvidia/Nemotron-3-Diarization),
[pinned NeMo source](https://github.com/NVIDIA-NeMo/Speech/tree/16b0ff2584c6355c53cbd6c28f0f431a76b24956),
[Lhotse release](https://pypi.org/project/lhotse/2.0.0a6/).
