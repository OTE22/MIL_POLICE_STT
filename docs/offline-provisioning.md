# Offline provisioning

**Who this is for:** whoever prepares the AI model files, and anyone installing at a site
with no internet. Practical, but it assumes you are comfortable with a command line.

After provisioning, normal operation needs **no Internet access**: no model downloads, no
CDN fonts/scripts (IBM Plex Sans Arabic and all JS/CSS are bundled), no cloud STT or
diarization.

## Model directory layout

```
<MODEL_DIR>/                          Windows: C:\ProgramData\InvestigationAI\models
├── cohere-transcribe-arabic-07-2026/ Linux:   /opt/investigation-ai/models   Docker: /models
│   ├── config.json  generation_config.json  model.safetensors  normalizer.json
│   ├── preprocessor_config.json  processor_config.json  special_tokens_map.json
│   ├── tokenizer.json  tokenizer.model  tokenizer_config.json
│   └── MANIFEST.json                 {model, revision, source, files:{path:{size, sha256}}}
├── diar_streaming_sortformer_4spk-v2.1/
│   ├── diar_streaming_sortformer_4spk-v2.1.nemo
│   └── MANIFEST.json
└── silero-vad/                        copy of the files bundled in the silero-vad wheel (+ MANIFEST.json)
```

## Provisioning on a connected machine

```bash
HF_TOKEN=hf_xxx python scripts/provision_models.py --model-dir ./bundle/models
```

* Downloads the **pinned revisions** from `app/config.py`
  (`COHERE_STT_REVISION`, `NVIDIA_DIARIZATION_REVISION`), never `main`.
* The Cohere repository is gated: accept the licence on huggingface.co once; the token is used
  only for this download and is not stored.
* Writes `MANIFEST.json` with SHA-256 per file.

Then copy `bundle/models` to every workstation (USB / internal file share) and install the
central public key (`central_public_key.pem`).

### Slow or unstable links (resumable download of the 4 GB STT weights)

`huggingface_hub` cannot always resume a partial download across processes. Use the
resumable helper instead (each attempt continues from the current file size via HTTP Range):

```powershell
$env:HF_TOKEN = "hf_..."                               # not stored anywhere
.\desktop-agent\scripts\resume_cohere_weights.ps1        # or run detached with Start-Process
# when the file is complete the script runs finalize_cohere_weights.py automatically:
#   size + SHA-256 (404ff5dc…1910a5) check, rename .part -> model.safetensors, MANIFEST.json
```

`python scripts/finalize_cohere_weights.py --model-dir <dir>` can also be run by hand after
copying `model.safetensors` from another machine.

## Integrity verification

`AGENT_VERIFY_MODEL_INTEGRITY`:

| value | behaviour |
|---|---|
| `size` (default) | every file in the manifest must exist with the recorded size |
| `full` | additionally verifies SHA-256 of every file (slow for the 4 GB STT model; use after copying a bundle) |
| `none` | skip |

A failed check blocks loading with `stt_model_integrity` / `diarization_model_integrity`.
`python scripts/healthcheck.py` reports manifest revisions and verification results.

## Version pinning

Model names and revisions are recorded on every transcript (`stt_model`,
`stt_model_revision`, `diarization_model`, `diarization_model_revision`, `agent_version`,
`processing_device`) and on the workstation registry. Upgrading a model means changing the
pinned revision in configuration, re-provisioning, re-running the acceptance tests, and
re-registering the workstation — never an automatic download at start-up.

## Python dependencies offline

Build a wheelhouse on a connected machine and install from it on the workstation:

```bash
pip download -r requirements-gpu.txt -r requirements.txt -d wheelhouse
pip install --no-index --find-links wheelhouse -r requirements-gpu.txt -r requirements.txt
```

The Docker image (`desktop-agent/Dockerfile`) can likewise be built once and exported with
`docker save` / `docker load`.
