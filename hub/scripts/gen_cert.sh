#!/usr/bin/env bash
# Create a local TLS certificate for https://localhost:8443.
# Prefers mkcert (browser-trusted local CA); falls back to a self-signed OpenSSL certificate.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p certs
if command -v mkcert >/dev/null 2>&1; then
  mkcert -install
  mkcert -cert-file certs/cert.pem -key-file certs/key.pem localhost 127.0.0.1 ::1
else
  echo "mkcert not found; generating a self-signed certificate with OpenSSL (browser will warn)."
  openssl req -x509 -newkey rsa:2048 -sha256 -days 365 -nodes \
    -keyout certs/key.pem -out certs/cert.pem -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1"
fi
chmod 600 certs/key.pem
echo "Wrote certs/cert.pem and certs/key.pem"
