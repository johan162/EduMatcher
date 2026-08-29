#!/usr/bin/env bash
# EduMatcher control script — installed alongside compose.yaml and .env.
#
#   ./edumatcher.sh start | stop | restart | status | logs [service]
#   ./edumatcher.sh shell [command...]
#   ./edumatcher.sh urls
#   ./edumatcher.sh mounts
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

# Every container this deployment owns. The names are fixed in compose.yaml
# rather than derived from the project, which is why two installs collide —
# see assert_no_foreign_stack below.
CONTAINERS="edumatcher edumatcher-terminal-gui edumatcher-log-gui edumatcher-config-gui edumatcher-trader-gui"

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

# Resolve a directory through symlinks so /tmp and /private/tmp compare equal
# on macOS. Non-existent paths are returned unchanged.
norm_dir() { if [[ -d "$1" ]]; then (cd "$1" && pwd -P); else printf '%s' "$1"; fi; }

# This deployment and the repository's deployment/docker one use the same fixed
# container names AND the same host ports, so only one can run at a time. If the
# other one is up, compose quietly leaves its containers alone and you end up
# looking at its exchange through this install's URLs — same ports, same
# in-container paths, no error anywhere. Refuse instead.
assert_no_foreign_stack() {
    local name="${CONTAINER_NAME:-edumatcher}" src
    $ENGINE container inspect "$name" >/dev/null 2>&1 || return 0
    src=$($ENGINE inspect "$name" \
            --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' \
            2>/dev/null || true)
    [[ "$(norm_dir "$src")" == "$(norm_dir "$HERE/data")" ]] && return 0
    echo -e "${RED}✗ A container named '$name' already exists, from a different EduMatcher install.${NC}" >&2
    echo -e "    its data directory:  ${src:-<none>}" >&2
    echo -e "    this install:        $HERE/data" >&2
    echo >&2
    echo -e "${YELLOW}  Both deployments use the same container names and host ports, so only one" >&2
    echo -e "  can run at a time. Stop the other one, then retry:${NC}" >&2
    echo -e "    a source checkout:     make -C <repo>/deployment/docker down-all" >&2
    echo -e "    another curl install:  cd <that directory> && ./edumatcher.sh stop" >&2
    exit 1
}

cmd_start() {
    detect_engine
    assert_no_foreign_stack
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

# An interactive shell inside the exchange container, or one command run there.
# Every pm-* command is on the image's PATH and EDUMATCHER_DATA_DIR is already
# /data, so `pm-opctl-cli`, `pm-config-show`, `pm-alf-console` and the rest work
# exactly as the guides describe them.
#
#   ./edumatcher.sh shell                       an interactive bash
#   ./edumatcher.sh shell pm-opctl-cli list     one command, then exit
#   ./edumatcher.sh shell pm-alf-console --id TRADER01
cmd_shell() {
    detect_engine
    local name="${CONTAINER_NAME:-edumatcher}" state
    $ENGINE container inspect "$name" >/dev/null 2>&1 \
        || die "No container '$name'. Start the exchange first: ./edumatcher.sh start"
    state=$($ENGINE inspect "$name" --format '{{.State.Status}}' 2>/dev/null || echo "?")
    [[ "$state" == "running" ]] \
        || die "Container '$name' is $state. Start the exchange first: ./edumatcher.sh start"

    # -t only when there is a terminal on both ends, so that
    # `./edumatcher.sh shell pm-opctl-cli list > file` still works.
    local tty_flags="-i"
    [[ -t 0 && -t 1 ]] && tty_flags="-it"

    # The full-screen tools (pm-alf-console, pm-viewer, pm-board) render as
    # garbage without a usable TERM, and the container inherits none.
    if [[ $# -gt 0 ]]; then
        $ENGINE exec $tty_flags -e TERM="${TERM:-xterm-256color}" "$name" "$@"
    else
        info "Shell in '$name' — every pm-* command is on the PATH. Ctrl-D to leave."
        $ENGINE exec $tty_flags -e TERM="${TERM:-xterm-256color}" "$name" bash
    fi
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

# Which directory on your disk is behind each path inside each container.
# The first question when a GUI shows something you did not expect: the health
# pages report container paths like /backend-data/log.db, which say nothing
# about whose data that is. The image name answers the other half — a
# 'ghcr.io/...' image is a released install, 'localhost/...' one built from a
# source checkout.
cmd_mounts() {
    detect_engine
    local here_data name img state
    here_data="$(norm_dir "$HERE/data")"
    echo "This install: $HERE"
    echo

    for name in $CONTAINERS; do
        if ! $ENGINE container inspect "$name" >/dev/null 2>&1; then
            printf "%-24s %s\n\n" "$name" "(not created)"
            continue
        fi
        img=$($ENGINE inspect "$name" --format '{{.Config.Image}}' 2>/dev/null || echo "?")
        state=$($ENGINE inspect "$name" --format '{{.State.Status}}' 2>/dev/null || echo "?")
        printf "%-24s %s  [%s]\n" "$name" "$img" "$state"

        $ENGINE inspect "$name" \
            --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}' \
            2>/dev/null |
        while read -r src _arrow dst; do
            [[ -z "${src:-}" ]] && continue
            # Only the data mounts can belong to a foreign install; the named
            # volumes are this project's own and live in the engine's storage.
            case "$dst" in
                /data|/backend-data|/config)
                    if [[ "$(norm_dir "$src")" == "$here_data" || "$(norm_dir "$src")" == "$(norm_dir "$HERE/config")" ]]; then
                        printf "    %s -> %s\n" "$src" "$dst"
                    else
                        printf "    ${RED}%s -> %s   NOT this install${NC}\n" "$src" "$dst"
                    fi
                    ;;
                *) printf "    %s -> %s\n" "$src" "$dst" ;;
            esac
        done
        echo
    done
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
    shell)     shift; cmd_shell "$@" ;;
    urls)      shift; cmd_urls "$@" ;;
    mounts)    shift; cmd_mounts "$@" ;;
    config)    shift; cmd_config "$@" ;;
    update)    shift; cmd_update "$@" ;;
    uninstall) shift; cmd_uninstall "$@" ;;
    *)
        awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "${BASH_SOURCE[0]}"
        exit 1
        ;;
esac
