#!/bin/sh
# Native Linux install of the Local AI Agent (systemd). Run as root.
#
#   sudo ./install_agent.sh https://central.unit.local:8443 [cpu|gpu] [--quiet]
#
# Installs the AI onto THIS desktop. Audio is processed here and never leaves the machine;
# only the finished text is sent to the server.
#
# Every step says what it is about to do, why it matters, how to tell it worked, and what to
# do if it did not. Pass --quiet as the third argument to skip the explanations.
set -eu

CENTRAL_URL="${1:-https://central.unit.local:8443}"
COMPUTE="${2:-cpu}"
QUIET="${3:-}"
ROOT=/opt/investigation-ai
SRC="$(cd "$(dirname "$0")/.." && pwd)"

if [ -t 1 ]; then
  GRN=$(printf '\033[32m'); YEL=$(printf '\033[33m'); RED=$(printf '\033[31m')
  CYN=$(printf '\033[36m'); DIM=$(printf '\033[2m'); RST=$(printf '\033[0m')
else GRN=; YEL=; RED=; CYN=; DIM=; RST=; fi

step() { printf '\n%s== %s ==%s\n' "$CYN" "$*" "$RST"; }
ok()   { printf '  %s[ ok ]%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '  %s[warn]%s %s\n' "$YEL" "$RST" "$*"; }
die()  { printf '\n  %s[FAIL]%s %s\n\n' "$RED" "$RST" "$*" >&2; exit 1; }

# explain WHAT WHY GOOD FAIL - printed BEFORE the work, while it is still possible to stop.
explain() {
  [ "$QUIET" = "--quiet" ] && return 0
  printf '\n  %s+- WHAT %s %s\n' "$DIM" "$RST" "$1"
  printf '  %s|  WHY  %s %s\n'   "$DIM" "$RST" "$2"
  printf '  %s|  GOOD %s %s\n'   "$DIM" "$RST" "$3"
  printf '  %s+- FAIL %s %s\n\n' "$DIM" "$RST" "$4"
}

printf '\n%s== Military STT AI - Local Agent installer for Linux (%s) ==%s\n' "$CYN" "$COMPUTE" "$RST"
printf '   Reporting to: %s\n' "$CENTRAL_URL"

# ---------------------------------------------------------------------- 1/6
step "1/6  Checking this desktop"
explain \
  "Check what the installer needs: root rights, Python 3, FFmpeg and disk space." \
  "Every later step assumes these. Finding out now takes seconds; finding out halfway through a multi-gigabyte install wastes an hour." \
  "Four [ ok ] lines below." \
  "Each failure names exactly what to install. Install it and run this script again - re-running is safe."

[ "$(id -u)" = "0" ] || die "This must run as root. Use: sudo $0 $CENTRAL_URL $COMPUTE"
ok "running as root"

command -v python3 >/dev/null || die "Python 3 not found. Install it: apt install python3 python3-venv"
ok "Python found: $(python3 --version 2>&1)"

if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  ok "FFmpeg found"
else
  die "FFmpeg not found. It reads the audio files. Install it: apt install ffmpeg"
fi

free_gb=$(df -BG --output=avail /opt 2>/dev/null | tail -1 | tr -dc '0-9') || free_gb=0
if [ "${free_gb:-0}" -lt 15 ]; then
  warn "only ${free_gb} GB free on /opt - the models need about 10 GB plus room to unpack"
else
  ok "${free_gb} GB free for the models"
fi

# ---------------------------------------------------------------------- 2/6
step "2/6  Creating the service account and folders"
explain \
  "Create an unprivileged 'mstt' user and the folders under $ROOT." \
  "The agent runs as its own user with no login shell, so a fault in it cannot reach the rest of the machine." \
  "'service account ready' and 'folders ready'." \
  "If useradd fails the name may already be taken by something else - check with: id mstt"

id mstt >/dev/null 2>&1 || useradd --system --home "$ROOT" --shell /usr/sbin/nologin mstt
ok "service account ready (mstt, no login shell)"
mkdir -p "$ROOT/app" "$ROOT/agent" "$ROOT/models"
ok "folders ready under $ROOT"

# ---------------------------------------------------------------------- 3/6
step "3/6  Copying the application"
explain \
  "Copy the agent program to $ROOT/app." \
  "It runs from its own copy, so the folder you unpacked can be deleted afterwards without breaking anything." \
  "'application copied'." \
  "If rsync is missing: apt install rsync. If files are reported missing, unpack the delivered package again."

command -v rsync >/dev/null || die "rsync not found. Install it: apt install rsync"
rsync -a --delete --exclude .venv-test --exclude models --exclude data \
      --exclude __pycache__ --exclude tests "$SRC/" "$ROOT/app/"
ok "application copied"

# ---------------------------------------------------------------------- 4/6
step "4/6  Installing the AI runtime ($COMPUTE)"
explain \
  "Create a private Python environment and install the AI libraries into it." \
  "THIS IS THE LONGEST STEP - typically 10-30 minutes, longer for GPU. It downloads several gigabytes. Long silences are normal and do NOT mean it has frozen." \
  "'runtime installed'. Output that pauses for minutes is normal." \
  "Nearly always the network or a proxy. On a desktop with no internet, ask for the offline package rather than retrying."

[ -x "$ROOT/venv/bin/python" ] || python3 -m venv "$ROOT/venv"
"$ROOT/venv/bin/pip" install --upgrade pip
"$ROOT/venv/bin/pip" install -r "$ROOT/app/requirements-$COMPUTE.txt"
"$ROOT/venv/bin/pip" install -r "$ROOT/app/requirements.txt"
ok "runtime installed"

# ---------------------------------------------------------------------- 5/6
step "5/6  Writing the configuration"
explain \
  "Record which server this desktop reports to, and how the agent listens." \
  "The agent listens ONLY on this machine (127.0.0.1:17117). Nothing on the network can reach it - the browser on this same desktop talks to it locally." \
  "'configuration written', or 'existing configuration kept' when re-running." \
  "If the server address is wrong, edit $ROOT/app/.env then: systemctl restart military-stt-agent"

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
  ok "configuration written"
else
  ok "existing configuration kept ($ROOT/app/.env)"
fi
chown -R mstt:mstt "$ROOT"

# ---------------------------------------------------------------------- 6/6
step "6/6  Starting it automatically at every boot"
explain \
  "Register the agent with systemd so it starts by itself after every restart." \
  "The investigator must never have to start anything by hand." \
  "'service enabled and started', then 'agent is running'." \
  "If it is not running, read the reason with: journalctl -u military-stt-agent -n 50"

install -m 0644 "$SRC/linux/military-stt-agent.service" /etc/systemd/system/military-stt-agent.service
systemctl daemon-reload
systemctl enable --now military-stt-agent
ok "service enabled and started"
sleep 2
if systemctl is-active --quiet military-stt-agent; then
  ok "agent is running"
else
  warn "the service is not active yet - check: journalctl -u military-stt-agent -n 50"
fi

# ---------------------------------------------------------------------------
printf '\n%s== Installed ==%s\n\n' "$GRN" "$RST"
cat <<EOF
  The agent is on this desktop and will start automatically after every reboot.
  It is NOT finished yet - it still needs the models and the server's key.

Do these four things, in order:

  1. INSTALL THE SERVER'S KEY
     Copy central_public_key.pem (handed to you by whoever set up the server) to:
       $ROOT/central_public_key.pem
     Without it the agent refuses every job. The key only VERIFIES signatures and
     cannot create them, so carrying it on a USB stick is safe.

  2. INSTALL THE AI MODELS
       $ROOT/venv/bin/python $ROOT/app/scripts/provision_models.py
     Several gigabytes, and it can take a long time. The Arabic speech model is
     access-controlled, so you need an HF_TOKEN from your administrator.

  3. CHECK IT WORKS
       $ROOT/venv/bin/python $ROOT/app/scripts/healthcheck.py --load
     This actually loads the models, so allow a minute or two. It tells you
     plainly whether each one is ready.

  4. SEE IT RUNNING
     Open http://127.0.0.1:17117/health in a browser on THIS desktop.
     That address works only here - the agent is not reachable from the network.

  Then sign in to $CENTRAL_URL from this desktop's browser, open a session and
  press the record button. The recording tab shows the agent's status.

  Useful later:
    systemctl status military-stt-agent      is it running
    journalctl -u military-stt-agent -f      watch what it is doing
    docs/troubleshooting.md                  symptoms in Arabic, as they appear on screen
EOF
