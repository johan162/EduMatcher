#!/usr/bin/env bash
# Install and start EduMatcher from prebuilt container images.
#
#   curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/deployment/curl/install.sh | bash
#
# With options (note the '-s --' so the shell passes them to the script):
#
#   curl -fsSL .../install.sh | bash -s -- --config s10-nominal
#   curl -fsSL .../install.sh | bash -s -- --version 0.20.5 --dir ~/exchange
#
# With --sim it installs the AI-trader simulation instead of the plain
# exchange: a market that trades itself, into ~/.edumatcher-sim.
#
#   curl -fsSL .../install.sh | bash -s -- --sim
#   curl -fsSL .../install.sh | bash -s -- --sim --speed 10 --start 2026-11-02T08:58
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
INSTALL_DIR="${INSTALL_DIR:-}"
VERSION=""
CONFIG=""
START=1
SIM=0
SPEED=""
SIM_START=""

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info() { echo -e "${BLUE}- $*${NC}"; }
ok()   { echo -e "${GREEN}✓ $*${NC}"; }
warn() { echo -e "${YELLOW}⚠ $*${NC}"; }
die()  { echo -e "${RED}✗ $*${NC}" >&2; exit 1; }

usage() {
    awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "$0"
    cat <<'USAGE'
Options:
  --sim             Install the AI-trader simulation instead of the exchange
  --version X.Y.Z   Release to install (default: the latest release)
    --config NAME     Bundled example to deploy (default: s10-basic)
  --config FILE     ...or a path to an engine_config.yaml of your own
                    (with --sim, only a file of your own)
  --speed N         --sim only: run the calendar N times faster than real time
  --start TS        --sim only: where an accelerated calendar starts,
                    e.g. 2026-11-02T08:58
  --dir PATH        Install location (default: ~/.edumatcher,
                    or ~/.edumatcher-sim with --sim)
  --no-start        Install the files but do not start anything
  --help            This text
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --version) VERSION="${2:-}"; shift 2 ;;
        --config)  CONFIG="${2:-}";  shift 2 ;;
        --dir)     INSTALL_DIR="${2:-}"; shift 2 ;;
        --sim)     SIM=1; shift ;;
        --speed)   SPEED="${2:-}"; shift 2 ;;
        --start)   SIM_START="${2:-}"; shift 2 ;;
        --no-start) START=0; shift ;;
        --help|-h) usage; exit 0 ;;
        *) die "Unknown option: $1  (try --help)" ;;
    esac
done

if [[ "$SIM" -eq 0 && ( -n "$SPEED" || -n "$SIM_START" ) ]]; then
    die "--speed and --start apply to the simulation only; add --sim."
fi
[[ -n "$INSTALL_DIR" ]] || INSTALL_DIR=$([[ "$SIM" -eq 1 ]] && echo "$HOME/.edumatcher-sim" || echo "$HOME/.edumatcher")

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
if [[ "$SIM" -eq 1 ]]; then
    ok "Installing the EduMatcher AI-trader simulation $VERSION"
else
    ok "Installing EduMatcher $VERSION"
fi

FETCH_REF="${REPO_REF:-$TAG}"
[[ -n "$REPO_REF" ]] && warn "Fetching support files from '${REPO_REF}', not from tag ${TAG}"
BASE_URL="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${FETCH_REF}/deployment/curl"

# --- Fetch ---------------------------------------------------------------
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"
info "Downloading into $INSTALL_DIR ..."
if [[ "$SIM" -eq 1 ]]; then
    FILES="compose.ai-sim.yaml edumatcher.sh .env.sim.example"
    ENV_TEMPLATE=.env.sim.example
else
    FILES="compose.yaml compose.zmq.yaml edumatcher.sh .env.example"
    ENV_TEMPLATE=.env.example
fi
for f in $FILES; do
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
    cp "$ENV_TEMPLATE" .env
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

if [[ "$SIM" -eq 1 ]]; then
    set_env EM_STACK sim
    [[ -n "$SPEED" ]]     && set_env EM_SPEED "$SPEED"
    [[ -n "$SIM_START" ]] && set_env EM_START "$SIM_START"
fi

if [[ -n "$CONFIG" ]]; then
    if [[ -f "$CONFIG" ]]; then
        cp "$CONFIG" config/engine_config.yaml
        set_env EM_CONFIG_FILE /config/engine_config.yaml
        ok "Will deploy your configuration: $CONFIG"
    elif [[ "$SIM" -eq 1 ]]; then
        die "--sim takes a path to an engine_config.yaml of your own, not an example name."
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
info "Pulling images and starting the exchange (this is the slow part; nothing is built locally)..."
./edumatcher.sh start

if [[ "$SIM" -eq 1 ]]; then
    cat <<EOF

To login to the Trading Workstation you need an API-key. The simulation have a pre-configured API-key 
that you can use for testing purposes.

The first five API keys and the Admin key are:

| Participant| Role         | API key               |
|------------|--------------|-----------------------|
| `TRADER01` | student desk | `key-trader01-rwlr0v` |
| `TRADER02` | student desk | `key-trader02-uzytnc` |
| `TRADER03` | student desk | `key-trader03-rwqo7n` |
| `TRADER04` | student desk | `key-trader04-3etdg0` |
| `TRADER05` | student desk | `key-trader05-k0c8fm` |
| `OPS01`    | (ADMIN)      | `key-ops01-3e34rs`    |


You can find the full list of API keys in the simulation configuration in the "Ten Minute Start" chapter in 
the "AI Traders and Market Simulation" book.

Everything lives in $INSTALL_DIR:
  ./edumatcher.sh status            what is running
  ./edumatcher.sh shell             a shell inside the simulation container
  ./edumatcher.sh shell pm-market-sim --status --id OPS01
  ./edumatcher.sh logs terminal-gui follow one service
  ./edumatcher.sh stop              stop everything, keep the data

The market keeps real trading hours (09:00-16:05 Stockholm time, weekdays).
To watch a day right now, run it on an accelerated clock:
  ./edumatcher.sh speed 10 2026-11-02T08:58 && ./edumatcher.sh restart
EOF
else
    cat <<EOF

Everything lives in $INSTALL_DIR:
  ./edumatcher.sh status            what is running
  ./edumatcher.sh logs terminal-gui follow one service
    ./edumatcher.sh config s10-nominal    switch example configuration
  ./edumatcher.sh config ./mine.yaml    ...or run one of your own
  ./edumatcher.sh stop              stop everything, keep the data
EOF
fi
