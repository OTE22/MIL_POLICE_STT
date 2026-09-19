# Linux workstation installation

**Who this is for:** whoever sets up an interviewing computer running Linux. Follow it in
order; you do not need to understand the AI. Allow 20-45 minutes, mostly downloading.

**Setting up the SERVER instead?** That is [production-deployment.md](production-deployment.md).

Two supported options with the same agent API on `http://127.0.0.1:17117`.

## Option A — native (systemd)

```bash
sudo apt install -y python3.11 python3.11-venv ffmpeg libsndfile1
sudo ./desktop-agent/linux/install_agent.sh https://central.unit.local:8443 gpu   # or cpu
sudo cp central_public_key.pem /opt/investigation-ai/central_public_key.pem
sudo -u mstt HF_TOKEN=hf_... /opt/investigation-ai/venv/bin/python /opt/investigation-ai/app/scripts/provision_models.py --model-dir /opt/investigation-ai/models
sudo -u mstt /opt/investigation-ai/venv/bin/python /opt/investigation-ai/app/scripts/healthcheck.py --load
sudo systemctl status military-stt-agent
```

`linux/military-stt-agent.service` runs the agent as the unprivileged `mstt` user with
`Restart=always`, `ProtectSystem=full`, `NoNewPrivileges` and offline HF environment
variables.

## Option B — Docker with the NVIDIA container runtime

```bash
cd desktop-agent
cp .env.example .env    # adjust AGENT_CENTRAL_URL, AGENT_ALLOWED_ORIGINS
mkdir -p models data && cp central_public_key.pem data/
HF_TOKEN=hf_... python3 scripts/provision_models.py --model-dir ./models    # on the host, once
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
curl http://127.0.0.1:17117/capabilities
```

The container publishes its port only on the host loopback interface
(`127.0.0.1:17117:17117`), mounts `./models` read-only and `./data` for the SQLite store /
temporary job files. CPU-only development: `docker compose up -d --build`.

## Central server (Linux host)

```bash
cp .env.example .env && edit secrets
sh scripts/generate_self_signed_cert.sh central.unit.local      # or install an organisation certificate
docker compose up -d --build
```

Ports: 8080 (HTTP) and 8443 (HTTPS) by default; set `CENTRAL_HTTP_PORT/HTTPS_PORT`.
Recordings are stored under `./storage/recordings/`, keys under `./secrets/`, database in the
`postgres-data` volume — back up all three.
