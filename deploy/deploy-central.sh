#!/usr/bin/env bash
# =============================================================================
#  Military STT AI - Central server deployment
# =============================================================================
#  Runs the web application: nginx + React (Arabic RTL) + FastAPI + PostgreSQL.
#  It stores, authorises and audits. It runs NO AI - the models live on the
#  investigator desktops (see deploy-edge.sh).
#
#      sudo ./deploy-central.sh --hostname central.unit.local \
#           --cert /etc/ssl/unit.crt --key /etc/ssl/unit.key
#
#  Secrets are generated with openssl, written once to a 0600 .env, and never
#  regenerated on a re-run - an existing deployment keeps working.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

HOSTNAME_FQDN=""
CERT_SRC=""; KEY_SRC=""
SELF_SIGNED="false"
HTTP_PORT="8080"; HTTPS_PORT="8443"
HTTP_PORT_SET=false; HTTPS_PORT_SET=false
FORCE_TLS="false"
QUIET="false"
IMAGE_TAR=""
ADMIN_USER="admin"
ADMIN_PASSWORD=""
KEEP_TEST_DB="false"
SKIP_BUILD="false"

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; BLU=$'\033[34m'; DIM=$'\033[2m'; RST=$'\033[0m'
step() { printf '\n%s==> %s%s\n' "$BLU" "$*" "$RST"; }
ok()   { printf '  %s[ ok ]%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '  %s[warn]%s %s\n' "$YEL" "$RST" "$*"; }
die()  { printf '\n%s[FAIL]%s %s\n\n' "$RED" "$RST" "$*" >&2; exit 1; }
note() { printf '  %s%s%s\n' "$DIM" "$*" "$RST"; }

# explain WHAT / WHY / SUCCESS / IF-IT-FAILS
#
# Each step says, in plain words, what it is about to do and how to tell whether it worked.
# A deployment is done once, often by someone who did not build the system, and a bare
# "[ ok ] postgres started" tells that person nothing about whether they can continue.
# Pass --quiet to suppress these if you already know the system.
explain() {
  [ "$QUIET" = "true" ] && return 0
  printf '\n  %s┌ WHAT %s %s\n' "$DIM" "$RST" "$1"
  printf '  %s│ WHY  %s %s\n'   "$DIM" "$RST" "$2"
  printf '  %s│ GOOD %s %s\n'   "$DIM" "$RST" "$3"
  printf '  %s└ FAIL %s %s\n\n' "$DIM" "$RST" "$4"
}

usage() {
  sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Options
  --hostname FQDN     Name investigators will use in the browser (required)
  --cert FILE         TLS certificate (PEM). Use an organisation-issued one in production.
  --key FILE          TLS private key (PEM)
  --self-signed       Generate a self-signed certificate instead (LAN pilots only)
  --http-port PORT    Published HTTP port                          (default: 8080)
  --https-port PORT   Published HTTPS port                         (default: 8443)
  --force-tls         Redirect all plain HTTP to HTTPS (recommended in production)
  --quiet             Skip the plain-language explanation printed before each step
  --admin-user NAME   Bootstrap administrator username             (default: admin)
  --admin-password P  Bootstrap administrator password  (default: generated and printed once)
  --image-tar FILE    Load prebuilt images instead of building (air-gapped servers)
  --skip-build        Reuse the images already present
  --keep-test-db      Also create the *_test database (development machines only)
  -h, --help          This help
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --hostname)       HOSTNAME_FQDN="${2:?}"; shift 2 ;;
    --cert)           CERT_SRC="${2:?}"; shift 2 ;;
    --key)            KEY_SRC="${2:?}"; shift 2 ;;
    --self-signed)    SELF_SIGNED="true"; shift ;;
    --http-port)      HTTP_PORT="${2:?}"; HTTP_PORT_SET=true; shift 2 ;;
    --https-port)     HTTPS_PORT="${2:?}"; HTTPS_PORT_SET=true; shift 2 ;;
    --force-tls)      FORCE_TLS="true"; shift ;;
    --quiet)          QUIET="true"; shift ;;
    --admin-user)     ADMIN_USER="${2:?}"; shift 2 ;;
    --admin-password) ADMIN_PASSWORD="${2:?}"; shift 2 ;;
    --image-tar)      IMAGE_TAR="${2:?}"; shift 2 ;;
    --skip-build)     SKIP_BUILD="true"; shift ;;
    --keep-test-db)   KEEP_TEST_DB="true"; shift ;;
    -h|--help)        usage; exit 0 ;;
    *)                die "unknown option: $1  (try --help)" ;;
  esac
done

[ -n "$HOSTNAME_FQDN" ] || { usage; die "--hostname is required"; }
if [ "$SELF_SIGNED" = "false" ] && { [ -z "$CERT_SRC" ] || [ -z "$KEY_SRC" ]; }; then
  die "give --cert and --key, or --self-signed for a LAN pilot"
fi

# =============================================================================
explain \
  "Check this machine can run the server: Docker, disk space, and the ports we need." \
  "Every later step assumes these. Finding out now takes seconds; finding out during the database start costs an hour." \
  "Every line below says [ ok ]." \
  "Install Docker, free up disk, or stop whatever already uses ports 80/443. Then run this script again - it is safe to re-run."

# A kept .env is the port authority on re-runs. Flags still win when given explicitly.
if [ -f "$ENV_FILE" ]; then
  env_http="$(grep -E '^CENTRAL_HTTP_PORT=' "$ENV_FILE" | tail -1 | cut -d= -f2 | tr -d '[:space:]')"
  env_https="$(grep -E '^CENTRAL_HTTPS_PORT=' "$ENV_FILE" | tail -1 | cut -d= -f2 | tr -d '[:space:]')"
  if [ "$HTTP_PORT_SET" = "false" ] && [ -n "$env_http" ] && [ "$env_http" != "$HTTP_PORT" ]; then
    HTTP_PORT="$env_http";  note "using HTTP port $HTTP_PORT from the existing $ENV_FILE"
  fi
  if [ "$HTTPS_PORT_SET" = "false" ] && [ -n "$env_https" ] && [ "$env_https" != "$HTTPS_PORT" ]; then
    HTTPS_PORT="$env_https"; note "using HTTPS port $HTTPS_PORT from the existing $ENV_FILE"
  fi
fi

step "1/7  Preflight"
# =============================================================================
[ "$(id -u)" -eq 0 ] || die "run as root (sudo $0 ...)"
command -v docker >/dev/null || die "docker is not installed"
docker compose version >/dev/null 2>&1 || die "the docker compose plugin is not available"
docker info >/dev/null 2>&1 || die "the docker daemon is not reachable"
command -v openssl >/dev/null || die "openssl is required (secret generation)"
[ -f "$REPO_ROOT/docker-compose.yml" ] || die "run this from the deploy/ directory of the source tree"
ok "docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?')"

for p in "$HTTP_PORT" "$HTTPS_PORT"; do
  if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${p}$"; then
    # Our own nginx holding the port is a re-run, not a conflict.
    if docker ps --format '{{.Names}} {{.Ports}}' 2>/dev/null | grep -q "mstt-nginx.*:${p}->"; then
      note "port $p is held by this stack's own nginx (re-run) - fine"
    else
      die "port $p is already in use by something else on this host"
    fi
  fi
done
ok "ports $HTTP_PORT and $HTTPS_PORT are available to this stack"
note "hostname: $HOSTNAME_FQDN"

# =============================================================================
explain \
  "Create the passwords and signing keys this server will use, and write them to a private file (.env)." \
  "These are generated ONCE and never regenerated. The signing key proves to every desktop that a job really came from this server - regenerate it and every desktop stops trusting you." \
  "'secrets generated' or 'existing .env kept'. Re-running never overwrites what is already there." \
  "If .env exists but is unreadable, fix its permissions. NEVER delete it to 'start clean' - you would invalidate every desktop already deployed."

step "2/7  Secrets and configuration"
# =============================================================================
GENERATED_ADMIN_PW=""
if [ -f "$ENV_FILE" ]; then
  ok "reusing the existing $ENV_FILE (secrets are NOT regenerated)"
  cp -a "$ENV_FILE" "$ENV_FILE.bak.$(date +%Y%m%d%H%M%S)"
else
  [ -n "$ADMIN_PASSWORD" ] || { ADMIN_PASSWORD="$(openssl rand -base64 18)Aa1!"; GENERATED_ADMIN_PW="$ADMIN_PASSWORD"; }
  umask 077
  cat > "$ENV_FILE" <<ENV
# Central server - generated by deploy-central.sh on $(date -Is)
# Contains live secrets. Mode 0600, never commit this file.
POSTGRES_DB=military_stt
POSTGRES_USER=stt
POSTGRES_PASSWORD=$(openssl rand -hex 24)

CENTRAL_ENVIRONMENT=production
CENTRAL_DEBUG=false
CENTRAL_JWT_SECRET=$(openssl rand -hex 32)
CENTRAL_ACCESS_TOKEN_EXPIRE_MINUTES=480
CENTRAL_PROCESSING_TOKEN_ACCEPT_TTL_SECONDS=600
CENTRAL_PROCESSING_TOKEN_SUBMIT_TTL_SECONDS=86400
CENTRAL_MAX_UPLOAD_BYTES=2147483648
# Empty in production: the frontend is served from the same origin as the API.
CENTRAL_CORS_ALLOWED_ORIGINS=

CENTRAL_BOOTSTRAP_ADMIN_USERNAME=$ADMIN_USER
CENTRAL_BOOTSTRAP_ADMIN_PASSWORD=$ADMIN_PASSWORD

CENTRAL_HTTP_PORT=$HTTP_PORT
CENTRAL_HTTPS_PORT=$HTTPS_PORT

# Never ship dev dependencies (pytest and friends) in a production image.
INSTALL_DEV=false
CREATE_TEST_DB=$KEEP_TEST_DB
ENV
  chmod 0600 "$ENV_FILE"
  ok "$ENV_FILE written (0600) with freshly generated secrets"
fi
[ "$KEEP_TEST_DB" = "true" ] && warn "the *_test database will be created - development only"

install -d -m 0750 "$REPO_ROOT/secrets" "$REPO_ROOT/storage"
ok "storage and secrets directories ready"
note "the ES256 processing keypair is generated by the backend on first start,"
note "into $REPO_ROOT/secrets - back it up, and never copy the private key to a desktop."

# =============================================================================
explain \
  "Install the HTTPS certificate so browsers and desktops can reach this server securely." \
  "Investigators send interview audio over this connection. Without TLS it crosses the network readable by anyone on it." \
  "'certificate installed'. With --self-signed you also get a warning - that is expected for a pilot, not for production." \
  "Check that --cert and --key point at real files and that the key matches the certificate. A mismatch is the usual cause."

step "3/7  TLS certificate"
# =============================================================================
CERT_DIR="$REPO_ROOT/central/nginx/certs"
install -d -m 0755 "$CERT_DIR"
if [ "$SELF_SIGNED" = "true" ]; then
  if [ -f "$CERT_DIR/cert.pem" ] && [ -f "$CERT_DIR/key.pem" ]; then
    ok "certificate already present - keeping it"
  else
    openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
      -keyout "$CERT_DIR/key.pem" -out "$CERT_DIR/cert.pem" \
      -subj "/CN=$HOSTNAME_FQDN/O=Military STT AI" \
      -addext "subjectAltName=DNS:$HOSTNAME_FQDN,DNS:localhost,IP:127.0.0.1" 2>/dev/null \
      || die "openssl could not generate the certificate"
    ok "self-signed certificate generated for $HOSTNAME_FQDN"
  fi
  warn "self-signed: every investigator's browser will warn until this certificate is"
  warn "distributed as a trusted root. Use an organisation-issued certificate in production."
else
  [ -f "$CERT_SRC" ] || die "certificate not found: $CERT_SRC"
  [ -f "$KEY_SRC" ]  || die "private key not found: $KEY_SRC"
  openssl x509 -in "$CERT_SRC" -noout >/dev/null 2>&1 || die "$CERT_SRC is not a PEM certificate"
  openssl pkey -in "$KEY_SRC" -noout >/dev/null 2>&1  || die "$KEY_SRC is not a PEM private key"
  # A cert and key that do not belong together produce a container that starts
  # and then refuses every TLS handshake - catch it here instead.
  c_mod="$(openssl x509 -in "$CERT_SRC" -noout -pubkey | openssl pkey -pubin -outform DER 2>/dev/null | sha256sum)"
  k_mod="$(openssl pkey -in "$KEY_SRC" -pubout -outform DER 2>/dev/null | sha256sum)"
  [ "$c_mod" = "$k_mod" ] || die "the certificate and the private key do not match"
  install -m 0644 "$CERT_SRC" "$CERT_DIR/cert.pem"
  install -m 0600 "$KEY_SRC"  "$CERT_DIR/key.pem"
  ok "certificate and key installed and verified as a matching pair"
  if ! openssl x509 -in "$CERT_DIR/cert.pem" -noout -checkend 2592000 >/dev/null 2>&1; then
    warn "this certificate expires within 30 days"
  fi
  subj="$(openssl x509 -in "$CERT_DIR/cert.pem" -noout -subject | sed 's/^subject=//')"
  note "subject:$subj"
fi

if [ "$FORCE_TLS" = "true" ]; then
  CONF="$REPO_ROOT/central/nginx/conf.d/central.conf"
  if grep -q '^\s*return 301 https' "$CONF"; then
    ok "HTTP -> HTTPS redirect already enabled"
  else
    sed -i "s|^\([[:space:]]*\)#[[:space:]]*return 301 https://\$host:[0-9]*\$request_uri;|\1return 301 https://\$host:$HTTPS_PORT\$request_uri;|" "$CONF"
    grep -q '^\s*return 301 https' "$CONF" \
      && ok "HTTP -> HTTPS redirect enabled on port $HTTPS_PORT" \
      || warn "could not enable the redirect automatically - edit $CONF by hand"
  fi
fi

# =============================================================================
explain \
  "Build the four application images: database, backend, web interface, and the web server in front of them." \
  "This machine runs the system from these images. Building takes the longest of any step - several minutes is normal, and nothing is wrong if it looks paused." \
  "'images built'. Some steps print a lot of output; that is the build, not an error." \
  "Almost always no disk space or no network to fetch base images. Check 'df -h' and your proxy settings."

step "4/7  Images"
# =============================================================================
DC=(docker compose --env-file "$ENV_FILE" -f "$REPO_ROOT/docker-compose.yml")
if [ -n "$IMAGE_TAR" ]; then
  [ -f "$IMAGE_TAR" ] || die "image archive not found: $IMAGE_TAR"
  docker load -i "$IMAGE_TAR" >/dev/null || die "docker load failed"
  ok "images loaded from $IMAGE_TAR"
elif [ "$SKIP_BUILD" = "true" ]; then
  ok "reusing the images already present"
else
  note "building (INSTALL_DEV=false - no test tooling in the production image)"
  INSTALL_DEV=false "${DC[@]}" build || die "image build failed"
  ok "images built"
fi

# =============================================================================
explain \
  "Start everything, then update the database structure to match this version." \
  "The database update runs automatically. If it finds data it cannot safely convert it STOPS rather than guessing - that refusal is a feature, and this script prints what it means." \
  "'postgres, backend, frontend and nginx started', with no [REFUSED] block after it." \
  "If you see [REFUSED], read the explanation printed with it. It names the exact data problem, and it is a question only your unit can answer - never a bug to work around."

step "5/7  Starting the stack"
# =============================================================================
"${DC[@]}" up -d --remove-orphans || die "the stack did not start"
systemctl enable docker >/dev/null 2>&1 || true    # come back after a reboot
ok "postgres, backend, frontend and nginx started"

# nginx caches the backend's container IP from config-load time. If this deploy recreated
# the backend (an upgrade always does), nginx still points at the OLD IP and serves 502s.
# One restart re-resolves it; on a fresh install it is a harmless second.
"${DC[@]}" restart nginx >/dev/null 2>&1 || true
ok "nginx re-resolved the backend address"

# --- collation safety after the pgvector image switch ------------------------
# The database image moved from postgres:16-alpine to pgvector/pgvector:pg16 (same major
# version, so the data volume mounts unchanged). Alpine uses musl and Debian uses glibc,
# and their collations sort text differently - indexes built under one can be silently
# wrong under the other. Postgres records the collation version a database was built
# with; when the running library disagrees, reindex once and record the new version.
# On a fresh install the versions agree and this does nothing.
for _db in military_stt military_stt_test; do
  mismatch="$("${DC[@]}" exec -T postgres psql -U stt -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname='${_db}'
       AND datcollversion IS DISTINCT FROM pg_database_collation_actual_version(oid)" \
    2>/dev/null | tr -d '[:space:]' || true)"
  if [ "$mismatch" = "1" ]; then
    warn "collation library changed for ${_db} (image switch) - reindexing once"
    # REFRESH COLLATION VERSION cannot transition from alpine's NULL version, so the
    # recorded version is stamped directly - the documented workaround for exactly this
    # alpine(musl) -> debian(glibc) move. The REINDEX is the part that protects the data.
    "${DC[@]}" exec -T postgres psql -U stt -d "${_db}" -c "REINDEX DATABASE ${_db};" >/dev/null \
      && "${DC[@]}" exec -T postgres psql -U stt -d postgres -c \
           "UPDATE pg_database SET datcollversion = pg_database_collation_actual_version(oid) WHERE datname='${_db}';" >/dev/null \
      && ok "${_db} reindexed for the new collation library" \
      || warn "could not reindex ${_db} - run manually: REINDEX DATABASE ${_db};"
  fi
done

# A migration that refuses is a DATA question only an operator can answer, so it must never
# be buried under a generic health-check failure. Each entry is a marker the migration prints
# and the one-line explanation an operator needs.
migration_refusals() {
  cat <<'MARKERS'
Cannot backfill canonical identities|One reference number is recorded under two different names.
Cannot retire family-keyed references|One reference is recorded against more than one person: رقم السجل identifies a family, so these may be relatives collapsed into one identity.
MARKERS
}

# Report a refusal if the logs contain one. Returns 0 when it reported something.
report_migration_refusal() {
  local logs marker explanation
  logs="$("${DC[@]}" logs backend 2>&1 || true)"
  while IFS='|' read -r marker explanation; do
    [ -n "$marker" ] || continue
    if printf '%s' "$logs" | grep -q "$marker"; then
      printf '\n%s[REFUSED]%s a database migration stopped on purpose.\n' "$RED" "$RST" >&2
      printf '          %s\n' "$explanation" >&2
      printf '          Nothing was changed. Resolve it, then run again:\n\n' >&2
      printf '%s' "$logs" | grep -A 2 "$marker" | sed 's/^/          /' >&2
      printf '\n' >&2
      return 0
    fi
  done < <(migration_refusals)
  return 1
}

printf '  waiting for the database and Alembic migrations '
for i in $(seq 1 90); do
  if "${DC[@]}" exec -T backend curl -fsS --max-time 3 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    printf ' up\n'; break
  fi
  # Fail fast when the backend has EXITED. A migration that refuses takes seconds; waiting the
  # full three minutes to say so wastes the operator time and hides the reason.
  if [ -z "$("${DC[@]}" ps -q --status running backend 2>/dev/null)" ] \
     && [ -n "$("${DC[@]}" ps -aq backend 2>/dev/null)" ]; then
    printf '\n'
    report_migration_refusal && exit 1
    # Any other startup failure: show what Alembic actually said rather than a tail of noise.
    printf '%s[FAILED]%s the backend exited during startup.\n' "$RED" "$RST" >&2
    "${DC[@]}" logs backend 2>&1 | grep -iE "error|traceback|alembic|refus" | tail -20 | sed 's/^/          /' >&2
    die "the backend exited before becoming healthy"
  fi
  if [ "$i" -eq 90 ]; then
    printf '\n'
    report_migration_refusal && exit 1
    "${DC[@]}" logs --tail 40 backend
    die "the backend never became healthy"
  fi
  printf '.'; sleep 2
done
rev="$("${DC[@]}" exec -T backend alembic current 2>/dev/null | tail -1 || true)"
ok "backend healthy - schema at ${rev:-unknown}"

# =============================================================================
explain \
  "Prove the server actually works: answer over HTTPS, serve the Arabic interface, and hand out the key the desktops need." \
  "A container that is 'running' is not the same as a server that works. This step checks the things a user would notice, and exports the public key file you will carry to each desktop." \
  "'API reachable over HTTPS', 'Arabic RTL frontend is being served', and 'public key exported'." \
  "A failure here means the stack started but is not usable - do NOT deploy desktops yet. The message names which check failed."

step "6/7  Verifying the deployment"
# =============================================================================
BASE_HTTP="http://127.0.0.1:$HTTP_PORT"
BASE_TLS="https://127.0.0.1:$HTTPS_PORT"

code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$BASE_HTTP/api/health" || echo 000)"
if [ "$FORCE_TLS" = "true" ]; then
  [ "$code" = "301" ] && ok "HTTP is redirected to HTTPS (301)" || warn "expected a 301 redirect on HTTP, got $code"
else
  [ "$code" = "200" ] && ok "API reachable over HTTP ($BASE_HTTP)" || warn "HTTP health returned $code"
fi

code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "$BASE_TLS/api/health" || echo 000)"
[ "$code" = "200" ] && ok "API reachable over HTTPS ($BASE_TLS)" || die "HTTPS health returned $code - check the certificate"

# The frontend must be served as a real page, not a proxy error.
curl -sk --max-time 10 "$BASE_TLS/" | grep -q 'dir="rtl"' \
  && ok "Arabic RTL frontend is being served" \
  || warn "the frontend did not return an RTL document"

# The ES256 public key must exist and must be a PUBLIC key.
pk="$(curl -sk --max-time 10 "$BASE_TLS/api/local-processing/public-key" || true)"
printf '%s' "$pk" | grep -q "BEGIN PUBLIC KEY" \
  && ok "ES256 processing keypair present and serving its public half" \
  || die "the public key endpoint did not return a PEM public key"
[ -f "$REPO_ROOT/secrets/processing_token_private.pem" ] \
  && ok "private signing key stored in $REPO_ROOT/secrets (never distribute it)"

# Export the public key so it can be carried to the workstations. printf '%b'
# turns the JSON-escaped newlines into real ones.
pem="$(printf '%s' "$pk" \
  | sed -e 's/.*"public_key_pem"[[:space:]]*:[[:space:]]*"//' -e 's/".*//')"
[ -n "$pem" ] || die "could not extract the public key from the API response"
printf '%b\n' "$pem" > "$SCRIPT_DIR/central_public_key.pem"
chmod 0444 "$SCRIPT_DIR/central_public_key.pem"
grep -q "BEGIN PUBLIC KEY" "$SCRIPT_DIR/central_public_key.pem" \
  || die "the exported public key is not valid PEM"
ok "public key exported to deploy/central_public_key.pem"

# --- schema level -----------------------------------------------------------
# b2e94c1f7a06 is what makes an investigator a person in the registry. Without it the
# picker cannot offer them and no voice print can ever be filed against one, so a stack
# that came up on an older head is reported here rather than discovered by a user.
if "${DC[@]}" exec -T postgres psql -U stt -d military_stt -tAc \
     "SELECT 1 FROM alembic_version WHERE version_num='b2e94c1f7a06'" 2>/dev/null | grep -q 1; then
  ok "schema at b2e94c1f7a06 (investigators are registry people)"
else
  warn "schema is NOT at b2e94c1f7a06 - investigators cannot be identified or voice-enrolled."
  warn "  Check for a refused migration: ${DC[*]} logs backend | grep -i alembic"
fi

# --- staff who cannot yet be identified -------------------------------------
# الجهاز + الرقم العسكري are what produce a user's الرقم المرجعي. Accounts created before
# they became mandatory - the bootstrap administrator above is always one - have neither,
# so they cannot be bound to a speaker or carry a voice print. This is not a failure: the
# system works, and completing the profile fixes it. But it is invisible from the interface
# until someone tries, so it is stated here.
incomplete="$("${DC[@]}" exec -T postgres psql -U stt -d military_stt -tAc \
  "SELECT string_agg(full_name, ', ') FROM investigator_profiles
    WHERE COALESCE(NULLIF(btrim(military_id), ''), NULL) IS NULL
       OR security_branch IS NULL" 2>/dev/null | tr -d '\r' | head -1 || true)"
if [ -n "${incomplete// /}" ]; then
  warn "these accounts have no الرقم المرجعي and cannot be identified as speakers:"
  warn "    $incomplete"
  warn "  Fix in إدارة المستخدمين: set الجهاز and الرقم العسكري. Until then they appear"
  warn "  in the speaker picker DISABLED, and no voice print can be filed against them."
else
  ok "every staff account can be identified (الجهاز + الرقم العسكري present)"
fi

if [ "$KEEP_TEST_DB" = "false" ]; then
  if "${DC[@]}" exec -T postgres psql -U stt -lqt 2>/dev/null | cut -d'|' -f1 | grep -qw "military_stt_test"; then
    warn "a *_test database exists (created by an earlier development run)"
  else
    ok "no test database in this cluster"
  fi
fi

# =============================================================================
explain \
  "Print what you need to keep: the address, the administrator password, and what to back up." \
  "The administrator password is shown ONCE and cannot be recovered. The secrets folder cannot be recreated either." \
  "A summary block with the URL and a first-run checklist. Copy the password into your password manager before closing this window." \
  "If you lost the password, you can reset it, but only from this machine with database access."

step "7/7  Done"
# =============================================================================
cat <<EOF

$(printf '%s' "$GRN")Central server deployed.$(printf '%s' "$RST")

  URL              https://$HOSTNAME_FQDN:$HTTPS_PORT
  administrator    $ADMIN_USER
EOF
if [ -n "$GENERATED_ADMIN_PW" ]; then
  cat <<EOF
  password         $GENERATED_ADMIN_PW
                   $(printf '%s' "$YEL")Shown once. Store it in your password manager now.$(printf '%s' "$RST")
                   A password change is forced at first sign-in.
EOF
else
  echo "  password         unchanged (see CENTRAL_BOOTSTRAP_ADMIN_PASSWORD in $ENV_FILE)"
fi
cat <<EOF

  config           $ENV_FILE           (0600 - contains live secrets)
  signing keys     $REPO_ROOT/secrets       BACK THIS UP
  evidence         $REPO_ROOT/storage       BACK THIS UP
  public key       $SCRIPT_DIR/central_public_key.pem   -> copy to each desktop

  logs             ${DC[*]} logs -f backend
  stop             ${DC[*]} down
  people on a case curl -sk $BASE_TLS/api/investigations/<id>/people   (one shape, canonical names)

Next, on each investigator desktop:

  sudo ./deploy-edge.sh --central-url https://$HOSTNAME_FQDN:$HTTPS_PORT \
       --public-key ./central_public_key.pem

FIRST-RUN CHECKLIST (in this order)

  1. Sign in as $ADMIN_USER and change the password when prompted.
  2. إدارة المستخدمين -> edit the administrator and fill in الجهاز and الرقم العسكري.
     These two produce the account's الرقم المرجعي (MIL-<الجهاز>-<الرقم>). Until they are
     set the account cannot be bound to a speaker and cannot carry a voice print - it will
     appear in the speaker picker DISABLED. Every user created from now on is required to
     supply them, so this applies only to the bootstrap account.
  3. Create the investigator accounts. الجهاز آخر is refused on purpose: it is a catch-all,
     not a namespace, and two "other" forces sharing a serial would collapse into one
     identity and pool two people's voice prints.
  4. Deploy the desktops (below), then run one recording end to end before going live.

Back up before going live: $REPO_ROOT/secrets, $REPO_ROOT/storage, and a
pg_dump of the database. Losing secrets/ invalidates every processing token.
EOF
