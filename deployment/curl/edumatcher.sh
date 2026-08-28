#!/usr/bin/env bash
# EduMatcher control script — installed alongside compose.yaml and .env.
#
#   ./edumatcher.sh start | stop | restart | status | logs [service]
#   ./edumatcher.sh urls
#   ./edumatcher.sh config <example-name | path/to/engine_config.yaml>
#   ./edumatcher.sh update [version]
#   ./edumatcher.sh uninstall [--data]
#
# Everything runs from this directory; there is nothing installed elsewhere.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}- $*${NC}"; }
ok()    { echo -e "${GREEN}✓ $*${NC}"; }
warn()  { echo -e "${YELLOW}⚠ $*${NC}"; }
die()   { echo -e "${RED}✗ $*${NC}" >&2; exit 1; }

# --- Container engine ------------------------------------------------------
# Podman is preferred when both are installed, matching the repository's own
# tooling. Override with EM_ENGINE=docker.
detect_engine() {
    ENGINE="${EM_ENGINE:-}"
    if [[ -z "$ENGINE" ]]; then
        if command -v podman >/dev/null 2>&1; then ENGINE=podman
        elif command -v docker >/dev/null 2>&1; then ENGINE=docker
        else die "Neither podman nor docker is installed."; fi
    fi
    if [[ "$ENGINE" == "podman" ]]; then
        if command -v podman-compose >/dev/null 2>&1; then COMPOSE="podman-compose"
        elif podman compose version >/dev/null 2>&1; then COMPOSE="podman compose"
        else die "podman is installed but has no compose support (install podman-compose)."; fi
    else
        if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"
        elif command -v docker-compose >/dev/null 2>&1; then COMPOSE="docker-compose"
        else die "docker is installed but has no compose support."; fi
    fi
}

# Reads the deployed configuration and prints "<port> <api_key>" for the first
# read-only credential (gateway_id: null). terminal-gui's history endpoints
# need it; it is generated per configuration, so it cannot be a fixed default.
READONLY_CREDENTIAL_PY='
import json
try:
    cfg = json.load(open("/data/ref_data/engine_config.json"))
except OSError:
    raise SystemExit(1)
for name, gw in sorted((cfg.get("api_gateways") or {}).items()):
    if not gw.get("enabled", True):
        continue
    for cred in gw.get("credentials") or []:
        if cred.get("gateway_id") is None:
            print(gw.get("port", 8080), cred["api_key"])
            raise SystemExit(0)
raise SystemExit(1)
'

cmd_start() {
    detect_engine
    mkdir -p data config
    info "Engine: $ENGINE ($COMPOSE)"

    # Two phases, deliberately: the read-only API key does not exist until the
    # exchange has deployed its configuration, so the backend has to be up
    # before the GUIs can be given their environment.
    $COMPOSE up -d edumatcher
    printf -- "- waiting for the exchange to deploy its configuration"
    for _ in $(seq 1 60); do
        if $ENGINE exec edumatcher test -f /data/ref_data/engine_config.json >/dev/null 2>&1; then
            break
        fi
        printf "."; sleep 1
    done
    echo

    cred=$($ENGINE exec edumatcher python3 -c "$READONLY_CREDENTIAL_PY" 2>/dev/null || true)
    if [[ -n "$cred" ]]; then
        set -- $cred
        export API_GATEWAY_URL="http://edumatcher:$1"
        export PM_TERMINAL_API_KEY="$2"
        ok "Read-only API key resolved from the deployed configuration (port $1)"
    else
        warn "No read-only credential (gateway_id: null) in the deployed configuration."
        warn "The live market-data feed will work; history panels will not."
    fi

    $COMPOSE up -d
    echo
    cmd_urls
}

cmd_stop() {
    detect_engine
    $COMPOSE down
    ok "Stopped. Your data in ./data is untouched."
}

cmd_restart() { cmd_stop; cmd_start; }

cmd_status() {
    detect_engine
    $COMPOSE ps
    echo
    info "Exchange process table:"
    $ENGINE exec edumatcher pm-opctl-cli list --no-restart 2>/dev/null \
        || warn "The exchange container is not running."
}

cmd_logs() {
    detect_engine
    if [[ $# -gt 0 ]]; then $COMPOSE logs -f "$1"; else $COMPOSE logs -f; fi
}

cmd_urls() {
    # shellcheck disable=SC1091
    [[ -f .env ]] && source .env
    echo "Open:"
    echo "  Trading terminal   http://localhost:${TERMINAL_GUI_PORT:-8090}"
    echo "  Log viewer         http://localhost:${LOG_GUI_PORT:-8091}"
    echo "  Config builder     http://localhost:${CONFIG_GUI_PORT:-8092}"
    echo "  Trader GUI         http://localhost:${TRADER_GUI_PORT:-8093}"
    echo "  REST API docs      http://localhost:8080/docs"
}

EXAMPLES="one-basic one-nominal one-complex three-basic three-nominal three-complex
ten-basic ten-nominal ten-complex thirty-basic thirty-nominal thirty-complex"

cmd_config() {
    [[ $# -eq 1 ]] || die "Usage: ./edumatcher.sh config <example-name | path/to/engine_config.yaml>"
    local want="$1"
    if [[ -f "$want" ]]; then
        mkdir -p config
        cp "$want" config/engine_config.yaml
        set_env EM_CONFIG_FILE /config/engine_config.yaml
        ok "Using your own configuration: $want"
    else
        # shellcheck disable=SC2076
        [[ " $(echo $EXAMPLES) " =~ " $want " ]] || {
            echo "Unknown example '$want'. Available:" >&2
            for e in $EXAMPLES; do echo "  $e" >&2; done
            echo "Or pass a path to your own engine_config.yaml." >&2
            exit 1
        }
        set_env EM_CONFIG "$want"
        set_env EM_CONFIG_FILE ""
        ok "Using bundled example: $want"
    fi
    echo "Apply it with: ./edumatcher.sh restart"
}

# Set KEY=VALUE in .env, replacing any existing assignment.
set_env() {
    local key="$1" value="${2:-}"
    touch .env
    if grep -qE "^${key}=" .env; then
        sed -i.bak -E "s|^${key}=.*|${key}=${value}|" .env && rm -f .env.bak
    else
        printf '%s=%s\n' "$key" "$value" >> .env
    fi
}

cmd_update() {
    detect_engine
    local version="${1:-latest}"
    set_env EM_VERSION "$version"
    info "Pulling images for version '$version'..."
    $COMPOSE pull
    ok "Pulled. Restarting..."
    cmd_restart
}

cmd_uninstall() {
    detect_engine
    $COMPOSE down --volumes || true
    if [[ "${1:-}" == "--data" ]]; then
        rm -rf data config
        ok "Containers, volumes and ./data removed."
    else
        ok "Containers and volumes removed. ./data kept — add --data to delete it."
    fi
}

case "${1:-}" in
    start)     shift; cmd_start "$@" ;;
    stop)      shift; cmd_stop "$@" ;;
    restart)   shift; cmd_restart "$@" ;;
    status)    shift; cmd_status "$@" ;;
    logs)      shift; cmd_logs "$@" ;;
    urls)      shift; cmd_urls "$@" ;;
    config)    shift; cmd_config "$@" ;;
    update)    shift; cmd_update "$@" ;;
    uninstall) shift; cmd_uninstall "$@" ;;
    *)
        awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "${BASH_SOURCE[0]}"
        exit 1
        ;;
esac
