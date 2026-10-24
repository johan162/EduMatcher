#!/usr/bin/env bash
# mkweb.sh - Upload the built web site in web_site/ via sftp.
#
# Uploads the generated site (root *.html, assets/, docs/, downloads/) into the
# login directory on the server. Build sources (src/, data/, build.py, ...) are
# not uploaded. Build the site first with `make web-site`.
#
# Environment variables (required):
#   TIRNEX_ADITUS_FTP_SITE  - sftp host
#   TIRNEX_ADITUS_FTP_USER  - user name
#   TIRNEX_ADITUS_FTP_PWD   - password
#
# Usage:
#   ./scripts/mkweb.sh

set -euo pipefail

: "${TIRNEX_ADITUS_FTP_SITE:?TIRNEX_ADITUS_FTP_SITE is not set}"
: "${TIRNEX_ADITUS_FTP_USER:?TIRNEX_ADITUS_FTP_USER is not set}"
: "${TIRNEX_ADITUS_FTP_PWD:?TIRNEX_ADITUS_FTP_PWD is not set}"

SITE_DIR="$(cd "$(dirname "$0")/.." && pwd)/web_site"
DIRS=(assets docs downloads)

for d in "${DIRS[@]}"; do
    if [[ ! -d "$SITE_DIR/$d" ]]; then
        echo "✗ $SITE_DIR/$d is missing - build the site first (make web-site)" >&2
        exit 1
    fi
done

command -v expect >/dev/null || { echo "✗ 'expect' is required" >&2; exit 1; }

BATCH="$(mktemp)"
trap 'rm -f "$BATCH"' EXIT

{
    echo "lcd \"$SITE_DIR\""
    echo "put *.html"
    for d in "${DIRS[@]}"; do
        echo "-mkdir $d"
        echo "put -r $d"
    done
} >"$BATCH"

echo "→ Uploading $SITE_DIR to $TIRNEX_ADITUS_FTP_USER@$TIRNEX_ADITUS_FTP_SITE"

# sftp reads passwords only from a terminal, so expect feeds it from the environment.
# BatchMode=no must come first: sftp -b otherwise forces BatchMode=yes (no password auth).
BATCH="$BATCH" expect <<'EOF'
set timeout 60
spawn sftp -oBatchMode=no -oStrictHostKeyChecking=accept-new -b $env(BATCH) $env(TIRNEX_ADITUS_FTP_USER)@$env(TIRNEX_ADITUS_FTP_SITE)
expect {
    -nocase "password:" { send -- "$env(TIRNEX_ADITUS_FTP_PWD)\r" }
    timeout { puts stderr "✗ Timed out waiting for password prompt"; exit 1 }
    eof
}
set timeout -1
catch {expect eof}
lassign [wait] pid spawnid os_error status
exit $status
EOF

echo "✓ Upload complete"
