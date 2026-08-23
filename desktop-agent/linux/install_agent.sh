#!/bin/sh
# Native Linux install of the Local AI Agent (systemd). Run as root.
#   ./install_agent.sh https://central.unit.local:8443 [cpu|gpu]
set -eu
CENTRAL_URL="${1:-https://central.unit.local:8443}"
COMPUTE="${2:-cpu}"
ROOT=/opt/investigation-ai
SRC="$(cd "$(dirname "$0")/.." && pwd)"
id mstt >/dev/null 2>&1 || useradd --system --home "$ROOT" --shell /usr/sbin/nologin mstt
mkdir -p "$ROOT/app" "$ROOT/agent" "$ROOT/models"
rsync -a --delete --exclude .venv-test --exclude models --exclude data --exclude __pycache__ --exclude tests "$SRC/" "$ROOT/app/"
[ -x "$ROOT/venv/bin/python" ] || python3 -m venv "$ROOT/venv"
"$ROOT/venv/bin/pip" install --upgrade pip
"$ROOT/venv/bin/pip" install -r "$ROOT/app/requirements-$COMPUTE.txt"
"$ROOT/venv/bin/pip" install -r "$ROOT/app/requirements.txt"
command -v ffmpeg >/dev/null || echo "WARNING: ffmpeg not found - install it (apt install ffmpeg)"
if [ ! -f "$ROOT/app/.env" ]; then
  HOSTPART="$(echo "$CENTRAL_URL" | sed -E 's#^(https?://[^/]+).*#\1#')"
  cat > "$ROOT/app/.env" <<ENV
AGENT_BIND_HOST=127.0.0.1
AGENT_PORT=17117
AGENT_DEVICE_NAME=$(hostname)
AGENT_CENTRAL_URL=$CENTRAL_URL
AGENT_CENTRAL_PUBLIC_KEY_PATH=$ROOT/central_public_key.pem
AGENT_CENTRAL_VERIFY_TLS=true
AGENT_ALLOWED_ORIGINS=$HOSTPART
AGENT_PRELOAD_MODELS=true
ENV
fi
chown -R mstt:mstt "$ROOT"
install -m 0644 "$SRC/linux/military-stt-agent.service" /etc/systemd/system/military-stt-agent.service
systemctl daemon-reload
systemctl enable --now military-stt-agent
echo "Installed. Next: copy the central public key to $ROOT/central_public_key.pem, provision models with $ROOT/venv/bin/python $ROOT/app/scripts/provision_models.py, then run healthcheck.py --load"
