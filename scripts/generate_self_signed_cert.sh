#!/bin/sh
# Generates a self-signed TLS certificate for LAN pilots (replace with an
# organisation-issued certificate in production).
set -eu
DIR="$(cd "$(dirname "$0")/.." && pwd)/central/nginx/certs"
mkdir -p "$DIR"
if [ -f "$DIR/cert.pem" ] && [ -f "$DIR/key.pem" ]; then
  echo "certificate already present in $DIR"; exit 0
fi
HOST="${1:-localhost}"
openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
  -keyout "$DIR/key.pem" -out "$DIR/cert.pem" \
  -subj "/CN=$HOST/O=Military STT AI" \
  -addext "subjectAltName=DNS:$HOST,DNS:localhost,IP:127.0.0.1"
echo "self-signed certificate written to $DIR"
