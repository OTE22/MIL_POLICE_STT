#!/usr/bin/env bash
# =============================================================================
#  Military STT AI - Central server deployment
# =============================================================================
#  Runs the web application: nginx + React (Arabic RTL) + FastAPI + PostgreSQL.
#  It stores, authorises and audits. It runs NO AI - the models live on the
#  investigator desktops (see deploy-edge.sh).
#
#  Pick the environment FIRST - it changes what is installed and what is allowed:
#
#    PRODUCTION   real cases. Arabic formalization runs LOCALLY or not at all; no
#                 cloud AI is ever contacted. An APPROVED Word template must be
#                 uploaded before an official محضر can be issued. No test database,
#                 no dev dependencies in the image.
#
#    DEVELOPMENT  demonstrations, training, integration work. May use the hosted
#                 NVIDIA catalogue for Arabic formalization, WITH SYNTHETIC DATA
#                 ONLY, and ships with a clearly-marked non-approved template so the
#                 report composer works on day one.
#
#      sudo ./deploy-central.sh --environment production \
#           --hostname central.unit.local \
#           --cert /etc/ssl/unit.crt --key /etc/ssl/unit.key
#
#      sudo ./deploy-central.sh --environment development \
#           --hostname localhost --self-signed
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
KEEP_TEST_DB_SET=false
SKIP_BUILD="false"
# Nothing is assumed: an operator who does not say which environment this is gets asked.
ENVIRONMENT=""
NVIDIA_KEY_SRC=""
# How this server can be REACHED. The hostname goes in the certificate; every static IP
# and alias listed here goes in too, so a browser is happy whichever one an investigator
# types. Left empty, the script detects this machine's own addresses and uses those.
EXTRA_IPS=""
EXTRA_NAMES=""
# Which host interface Docker publishes on. 0.0.0.0 = every interface, which is what a
# server with a static IP wants. Narrow it on a multi-homed machine that must not answer
# on, say, its management network.
BIND_ADDR="0.0.0.0"
# Field mode: an already-deployed, already-tested server is being given its real address.
RECONFIGURE="false"

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; BLU=$'\033[34m'; DIM=$'\033[2m'; RST=$'\033[0m'
step() { printf '\n%s==> %s%s\n' "$BLU" "$*" "$RST"; }
ok()   { printf '  %s[ ok ]%s %s\n' "$GRN" "$RST" "$*"; }
warn() { printf '  %s[warn]%s %s\n' "$YEL" "$RST" "$*"; }
die()  { printf '\n%s[FAIL]%s %s\n\n' "$RED" "$RST" "$*" >&2; exit 1; }
note() { printf '  %s%s%s\n' "$DIM" "$*" "$RST"; }

# --- how each step explains itself -------------------------------------------
#
# A deployment is done once, often by someone who has never seen the system, and a bare
# "[ ok ] postgres started" tells that person nothing about whether they may continue.
# Every step therefore answers five questions BEFORE it runs:
#
#   WHAT  in plain words, what is about to happen
#   WHY   why this step exists at all, and what breaks without it
#   TIME  roughly how long to wait before suspecting a problem
#   GOOD  what success looks like on screen
#   FAIL  what to do about it, and whether it is safe to re-run
#
# Pass --quiet to suppress them once you know the system.

# Wrap to the terminal, capped for readability on very wide windows.
TERM_COLS="$( { tput cols 2>/dev/null || echo 80; } )"
case "$TERM_COLS" in ''|*[!0-9]*) TERM_COLS=80 ;; esac
[ "$TERM_COLS" -gt 100 ] && TERM_COLS=100
[ "$TERM_COLS" -lt 60 ] && TERM_COLS=80
WRAP_AT=$((TERM_COLS - 12))

# _field LABEL TEXT - one wrapped, hanging-indented field of the explanation box.
_field() {
  # The trailing newline matters: `while read` discards a final UNTERMINATED line, which
  # silently swallowed one-line fields (TIME) and the last line of longer ones.
  printf '%s\n' "$2" | fold -s -w "$WRAP_AT" | {
    first=1
    while IFS= read -r line; do
      if [ "$first" = 1 ]; then
        printf '  %s| %-4s %s%s\n' "$DIM" "$1" "$RST" "$line"; first=0
      else
        printf '  %s|      %s%s\n' "$DIM" "$RST" "$line"
      fi
    done
  }
}

# explain WHAT WHY TIME GOOD FAIL
explain() {
  [ "$QUIET" = "true" ] && return 0
  rule="$(printf '%*s' "$((WRAP_AT + 7))" '' | tr ' ' '-')"
  printf '\n  %s+%s%s\n' "$DIM" "$rule" "$RST"
  _field "WHAT" "$1"
  _field "WHY"  "$2"
  _field "TIME" "$3"
  _field "GOOD" "$4"
  _field "FAIL" "$5"
  printf '  %s+%s%s\n\n' "$DIM" "$rule" "$RST"
}

# roadmap TITLE LINE... - the whole journey, printed once before step 1 so nobody is
# surprised by a step that takes twenty minutes.
roadmap() {
  [ "$QUIET" = "true" ] && return 0
  title="$1"; shift
  printf '\n%s%s%s\n' "$BLU" "$title" "$RST"
  for entry in "$@"; do printf '  %s\n' "$entry"; done
  printf '\n'
}

# --- how this machine can be reached -----------------------------------------
#
# A server is rarely used at "localhost". It has a static IP, and ideally a name. Both
# have to end up in the TLS certificate or the browser refuses the connection, and a
# certificate cannot be amended afterwards - so they are collected BEFORE it is issued.

# Every global IPv4 address of this machine, one per line.
detect_ips() {
  if command -v ip >/dev/null 2>&1; then
    ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1
  elif command -v hostname >/dev/null 2>&1; then
    hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.'
  fi | grep -vE '^(127\.|169\.254\.)' | sort -u || true
}

is_ipv4() {
  case "$1" in
    *[!0-9.]*) return 1 ;;
    *.*.*.*)   return 0 ;;
    *)         return 1 ;;
  esac
}

# What does this name resolve to on THIS machine, if anything?
#
# Tried in order of trustworthiness: getent reads the SAME path the application will use
# (hosts file, then DNS), which is exactly what we want to know; the others are fallbacks
# for minimal images. Two traps are handled explicitly:
#
#   * a tool that exists but answers nothing must NOT end the chain, so each result is
#     captured and only a non-empty answer is accepted (Windows ships a python3 stub that
#     runs and prints nothing at all);
#   * nslookup prints the DNS SERVER address before the answer, so only the lines after
#     "Name:" are read - otherwise every name appears to resolve to the resolver itself.
#
# No output means "no answer", which the caller reads as "DNS is not set up yet".
resolve_name() {
  _name="$1"; _got=""

  if command -v getent >/dev/null 2>&1; then
    _got="$(getent ahostsv4 "$_name" 2>/dev/null | awk '{print $1}' | sort -u | head -5)"
    [ -n "$_got" ] && { printf '%s\n' "$_got"; return 0; }
  fi
  if command -v dig >/dev/null 2>&1; then
    _got="$(dig +short "$_name" A 2>/dev/null | grep -E '^[0-9.]+$')"
    [ -n "$_got" ] && { printf '%s\n' "$_got"; return 0; }
  fi
  if command -v host >/dev/null 2>&1; then
    _got="$(host -t A "$_name" 2>/dev/null | sed -n 's/.*has address //p')"
    [ -n "$_got" ] && { printf '%s\n' "$_got"; return 0; }
  fi
  if command -v python3 >/dev/null 2>&1; then
    _got="$(python3 -c 'import socket,sys
try:
    print("\n".join(sorted({i[4][0] for i in socket.getaddrinfo(sys.argv[1], None, socket.AF_INET)})))
except Exception:
    pass' "$_name" 2>/dev/null)"
    [ -n "$_got" ] && { printf '%s\n' "$_got"; return 0; }
  fi
  if command -v nslookup >/dev/null 2>&1; then
    _got="$(nslookup "$_name" 2>/dev/null | sed -n '/^Name:/,$p' \
            | awk '/^Address(es)?: /{print $NF}' | grep -E '^[0-9.]+$')"
    [ -n "$_got" ] && { printf '%s\n' "$_got"; return 0; }
  fi
  ping -c1 -W1 "$_name" 2>/dev/null | sed -n 's/^PING [^(]*(\([0-9.]*\)).*/\1/p' || true
}

# --- issuing the certificate --------------------------------------------------
#
# Shared by the normal deployment and by --reconfigure-address, because the certificate is
# the ONE thing that must change when a server is given a new address. A browser matches
# what the operator typed against the names inside the certificate; a certificate cannot be
# amended, only replaced.
issue_certificate() {
  CERT_DIR="$REPO_ROOT/central/nginx/certs"
  install -d -m 0755 "$CERT_DIR"

  # What the certificate must cover for this deployment.
  want_san=""
  is_ipv4 "$HOSTNAME_FQDN" || want_san="DNS:$HOSTNAME_FQDN"
  for _n in $EXTRA_NAMES; do want_san="${want_san:+$want_san,}DNS:$_n"; done
  want_san="${want_san:+$want_san,}DNS:localhost"
  for _a in $EXTRA_IPS; do want_san="$want_san,IP:$_a"; done
  want_san="$want_san,IP:127.0.0.1"

CERT_DIR="$REPO_ROOT/central/nginx/certs"
install -d -m 0755 "$CERT_DIR"
if [ "$SELF_SIGNED" = "true" ]; then
  # An existing certificate is kept ONLY if it already covers every address this run
  # asks for. Otherwise it is replaced - silently keeping a localhost-only certificate is
  # exactly what breaks a server the moment it is given a static IP.
  cert_covers_all=false
  if [ -f "$CERT_DIR/cert.pem" ] && [ -f "$CERT_DIR/key.pem" ]; then
    have="$(openssl x509 -in "$CERT_DIR/cert.pem" -noout -ext subjectAltName 2>/dev/null | tr -d ' ')"
    cert_covers_all=true
    for _want in $(printf '%s' "$want_san" | tr ',' ' '); do
      case "$_want" in
        DNS:*) printf '%s' "$have" | grep -q "DNS:${_want#DNS:}\(,\|$\)" || cert_covers_all=false ;;
        IP:*)  printf '%s' "$have" | grep -q "IPAddress:${_want#IP:}\(,\|$\)" || cert_covers_all=false ;;
      esac
    done
  fi

  if [ "$cert_covers_all" = "true" ]; then
    ok "certificate already present and covers every address - keeping it"
  else
    if [ -f "$CERT_DIR/cert.pem" ]; then
      stamp="$(date +%Y%m%d%H%M%S)"
      cp -a "$CERT_DIR/cert.pem" "$CERT_DIR/cert.pem.replaced.$stamp"
      [ -f "$CERT_DIR/key.pem" ] && cp -a "$CERT_DIR/key.pem" "$CERT_DIR/key.pem.replaced.$stamp"
      warn "the existing certificate does not cover every requested address - replacing it"
      note "previous certificate AND key kept as *.replaced.$stamp"
    fi
    # Every way the server may be addressed has to be IN the certificate. A browser
    # matches what the user TYPED against this list, so a certificate naming only the
    # hostname fails the moment someone uses the IP - and it cannot be amended later.
    san="$want_san"

    # openssl writes the key BEFORE it finishes validating everything else, so writing
    # straight into place can leave a new key beside the old certificate - a mismatched
    # pair that nginx refuses. Build both aside, then move them in together.
    if ! openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
           -keyout "$CERT_DIR/key.pem.new" -out "$CERT_DIR/cert.pem.new" \
           -subj "/CN=$HOSTNAME_FQDN/O=Military STT AI" \
           -addext "subjectAltName=$san" 2>/dev/null; then
      rm -f "$CERT_DIR/cert.pem.new" "$CERT_DIR/key.pem.new"
      die "openssl could not generate the certificate - the existing one is untouched"
    fi
    mv -f "$CERT_DIR/cert.pem.new" "$CERT_DIR/cert.pem"
    mv -f "$CERT_DIR/key.pem.new"  "$CERT_DIR/key.pem"
    chmod 0644 "$CERT_DIR/cert.pem"; chmod 0600 "$CERT_DIR/key.pem"
    ok "self-signed certificate generated"
    note "valid for: $san"
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
  # A certificate that does not name the address people actually type produces a browser
  # warning on every visit - worth saying now rather than discovering it at go-live.
  cert_san="$(openssl x509 -in "$CERT_DIR/cert.pem" -noout -ext subjectAltName 2>/dev/null | tr -d ' ')"
  [ -n "$cert_san" ] && note "certificate covers:$(printf '%s' "$cert_san" | tail -1)"
  for _target in "$HOSTNAME_FQDN" $EXTRA_NAMES; do
    printf '%s' "$cert_san" | grep -q "DNS:$_target\(,\|$\)" \
      || warn "the certificate does NOT list '$_target' - browsers will warn when it is used"
  done
  for _a in $EXTRA_IPS; do
    printf '%s' "$cert_san" | grep -q "IP Address:$_a\(,\|$\)" \
      || warn "the certificate does NOT list IP $_a - browsers will warn when it is used"
  done
fi

}

# --- giving a deployed server its real address --------------------------------
#
# The field workflow: build and test the whole system somewhere convenient, then carry it
# into the air-gapped room and run THIS, once, to point it at its static IP and its DNS
# name. It re-issues the certificate, republishes the ports and re-checks the name. It
# does not build, migrate, or touch a single row of data.
reconfigure_address() {
  [ -f "$ENV_FILE" ] || die "no $ENV_FILE - this machine has not been deployed yet. Run without --reconfigure-address first."

  roadmap "Changing this server's address (3 steps, under a minute)" \
    "1. Certificate   re-issue it for the new name and IPs      seconds" \
    "2. Publish       republish the ports on the new interface  seconds" \
    "3. Verify        prove every address answers, re-check DNS seconds" \
    "" \
    "Nothing is rebuilt and no data is touched. Secrets, cases, transcripts, voice" \
    "prints and issued reports are all left exactly as they are."

  explain \
    "Re-issue the TLS certificate so it covers the address this server will actually be reached at, and republish the ports on the right interface." \
    "A certificate lists the names and addresses a browser will accept, and it cannot be amended - only replaced. A server that was built and tested at localhost carries a certificate that says localhost, so the moment it is given a static IP every browser refuses it. This is also why the ports are republished rather than merely restarted: Docker fixes a published address when the container is CREATED, so a changed bind address only takes effect on a recreate." \
    "Under a minute." \
    "certificate replaced, nginx recreated, and every address answering." \
    "Everything here is safe to repeat. The previous certificate is kept beside the new one, and no application data is involved at any point."

  step "1/3  Certificate for the new address"
  issue_certificate

  step "2/3  Publishing on the new address"
  # The published address is baked in when the container is created, so a restart is not
  # enough - this is the same trap that makes a changed port silently do nothing.
  if grep -q '^CENTRAL_BIND_ADDRESS=' "$ENV_FILE"; then
    sed -i "s|^CENTRAL_BIND_ADDRESS=.*|CENTRAL_BIND_ADDRESS=$BIND_ADDR|" "$ENV_FILE"
  else
    printf 'CENTRAL_BIND_ADDRESS=%s\n' "$BIND_ADDR" >> "$ENV_FILE"
  fi
  sed -i "s|^CENTRAL_HTTP_PORT=.*|CENTRAL_HTTP_PORT=$HTTP_PORT|"   "$ENV_FILE"
  sed -i "s|^CENTRAL_HTTPS_PORT=.*|CENTRAL_HTTPS_PORT=$HTTPS_PORT|" "$ENV_FILE"
  ok "$ENV_FILE updated (bind $BIND_ADDR, ports $HTTP_PORT/$HTTPS_PORT)"

  "${DC[@]}" up -d --force-recreate nginx >/dev/null 2>&1 \
    || die "could not recreate nginx - check: ${DC[*]} logs nginx"
  ok "nginx recreated with the new certificate and ports"
  sleep 3

  step "3/3  Verifying the new address"
  BASE_TLS="https://127.0.0.1:$HTTPS_PORT"
  code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "$BASE_TLS/api/health" || echo 000)"
  [ "$code" = "200" ] && ok "the server itself is healthy" \
                      || die "the server did not answer locally (got $code) - check ${DC[*]} logs"

  for _addr in $EXTRA_IPS; do
    code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 8 "https://$_addr:$HTTPS_PORT/api/health" || echo 000)"
    [ "$code" = "200" ] && ok "reachable at https://$_addr:$HTTPS_PORT" \
      || warn "NOT reachable at https://$_addr:$HTTPS_PORT (got $code) - check the host firewall"
  done

  if ! is_ipv4 "$HOSTNAME_FQDN"; then
    if [ -n "$(resolve_name "$HOSTNAME_FQDN" | head -1)" ]; then
      code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 8 "https://$HOSTNAME_FQDN:$HTTPS_PORT/api/health" || echo 000)"
      [ "$code" = "200" ] && ok "reachable by name at https://$HOSTNAME_FQDN:$HTTPS_PORT" \
        || warn "the name resolves but did not answer (got $code)"
    else
      warn "'$HOSTNAME_FQDN' does not resolve here yet - see the DNS options printed below"
    fi
  fi

  # The certificate now matches; the desktops still point at the OLD address.
  cat <<EOF

$(printf '%s' "$GRN")Address updated.$(printf '%s' "$RST")

  browser          https://$HOSTNAME_FQDN:$HTTPS_PORT
EOF
  for _n in $EXTRA_NAMES; do echo "                   https://$_n:$HTTPS_PORT"; done
  for _a in $EXTRA_IPS;   do echo "                   https://$_a:$HTTPS_PORT"; done
  cat <<EOF

  $(printf '%s' "$YEL")Each investigator desktop still points at the OLD address.$(printf '%s' "$RST")
  On every desktop, either re-run the installer:

      sudo ./deploy-edge.sh --central-url https://$HOSTNAME_FQDN:$HTTPS_PORT \
           --public-key ./central_public_key.pem

  or edit AGENT_CENTRAL_URL in the agent's agent.env and restart the agent service.
  The signing key did NOT change, so no key needs redistributing.

  If the name does not resolve on a desktop yet, use one of the IP addresses above -
  the certificate covers both, so nothing else has to change.

EOF
}

usage() {
  sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  cat <<'EOF'

Options
  --environment ENV   production | development   (required; asked if omitted)
  --nvidia-key FILE   DEVELOPMENT ONLY: file holding an NVIDIA API key for Arabic
                      formalization. Refused in production, which is local-only.
  --hostname FQDN     Name investigators will use in the browser (required)
  --ip ADDR           A static IP this server answers on. Repeatable. Added to the
                      certificate so the browser trusts it. Default: auto-detected.
  --extra-name NAME   Another DNS name for the same server (short name, alias).
                      Repeatable, also added to the certificate.
  --bind ADDR         Host interface to publish on (default: 0.0.0.0 = all of them)
  --reconfigure-address
                      Change the address of an ALREADY DEPLOYED server and nothing else.
                      Re-issues the certificate for the new name/IPs, republishes the
                      ports and re-checks DNS. Builds nothing, touches no data - the
                      last step when the machine reaches its final network.
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
    --environment)    ENVIRONMENT="${2:?}"; shift 2 ;;
    --production)     ENVIRONMENT="production"; shift ;;
    --development|--dev) ENVIRONMENT="development"; shift ;;
    --nvidia-key)     NVIDIA_KEY_SRC="${2:?}"; shift 2 ;;
    --hostname)       HOSTNAME_FQDN="${2:?}"; shift 2 ;;
    --ip)             EXTRA_IPS="$EXTRA_IPS ${2:?}"; shift 2 ;;
    --extra-name)     EXTRA_NAMES="$EXTRA_NAMES ${2:?}"; shift 2 ;;
    --bind)           BIND_ADDR="${2:?}"; shift 2 ;;
    --reconfigure-address) RECONFIGURE="true"; shift ;;
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
    --keep-test-db)   KEEP_TEST_DB="true"; KEEP_TEST_DB_SET=true; shift ;;
    -h|--help)        usage; exit 0 ;;
    *)                die "unknown option: $1  (try --help)" ;;
  esac
done

# --- which environment is this? ----------------------------------------------
# Asked before anything else because it decides what gets installed, whether a cloud
# AI may be contacted at all, and what the operator must do before issuing a محضر.
if [ -z "$ENVIRONMENT" ] && [ "$RECONFIGURE" = "true" ] && [ -f "$ENV_FILE" ]; then
  ENVIRONMENT="$(grep -E '^CENTRAL_ENVIRONMENT=' "$ENV_FILE" | tail -1 | cut -d= -f2 | tr -d '[:space:]')"
  [ -n "$ENVIRONMENT" ] && note "environment $ENVIRONMENT (from the existing $ENV_FILE)"
fi
if [ -z "$ENVIRONMENT" ]; then
  if [ -t 0 ]; then
    cat <<'ASK'

  Which environment is this machine?

    1) production    real cases. Local-only AI, approved Word template required,
                     no test database, no development dependencies.
    2) development   demos, training, integration. May use hosted AI with SYNTHETIC
                     data only, and ships a clearly-marked non-approved template.

ASK
    printf '  Enter 1 or 2: '
    read -r _answer
    case "${_answer:-}" in
      1|p|prod|production)  ENVIRONMENT="production" ;;
      2|d|dev|development)  ENVIRONMENT="development" ;;
      *) die "answer 1 or 2, or pass --environment production|development" ;;
    esac
  else
    die "--environment production|development is required (no terminal to ask on)"
  fi
fi
case "$ENVIRONMENT" in
  production|development) ;;
  *) die "--environment must be 'production' or 'development' (got: $ENVIRONMENT)" ;;
esac
IS_PROD=false; [ "$ENVIRONMENT" = "production" ] && IS_PROD=true

# Development defaults that would be wrong in production, applied only when not overridden.
if [ "$IS_PROD" = "false" ]; then
  [ "$KEEP_TEST_DB_SET" = "false" ] && KEEP_TEST_DB="true"
  if [ -z "$CERT_SRC" ] && [ -z "$KEY_SRC" ] && [ "$SELF_SIGNED" = "false" ]; then
    SELF_SIGNED="true"
    note "development: no certificate given, generating a self-signed one"
  fi
fi

[ -n "$HOSTNAME_FQDN" ] || { usage; die "--hostname is required"; }
if [ "$SELF_SIGNED" = "false" ] && { [ -z "$CERT_SRC" ] || [ -z "$KEY_SRC" ]; }; then
  die "give --cert and --key, or --self-signed for a LAN pilot"
fi
if [ "$IS_PROD" = "true" ]; then
  [ "$SELF_SIGNED" = "false" ] || warn "production with a SELF-SIGNED certificate - browsers will warn every investigator"
  [ -n "$NVIDIA_KEY_SRC" ] && die "--nvidia-key is refused in production: formalization runs locally or not at all"
  [ "$KEEP_TEST_DB" = "true" ] && warn "--keep-test-db in production - a test database on a live server is a needless target"
fi

printf '\n  %sEnvironment: %s%s\n' "$BLU" "$ENVIRONMENT" "$RST"

# --- settle the addresses before anything is generated ------------------------
DETECTED_IPS="$(detect_ips | tr '\n' ' ' || true)"
if [ -z "${EXTRA_IPS// /}" ]; then
  # Nothing declared: trust the machine's own addresses. This is what makes a static-IP
  # server work out of the box instead of only at localhost.
  EXTRA_IPS="$DETECTED_IPS"
  [ -n "${EXTRA_IPS// /}" ] && note "detected addresses: ${EXTRA_IPS# }  (override with --ip)"
fi
for _a in $EXTRA_IPS; do
  is_ipv4 "$_a" || die "--ip expects an IPv4 address, got: $_a  (use --extra-name for DNS names)"
done
for _n in $EXTRA_NAMES; do
  is_ipv4 "$_n" && die "--extra-name expects a DNS name, got an IP: $_n  (use --ip instead)"
done
# The hostname may itself be an IP - people do that on a LAN with no DNS at all.
if is_ipv4 "$HOSTNAME_FQDN"; then
  case " $EXTRA_IPS " in *" $HOSTNAME_FQDN "*) ;; *) EXTRA_IPS="$EXTRA_IPS $HOSTNAME_FQDN" ;; esac
  note "--hostname is an IP address; the certificate will be issued for it directly"
fi

if [ "$RECONFIGURE" = "true" ]; then
  # Exactly the invocation the normal deployment uses, so this acts on the SAME
  # containers and resolves the same relative volume paths.
  DC=(docker compose --env-file "$ENV_FILE" -f "$REPO_ROOT/docker-compose.yml")
  reconfigure_address
  exit 0
fi

roadmap "What is about to happen (8 steps, about 10-25 minutes in total)" \
  "1. Preflight        check Docker, disk and ports          seconds" \
  "2. Secrets          generate passwords and signing keys   seconds  (once, never again)" \
  "3. TLS              install the HTTPS certificate         seconds" \
  "4. Images           build or load the containers          5-20 min (the long one)" \
  "5. Start            database, migrations, then the app    1-2 min" \
  "6. Formalization    optional Arabic AI helper             seconds  (detect only)" \
  "7. Verify           prove it actually works               seconds" \
  "8. Done             passwords, backups, what to do first  -" \
  "" \
  "Nothing is written to disk until step 2. Every step is safe to re-run: secrets are" \
  "never regenerated, and an existing deployment keeps working." 

# =============================================================================
explain \
  "Check that this machine can actually run the server: Docker and its compose plugin, openssl, and the two network ports investigators will connect to." \
  "Every later step assumes all of this. Finding a missing dependency now costs seconds; finding it while the database is starting costs an hour of confused digging AND leaves a half-created deployment to clean up by hand. This step deliberately writes nothing to disk." \
  "A few seconds." \
  "Every line says [ ok ], and the environment banner above matches what you intended to install." \
  "Install Docker, free disk space, or stop whatever already holds the ports. Nothing has been written yet, so just run the script again - re-running is always safe."

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

step "1/8  Preflight"
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
  "Generate the database password, the session secret and the first administrator password, and write them once into a private file (.env, mode 0600). Also create the storage and secrets folders." \
  "These are generated ONCE and never regenerated, because they are identity rather than configuration. The ES256 signing key created on first start is how every investigator desktop knows a job really came from THIS server; regenerate it and every desktop rejects every job until it is redeployed. That is why a re-run keeps the existing file instead of making a fresh one." \
  "About a second." \
  "On a first run: secrets generated. On any later run: existing .env kept, plus a timestamped backup copy beside it." \
  "If .env exists but cannot be read, fix its permissions. NEVER delete it to start clean - that invalidates every desktop already deployed, and the old signing key cannot be recovered."

step "2/8  Secrets and configuration"
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

CENTRAL_ENVIRONMENT=$ENVIRONMENT
CENTRAL_DEBUG=$([ "$IS_PROD" = "true" ] && echo false || echo false)
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
# Which host interface nginx is published on. 0.0.0.0 answers on every address this
# machine has - including its static IP. Change it only to deliberately narrow that.
CENTRAL_BIND_ADDRESS=$BIND_ADDR

# Arabic formalization for the محضر (optional everywhere).
#   production  : LOCAL ONLY. The runtime below is contacted; no cloud call is ever
#                 made, whatever this file says. Leave the model names alone unless
#                 the approved profile changed after benchmarking.
#   development : may additionally use the hosted NVIDIA catalogue when
#                 secrets/nvidia_api_key exists - SYNTHETIC DATA ONLY.
CENTRAL_LLM_RUNTIME_MODE=$([ "$IS_PROD" = "true" ] && echo local || echo auto)
CENTRAL_OLLAMA_BASE_URL=http://host.docker.internal:11434
CENTRAL_REPORT_FUSHA_ENABLED=true

# Never ship dev dependencies (pytest and friends) in a production image.
INSTALL_DEV=$([ "$IS_PROD" = "true" ] && echo false || echo true)
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
  "Install the HTTPS certificate and its private key, after checking that both are valid PEM files and that they are genuinely a matching pair." \
  "Interview audio, identity documents and issued reports all cross this connection; without TLS they travel readable by anyone on the network, and the desktops refuse to trust a server they cannot verify. The matching-pair check exists because a mismatched key produces a server that starts happily and then refuses every browser - a failure that is very hard to diagnose from the logs." \
  "A few seconds." \
  "certificate installed. With --self-signed you also get a warning: expected for a LAN pilot, wrong for production, where every investigator would see a browser alarm." \
  "Check that --cert and --key point at real files and belong together. Re-running with corrected paths is safe."

step "3/8  TLS certificate"
# =============================================================================
issue_certificate

# --- can anyone actually REACH this name? ------------------------------------
# A certificate for central.unit.local is useless if no desktop can resolve that name.
# Checked here, while it is still cheap to fix, and answered with the three real options
# rather than a bare warning.
if ! is_ipv4 "$HOSTNAME_FQDN"; then
  resolved="$(resolve_name "$HOSTNAME_FQDN" | tr '\n' ' ' || true)"
  if [ -z "${resolved// /}" ]; then
    warn "'$HOSTNAME_FQDN' does not resolve on this machine yet."
    dns_todo=true
  else
    matched=false
    for _r in $resolved; do
      for _a in $EXTRA_IPS 127.0.0.1; do [ "$_r" = "$_a" ] && matched=true; done
    done
    if [ "$matched" = "true" ]; then
      ok "'$HOSTNAME_FQDN' resolves here to ${resolved% }"
      dns_todo=false
    else
      warn "'$HOSTNAME_FQDN' resolves to ${resolved% } - which is NOT an address of this machine."
      warn "  Investigators would be sent somewhere else entirely."
      dns_todo=true
    fi
  fi

  if [ "${dns_todo:-false}" = "true" ]; then
    primary_ip="$(printf '%s' "$EXTRA_IPS" | awk '{print $1}')"
    : "${primary_ip:=<this-server-ip>}"
    cat <<DNSHELP

  ${DIM}Three ways to make '$HOSTNAME_FQDN' work. Pick ONE:${RST}

  ${DIM}A. Your organisation's DNS server  (best - do this once, every machine benefits)${RST}
     Ask whoever runs DNS for an A record:
         $HOSTNAME_FQDN.  IN  A  $primary_ip
     Nothing to change on the desktops afterwards.

  ${DIM}B. The hosts file on each desktop  (no DNS server needed, but per-machine)${RST}
     Linux / macOS   sudo sh -c 'echo "$primary_ip  $HOSTNAME_FQDN" >> /etc/hosts'
     Windows         run Notepad as administrator, open
                     C:\\Windows\\System32\\drivers\\etc\\hosts
                     and add this line:
                     $primary_ip  $HOSTNAME_FQDN

  ${DIM}C. Skip DNS and use the IP  (works immediately, no setup)${RST}
     Deploy with the IP as the hostname, and everyone types the address:
         --hostname $primary_ip
     The certificate already covers it, so there is no extra browser warning.

  ${DIM}You can continue now and fix DNS later - only the name is affected, not the${RST}
  ${DIM}server. Every address in the certificate keeps working meanwhile.${RST}

DNSHELP
  fi
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
  "Build the application images - database, backend, Arabic web interface and the web server in front of them - or load prebuilt ones from a tar file for a site with no internet." \
  "This is the long step, and it is done here so everything afterwards is fast and repeatable: the stack then starts from identical bytes every time, and the very same images can be carried into an air-gapped site on a disk. A production build deliberately excludes the test dependencies, so the server ships nothing it does not need." \
  "5-20 minutes on a first build; seconds if the images already exist or you passed --skip-build. Long silences are normal - it is downloading packages, not stuck." \
  "images built (or images loaded). A lot of scrolling output here is the build itself, not errors." \
  "Almost always disk space or the network (a package mirror or proxy). Check df -h, fix it, and re-run: Docker resumes from its cache rather than starting over."

step "4/8  Images"
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
  "Start PostgreSQL and wait until it truly accepts connections, bring up the backend, the Arabic interface and nginx, and update the database structure to match this version of the code." \
  "The order is the whole point: the schema is created and upgraded BEFORE the application serves anything, because a backend running against a mismatched schema would quietly write wrong data instead of failing loudly. On an upgrade, a migration that finds data it cannot safely convert STOPS rather than guessing - that refusal protects existing case data, and this script prints what it means in plain words." \
  "1-2 minutes, most of it waiting for postgres to finish its own startup." \
  "postgres, backend, frontend and nginx started, the schema revision printed, and no [REFUSED] block." \
  "Read docker compose logs backend; a refused migration is named there. If you see [REFUSED], the message names the exact data problem - it is a question only your unit can answer. Never delete the database volume to make it start: on a server with real cases that destroys the evidence."

step "5/8  Starting the stack"
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
  "Set up the OPTIONAL helper that suggests Modern Standard Arabic wording for the محضر - in the way this environment allows, and no other." \
  "The report workflow is COMPLETE without any AI: the investigator writes the wording by hand and issues the document normally. The one thing that must never happen is real investigation text leaving the building, so a production server only ever talks to a model on its own network - and that is enforced in the application code, not by this script. This step only DETECTS what is present; it never installs or downloads a model, because a production machine must not fetch software at deploy time." \
  "A few seconds - it only looks." \
  "Either a named runtime with its provisioned models, or unavailable with a plain reason. Both are correct, expected outcomes." \
  "Nothing here can block or fail the deployment. If formalization is unavailable, the composer shows a short note and the operator types the wording."

step "6/8  Arabic formalization (optional AI)"
# =============================================================================
if [ "$IS_PROD" = "true" ]; then
  note "production: LOCAL ONLY. No cloud provider can be reached from here - the code"
  note "refuses to construct one when CENTRAL_ENVIRONMENT=production."

  if [ -f "$REPO_ROOT/secrets/nvidia_api_key" ]; then
    warn "secrets/nvidia_api_key exists on a PRODUCTION server."
    warn "  It is ignored - no cloud call is possible here - but it should not be on this"
    warn "  machine at all. Delete it, and rotate the key if it was ever used elsewhere."
  else
    ok "no cloud API key present (correct for production)"
  fi

  # Is a local runtime actually there? Reported, never installed by this script:
  # production must not download models, and an operator provisions them deliberately.
  OLLAMA_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
  if curl -s --max-time 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
    models="$(curl -s --max-time 5 "$OLLAMA_URL/api/tags" \
      | tr ',' '\n' | sed -n 's/.*"name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
      | paste -sd, - | sed 's/,/, /g')"
    if [ -n "$models" ]; then
      ok "local model runtime reachable at $OLLAMA_URL"
      note "provisioned models: $models"
      note "the server picks the strongest APPROVED profile whose model is installed;"
      note "adjust the approved names under 'محضر التحقيق' in إعدادات النظام after benchmarking."
    else
      warn "a runtime answers at $OLLAMA_URL but NO model is installed."
      warn "  Provision one on this machine (for example: ollama pull qwen3:8b), then restart the backend."
      warn "  Until then the composer shows: خدمة اقتراح الصياغة غير متوفرة على هذا الجهاز."
    fi
  else
    warn "no local model runtime at $OLLAMA_URL - Arabic formalization will be unavailable."
    warn "  This is a supported state: the محضر is still written, reviewed and issued by hand."
    warn "  To enable it later: install Ollama on this host, pull an approved model, restart the backend."
  fi
else
  note "development: the hosted NVIDIA catalogue may be used for formalization."
  warn "SYNTHETIC OR ANONYMISED TEXT ONLY. Never send real investigation content to a"
  warn "  hosted provider from a development machine."

  if [ -n "$NVIDIA_KEY_SRC" ]; then
    [ -f "$NVIDIA_KEY_SRC" ] || die "--nvidia-key: no such file: $NVIDIA_KEY_SRC"
    install -m 0600 "$NVIDIA_KEY_SRC" "$REPO_ROOT/secrets/nvidia_api_key"
    ok "API key installed at secrets/nvidia_api_key (0600, gitignored)"
  elif [ -f "$REPO_ROOT/secrets/nvidia_api_key" ]; then
    chmod 0600 "$REPO_ROOT/secrets/nvidia_api_key" 2>/dev/null || true
    ok "existing secrets/nvidia_api_key kept"
  else
    note "no key provided - formalization will report itself unavailable, which is fine."
    note "To add one later:  install -m 0600 /path/to/key $REPO_ROOT/secrets/nvidia_api_key"
    note "then restart the backend. The key is NEVER stored in the database or logged."
  fi
fi

# =============================================================================
explain \
  "Prove the server really works: answer over HTTPS, serve the Arabic interface, export the public key the desktops need, and report whether the schema, the staff profiles and the report template are ready for real use." \
  "A container that is running is not the same as a server that works, and this step checks what a user would actually notice. It also writes deploy/central_public_key.pem - without that file you cannot install a single desktop. Finally it surfaces the states that stay invisible in the interface until someone hits them: staff accounts that cannot yet be identified as speakers, and a report template that is not the approved one." \
  "A few seconds." \
  "API reachable over HTTPS, Arabic RTL frontend is being served, public key exported - plus notes about anything that needs attention before go-live." \
  "A failure means the stack started but is not usable: do NOT deploy desktops yet. The message names the failing check."

step "7/8  Verifying the deployment"
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

# --- does it answer on every address people will actually use? ----------------
# 127.0.0.1 working proves the stack is up; it proves nothing about the static IP an
# investigator will type. Each declared address is tried for real.
for _addr in $EXTRA_IPS; do
  code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 8 "https://$_addr:$HTTPS_PORT/api/health" || echo 000)"
  if [ "$code" = "200" ]; then
    ok "reachable at https://$_addr:$HTTPS_PORT"
  else
    warn "NOT reachable at https://$_addr:$HTTPS_PORT (got $code)"
    warn "  Check the host firewall, and that CENTRAL_BIND_ADDRESS ($BIND_ADDR) covers this address."
  fi
done
if ! is_ipv4 "$HOSTNAME_FQDN" && [ -n "$(resolve_name "$HOSTNAME_FQDN")" ]; then
  code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 8 "https://$HOSTNAME_FQDN:$HTTPS_PORT/api/health" || echo 000)"
  [ "$code" = "200" ] \
    && ok "reachable by name at https://$HOSTNAME_FQDN:$HTTPS_PORT" \
    || warn "the name resolves but did not answer (got $code)"
fi

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
# الجهاز + الرقم العسكري are what record a user's service details. Accounts created before
# they became mandatory - the bootstrap administrator above is always one - have neither,
# so they cannot be bound to a speaker or carry a voice print. This is not a failure: the
# system works, and completing the profile fixes it. But it is invisible from the interface
# until someone tries, so it is stated here.
incomplete="$("${DC[@]}" exec -T postgres psql -U stt -d military_stt -tAc \
  "SELECT string_agg(full_name, ', ') FROM investigator_profiles
    WHERE COALESCE(NULLIF(btrim(military_id), ''), NULL) IS NULL
       OR security_branch IS NULL" 2>/dev/null | tr -d '\r' | head -1 || true)"
if [ -n "${incomplete// /}" ]; then
  warn "these accounts have incomplete service details:"
  warn "    $incomplete"
  warn "  Fix in إدارة المستخدمين: set الجهاز and الرقم العسكري. Until then they appear"
  warn "  in the speaker picker DISABLED, and no voice print can be filed against them."
else
  ok "every staff account can be identified (الجهاز + الرقم العسكري present)"
fi

# --- the محضر: can this server actually issue one? --------------------------
# Reported here because both answers are legitimate but they mean different things, and
# the difference is invisible until an investigator presses إنشاء المحضر النهائي.
tpl="$(curl -sk --max-time 10 "$BASE_TLS/api/report-templates" -H 'Accept: application/json' 2>/dev/null || true)"
if printf '%s' "$tpl" | grep -q '"production_ready":true'; then
  ok "an APPROVED report template is active - official محاضر can be issued"
elif printf '%s' "$tpl" | grep -q '"is_development":true'; then
  if [ "$IS_PROD" = "true" ]; then
    warn "the active report template is the DEVELOPMENT stand-in."
    warn "  Finalization is REFUSED in production until the approved Word file is uploaded:"
    warn "    القالب الرسمي للمحضر -> رفع قالب بديل -> تفعيل"
    warn "  Drafting works meanwhile; only issuing the final document is blocked."
  else
    ok "development report template active (نموذج غير معتمد) - fine for this environment"
  fi
else
  note "report template state could not be read here (it needs an administrator session)."
  note "  Check it in the interface: القالب الرسمي للمحضر"
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
  "Print everything you must keep or do next: the address, the administrator password, what to back up, and an ordered first-run checklist." \
  "The administrator password is shown ONCE, here, and cannot be recovered afterwards. The secrets folder cannot be recreated either - losing it invalidates every desktop you have deployed. The checklist is ordered deliberately: each item unblocks the next, and skipping the profile step leaves accounts that silently cannot be voice-identified." \
  "-" \
  "A summary block with the URL and the checklist. Copy the password into your password manager BEFORE closing this window." \
  "If the password is lost it can be reset, but only from this machine with database access."

step "8/8  Done"
# =============================================================================
cat <<EOF

$(printf '%s' "$GRN")Central server deployed.$(printf '%s' "$RST")  ($ENVIRONMENT)

  URL              https://$HOSTNAME_FQDN:$HTTPS_PORT
  administrator    $ADMIN_USER
EOF
if [ -n "${EXTRA_IPS// /}" ] || [ -n "${EXTRA_NAMES// /}" ]; then
  echo "  also reachable at"
  for _n in $EXTRA_NAMES; do echo "                   https://$_n:$HTTPS_PORT"; done
  for _a in $EXTRA_IPS;   do echo "                   https://$_a:$HTTPS_PORT"; done
  echo "                   (all of these are in the certificate, so no extra browser warning)"
fi
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

  Use whichever address that desktop can actually reach. If the name is not in DNS yet,
  use an IP from the list above - the certificate covers both, so nothing else changes.

FIRST-RUN CHECKLIST (in this order)

  1. Sign in as $ADMIN_USER and change the password when prompted.
  2. إدارة المستخدمين -> edit the administrator and fill in الجهاز and الرقم العسكري.
     These two record the account's service details. Until they are
     set the account cannot be bound to a speaker and cannot carry a voice print - it will
     appear in the speaker picker DISABLED. Every user created from now on is required to
     supply them, so this applies only to the bootstrap account.
  3. Create the investigator accounts. الجهاز آخر is refused on purpose: it is a catch-all,
     not a namespace, and two "other" forces sharing a serial would collapse into one
     identity and pool two people's voice prints.
  4. Deploy the desktops (below), then run one recording end to end before going live.
  5. القالب الرسمي للمحضر -> upload the approved Word file and press تفعيل.
$(if [ "$IS_PROD" = "true" ]; then cat <<'PROD'
     REQUIRED in production: the bundled template is marked نموذج غير معتمد and the
     server REFUSES to issue a final محضر on it. Everything else - drafting, editing
     the Q&A, the approximate preview - works before you do this.
PROD
else cat <<'DEV'
     Optional in development: the bundled نموذج غير معتمد template already works, so
     you can issue reports immediately for testing.
DEV
fi)
  6. Issue one محضر end to end and open it in the Word version your unit actually uses.
     Check RTL, the هامش column, pagination across many questions, and the signature
     block. A template renders correctly here and can still look wrong in Word.

$(if [ "$IS_PROD" = "true" ]; then cat <<'PROD'
PRODUCTION NOTES

  * Arabic formalization is LOCAL ONLY. No cloud provider can be contacted from this
    server - it is refused in code, not by configuration. If no approved local model is
    provisioned, the composer says so and the محضر is written by hand.
  * Do not place an NVIDIA (or any cloud) API key on this machine. It would be ignored,
    but it does not belong here.
  * Issued reports live in storage/reports and template versions in storage/report-templates.
    BOTH must be in your backup: an issued محضر is evidence, and the template version it
    cites must remain retrievable to verify it.
PROD
else cat <<'DEV'
DEVELOPMENT NOTES

  * This install may use the hosted NVIDIA catalogue for الصياغة بالفصحى, with SYNTHETIC
    OR ANONYMISED text only. Never paste real investigation content into it.
  * The image contains the test dependencies and a *_test database exists, so the backend
    test suite can be run here (one line, from the repository root):
      docker compose run --rm --no-deps -e SKIP_MIGRATIONS=true -v "$PWD/central/backend:/app" --entrypoint "" backend sh -c "cd /app && python -m pytest tests -q"
  * Never point a development install at real case data.
DEV
fi)

Back up before going live: $REPO_ROOT/secrets, $REPO_ROOT/storage, and a
pg_dump of the database. Losing secrets/ invalidates every processing token.
EOF
