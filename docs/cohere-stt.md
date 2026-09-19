# Arabic speech-to-text — Cohere Transcribe Arabic

**Who this is for:** developers and whoever provisions the models.

| | |
|---|---|
| Model | `CohereLabs/cohere-transcribe-arabic-07-2026` (2 B-parameter Conformer encoder-decoder, Arabic + dialects + English) |
| Pinned revision | `c3e911b42149bf7a1e53d5cef9878aee87515a23` (`AGENT_STT_MODEL_REVISION`) |
| Licence | Apache-2.0 — the Hugging Face repository is **gated**: accept the licence once with an HF account and use `HF_TOKEN` only for provisioning |
| Runtime | Hugging Face Transformers ≥ 5.4 (`CohereAsrForConditionalGeneration`, `AutoProcessor`), PyTorch |
| Provider key | `AGENT_STT_PROVIDER=cohere_local` (`TranscriptionService` interface in `app/ai/transcription_service.py`) |
| Input | 16 kHz mono float32 waveform (the processing copy), one window per speaker segment |
| Language | `AGENT_STT_LANGUAGE=ar` |

## Loading (offline)

```python
processor = AutoProcessor.from_pretrained(MODEL_DIR, local_files_only=True)
model = CohereAsrForConditionalGeneration.from_pretrained(MODEL_DIR, local_files_only=True, dtype=dtype)
model.to(device).eval()
```

`HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1` are set in the Docker image and the systemd unit;
nothing is downloaded at runtime. The model directory contains the snapshot files listed in
`scripts/provision_models.py` plus `MANIFEST.json` (SHA-256 of every file).

## Inference (per segment)

```python
inputs = processor(audio=clip, sampling_rate=16000, return_tensors="pt", language="ar")
chunk_index = inputs.get("audio_chunk_index")         # present only for long-form input
inputs = inputs.to(model.device, dtype=model.dtype)
outputs = model.generate(**inputs, max_new_tokens=448, num_beams=1)
text = processor.decode(outputs, skip_special_tokens=True, [audio_chunk_index=…, language="ar"])
```

Segments are ≤ 28 s, i.e. shorter than the feature extractor's `max_audio_clip_s`, so the
long-form chunking path is normally not used; it is still handled when present.

## Device / dtype

`AGENT_STT_DEVICE=auto` → CUDA if available, else CPU. `AGENT_STT_DTYPE=auto` → float16 on
GPU, float32 on CPU. CPU mode works but is slow (the UI warns
"سيتم استخدام المعالج المركزي، وقد تستغرق عملية المعالجة وقتاً أطول."); an NVIDIA GPU with
≥ 8 GB VRAM is recommended for production workstations.

## Failure behaviour

* Model files missing → `stt_model_missing` (`النموذج غير جاهز` in the UI).
* Integrity mismatch → `stt_model_integrity`.
* Load/inference error → `stt_model_load_failed` / `transcription_failed`.

In every case the job fails and the investigator sees
"تعذر تشغيل نموذج تحويل الصوت إلى نص على هذا الجهاز." — no cloud API, no Whisper, no central
inference is ever attempted.
