# Audio pipeline

## Input validation (browser → agent → central)

| Check | Where |
|---|---|
| Extension `wav, mp3, m4a, webm` | frontend, agent (`/jobs`), central (token request + audio upload) |
| MIME type allow-list | frontend, agent, central |
| Size ≤ 2 GiB (configurable) | frontend, agent streaming limit, central streaming limit, nginx |
| Empty file | agent, central |
| Magic bytes (RIFF/WAVE, ID3/MPEG sync, ftyp, EBML, OggS) | agent, central — the filename is never trusted |
| Readability + duration via `ffprobe` | agent (`audio_too_short`, `audio_too_long`, `malformed_audio`) |

## Original vs processing copy

* The original upload is stored unchanged as `original.<ext>`; its SHA-256, size, MIME,
  duration and codec are recorded and sent to the central server, which re-hashes the
  uploaded original and refuses a mismatch.
* FFmpeg creates `processing_16k_mono.wav` (`-ac 1 -ar 16000 -sample_fmt s16`) used by VAD,
  diarization and STT. It is deleted after finalization.

## VAD (Silero)

`get_speech_timestamps(threshold=0.5, min_speech_duration_ms=250, min_silence_duration_ms=300,
speech_pad_ms=60)` — all configurable (`AGENT_VAD_*`). VAD regions are used to:

* trim diarization turns so silence is never sent to the STT model,
* pick split points inside long turns,
* fail early with `no_speech_detected` if the recording contains no speech.

## From speaker turns to STT windows (segment_service)

1. **clean** — clip to the audio, drop empty turns.
2. **trim_to_vad** — intersect each turn with speech regions.
3. **drop_tiny** — fragments shorter than 0.3 s are dropped (the longest fragment is kept
   if nothing else remains).
4. **merge** — consecutive fragments of the **same** speaker separated by ≤ 0.7 s are
   consolidated (`SPEAKER_00 10.20–12.10` + `SPEAKER_00 12.25–15.40` → `10.20–15.40`) as long as
   the result stays ≤ 28 s and **no other speaker starts or is active inside the gap**.
   Merging never crosses another speaker.
5. **split_long** — turns longer than 28 s are cut at the widest VAD silence inside the first
   28 s (hard cut as last resort), keeping STT inputs bounded and context-rich.
6. **windows** — 0.3 s of context is added before/after each segment, **clamped to half of the
   gap** to the neighbouring segment (any speaker). Two windows therefore never contain the
   same audio → no duplicated words between neighbouring segments, no reconciliation step is
   needed afterwards. Timestamps shown to the user are the segment boundaries, not the padded
   window.

### Overlap

Sortformer emits independent activity per speaker, so simultaneous speech appears as two
turns that intersect in time. `mark_overlaps` flags every turn that intersects a turn of a
different speaker by ≥ 0.2 s (`is_overlap = true`). Both speakers' segments are kept and
transcribed from their own (overlapping) windows — this is the one intentional case where two
windows share audio, because dropping one voice would misattribute speech. The UI shows
`تداخل في الكلام` on those segments. No source separation is attempted (MVP).

### Speaker change vs diarization

* *Speaker change detection* only says "a different voice started".
* *Diarization* additionally groups every occurrence of the same voice under one anonymous
  label across the whole recording (`SPEAKER_00 → SPEAKER_01 → SPEAKER_00`). Sortformer's
  arrival-order speaker cache provides this grouping; labels are re-numbered by first
  appearance so `SPEAKER_00` is always the first person who spoke.

## Output

```json
{
  "segments": [
    {"speaker_label": "SPEAKER_00", "start_seconds": 2.4, "end_seconds": 8.9, "text": "أين كنت مساء أمس؟", "is_overlap": false, "confidence": null},
    {"speaker_label": "SPEAKER_01", "start_seconds": 9.1, "end_seconds": 16.3, "text": "كنت في المنزل.", "is_overlap": false, "confidence": null}
  ],
  "stt_model": "CohereLabs/cohere-transcribe-arabic-07-2026", "stt_model_revision": "c3e911b4…",
  "diarization_model": "nvidia/diar_streaming_sortformer_4spk-v2.1", "diarization_model_revision": "fafaab5f…",
  "vad_model": "snakers4/silero-vad@silero-vad 6.2.1", "agent_version": "1.0.0", "processing_device": "cpu",
  "speaker_count": 2, "warnings": ["Processed on CPU."], "audio": {"sha256": "…", "duration_seconds": 21.0},
  "processing_metadata": {"timings": {...}, "vad": {...}, "segmenting": {...}, "diarization_streaming": {...}}
}
```

Segments with no recognized text are dropped and counted in `warnings`; the central server
re-sorts segments by time and assigns `sequence`.
