#!/usr/bin/env bash
# Install and start EduMatcher from prebuilt container images.
#
#   curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/deployment/curl/install.sh | bash
#
# With options (note the '-s --' so the shell passes them to the script):
#
#   curl -fsSL .../install.sh | bash -s -- --config ten-nominal
#   curl -fsSL .../install.sh | bash -s -- --version 0.20.5 --dir ~/exchange
#
# Needs podman or docker, and nothing else — no Python, no Node, no checkout.
# Everything lands in one directory you can inspect, move or delete.

set -euo pipefail

REPO_OWNER="${REPO_OWNER:-johan162}"
REPO_NAME="${REPO_NAME:-EduMatcher}"
# Branch or tag to fetch compose.yaml and edumatcher.sh from. Defaults to the
# release tag being installed, so the files and the images always come from the
# same commit. Override to test this installer before a release carries it:
#   REPO_REF=main curl -fsSL .../install.sh | bash -s -- --version 0.20.5
REPO_REF="${REPO_REF:-}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.edumatcher}"
VERSION=""
CONFIG=""
START=1

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info() { echo -e "${BLUE}- $*${NC}"; }
ok()   { echo -e "${GREEN}✓ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; }
die()  { echo -e "${RED}✗ $*${NC}" >&2; exit 1; }

usage() {
    awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"
    cat <<'USAGE'
Options:
  --version X.Y.Z   Release to install (default: the latest release)
  --config NAME     Bundled example to deploy (default: three-basic)
  --config FILE     ...or a path to an engine_config.yaml of your own
  --dir PATH        Install location (default: ~/.edumatcher)
  --no-start        Install the files but do not start anything
  --help            This text
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version) VERSION="${2:-}"; shift 2 ;;
        --config)  CONFIG="${2:-}";  shift 2 ;;
        --dir)     INSTALL_DIR="${2:-}"; shift 2 ;;
        --no-start) START=0; shift ;;
        --help|-h) usage; exit 0 ;;
        *) die "Unknown option: $1  (try --help)" ;;
    esac
done

# --- Preflight -------------------------------------------------------------
command -v curl >/dev/null 2>&1 || die "curl is required but not installed."

if command -v podman >/dev/null 2>&1; then
    ENGINE=podman
elif command -v docker >/dev/null 2>&1; then
    ENGINE=docker
else
    die "Neither podman nor docker is installed. Install one, then re-run this."
fi
ok "Container engine: $ENGINE"

# --- Which release? --------------------------------------------------------
# The compose file and control script are fetched at the tag whose images we
# are about to pull, so the two can never describe different systems.
if [[ -z "$VERSION" ]]; then
    info "Resolving the latest release..."
    TAG=$(curl -fsSL "https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/releases/latest" \
          | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1)
    [[ -n "$TAG" ]] || die "Could not determine the latest release. Pass --version X.Y.Z."
    VERSION="${TAG#v}"
else
    TAG="v${VERSION#v}"
    VERSION="${TAG#v}"
fi
ok "Installing EduMatcher $VERSION"

FETCH_REF="${REPO_REF:-$TAG}"
[[ -n "$REPO_REF" ]] && warn "Fetching support files from '${REPO_REF}', not from tag ${TAG}"
BASE_URL="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${FETCH_REF}/deployment/curl"

# --- Fetch ---------------------------------------------------------------
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"
info "Downloading into $INSTALL_DIR ..."
for f in compose.yaml edumatcher.sh .env.example; do
    curl -fsSL "${BASE_URL}/${f}" -o "$f" \
        || die "Could not download ${f} from ${BASE_URL} — does ${FETCH_REF} exist?"
done
chmod +x edumatcher.sh
mkdir -p data config

# --- Configure -------------------------------------------------------------
# An existing .env is the user's; keep it and only re-pin the version.
if [[ -f .env ]]; then
    info "Keeping your existing .env"
else
    cp .env.example .env
fi

set_env() {
    local key="$1" value="${2:-}"
    if grep -qE "^${key}=" .env; then
        sed -i.bak -E "s|^${key}=.*|${key}=${value}|" .env && rm -f .env.bak
    else
        printf '%s=%s\n' "$key" "$value" >> .env
    fi
}
set_env EM_VERSION "$VERSION"
set_env GHCR_OWNER "$REPO_OWNER"

if [[ -n "$CONFIG" ]]; then
    if [[ -f "$CONFIG" ]]; then
        cp "$CONFIG" config/engine_config.yaml
        set_env EM_CONFIG_FILE /config/engine_config.yaml
        ok "Will deploy your configuration: $CONFIG"
    else
        set_env EM_CONFIG "$CONFIG"
        set_env EM_CONFIG_FILE ""
        ok "Will deploy bundled example: $CONFIG"
    fi
fi

ok "Installed in $INSTALL_DIR"

if [[ "$START" -eq 0 ]]; then
    echo
    echo "Not starting (--no-start). When you are ready:"
    echo "  cd $INSTALL_DIR && ./edumatcher.sh start"
    exit 0
fi

# --- Start -----------------------------------------------------------------
echo
info "Pulling images (this is the slow part; nothing is built locally)..."
./edumatcher.sh start

cat <<EOF

Everything lives in $INSTALL_DIR:
  ./edumatcher.sh status            what is running
  ./edumatcher.sh logs terminal-gui follow one service
  ./edumatcher.sh config ten-nominal    switch example configuration
  ./edumatcher.sh config ./mine.yaml    ...or run one of your own
  ./edumatcher.sh stop              stop everything, keep the data
EOF
