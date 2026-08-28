#!/usr/bin/env bash
# START HERE. Run this first if you do not know which script to run.
#
#   ./START-HERE.sh
#
# It explains the two machine roles, checks whether THIS machine is ready to be either of
# them, and prints the exact command to run next. It changes nothing.
set -uo pipefail

if [ -t 1 ]; then
  GRN=$'\033[32m'; YEL=$'\033[33m'; RED=$'\033[31m'; CYN=$'\033[36m'
  BLD=$'\033[1m'; DIM=$'\033[2m'; RST=$'\033[0m'
else GRN=; YEL=; RED=; CYN=; BLD=; DIM=; RST=; fi

ok()   { printf '  %s[ ok ]%s %s\n' "$GRN" "$RST" "$*"; }
bad()  { printf '  %s[ no ]%s %s\n' "$RED" "$RST" "$*"; }
warn() { printf '  %s[warn]%s %s\n' "$YEL" "$RST" "$*"; }
head2(){ printf '\n%s%s%s\n' "$CYN$BLD" "$*" "$RST"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cat <<EOF

${CYN}${BLD}=======================================================================
  Military STT AI - where to start
=======================================================================${RST}

This system runs on TWO kinds of machine. You install a different thing on
each, and the ${BLD}server must be done first${RST}.

  ${BLD}1. THE SERVER${RST} - one machine for the whole unit
     Holds the cases, the transcripts and the person registry. Investigators
     reach it with a browser. Nobody records audio on it.

  ${BLD}2. THE INVESTIGATOR DESKTOP${RST} - one install per interviewing computer
     Runs the AI that turns speech into text. ${BLD}The audio never leaves this
     machine${RST} - only the finished text is sent to the server. This is why the
     AI is installed on every desktop instead of once on the server.

EOF

head2 "Is this machine ready?"
printf '%s  Checking what is installed here. Nothing is changed.%s\n\n' "$DIM" "$RST"

HAS_DOCKER=no; HAS_PY=no; HAS_FFMPEG=no; IS_ROOT=no; HAS_GPU=no

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  HAS_DOCKER=yes; ok "Docker is installed and running"
elif command -v docker >/dev/null 2>&1; then
  bad "Docker is installed but NOT running - start it, then run this again"
else
  bad "Docker is not installed"
fi

# `command -v python3` is not enough: Windows ships a Microsoft Store stub named python3 that
# resolves but does not run, and some systems keep a dangling symlink. Ask it for its version
# and require the answer to look like one - a check that passes on a broken tool is worse than
# no check, because it sends someone confidently into a build that cannot work.
py_version="$(python3 --version 2>&1 || true)"
if printf '%s' "$py_version" | grep -qE '^Python 3\.[0-9]+'; then
  HAS_PY=yes; ok "Python found: $py_version"
else
  bad "Python 3 is not usable  (apt install python3 python3-venv)"
  [ -n "$py_version" ] && printf '         %sit answered: %s%s
' "$DIM" "$py_version" "$RST"
fi

if command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1; then
  HAS_FFMPEG=yes; ok "FFmpeg is installed"
else
  bad "FFmpeg is not installed  (apt install ffmpeg)  - needed to read audio"
fi

[ "$(id -u)" = "0" ] && { IS_ROOT=yes; ok "running as root"; } || warn "not root - installers need 'sudo'"

if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  HAS_GPU=yes
  ok "NVIDIA GPU found: $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)"
else
  printf '  %s[info]%s No NVIDIA GPU detected - use "cpu" below. It works everywhere, just slower.\n' "$DIM" "$RST"
fi

free_gb=$(df -BG --output=avail "$SCRIPT_DIR" 2>/dev/null | tail -1 | tr -dc '0-9')
if [ "${free_gb:-0}" -lt 20 ]; then
  warn "only ${free_gb:-?} GB free here - allow about 20 GB for models and images"
else
  ok "${free_gb} GB free"
fi

COMPUTE="cpu"; [ "$HAS_GPU" = "yes" ] && COMPUTE="gpu"

head2 "What to run next"
cat <<EOF

${BLD}If this machine is THE SERVER:${RST}

    sudo ./deploy-central.sh --hostname central.unit.local --self-signed --force-tls

  Replace central.unit.local with the name investigators will type in their
  browser. Use --cert/--key instead of --self-signed if your unit issued a
  real certificate.

  ${DIM}Needs: Docker.  Takes: 10-20 minutes, mostly building.${RST}
  ${DIM}Afterwards it prints the administrator password ONCE - write it down.${RST}

${BLD}If this machine is AN INVESTIGATOR DESKTOP:${RST}

  First download the AI models next to this script (they are not included -
  they are several gigabytes). Then:

    sudo ./deploy-edge.sh --central-url https://central.unit.local:8443 \\
         --public-key ./central_public_key.pem --compute $COMPUTE

  central_public_key.pem is produced by the server install. Copy it here.

  ${DIM}Needs: Docker, the models, the server's key.  Takes: 20-40 minutes.${RST}

  ${DIM}No Docker on the desktop? Use the native installer instead:${RST}
    sudo ../desktop-agent/linux/install_agent.sh https://central.unit.local:8443 $COMPUTE

${BLD}On a WINDOWS desktop${RST}, use PowerShell as administrator:

    .\\START-HERE.ps1

EOF

head2 "The order matters"
cat <<EOF

  1. Install THE SERVER first.                       (deploy-central.sh)
  2. Copy central_public_key.pem off the server.
  3. Complete the administrator profile in the web interface
     - الجهاز and الرقم العسكري are required before anyone can be
       identified as a speaker or have a voice print taken.
  4. Install EACH DESKTOP.                           (deploy-edge.sh)
  5. Record one real interview end to end before going live.

  Every script re-runs safely. If one stops, fix what it names and run it again.

  Full guide:  docs/production-deployment.md
  Problems:    docs/troubleshooting.md   (symptoms in Arabic, as they appear)

EOF

if [ "$HAS_DOCKER" = "no" ]; then
  printf '%s  Docker is required for both roles. Install it first:%s\n' "$YEL" "$RST"
  printf '    curl -fsSL https://get.docker.com | sh\n\n'
fi
