#!/usr/bin/env bash
# mkweb.sh - Upload the built web site in web_site/ via sftp.
#
# First removes the previously uploaded site from the server (root *.html and the
# directories assets/, docs/ and downloads/), then uploads the generated site
# (root *.html, assets/, docs/, downloads/) into the login directory. This way
# pages, chapters and old-version downloads that no longer exist locally do not
# linger on the server. Anything else in the login directory is left alone.
# Build sources (src/, data/, build.py, ...) are not uploaded. Build the site
# first with `make web-site`.
#
# Environment variables (required):
#   TIRNEX_ADITUS_FTP_SITE  - sftp host
#   TIRNEX_ADITUS_FTP_USER  - user name
#   TIRNEX_ADITUS_FTP_PWD   - password
#
# Usage:
#   ./scripts/mkweb.sh [--no-clean] [--dry-run]
#
# Options:
#   --no-clean   Upload only (overwrite files, do not remove anything first)
#   --dry-run    List what would be removed on the server; remove and upload nothing
#   -h, --help   Show this help

set -euo pipefail

CLEAN=true
DRY_RUN=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-clean) CLEAN=false ;;
        --dry-run)  DRY_RUN=true ;;
        -h|--help)  awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
        *) echo "✗ Unknown option: $1 (see --help)" >&2; exit 1 ;;
    esac
    shift
done

: "${TIRNEX_ADITUS_FTP_SITE:?TIRNEX_ADITUS_FTP_SITE is not set}"
: "${TIRNEX_ADITUS_FTP_USER:?TIRNEX_ADITUS_FTP_USER is not set}"
: "${TIRNEX_ADITUS_FTP_PWD:?TIRNEX_ADITUS_FTP_PWD is not set}"

SITE_DIR="${MKWEB_SITE_DIR:-$(cd "$(dirname "$0")/.." && pwd)/web_site}"
DIRS=(assets docs downloads)

for d in "${DIRS[@]}"; do
    if [[ ! -d "$SITE_DIR/$d" ]]; then
        echo "✗ $SITE_DIR/$d is missing - build the site first (make web-site)" >&2
        exit 1
    fi
done
# Never wipe the server for a site that cannot replace it.
for f in index.html docs/index.html; do
    if [[ ! -f "$SITE_DIR/$f" ]]; then
        echo "✗ $SITE_DIR/$f is missing - build the site first (make web-site)" >&2
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

# ---------------------------------------------------------------------------
# Step 1: clean the target site (one interactive sftp session)
# ---------------------------------------------------------------------------
# sftp has no recursive delete, so the session lists each directory with
# 'ls -l' and removes files and then (now empty) directories bottom-up. Only
# the root *.html files and the directories in MKWEB_DIRS are touched.
clean_remote() {
    echo "→ Cleaning $TIRNEX_ADITUS_FTP_USER@$TIRNEX_ADITUS_FTP_SITE (*.html ${DIRS[*]})"
    MKWEB_DIRS="${DIRS[*]}" MKWEB_DRY="$DRY_RUN" expect <<'EOF'
set timeout 120
set dry $env(MKWEB_DRY)
set managed $env(MKWEB_DIRS)
set removed 0
set failed 0
log_user 0

spawn sftp -oBatchMode=no -oStrictHostKeyChecking=accept-new $env(TIRNEX_ADITUS_FTP_USER)@$env(TIRNEX_ADITUS_FTP_SITE)
expect {
    -nocase "password:" { send -- "$env(TIRNEX_ADITUS_FTP_PWD)\r" }
    timeout { puts stderr "✗ Timed out waiting for password prompt"; exit 1 }
    eof { puts stderr "✗ sftp exited before login"; exit 1 }
}
expect {
    "sftp> " {}
    -nocase "permission denied" { puts stderr "✗ Login failed"; exit 1 }
    timeout { puts stderr "✗ Timed out waiting for the sftp prompt"; exit 1 }
    eof { puts stderr "✗ sftp exited after login"; exit 1 }
}

# Run one sftp command and return what it printed (minus the echoed command).
proc cmd {c} {
    send -- "$c\r"
    expect {
        -re "(.*)sftp> " { return $expect_out(1,string) }
        timeout { puts stderr "✗ Timed out running: $c"; exit 1 }
        eof { puts stderr "✗ sftp ended while running: $c"; exit 1 }
    }
}

# 'ls -l' of one directory as a list of {type name}; the name is everything
# after the eighth column so that names with spaces survive.
proc ls_long {path} {
    set out [cmd "ls -l \"$path\""]
    set res {}
    foreach line [split $out "\n"] {
        set line [string trimright $line "\r"]
        if {[regexp {^([d\-l])[rwxsStT\-]{9}\s+\d+\s+\S+\s+\S+\s+\d+\s+\S+\s+\d+\s+\S+\s+(.+)$} $line -> t name]} {
            lappend res [list $t $name]
        }
    }
    return $res
}

proc remove {kind path} {
    global dry removed failed
    if {$dry} {
        puts "  would remove $path"
        incr removed
        return
    }
    set out [cmd "$kind \"$path\""]
    if {[regexp -nocase {couldn't|failure|permission denied|no such file} $out]} {
        puts stderr "  ✗ could not remove $path: [string trim $out]"
        incr failed
    } else {
        incr removed
    }
}

proc rm_tree {path} {
    foreach e [ls_long $path] {
        lassign $e t name
        if {$t eq "d"} {
            rm_tree "$path/$name"
            remove rmdir "$path/$name"
        } else {
            remove rm "$path/$name"
        }
    }
}

foreach e [ls_long "."] {
    lassign $e t name
    if {$t eq "d"} {
        if {[lsearch -exact $managed $name] >= 0} {
            rm_tree $name
            remove rmdir $name
        }
    } elseif {[string match "*.html" $name]} {
        remove rm $name
    }
}

send -- "bye\r"
catch {expect eof}
if {$failed > 0} {
    puts stderr "✗ $failed item(s) could not be removed"
    exit 1
}
if {$dry} {
    puts "✓ Dry run: $removed item(s) would be removed"
} else {
    puts "✓ Removed $removed item(s) from the server"
}
exit 0
EOF
}

if [[ "$CLEAN" == "true" || "$DRY_RUN" == "true" ]]; then
    clean_remote
fi

if [[ "$DRY_RUN" == "true" ]]; then
    echo "✓ Dry run complete - nothing removed, nothing uploaded"
    exit 0
fi

# ---------------------------------------------------------------------------
# Step 2: upload
# ---------------------------------------------------------------------------
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
