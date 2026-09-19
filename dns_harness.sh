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


# --- can anyone actually REACH this name? ------------------------------------
# A certificate for central.unit.local is useless if no desktop can resolve that name.
# Checked here, while it is still cheap to fix, and answered with the three real options
# rather than a bare warning.
if ! is_ipv4 "$HOSTNAME_FQDN"; then
  resolved="$(resolve_name "$HOSTNAME_FQDN" | tr '\n' ' ')"
  if [ -z "${resolved// /}" ]; then
    warn "'$HOSTNAME_FQDN' does not resolve on this machine yet."
    dns_todo=true
  else
    matched=false
    for _r in $resolved; do
      for _a in $EXTRA_IPS 127.0.0.1; do [ "$_r" = "$_a" ] && matched=true; done
    done
    if [ "$matched" = "true" ]; then
      ok "'$HOSTNAME_FQDN' resolves here to:${resolved% }"
      dns_todo=false
    else
      warn "'$HOSTNAME_FQDN' resolves to${resolved% } - which is NOT an address of this machine."
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

