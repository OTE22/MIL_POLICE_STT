# Military STT AI — Investigation / Interview Session Management

A distributed, offline-first web application for managing investigation and interview
sessions: record or upload audio, detect **who spoke when** (NVIDIA Sortformer), transcribe
**what was said** in Arabic (Cohere Transcribe Arabic), map anonymous speakers to real names,
correct the transcript without losing the AI result, and keep a complete audit trail.

* **User interface:** Arabic, RTL (`<html lang="ar" dir="rtl">`)
* **Code, APIs, schema, docs:** English

```
                         CENTRAL SERVER (Docker Compose)
                 ┌───────────────────────────────────────┐
                 │ frontend  : React + Vite, Arabic RTL   │
                 │ backend   : FastAPI, SQLAlchemy, JWT   │
                 │ postgres  : PostgreSQL 16              │
                 │ nginx     : reverse proxy / TLS        │
                 └───────────────────┬───────────────────┘
                                     │ HTTPS / LAN
               ┌─────────────────────┼─────────────────────┐
               ▼                     ▼                     ▼
         DESKTOP 01            DESKTOP 02            DESKTOP 03
         Local AI Agent        Local AI Agent        Local AI Agent
         127.0.0.1:17117       127.0.0.1:17117       127.0.0.1:17117
         FFmpeg → Silero VAD → NVIDIA Sortformer (who) → Cohere Transcribe Arabic (what)
```

| Concern | Technology |
|---|---|
| Speaker diarization (**who spoke when**) | `nvidia/diar_streaming_sortformer_4spk-v2.1` via NVIDIA NeMo — revision `fafaab5faa1617a0ca52d38dd3dc4bd636800d3d` |
| Arabic speech-to-text (**what was said**) | `CohereLabs/cohere-transcribe-arabic-07-2026` via Transformers ≥ 5.4 — revision `c3e911b42149bf7a1e53d5cef9878aee87515a23` |
| Voice activity detection | Silero VAD (bundled in the `silero-vad` wheel, no download) |
| Audio preprocessing | FFmpeg → 16 kHz mono PCM WAV processing copy; original never modified |
| Central server | FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL 16 · PyJWT · Argon2 · nginx |
| Frontend | React 18 · Vite · TypeScript · bundled IBM Plex Sans Arabic (no CDN) |

The central server **never** runs AI inference. If a workstation cannot run a model, the
job fails with an explicit Arabic error — there is no cloud / Whisper / central fallback.

## Repository layout

```
MILITARY_STT_AI/
├── docker-compose.yml          # central stack: postgres, backend, frontend, nginx
├── .env.example                # central configuration
├── central/
│   ├── backend/                # FastAPI app, Alembic migrations, tests
│   ├── frontend/               # React Arabic RTL app (built into an nginx image)
│   ├── nginx/                  # reverse proxy config + certs
│   └── postgres/               # init script (creates the isolated test DB)
├── desktop-agent/              # Local AI Agent (one per investigator desktop)
│   ├── app/                    # api/ ai/ audio/ jobs/ security/ sync/
│   ├── scripts/                # provision_models.py, healthcheck.py, real-model tests
│   ├── windows/                # install_agent.ps1 (service / scheduled task)
│   ├── linux/                  # systemd unit + installer
│   ├── docker-compose.yml      # containerised agent (CPU) + docker-compose.gpu.yml
│   └── tests/
├── docs/                       # architecture, installation, security, testing …
└── scripts/                    # helper scripts (TLS cert, E2E)
```

## Quick start (development, single machine)

```bash
cp .env.example .env                        # edit secrets
sh scripts/generate_self_signed_cert.sh     # TLS cert for nginx :8443
docker compose up -d --build                # central: http://localhost:8080  https://localhost:8443
# first login: admin / CENTRAL_BOOTSTRAP_ADMIN_PASSWORD  (password change is forced)

cd desktop-agent
python scripts/provision_models.py --model-dir ./models            # needs HF_TOKEN for the gated Cohere model
curl -s http://localhost:8080/api/local-processing/public-key | python -c "import sys,json;print(json.load(sys.stdin)['public_key_pem'])" > data/central_public_key.pem
docker compose up -d --build                # agent on http://127.0.0.1:17117 (CPU)
```

Then open `http://localhost:8080`, create an investigator, create a session, open the
**التسجيل** tab, record or upload audio and press **معالجة التسجيل**.

## Documentation

| Document | Content |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Distributed architecture, data flow, responsibilities |
| [docs/central-server.md](docs/central-server.md) | Services, configuration, PostgreSQL schema, roles/permissions, API |
| [docs/desktop-agent.md](docs/desktop-agent.md) | Local agent architecture, API, job states, synchronization |
| [docs/audio-pipeline.md](docs/audio-pipeline.md) | Validation, FFmpeg, VAD, segmentation and reconciliation rules |
| [docs/cohere-stt.md](docs/cohere-stt.md) | The Arabic STT model, loading, configuration |
| [docs/nvidia-diarization.md](docs/nvidia-diarization.md) | Sortformer diarization, speaker change vs diarization, overlap, limits |
| [docs/windows-installation.md](docs/windows-installation.md) | Windows workstation installation (service) |
| [docs/linux-installation.md](docs/linux-installation.md) | Linux workstation installation (systemd / Docker) |
| [docs/offline-provisioning.md](docs/offline-provisioning.md) | Model provisioning, integrity manifests, air-gapped operation |
| [docs/security.md](docs/security.md) | Auth, RBAC, processing tokens, browser ↔ agent security, TLS |
| [docs/testing.md](docs/testing.md) | Test suites, how to run them, real-model and E2E acceptance |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common problems and fixes |

## Status

See [docs/testing.md](docs/testing.md) for the exact verification status of every layer,
including what has been verified end-to-end on this machine and what still requires a
GPU workstation / Hugging Face access for the gated Cohere model.
