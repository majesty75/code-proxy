#!/usr/bin/env bash
# install-corp-ca.sh — wire a corporate root CA into every TLS surface
# the UTA stack touches on a fresh WSL2 Ubuntu box.
#
# Usage:
#     sudo ./scripts/install-corp-ca.sh /path/to/CompanyRoot.crt
#     sudo ./scripts/install-corp-ca.sh /path/to/CompanyRoot.cer    # auto DER→PEM
#
# What it does (idempotent):
#   1. Converts DER → PEM if needed.
#   2. Installs the cert into /usr/local/share/ca-certificates/.
#   3. Runs update-ca-certificates so apt/curl/git/wget trust it.
#   4. Appends pip / requests / Python env vars to ~/.bashrc.
#   5. Adds git http.sslCAInfo for the user.
#   6. Verifies pypi.org and github.com are reachable.
#
# Run as YOUR user (not root) but with sudo available; the script re-invokes
# sudo only for the apt-trust step.
set -euo pipefail

green()  { printf "\033[32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
red()    { printf "\033[31m%s\033[0m\n" "$*" 1>&2; }
step()   { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }

CERT_INPUT="${1:-}"
if [[ -z "${CERT_INPUT}" ]]; then
  red "usage: $0 /path/to/CompanyRoot.crt"
  exit 2
fi
if [[ ! -f "${CERT_INPUT}" ]]; then
  red "file not found: ${CERT_INPUT}"
  exit 2
fi

WORK_DIR="${HOME}/certs"
mkdir -p "${WORK_DIR}"
DEST_NAME="$(basename "${CERT_INPUT}")"
DEST_NAME="${DEST_NAME%.cer}.crt"   # force .crt extension
DEST="${WORK_DIR}/${DEST_NAME}"

step "Detecting cert format"
if openssl x509 -inform pem -in "${CERT_INPUT}" -noout >/dev/null 2>&1; then
  green "✓ PEM format"
  cp -f "${CERT_INPUT}" "${DEST}"
elif openssl x509 -inform der -in "${CERT_INPUT}" -noout >/dev/null 2>&1; then
  yellow "• DER format — converting to PEM"
  openssl x509 -inform der -in "${CERT_INPUT}" -out "${DEST}"
  green "✓ Converted → ${DEST}"
else
  red "Not a recognisable X.509 cert. Ask IT for a PEM/DER root."
  exit 1
fi

step "Adding to system trust store"
sudo cp -f "${DEST}" "/usr/local/share/ca-certificates/${DEST_NAME}"
sudo update-ca-certificates | tail -3
green "✓ apt / curl / git / wget will now trust it"

step "Appending env vars to ~/.bashrc"
MARKER="# --- UTA corp CA (managed by install-corp-ca.sh) ---"
if grep -qF "${MARKER}" "${HOME}/.bashrc" 2>/dev/null; then
  yellow "• ~/.bashrc already has the block, leaving it alone"
else
  cat >> "${HOME}/.bashrc" <<EOF

${MARKER}
export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
export PIP_CERT=/etc/ssl/certs/ca-certificates.crt
export NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
EOF
  green "✓ Env vars appended (open a new shell or 'source ~/.bashrc')"
fi

step "Configuring git"
git config --global http.sslCAInfo /etc/ssl/certs/ca-certificates.crt
green "✓ git http.sslCAInfo set globally"

step "Verifying"
ok=true
curl -sSfI -o /dev/null https://pypi.org           && green "  ✓ https://pypi.org"          || { red "  ✗ pypi.org";    ok=false; }
curl -sSfI -o /dev/null https://github.com         && green "  ✓ https://github.com"        || { red "  ✗ github.com";  ok=false; }
curl -sSfI -o /dev/null https://registry-1.docker.io/v2/ \
  && green "  ✓ https://registry-1.docker.io" \
  || yellow "  • registry-1.docker.io blocked from WSL — that's fine if Docker Desktop pulls work."

if ! $ok; then
  red "One or more endpoints still failing. Likely causes:"
  red "  - You also need a proxy: HTTP_PROXY / HTTPS_PROXY"
  red "  - The cert file is the leaf, not the root"
  red "  - There are intermediates that need concatenating into the same .crt"
  exit 1
fi

cat <<EOF

$(green "Done.") Your shell is configured. For Docker Desktop:

  1. Open Docker Desktop → Settings → Docker Engine
  2. If your registry is corporate, copy ${DEST} to:
       %USERPROFILE%\\.docker\\certs.d\\<registry-host>\\ca.crt
     (on Windows side; WSL doesn't push CA into Docker Desktop directly.)
  3. Restart Docker Desktop.

Test:
  docker pull hello-world
  python3 -c "import requests; print(requests.get('https://pypi.org').status_code)"
EOF
