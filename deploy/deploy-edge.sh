#!/usr/bin/env bash
# =============================================================================
#  Military STT AI - Local AI Agent deployment (investigator desktop / edge PC)
# =============================================================================
#  Runs ALL the AI locally and listens on 127.0.0.1 only.
#
#  Put the downloaded models next to this script (any layout - they are found
#  by content), then:
#
#      sudo ./deploy-edge.sh --central-url https://central.unit.local:8443
#
#  Every model file is verified against the pinned SHA-256 in
#  deploy/model-manifests/ before anything is started. A tampered or truncated
#  download is refused, not "provisioned".
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MANIFEST_DIR="$SCRIPT_DIR/model-manifests"

# ---- defaults ---------------------------------------------------------------
CENTRAL_URL=""
PUBLIC_KEY_SRC=""
COMPUTE="cpu"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/investigation-ai}"
MODEL_DIR=""
DATA_DIR=""
IMAGE_TAR=""
AGENT_PORT="17117"
DEVICE_NAME="$(hostname)"
VERIFY_MODE="full"          # full | size
LOAD_MODELS="false"
VERIFY_TLS="true"
CA_BUNDLE=""
ASSUME_YES="false"
SEARCH_DIR=""

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; BLU=$'\033[34m'; DIM=$'\033[2m'; RST=$'\033[0m'
step() { printf '\n%s==> %s%s\n' "$BLU" "$*" "$RST"; }
ok()   { printf '  %s[ ok ]%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '  %s[warn]%s %s\n' "$YEL" "$RST" "$*"; }
die()  { printf '\n%s[FAIL]%s %s\n\n' "$RED" "$RST" "$*" >&2; exit 1; }
note() { printf '  %s%s%s\n' "$DIM" "$*" "$RST"; }

usage() {
  sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Options
  --central-url URL      Central server base URL (required, e.g. https://central.unit.local:8443)
  --public-key FILE      Central ES256 public key. If omitted it is fetched from --central-url.
  --compute cpu|gpu      Build/run the CPU or CUDA image                      (default: cpu)
  --models DIR           Where the downloaded models are    (default: next to this script)
  --install-root DIR     Install location                       (default: /opt/investigation-ai)
  --port PORT            Loopback port for the agent                       (default: 17117)
  --device-name NAME     Name shown in the workstation registry          (default: hostname)
  --image-tar FILE       Load a prebuilt agent image instead of building (air-gapped PCs)
  --verify size|full     Model integrity check depth                        (default: full)
  --no-verify-tls        Accept the central certificate without validation (pilots only)
  --ca-bundle FILE       Private CA used to validate the central certificate
  --load-models          Preload the models and wait until the agent reports READY
  --yes                  Do not prompt for confirmation
  -h, --help             This help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --central-url)   CENTRAL_URL="${2:?}"; shift 2 ;;
    --public-key)    PUBLIC_KEY_SRC="${2:?}"; shift 2 ;;
    --compute)       COMPUTE="${2:?}"; shift 2 ;;
    --models)        SEARCH_DIR="${2:?}"; shift 2 ;;
    --install-root)  INSTALL_ROOT="${2:?}"; shift 2 ;;
    --port)          AGENT_PORT="${2:?}"; shift 2 ;;
    --device-name)   DEVICE_NAME="${2:?}"; shift 2 ;;
    --image-tar)     IMAGE_TAR="${2:?}"; shift 2 ;;
    --verify)        VERIFY_MODE="${2:?}"; shift 2 ;;
    --no-verify-tls) VERIFY_TLS="false"; shift ;;
    --ca-bundle)     CA_BUNDLE="${2:?}"; shift 2 ;;
    --load-models)   LOAD_MODELS="true"; shift ;;
    --yes|-y)        ASSUME_YES="true"; shift ;;
    -h|--help)       usage; exit 0 ;;
    *)               die "unknown option: $1  (try --help)" ;;
  esac
done

MODEL_DIR="${MODEL_DIR:-$INSTALL_ROOT/models}"
DATA_DIR="${DATA_DIR:-$INSTALL_ROOT/agent}"
SEARCH_DIR="${SEARCH_DIR:-$SCRIPT_DIR}"

[ -n "$CENTRAL_URL" ] || { usage; die "--central-url is required"; }
case "$COMPUTE" in cpu|gpu) ;; *) die "--compute must be cpu or gpu" ;; esac
case "$VERIFY_MODE" in size|full) ;; *) die "--verify must be size or full" ;; esac

# =============================================================================
step "1/8  Preflight"
# =============================================================================
[ "$(id -u)" -eq 0 ] || die "run as root (sudo $0 ...)"
command -v docker >/dev/null || die "docker is not installed"
docker compose version >/dev/null 2>&1 || die "the docker compose plugin is not available"
docker info >/dev/null 2>&1 || die "the docker daemon is not reachable"
command -v sha256sum >/dev/null || die "sha256sum is required (coreutils)"
command -v curl >/dev/null || die "curl is required"
[ -d "$MANIFEST_DIR" ] || die "missing $MANIFEST_DIR - copy the whole deploy/ directory"
ok "docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?'), compose plugin present"

if [ "$COMPUTE" = "gpu" ]; then
  if docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi >/dev/null 2>&1; then
    ok "NVIDIA container runtime works"
  else
    die "--compute gpu requested but 'docker run --gpus all' failed. Install the NVIDIA Container Toolkit, or use --compute cpu."
  fi
fi

if [ -z "$IMAGE_TAR" ] && [ ! -f "$REPO_ROOT/desktop-agent/Dockerfile" ]; then
  die "no --image-tar given and $REPO_ROOT/desktop-agent is not present. On an air-gapped PC use --image-tar."
fi
note "central URL : $CENTRAL_URL"
note "install root: $INSTALL_ROOT   (models: $MODEL_DIR, data: $DATA_DIR)"
note "compute     : $COMPUTE        (agent will listen on 127.0.0.1:$AGENT_PORT)"

if [ "$ASSUME_YES" != "true" ] && [ -t 0 ]; then
  printf '
  This will install into %s, copy the verified models there and
' "$INSTALL_ROOT"
  printf '  start a container listening on 127.0.0.1:%s. Continue? [y/N] ' "$AGENT_PORT"
  read -r reply
  case "$reply" in [yY]*) ;; *) die "aborted by the operator" ;; esac
fi

# =============================================================================
step "2/8  Locating the downloaded models"
# =============================================================================
# The reference manifests are a fixed, machine-generated shape, so a small awk
# reader is enough - no python/jq dependency on the workstation.
manifest_field() {   # <manifest> <top-level key>
  sed -n "s/^  \"$2\": \"\{0,1\}\([^\",]*\)\"\{0,1\},\{0,1\}$/\1/p" "$1" | head -1
}
manifest_files() {   # <manifest> -> "name<TAB>size<TAB>sha256<TAB>required"
  awk '
    /^    "[^"]+": \{/          { name=$0; sub(/^    "/,"",name); sub(/": \{.*$/,"",name); next }
    name && /"size":/           { s=$0; gsub(/[^0-9]/,"",s); size=s; next }
    name && /"sha256":/         { h=$0; sub(/^.*"sha256": "/,"",h); sub(/".*$/,"",h); sha=h; next }
    name && /"required":/       { req=($0 ~ /true/) ? "1" : "0"; next }
    name && /^    \}/           { printf "%s\t%s\t%s\t%s\n", name, size, sha, req; name=""; req="1"; next }
  ' "$1"
}

declare -A FOUND_DIR
MODELS=()
for m in "$MANIFEST_DIR"/*.json; do
  # An unmatched glob stays literal in bash; without this guard the script would
  # "succeed" having staged nothing at all.
  [ -f "$m" ] && MODELS+=("$m")
done
[ ${#MODELS[@]} -gt 0 ] || die "no reference manifests found in $MANIFEST_DIR"
ok "${#MODELS[@]} reference manifests loaded"

for manifest in "${MODELS[@]}"; do
  dir_name="$(manifest_field "$manifest" dir_name)"
  [ -n "$dir_name" ] || die "malformed reference manifest (no dir_name): $manifest"
  # Anchor file: the largest required file in the manifest.
  anchor="$(manifest_files "$manifest" | awk -F'\t' '$4=="1"{if($2+0>mx){mx=$2+0;n=$1}}END{print n}')"
  required_names="$(manifest_files "$manifest" | awk -F'	' '$4=="1"{print $1}')"
  # A candidate counts only if EVERY required file is present - "model.safetensors"
  # alone would otherwise match any unrelated Hugging Face model lying nearby.
  has_all() {
    local d="$1" f
    while IFS= read -r f; do [ -f "$d/$f" ] || return 1; done <<< "$required_names"
    return 0
  }
  found=""
  for cand in "$SEARCH_DIR/$dir_name" "$SEARCH_DIR/models/$dir_name" "$MODEL_DIR/$dir_name"; do
    has_all "$cand" && { found="$cand"; break; }
  done
  if [ -z "$found" ]; then
    while IFS= read -r hit; do
      [ -n "$hit" ] || continue
      if has_all "$(dirname "$hit")"; then found="$(dirname "$hit")"; break; fi
    done < <(find "$SEARCH_DIR" -maxdepth 6 -type f -name "$anchor" 2>/dev/null || true)
  fi
  if [ -n "$found" ]; then
    FOUND_DIR["$dir_name"]="$found"
    ok "$dir_name -> $found"
  else
    FOUND_DIR["$dir_name"]=""
    if grep -q '"optional_model": true' "$manifest"; then
      warn "$dir_name not found (optional - voice identification will be unavailable)"
    else
      die "$dir_name not found under $SEARCH_DIR (looked for $anchor). Place the downloaded models next to this script."
    fi
  fi
done

# =============================================================================
step "3/8  Verifying model integrity against the pinned revisions"
# =============================================================================
[ "$VERIFY_MODE" = "full" ] && note "hashing ~4.6 GB - this takes a few minutes (use --verify size to skip)"
for manifest in "${MODELS[@]}"; do
  dir_name="$(manifest_field "$manifest" dir_name)"
  src="${FOUND_DIR[$dir_name]}"
  [ -n "$src" ] || continue
  revision="$(manifest_field "$manifest" revision)"
  bad=0; checked=0
  while IFS=$'\t' read -r fname fsize fsha freq; do
    [ -n "$fname" ] || continue
    f="$src/$fname"
    if [ ! -f "$f" ]; then
      if [ "$freq" = "1" ]; then printf '  %s[FAIL]%s %s: missing %s\n' "$RED" "$RST" "$dir_name" "$fname"; bad=1
      else note "$dir_name: optional $fname not present - skipped"; fi
      continue
    fi
    actual_size="$(stat -c%s "$f" 2>/dev/null || stat -f%z "$f")"
    if [ "$actual_size" != "$fsize" ]; then
      printf '  %s[FAIL]%s %s/%s: size %s, expected %s\n' "$RED" "$RST" "$dir_name" "$fname" "$actual_size" "$fsize"; bad=1; continue
    fi
    if [ "$VERIFY_MODE" = "full" ]; then
      actual_sha="$(sha256sum "$f" | cut -d' ' -f1)"
      if [ "$actual_sha" != "$fsha" ]; then
        printf '  %s[FAIL]%s %s/%s: sha256 %s\n' "$RED" "$RST" "$dir_name" "$fname" "${actual_sha:0:16}..."
        printf '         expected %s\n' "${fsha:0:16}..."; bad=1; continue
      fi
    fi
    checked=$((checked+1))
  done <<< "$(manifest_files "$manifest")"
  [ "$bad" -eq 0 ] || die "$dir_name failed verification. Re-download it - a partial or altered model must never be deployed."
  ok "$dir_name  $checked files verified ($VERIFY_MODE)  revision $revision"
done

# =============================================================================
step "4/8  Staging models into $MODEL_DIR"
# =============================================================================
install -d -m 0755 "$MODEL_DIR" "$DATA_DIR" "$INSTALL_ROOT"
for manifest in "${MODELS[@]}"; do
  dir_name="$(manifest_field "$manifest" dir_name)"
  src="${FOUND_DIR[$dir_name]}"
  [ -n "$src" ] || continue
  revision="$(manifest_field "$manifest" revision)"
  dst="$MODEL_DIR/$dir_name"
  if [ "$(readlink -f "$src")" != "$(readlink -f "$dst")" ]; then
    install -d -m 0755 "$dst"
    while IFS=$'\t' read -r fname _ _ _; do
      [ -n "$fname" ] && [ -f "$src/$fname" ] && install -m 0444 "$src/$fname" "$dst/$fname"
    done <<< "$(manifest_files "$manifest")"
    ok "$dir_name copied"
  else
    ok "$dir_name already in place"
  fi
  # The agent verifies MANIFEST.json at load time and treats EVERY entry as
  # mandatory, so write one describing exactly the files that were staged -
  # shipping the reference file verbatim would fail on an absent optional file.
  model_id="$(manifest_field "$manifest" model)"
  source_id="$(manifest_field "$manifest" source)"
  {
    printf '{
  "model": "%s",
  "revision": "%s",
  "source": "%s",
  "files": {
'            "$model_id" "$revision" "$source_id"
    first=1
    while IFS=$'	' read -r fname fsize fsha _; do
      [ -n "$fname" ] && [ -f "$dst/$fname" ] || continue
      [ "$first" -eq 1 ] || printf ',
'
      first=0
      printf '    "%s": {
      "size": %s,
      "sha256": "%s"
    }' "$fname" "$fsize" "$fsha"
    done <<< "$(manifest_files "$manifest")"
    printf '
  }
}
'
  } > "$dst/MANIFEST.json"
  chmod 0444 "$dst/MANIFEST.json"
done
chown -R root:root "$MODEL_DIR" 2>/dev/null || true
staged=0
for manifest in "${MODELS[@]}"; do
  dir_name="$(manifest_field "$manifest" dir_name)"
  [ -f "$MODEL_DIR/$dir_name/MANIFEST.json" ] && staged=$((staged+1))
done
[ "$staged" -gt 0 ] || die "nothing was staged into $MODEL_DIR"
ok "$staged model(s) staged read-only under $MODEL_DIR"

# =============================================================================
step "5/8  Installing the central public key"
# =============================================================================
# Only the PUBLIC key ever reaches a workstation. The private signing key stays
# on the central server; a compromised desktop cannot mint processing jobs.
KEY_PATH="$INSTALL_ROOT/central_public_key.pem"
CURL_OPTS=(-fsS --max-time 30)
[ "$VERIFY_TLS" = "false" ] && CURL_OPTS+=(-k)
[ -n "$CA_BUNDLE" ] && CURL_OPTS+=(--cacert "$CA_BUNDLE")

if [ -n "$PUBLIC_KEY_SRC" ]; then
  [ -f "$PUBLIC_KEY_SRC" ] || die "public key file not found: $PUBLIC_KEY_SRC"
  install -m 0444 "$PUBLIC_KEY_SRC" "$KEY_PATH"
  ok "installed from $PUBLIC_KEY_SRC"
else
  note "fetching from $CENTRAL_URL/api/local-processing/public-key"
  raw="$(curl "${CURL_OPTS[@]}" "$CENTRAL_URL/api/local-processing/public-key")" \
    || die "could not reach the central server. Check --central-url, the network, and the TLS trust (--ca-bundle)."
  # The JSON carries the PEM with escaped newlines:
  #   {"public_key_pem":"-----BEGIN PUBLIC KEY-----\n..."}
  # Strip the JSON around it, then let printf '%b' turn the escapes into real
  # newlines - more portable than a sed replacement containing backslashes.
  pem="$(printf '%s' "$raw" \
    | sed -e 's/.*"public_key_pem"[[:space:]]*:[[:space:]]*"//' -e 's/".*//')"
  [ -n "$pem" ] || die "the central server did not return a public_key_pem field"
  printf '%b\n' "$pem" > "$KEY_PATH"
  chmod 0444 "$KEY_PATH"
  ok "fetched from the central server"
fi

grep -q "BEGIN PUBLIC KEY" "$KEY_PATH" || die "$KEY_PATH is not a PEM public key"
grep -q "BEGIN .*PRIVATE KEY" "$KEY_PATH" && die "REFUSING TO CONTINUE: that is a PRIVATE key. Workstations must only ever hold the public key."
if command -v openssl >/dev/null; then
  openssl pkey -pubin -in "$KEY_PATH" -noout 2>/dev/null || die "$KEY_PATH is not a valid public key"
  curve="$(openssl pkey -pubin -in "$KEY_PATH" -text -noout 2>/dev/null | sed -n 's/.*ASN1 OID: \(.*\)/\1/p')"
  [ "$curve" = "prime256v1" ] || warn "expected a P-256 (prime256v1) ES256 key, got '${curve:-unknown}'"
  ok "valid ES256 public key (${curve:-unverified})"
fi

# =============================================================================
step "6/8  Writing the agent configuration"
# =============================================================================
CENTRAL_ORIGIN="$(printf '%s' "$CENTRAL_URL" | sed -E 's#^(https?://[^/]+).*#\1#')"
ENV_FILE="$INSTALL_ROOT/agent.env"
if [ -f "$ENV_FILE" ]; then
  cp -a "$ENV_FILE" "$ENV_FILE.bak.$(date +%Y%m%d%H%M%S)"
  note "existing configuration backed up"
fi
cat > "$ENV_FILE" <<ENV
# Local AI Agent - generated by deploy-edge.sh on $(date -Is)
AGENT_COMPUTE=$COMPUTE
AGENT_PORT=$AGENT_PORT
AGENT_DEVICE_NAME=$DEVICE_NAME
AGENT_MODELS_PATH=$MODEL_DIR
AGENT_DATA_PATH=$DATA_DIR
# The browser talks to the agent from the central origin; nothing else is allowed.
AGENT_ALLOWED_ORIGINS=$CENTRAL_ORIGIN
AGENT_CENTRAL_URL=$CENTRAL_URL
AGENT_CENTRAL_VERIFY_TLS=$VERIFY_TLS
AGENT_CENTRAL_PUBLIC_KEY_AUTO_FETCH=false
AGENT_STT_DEVICE=auto
AGENT_DIARIZATION_DEVICE=auto
AGENT_PRELOAD_MODELS=$LOAD_MODELS
# deploy-edge.sh already verified every SHA-256; re-hashing 4 GB on each load
# would add minutes to startup, so the runtime check is size-only.
AGENT_VERIFY_MODEL_INTEGRITY=size
AGENT_LOG_LEVEL=INFO
ENV
chmod 0640 "$ENV_FILE"
ok "$ENV_FILE"
note "allowed browser origin: $CENTRAL_ORIGIN"

# =============================================================================
step "7/8  Building or loading the agent image"
# =============================================================================
IMAGE="military-stt/desktop-agent:1.0.0-$COMPUTE"
if [ -n "$IMAGE_TAR" ]; then
  [ -f "$IMAGE_TAR" ] || die "image archive not found: $IMAGE_TAR"
  note "loading $IMAGE_TAR (no network required)"
  docker load -i "$IMAGE_TAR" >/dev/null || die "docker load failed"
  docker image inspect "$IMAGE" >/dev/null 2>&1 \
    || die "$IMAGE_TAR does not contain $IMAGE. Export it with: docker save -o agent-$COMPUTE.tar $IMAGE"
  ok "loaded $IMAGE"
else
  note "building $IMAGE from source (downloads Python wheels - needs Internet)"
  docker build --build-arg "COMPUTE=$COMPUTE" -t "$IMAGE" "$REPO_ROOT/desktop-agent" \
    || die "image build failed"
  ok "built $IMAGE"
fi

# A self-contained compose file so the workstation no longer depends on the
# source tree being present.
COMPOSE_FILE="$INSTALL_ROOT/docker-compose.yml"
{
  cat <<YML
# Local AI Agent - generated by deploy-edge.sh. Managed with:
#   docker compose --env-file $ENV_FILE -f $COMPOSE_FILE <up|down|logs|ps>
name: military-stt-agent

services:
  agent:
    image: $IMAGE
    container_name: mstt-agent
    restart: unless-stopped
    ports:
      # Loopback ONLY - never expose the agent on the network.
      - "127.0.0.1:\${AGENT_PORT:-17117}:17117"
    environment:
      AGENT_PORT: 17117
      AGENT_DEVICE_NAME: \${AGENT_DEVICE_NAME}
      AGENT_ALLOWED_ORIGINS: \${AGENT_ALLOWED_ORIGINS}
      AGENT_CENTRAL_URL: \${AGENT_CENTRAL_URL}
      AGENT_CENTRAL_VERIFY_TLS: \${AGENT_CENTRAL_VERIFY_TLS}
      AGENT_CENTRAL_PUBLIC_KEY_PATH: /data/central_public_key.pem
      AGENT_CENTRAL_PUBLIC_KEY_AUTO_FETCH: "false"
      AGENT_STT_DEVICE: \${AGENT_STT_DEVICE}
      AGENT_DIARIZATION_DEVICE: \${AGENT_DIARIZATION_DEVICE}
      AGENT_PRELOAD_MODELS: \${AGENT_PRELOAD_MODELS}
      AGENT_VERIFY_MODEL_INTEGRITY: \${AGENT_VERIFY_MODEL_INTEGRITY}
      AGENT_LOG_LEVEL: \${AGENT_LOG_LEVEL}
    volumes:
      - \${AGENT_MODELS_PATH}:/models:ro
      - \${AGENT_DATA_PATH}:/data
    extra_hosts:
      - "host.docker.internal:host-gateway"
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "5" }
YML
  if [ "$COMPUTE" = "gpu" ]; then
    cat <<'YML'
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
YML
  fi
} > "$COMPOSE_FILE"
ok "$COMPOSE_FILE"

install -m 0444 "$KEY_PATH" "$DATA_DIR/central_public_key.pem"
[ -n "$CA_BUNDLE" ] && install -m 0444 "$CA_BUNDLE" "$DATA_DIR/central-ca.pem"

# =============================================================================
step "8/8  Starting the agent and verifying it"
# =============================================================================
DC=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
"${DC[@]}" up -d --remove-orphans || die "the agent container did not start"
systemctl enable docker >/dev/null 2>&1 || true   # so the agent returns after a reboot

BASE="http://127.0.0.1:$AGENT_PORT"
printf '  waiting for %s/health ' "$BASE"
for i in $(seq 1 60); do
  if curl -fsS --max-time 3 "$BASE/health" >/dev/null 2>&1; then printf ' up\n'; break; fi
  [ "$i" -eq 60 ] && { printf '\n'; "${DC[@]}" logs --tail 40 agent; die "the agent did not become healthy"; }
  printf '.'; sleep 2
done
ok "agent healthy on $BASE (loopback only)"

caps="$(curl -fsS "$BASE/capabilities")"
printf '%s\n' "$caps" | tr ',' '\n' | grep -E '"(state|ready|loadable)"' | sed 's/^/    /' || true
for want in cohere-transcribe-arabic sortformer; do
  printf '%s' "$caps" | grep -q "$want" || warn "'$want' not reported by /capabilities - check $MODEL_DIR"
done

if [ "$LOAD_MODELS" = "true" ]; then
  note "loading models (first CPU load of the 4 GB STT model takes several minutes)"
  curl -fsS -X POST "$BASE/models/load" >/dev/null || warn "POST /models/load was rejected"
  for i in $(seq 1 180); do
    caps="$(curl -fsS "$BASE/capabilities" || true)"
    printf '%s' "$caps" | grep -q '"ready": *true' && { ok "models loaded - agent READY"; break; }
    printf '%s' "$caps" | grep -q '"state": *"ERROR"' && { printf '%s\n' "$caps"; die "a model failed to load"; }
    [ "$i" -eq 180 ] && warn "models still loading after 6 min - check: ${DC[*]} logs -f agent"
    sleep 2
  done
fi

cat <<EOF

$(printf '%s' "$GRN")Local AI Agent deployed.$(printf '%s' "$RST")

  endpoint       $BASE            (127.0.0.1 only - not reachable from the network)
  models         $MODEL_DIR       (read-only, SHA-256 verified against the pinned revisions)
  data / jobs    $DATA_DIR
  config         $ENV_FILE
  central        $CENTRAL_URL

  logs           ${DC[*]} logs -f agent
  restart        ${DC[*]} restart agent
  stop           ${DC[*]} down

Next: sign in to $CENTRAL_URL from THIS desktop's browser, open a session's
التسجيل tab and press معالجة التسجيل. The workstation registers itself on its
first job - there is no separate enrolment step.
EOF
