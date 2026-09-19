DIM=''; RST=''; GRN=''; YEL=''; RED=''; BLU=''
ok()   { printf '  [ ok ] %s\n' "$*"; }
warn() { printf '  [warn] %s\n' "$*"; }
note() { printf '  %s\n' "$*"; }
die()  { printf '  [FAIL] %s\n' "$*"; exit 1; }
HOSTNAME_FQDN="$1"; EXTRA_IPS="$2"; EXTRA_NAMES="${3:-}"
# Every global IPv4 address of this machine, one per line.
detect_ips() {
  if command -v ip >/dev/null 2>&1; then
    ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1
  elif command -v hostname >/dev/null 2>&1; then
    hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+\.'
  fi | grep -vE '^(127\.|169\.254\.)' | sort -u
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
  ping -c1 -W1 "$_name" 2>/dev/null | sed -n 's/^PING [^(]*(\([0-9.]*\)).*/\1/p'
}


    san=""
    is_ipv4 "$HOSTNAME_FQDN" || san="DNS:$HOSTNAME_FQDN"
    for _n in $EXTRA_NAMES; do san="${san:+$san,}DNS:$_n"; done
    san="${san:+$san,}DNS:localhost"
    for _a in $EXTRA_IPS; do san="$san,IP:$_a"; done
    san="$san,IP:127.0.0.1"

    printf "SAN would be: %s\n" "$san"
