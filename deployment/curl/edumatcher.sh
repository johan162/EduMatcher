#!/usr/bin/env bash
# EduMatcher control script — installed alongside compose.yaml and .env.
#
#   ./edumatcher.sh start | stop | restart | status | logs [service]
#   ./edumatcher.sh shell [command...]
#   ./edumatcher.sh urls
#   ./edumatcher.sh mounts
#   ./edumatcher.sh config <example-name | path/to/engine_config.yaml>
#   ./edumatcher.sh speed <N> [start-time]      (AI-sim installs only)
#   ./edumatcher.sh share on [host-ip] | off
#   ./edumatcher.sh pull                       (download the images, start nothing)
#   ./edumatcher.sh update [version]
#   ./edumatcher.sh uninstall [--data]
#
# EM_STACK=sim in .env makes every command drive compose.ai-sim.yaml and the
# 'edumatcher-sim' containers instead; the installer sets it with --sim.
# EM_STACK=guis drives compose.guis.yaml: the six web GUIs only, for an
# exchange you run yourself with pipx; the installer sets it with --guis.
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

# Every container this deployment owns. The names are fixed in the compose
# file rather than derived from the project, which is why two installs collide
# — see assert_no_foreign_stack below. detect_engine overrides both of these
# for an AI-sim install.
CONTAINERS="edumatcher edumatcher-terminal-gui edumatcher-log-gui edumatcher-config-gui edumatcher-trader-gui edumatcher-book-gui edumatcher-dash-gui"
CONTAINER_NAME="edumatcher"

# Read one key out of .env without sourcing the whole file.
env_value() { [[ -f .env ]] && sed -n "s/^$1=//p" .env | tail -1; }

# 'sim' for an AI-trader simulation install, empty for the plain exchange.
stack() { case "$(env_value EM_STACK)" in sim) echo sim ;; guis) echo guis ;; esac; }

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

    # Overlay files are additive -f arguments, the same mechanism the source
    # checkout uses for ZMQ=1 and SSH=1. Word splitting here is intended.
    if [[ "$(stack)" == "guis" ]]; then
        COMPOSE_FILES="-f compose.guis.yaml"
        CONTAINER_NAME=""
        export EM_DATA_DIR="$(guis_data_dir)"
        CONTAINERS="edumatcher-host-terminal-gui edumatcher-host-log-gui edumatcher-host-config-gui edumatcher-host-trader-gui edumatcher-host-book-gui edumatcher-host-dash-gui"
        return
    fi
    if [[ "$(stack)" == "sim" ]]; then
        COMPOSE_FILES="-f compose.ai-sim.yaml"
        CONTAINER_NAME="edumatcher-sim"
        CONTAINERS="edumatcher-sim edumatcher-sim-terminal-gui edumatcher-sim-log-gui edumatcher-sim-trader-gui edumatcher-sim-book-gui edumatcher-sim-dash-gui"
        return
    fi
    COMPOSE_FILES="-f compose.yaml"
    if [[ "$(env_value EM_ZMQ)" == "1" ]]; then
        [[ -f compose.zmq.yaml ]] || die "EM_ZMQ=1 but compose.zmq.yaml is missing.
  It arrived with a later release — re-run the installer into this directory to
  fetch it; your .env and data are kept:
    curl -fsSL https://raw.githubusercontent.com/johan162/EduMatcher/main/deployment/curl/install.sh | bash -s -- --dir $HERE"
        COMPOSE_FILES="$COMPOSE_FILES -f compose.zmq.yaml"
    fi
}

# Reads the deployed configuration and prints "<port> <api_key>" for the first
# read-only credential (gateway_id: null). terminal-gui's history endpoints and
# everything book-gui shows need it; it is generated per configuration, so it
# cannot be a fixed default. An optional argument names the file, for an
# exchange that is not in a container.
READONLY_CREDENTIAL_PY='
import json, sys
try:
    cfg = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "/data/ref_data/engine_config.json"))
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

# The pipx exchange's data directory: what its pm-* commands use, so
# EDUMATCHER_DATA_DIR from this shell first, then .env, then the pipx default.
guis_data_dir() {
    local dir="${EDUMATCHER_DATA_DIR:-$(env_value EM_DATA_DIR)}"
    dir="${dir:-$HOME/.local/share/edumatcher}"
    echo "${dir/#\~/$HOME}"
}

# Resolve a directory through symlinks so /tmp and /private/tmp compare equal
# on macOS. Non-existent paths are returned unchanged.
norm_dir() { if [[ -d "$1" ]]; then (cd "$1" && pwd -P); else printf '%s' "$1"; fi; }

# This deployment and the repository's deployment/docker one use the same fixed
# container names AND the same host ports, so only one can run at a time. If the
# other one is up, compose quietly leaves its containers alone and you end up
# looking at its exchange through this install's URLs — same ports, same
# in-container paths, no error anywhere. Refuse instead.
assert_no_foreign_stack() {
    local name="$CONTAINER_NAME" src
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

# The GUIs of an exchange that is not in a container. There is no exchange to
# start; the read-only key is read from the deployed configuration on disk,
# so the exchange must have been through pm-setup (or a first start) already.
start_guis() {
    local data cred host
    data="$EM_DATA_DIR"
    [[ -f "$data/ref_data/engine_config.json" ]] || die "No deployed configuration in $data.
  Run pm-setup first, or point at your data directory:
    EDUMATCHER_DATA_DIR=/path/to/data ./edumatcher.sh start"
    # How the containers address this machine; compose maps the name to it.
    host="${EM_HOST:-$(env_value EM_HOST)}"
    export EM_HOST="${host:-host.docker.internal}"
    host="$EM_HOST"
    info "Exchange data directory: $data"

    cred=$(python3 -c "$READONLY_CREDENTIAL_PY" "$data/ref_data/engine_config.json" 2>/dev/null || true)
    if [[ -n "$cred" ]]; then
        set -- $cred
        export API_GATEWAY_URL="http://$host:$1"
        export PM_TERMINAL_API_KEY="$2" PM_BOOK_API_KEY="$2" PM_DASH_API_KEY="$2"
        ok "Read-only API key resolved from the deployed configuration (port $1)"
    else
        warn "No read-only credential (gateway_id: null) in the deployed configuration."
        warn "The trading terminal's live feed will work; its history panels and the"
        warn "order book viewer will not."
    fi
    $COMPOSE $COMPOSE_FILES up -d
    echo
    cmd_urls
    echo
    info "These are only the GUIs. Start the exchange itself on this machine: pm-opctl-cli start"
}

cmd_start() {
    detect_engine
    [[ "$(stack)" == "guis" ]] && { info "Engine: $ENGINE ($COMPOSE)"; start_guis; return; }
    assert_no_foreign_stack
    mkdir -p data config
    info "Engine: $ENGINE ($COMPOSE)"

    # The simulation's configuration is fixed and its read-only key is already
    # in the compose file, so there is nothing to resolve: one phase.
    if [[ "$(stack)" == "sim" ]]; then
        $COMPOSE $COMPOSE_FILES up -d
        echo
        cmd_urls
        return
    fi

    # Two phases, deliberately: the read-only API key does not exist until the
    # exchange has deployed its configuration, so the backend has to be up
    # before the GUIs can be given their environment.
    $COMPOSE $COMPOSE_FILES up -d edumatcher
    printf -- "- waiting for the exchange to deploy its configuration"
    for _ in $(seq 1 60); do
        if $ENGINE exec "$CONTAINER_NAME" test -f /data/ref_data/engine_config.json >/dev/null 2>&1; then
            break
        fi
        printf "."; sleep 1
    done
    echo

    cred=$($ENGINE exec "$CONTAINER_NAME" python3 -c "$READONLY_CREDENTIAL_PY" 2>/dev/null || true)
    if [[ -n "$cred" ]]; then
        set -- $cred
        export API_GATEWAY_URL="http://edumatcher:$1"
        export PM_TERMINAL_API_KEY="$2"
        export PM_BOOK_API_KEY="$2"
        export PM_DASH_API_KEY="$2"
        ok "Read-only API key resolved from the deployed configuration (port $1)"
    else
        warn "No read-only credential (gateway_id: null) in the deployed configuration."
        warn "The trading terminal's live feed will work; its history panels and the"
        warn "order book viewer will not."
    fi

    $COMPOSE $COMPOSE_FILES up -d
    echo
    cmd_urls
}

cmd_stop() {
    detect_engine
    $COMPOSE $COMPOSE_FILES down
    ok "Stopped. Your data in ./data is untouched."
}

cmd_restart() { cmd_stop; cmd_start; }

cmd_status() {
    detect_engine
    $COMPOSE $COMPOSE_FILES ps
    echo
    info "Exchange process table:"
    if [[ "$(stack)" == "guis" ]]; then
        pm-opctl-cli list --no-restart 2>/dev/null \
            || warn "pm-opctl-cli is not on the PATH, or the exchange is not running."
        return
    fi
    $ENGINE exec "$CONTAINER_NAME" pm-opctl-cli list --no-restart 2>/dev/null \
        || warn "The exchange container is not running."
}

cmd_logs() {
    detect_engine
    if [[ $# -gt 0 ]]; then $COMPOSE $COMPOSE_FILES logs -f "$1"; else $COMPOSE $COMPOSE_FILES logs -f; fi
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
    [[ "$(stack)" == "guis" ]] && die "There is no exchange container here: the exchange is the pipx one,
  and its pm-* commands are already on your own PATH."
    local name="$CONTAINER_NAME" state
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
    echo "  TapeDeck (market display)  http://localhost:${TERMINAL_GUI_PORT:-8090}"
    echo "  Log Operator Console       http://localhost:${LOG_GUI_PORT:-8091}"
    [[ "$(stack)" == "sim" ]] || echo "  Configuration GUI          http://localhost:${CONFIG_GUI_PORT:-8092}"
    echo "  Trading GUI                http://localhost:${TRADER_GUI_PORT:-8093}"
    echo "  Order Book Viewer          http://localhost:${BOOK_GUI_PORT:-8094}"
    echo "  Operator Dashboard         http://localhost:${DASH_GUI_PORT:-8095}"
    echo "  REST API docs              http://localhost:8080/docs"
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
    # The GUIs of a pipx exchange mount that exchange's directory instead.
    [[ "$(stack)" == "guis" ]] && here_data="$(norm_dir "$EM_DATA_DIR")"
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

EXAMPLES="s1-basic s1-nominal s1-complex s3-basic s3-nominal s3-complex
s10-basic s10-nominal s10-complex s30-basic s30-nominal s30-complex s150-basic s150-nominal s150-complex
s1-basic-nomm s1-nominal-nomm s1-complex-nomm s3-basic-nomm s3-nominal-nomm s3-complex-nomm
s10-basic-nomm s10-nominal-nomm s10-complex-nomm s30-basic-nomm s30-nominal-nomm s30-complex-nomm
s150-basic-nomm s150-nominal-nomm s150-complex-nomm s300-load s300-sim"

cmd_config() {
    [[ "$(stack)" == "guis" ]] && die "The exchange is yours (pipx): change its configuration with pm-config-gen / pm-cverifier / pm-setup."
    [[ $# -eq 1 ]] || die "Usage: ./edumatcher.sh config <example-name | path/to/engine_config.yaml>"
    local want="$1"
    if [[ -f "$want" ]]; then
        mkdir -p config
        [[ "$want" -ef config/engine_config.yaml ]] || cp "$want" config/engine_config.yaml
        # The simulation's market model lives beside the engine configuration
        # and is deployed with it, so it has to be mounted with it.
        local sim_yaml="$(dirname "$want")/market_sim.yaml"
        if [[ -f "$sim_yaml" && ! "$sim_yaml" -ef config/market_sim.yaml ]]; then
            cp "$sim_yaml" config/market_sim.yaml
        fi
        set_env EM_CONFIG_FILE /config/engine_config.yaml
        ok "Using your own configuration: $want"
    elif [[ "$(stack)" == "sim" ]]; then
        die "The simulation runs the s300-sim example or a configuration of your own.
  Pass a path to an engine_config.yaml; '$want' is not a file."
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

# How fast the trading calendar runs, and optionally where it starts. Both are
# read at every start, so they stay in effect until changed back.
#
#   ./edumatcher.sh speed 10 2026-11-02T08:58   a trading day in ~42 minutes
#   ./edumatcher.sh speed 1                     back to real trading hours
cmd_speed() {
    [[ "$(stack)" == "sim" ]] || die "'speed' applies to an AI-sim install only (EM_STACK=sim)."
    [[ $# -ge 1 ]] || die "Usage: ./edumatcher.sh speed <N> [start-time]"
    [[ "$1" =~ ^[0-9]+$ ]] || die "Speed must be a whole number (1 = real time)."
    set_env EM_SPEED "$1"
    set_env EM_START "${2:-}"
    ok "Speed ${1}x${2:+, starting $2}"
    echo "Apply it with: ./edumatcher.sh restart"
}

# Publish the exchange to the network (a classroom) or pull it back to this
# machine. 'on' also points the dashboard's drawer links at the host address,
# because their localhost default would send a student to their own machine.
# The protocol gateways have no password: use 'on' on a network you control.
#
#   ./edumatcher.sh share on                    auto-detected host address
#   ./edumatcher.sh share on 192.168.0.232
#   ./edumatcher.sh share off
host_ip() {
    local ip=""
    if command -v ip >/dev/null 2>&1; then
        ip="$(ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p' | head -1)"
    fi
    [[ -n "$ip" ]] || ip="$(ipconfig getifaddr en0 2>/dev/null || true)"
    printf '%s' "$ip"
}

cmd_share() {
    case "${1:-}" in
        on)
            local ip="${2:-$(host_ip)}"
            [[ -n "$ip" ]] || die "Could not detect this host's address — pass it: ./edumatcher.sh share on <host-ip>"
            local log_port book_port dash_port
            log_port="$(env_value LOG_GUI_PORT)"; book_port="$(env_value BOOK_GUI_PORT)"
            dash_port="$(env_value DASH_GUI_PORT)"
            set_env BIND_ADDR 0.0.0.0
            set_env LOG_GUI_URL "http://${ip}:${log_port:-8091}"
            set_env BOOK_GUI_URL "http://${ip}:${book_port:-8094}"
            ok "Sharing on ${ip}: published ports listen on all interfaces"
            warn "The gateways have no password — only do this on a network you control."
            echo "Apply it with: ./edumatcher.sh restart"
            echo "Students open: http://${ip}:${dash_port:-8095}"
            echo "If they cannot connect, open the ports in the host firewall (8090-8095/tcp)."
            ;;
        off)
            set_env BIND_ADDR 127.0.0.1
            set_env LOG_GUI_URL ""
            set_env BOOK_GUI_URL ""
            ok "Private: published ports listen on this machine only"
            echo "Apply it with: ./edumatcher.sh restart"
            ;;
        *) die "Usage: ./edumatcher.sh share on [host-ip] | off" ;;
    esac
}

# Download this install's images and start nothing: what 'install.sh --no-start'
# ends with, so a later 'start' needs no network.
cmd_pull() {
    detect_engine
    info "Pulling images (${COMPOSE_FILES#-f })..."
    $COMPOSE $COMPOSE_FILES pull
    ok "Images downloaded. Nothing was started."
}

cmd_update() {
    detect_engine
    local version="${1:-latest}"
    set_env EM_VERSION "$version"
    info "Pulling images for version '$version'..."
    $COMPOSE $COMPOSE_FILES pull
    ok "Pulled. Restarting..."
    cmd_restart
}

cmd_uninstall() {
    detect_engine
    $COMPOSE $COMPOSE_FILES down --volumes || true
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
    speed)     shift; cmd_speed "$@" ;;
    share)     shift; cmd_share "$@" ;;
    pull)      shift; cmd_pull "$@" ;;
    update)    shift; cmd_update "$@" ;;
    uninstall) shift; cmd_uninstall "$@" ;;
    *)
        awk 'NR>1 && /^#/ {sub(/^# ?/, ""); print; next} NR>1 {exit}' "${BASH_SOURCE[0]}"
        exit 1
        ;;
esac
