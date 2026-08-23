# Speaker diarization — NVIDIA Streaming Sortformer

| | |
|---|---|
| Model | `nvidia/diar_streaming_sortformer_4spk-v2.1` (end-to-end neural diarizer, arrival-order speaker cache) |
| Pinned revision | `fafaab5faa1617a0ca52d38dd3dc4bd636800d3d` (`AGENT_DIARIZATION_MODEL_REVISION`) |
| File | `diar_streaming_sortformer_4spk-v2.1.nemo` (471 MB), not gated |
| Runtime | NVIDIA NeMo `nemo_toolkit[asr]==3.0.0` (`SortformerEncLabelModel`), PyTorch |
| Provider key | `AGENT_DIARIZATION_PROVIDER=nvidia_sortformer` (`DiarizationService` interface) |
| Output | `SpeakerTurn(speaker_label, start_seconds, end_seconds, is_overlap)` |
| Limit | **4 speakers** (`MAX_SUPPORTED_SPEAKERS`) |

## What it does — and does not do

* Detects speaker activity and speaker changes.
* Groups repeated occurrences of the same anonymous voice (`SPEAKER_00` again after `SPEAKER_01`).
* Provides start/end timestamps; overlapping speech appears as intersecting turns.
* Does **not** know who the person is (no voice biometrics) and does **not** produce text.
  NeMo also ships ASR models — they are deliberately not used.

## Loading

```python
model = SortformerEncLabelModel.restore_from(restore_path=NEMO_PATH, map_location=device, strict=False)
model.eval()
m = model.sortformer_modules
m.chunk_len = 340; m.chunk_right_context = 40; m.fifo_len = 40
m.spkcache_update_period = 300; m.spkcache_len = 188
m._check_streaming_parameters()
turns = model.diarize(audio=[wav_path], batch_size=1)   # ["0.00 5.12 speaker_0", ...]
```

The default streaming configuration is the model card's **"very high latency"** preset
(≈ 30 s input buffer), which gives the best accuracy for offline processing of a finished
recording. It can be changed through `AGENT_DIARIZATION_CHUNK_LEN`, `_RIGHT_CONTEXT`,
`_FIFO_LEN`, `_UPDATE_PERIOD`, `_SPEAKER_CACHE_LEN` (all in 80 ms frames).

## Post-processing

1. `parse_nemo_segments` normalizes NeMo's output (`speaker_0` → `SPEAKER_00`).
2. `relabel_by_first_appearance` renumbers labels in order of first speech.
3. `mark_overlaps` flags turns of different speakers intersecting by ≥ 0.2 s.
4. `segment_service` (see audio-pipeline.md) trims to VAD, merges same-speaker turns without
   crossing another speaker, splits long turns and builds STT windows.

## The four-speaker limitation

The session form records `expected_speaker_count`; values above 4 show the operational
warning "نموذج فصل المتحدثين المعتمد يدعم حتى أربعة متحدثين كحد أقصى…" on the session, when the
processing token is issued and on the transcript. If the model reports four labels, the
result carries a warning that additional speakers may have been merged. Another provider
(e.g. NVIDIA clustering diarizer, pyannote) can be added behind `DiarizationService` without
touching the business logic.

## Acceptance test (spec §80)

```
python scripts/run_diarization_test.py recording.wav --expect SPEAKER_00,SPEAKER_01,SPEAKER_00
```

prints VAD regions, raw turns, post-processed segments and the collapsed speaker sequence,
and exits non-zero if the sequence differs from the expectation.
