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

HOSTNAME_FQDN=""
CERT_SRC=""; KEY_SRC=""
SELF_SIGNED="false"
HTTP_PORT="8080"; HTTPS_PORT="8443"
FORCE_TLS="false"
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
    --http-port)      HTTP_PORT="${2:?}"; shift 2 ;;
    --https-port)     HTTPS_PORT="${2:?}"; shift 2 ;;
    --force-tls)      FORCE_TLS="true"; shift ;;
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
  if command -v ss >/dev/null && ss -lnt "sport = :$p" 2>/dev/null | grep -q LISTEN; then
    die "port $p is already in use"
  fi
done
ok "ports $HTTP_PORT and $HTTPS_PORT are free"
note "hostname: $HOSTNAME_FQDN"

# =============================================================================
step "2/7  Secrets and configuration"
# =============================================================================
ENV_FILE="$REPO_ROOT/.env"
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
step "5/7  Starting the stack"
# =============================================================================
"${DC[@]}" up -d --remove-orphans || die "the stack did not start"
systemctl enable docker >/dev/null 2>&1 || true    # come back after a reboot
ok "postgres, backend, frontend and nginx started"

printf '  waiting for the database and Alembic migrations '
for i in $(seq 1 90); do
  if "${DC[@]}" exec -T backend curl -fsS --max-time 3 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    printf ' up\n'; break
  fi
  [ "$i" -eq 90 ] && { printf '\n'; "${DC[@]}" logs --tail 40 backend; die "the backend never became healthy"; }
  printf '.'; sleep 2
done
rev="$("${DC[@]}" exec -T backend alembic current 2>/dev/null | tail -1 || true)"
ok "backend healthy - schema at ${rev:-unknown}"

# =============================================================================
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

if [ "$KEEP_TEST_DB" = "false" ]; then
  if "${DC[@]}" exec -T postgres psql -U stt -lqt 2>/dev/null | cut -d'|' -f1 | grep -qw "military_stt_test"; then
    warn "a *_test database exists (created by an earlier development run)"
  else
    ok "no test database in this cluster"
  fi
fi

# =============================================================================
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

Next, on each investigator desktop:

  sudo ./deploy-edge.sh --central-url https://$HOSTNAME_FQDN:$HTTPS_PORT \
       --public-key ./central_public_key.pem

Back up before going live: $REPO_ROOT/secrets, $REPO_ROOT/storage, and a
pg_dump of the database. Losing secrets/ invalidates every processing token.
EOF
