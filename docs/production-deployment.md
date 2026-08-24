# Production deployment

How to put the system into service: **one central server** and **one Local AI Agent per
investigator desktop**. Two scripts do the work:

| Script | Runs on | Deploys |
|---|---|---|
| [`deploy/deploy-central.sh`](../deploy/deploy-central.sh) | the server | nginx + React (Arabic RTL) + FastAPI + PostgreSQL |
| [`deploy/deploy-edge.sh`](../deploy/deploy-edge.sh) | each desktop | the Local AI Agent and the three AI models |

Read [how-it-works.md](how-it-works.md) first if you have not — this document assumes you
know why the AI runs on the desktop and not on the server.

---

## 1. What you are deploying

```
              CENTRAL SERVER  (one per unit)
              stores, authorises, audits.  Runs NO AI.
              ┌──────────────────────────────────────┐
              │ nginx :443  →  frontend + FastAPI     │
              │                     ↓                 │
              │                PostgreSQL 16          │
              │                /storage (audio, scans)│
              │                /secrets (ES256 keys)  │
              └───────────────────┬──────────────────┘
                                  │ HTTPS over the unit LAN
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
   DESKTOP 01                DESKTOP 02                DESKTOP 03
   Local AI Agent on 127.0.0.1:17117 — runs ALL the AI, reachable
   only from that machine's own browser. Never exposed to the LAN.
```

The desktops need **no inbound** network access. They only make outbound HTTPS calls to the
central server. Nothing needs Internet access once the models are installed.

---

## 2. Requirements

### Central server

| | |
|---|---|
| OS | Linux with Docker Engine 24+ and the Compose plugin |
| CPU / RAM | 4 cores, 8 GB (it runs no models) |
| Disk | 40 GB for the system + **your audio retention** — plan ~1 GB per 30 h of WAV |
| Ports | 8443 (HTTPS) and optionally 8080 (HTTP), reachable from the desktops |
| TLS | An organisation-issued certificate for the server's FQDN |

### Investigator desktop

| | |
|---|---|
| OS | Linux with Docker Engine 24+ (Windows: use `desktop-agent/windows/install_agent.ps1`) |
| RAM | **16 GB minimum.** The STT model alone occupies ~4 GB while loaded |
| Disk | 15 GB (4.4 GB of models + a 4.96 GB container image + working space) |
| GPU | Optional but **strongly recommended** — see the speed note in §9 |
| Network | Outbound HTTPS to the central server. No inbound access at all |

> **Do not run the agent and the central server on the same 8 GB machine.** Loading a
> second multi-GB model while one is already resident is what exhausts memory.

---

## 3. Before you start — four decisions

1. **The server's hostname.** Investigators type it in the browser, and it goes into the
   certificate. `central.unit.local` in the examples.
2. **The TLS certificate.** Use an organisation-issued one. `--self-signed` exists for LAN
   pilots and makes every browser show a warning until the certificate is distributed as a
   trusted root.
3. **Whether the desktops have Internet.** If not, use the air-gapped path in §7.
4. **Where the recordings live and how long they are kept.** Audio and ID scans are the
   most sensitive data the system holds. Decide the retention policy before go-live.

---

## 4. Download the models (once)

Do this on any machine with Internet, then carry the files to each desktop. Everything is
pinned to an exact revision; the deploy script refuses anything else.

| Directory | Model | Answers | Size |
|---|---|---|---|
| `cohere-transcribe-arabic-07-2026/` | `CohereLabs/cohere-transcribe-arabic-07-2026` | ماذا قيل | 3.9 GB |
| `diar_streaming_sortformer_4spk-v2.1/` | `nvidia/diar_streaming_sortformer_4spk-v2.1` | من تكلّم ومتى | 450 MB |
| `speakerverification_speakernet/` | `nvidia/speakerverification_speakernet` | كيف يبدو الصوت (optional) | 21 MB |

The Cohere model is **gated**: accept the licence on its Hugging Face page first, then
download with a token. The token is used for the download only and is never stored.

The easiest way is the provisioning script, which downloads all three at the pinned
revisions:

```bash
cd desktop-agent
HF_TOKEN=hf_xxx python scripts/provision_models.py --model-dir ./models
```

**Place the resulting directories next to `deploy-edge.sh`.** The layout does not matter —
the script finds each model by its contents, so `deploy/models/…`, `deploy/…`, or a nested
copy all work:

```
deploy/
├── deploy-edge.sh
├── model-manifests/
└── models/
    ├── cohere-transcribe-arabic-07-2026/
    ├── diar_streaming_sortformer_4spk-v2.1/
    └── speakerverification_speakernet/
```

See [offline-provisioning.md](offline-provisioning.md) for slow links and resumable
downloads of the 4 GB weights file.

---

## 5. Deploy the central server

```bash
cd MILITARY_STT_AI/deploy
sudo ./deploy-central.sh \
     --hostname central.unit.local \
     --cert /etc/ssl/certs/unit.crt \
     --key  /etc/ssl/private/unit.key \
     --force-tls
```

What it does, in order:

1. **Preflight** — root, Docker, Compose, openssl, and that ports 8080/8443 are free.
2. **Secrets** — generates the PostgreSQL password, the JWT secret and the bootstrap admin
   password with `openssl rand`, and writes them once to a **mode-0600 `.env`**. A re-run
   never regenerates them, so an existing deployment keeps working.
3. **TLS** — validates that the certificate is PEM, that the key is PEM, and that **they
   are actually a matching pair** (a mismatch otherwise produces a server that starts and
   then fails every handshake). Warns if the certificate expires within 30 days.
   `--force-tls` turns on the HTTP→HTTPS redirect.
4. **Images** — builds with `INSTALL_DEV=false` so no test tooling reaches production.
5. **Start** — brings up PostgreSQL, applies the Alembic migrations, then starts the
   backend, frontend and nginx.
6. **Verify** — checks the API over HTTP and HTTPS, that the frontend really serves an
   RTL document, and that the ES256 endpoint returns a **public** key. It then exports
   `deploy/central_public_key.pem` for the desktops.
7. **Report** — prints the URL, the admin password **once**, and what to back up.

Write the admin password down when it is printed. It is shown once, and a password change
is forced at first sign-in.

---

## 6. Deploy an investigator desktop

Copy the `deploy/` directory (with the models and the exported `central_public_key.pem`)
to the desktop, then:

```bash
sudo ./deploy-edge.sh \
     --central-url https://central.unit.local:8443 \
     --public-key  ./central_public_key.pem \
     --compute gpu \
     --load-models
```

Omit `--public-key` and the script fetches the key from the server instead. Use
`--compute cpu` where there is no NVIDIA GPU.

What it does:

1. **Preflight** — root, Docker, and for `--compute gpu` it *proves* `docker run --gpus all`
   works before continuing rather than failing later.
2. **Locate the models** — by content, not by folder name. A directory counts only when
   **every** required file is present, so an unrelated `model.safetensors` lying nearby
   cannot be mistaken for the STT model.
3. **Verify integrity** — every file's size and **SHA-256** against the pinned revision in
   `deploy/model-manifests/`. A tampered or truncated model is refused and **nothing is
   staged**. This is the step that makes the deployment evidence-grade.
4. **Stage** — copies the models to `/opt/investigation-ai/models`, read-only (mode 0444),
   and writes a `MANIFEST.json` the agent re-checks at load time.
5. **Install the public key** — and refuse outright if handed a *private* key.
6. **Configure** — writes `/opt/investigation-ai/agent.env`, allowing exactly one browser
   origin: the central server's.
7. **Build or load the image**, and write a self-contained compose file so the desktop no
   longer depends on the source tree.
8. **Start and verify** — waits for `/health`, reports `/capabilities`, and with
   `--load-models` waits until the agent reports READY.

There is **no separate enrolment step** — the workstation registers itself when it reports
its first job.

### Integrity check depth

`--verify full` (the default) hashes every file: ~4.4 GB, a few minutes. `--verify size`
checks sizes only — it catches truncated downloads, but **provably cannot detect a
same-size modification** (tested). Use `full` for the initial install of every machine.

---

## 7. Air-gapped desktops

Building the agent image downloads several GB of Python wheels. Where that is impossible,
export the image on a connected machine:

```bash
# connected machine
docker build --build-arg COMPUTE=gpu -t military-stt/desktop-agent:1.0.0-gpu desktop-agent
docker save -o agent-gpu.tar military-stt/desktop-agent:1.0.0-gpu     # ~5 GB
```

Carry `agent-gpu.tar`, the `deploy/` directory and the models across, then:

```bash
sudo ./deploy-edge.sh --central-url https://central.unit.local:8443 \
     --public-key ./central_public_key.pem --compute gpu --image-tar ./agent-gpu.tar
```

The same works for the server with `--image-tar` after
`docker save -o central.tar military-stt/central-backend:1.0.0 military-stt/central-frontend:1.0.0 postgres:16-alpine nginx:1.27-alpine`.

---

## 8. Verify the deployment for real

The scripts check themselves, but before go-live run one real recording end to end:

```bash
# on the server
curl -sk https://central.unit.local:8443/api/health
# on a desktop
curl -s http://127.0.0.1:17117/capabilities        # expect stt/diarization state READY
curl -s http://<desktop-ip>:17117/health           # MUST fail - the agent is loopback-only
```

Then, in a browser on the desktop: sign in, create a session, record 30 seconds with two
people speaking in turn, press **معالجة التسجيل**, and confirm that the transcript comes
back with the speakers separated. That exercises every layer — token, agent, both models,
sync, storage and audit.

---

## 9. Operating it

**Back up** — these three, together:

| What | Why |
|---|---|
| `secrets/` | The ES256 keypair. Losing it invalidates every processing token. |
| `storage/` | The original audio and ID scans — the evidence itself. |
| `pg_dump` of the database | Sessions, transcripts, users, audit log. |

```bash
docker compose exec -T postgres pg_dump -U stt military_stt | gzip > backup-$(date +%F).sql.gz
```

**Logs** — `docker compose logs -f backend` on the server, and
`docker compose --env-file /opt/investigation-ai/agent.env -f /opt/investigation-ai/docker-compose.yml logs -f agent`
on a desktop. Agent logs rotate at 10 MB × 5.

**Upgrading** — pull the new source, re-run the same deploy script. Secrets and the `.env`
are preserved; migrations apply automatically on backend start.

**Speed** — measured on a CPU-only machine: models load in ~1 min 47 s and transcription
runs at roughly real time (RTFx 1.1), so an hour of audio takes about an hour. A CUDA GPU
changes this by an order of magnitude. Plan for a GPU on any desktop with real volume.

---

## 10. Security checklist before go-live

- [ ] TLS uses an organisation-issued certificate, and `--force-tls` is on.
- [ ] The bootstrap admin password was changed at first sign-in.
- [ ] `.env` is mode 0600 and is **not** in version control.
- [ ] `secrets/processing_token_private.pem` exists **only** on the server. No desktop has
      a private key — `deploy-edge.sh` refuses one, but verify.
- [ ] Each desktop's agent answers on `127.0.0.1` only; from another machine it is
      unreachable.
- [ ] `CENTRAL_CORS_ALLOWED_ORIGINS` is empty in production.
- [ ] No `*_test` database exists on the production cluster (`--keep-test-db` is off by
      default).
- [ ] Real users have the narrowest role that lets them work; `USER` is read-only and
      never sees ID scans or voice templates.
- [ ] A retention policy for `storage/` is agreed and scheduled.
- [ ] Backups have been **restored once** into a scratch environment to prove they work.

---

## 11. When something fails

| Symptom | Cause and fix |
|---|---|
| `bad interpreter` running a script | The file has CRLF endings. `tr -d '\r' < s.sh > s2.sh`. `.gitattributes` pins `*.sh` to LF. |
| Edge script: *"failed verification. Re-download it"* | The model is truncated or altered. Re-download — do not bypass this. |
| Edge script: *"not found under … (looked for …)"* | The models are not next to the script, or a required file is missing. |
| Agent shows **النموذج غير مثبّت** | `AGENT_MODELS_PATH` does not contain the model directory. Check `/opt/investigation-ai/models`. |
| Agent shows **النموذج غير محمّل** | Normal — lazy loading. Press تحميل النماذج or just start processing. |
| Browser cannot reach the agent | The origin is not in `AGENT_ALLOWED_ORIGINS`. It must exactly match the central URL, scheme and port included. |
| HTTPS fails immediately | The certificate and key are not a pair. The deploy script checks this — re-run it. |
| Job fails with an Arabic model error | Read it literally. There is no cloud fallback by design; the model genuinely could not run. |

More in [troubleshooting.md](troubleshooting.md).

---

## 12. Known limits

Carried over from [how-it-works.md](how-it-works.md), because they shape deployment:

* **Four speakers maximum** — Sortformer 4spk. Sessions above that are warned about.
* **CPU is slow** — see §9. Size the desktops accordingly.
* **The voice-matching threshold (0.65) was calibrated on synthesised voices.** Recalibrate
  on real interview recordings before relying on the suggestions operationally. They are
  suggestions a human confirms, so this degrades gracefully — but it should still be done.
* **Overlapping speech is flagged, not separated.**
* **A restart during processing fails that job.** The recording is intact; process it again.
