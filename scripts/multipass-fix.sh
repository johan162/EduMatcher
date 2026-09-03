#!/usr/bin/env bash

# Colors for output readability
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PLIST_PATH="/Library/LaunchDaemons/com.canonical.multipassd.plist"
CLIENT_CERT_DIR="$HOME/Library/Application Support/multipass"
DAEMON_CERT_DIR="/var/root/Library/Application Support/multipassd"
SOCKET_PATH="/var/run/multipass_socket"

# --- Helper Functions ---
log_info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

require_sudo() {
    if [ "$EUID" -ne 0 ]; then
        log_warn "This option requires elevated privileges. Prompting for sudo:"
        sudo -v || { log_error "Sudo access required. Exiting."; exit 1; }
    fi
}

usage() {
    echo "Usage: $0 [OPTION]"
    echo ""
    echo "Options:"
    echo "  --restart    Full restart of Multipass, clears SSL certs/keys, and re-initializes connection."
    echo "  --reinstall  Thorough cleanup of all data/configs and fresh reinstall via Homebrew."
    echo "  --health     Runs diagnostics on Multipass process, sockets, and driver status."
    echo "  --help       Show this help message."
    exit 1
}

# --- 1) RESTART & RE-INITIALIZE KEYS ---
do_restart() {
    require_sudo
    log_info "Stopping Multipass service..."
    sudo launchctl unload "$PLIST_PATH" 2>/dev/null

    log_info "Purging stale SSL certificates and sockets..."
    sudo rm -rf "$CLIENT_CERT_DIR/authenticated"
    sudo rm -rf "$DAEMON_CERT_DIR/authenticated"
    sudo rm -f "$SOCKET_PATH"

    log_info "Starting Multipass service..."
    sudo launchctl load "$PLIST_PATH"

    log_info "Waiting for service to initialize..."
    sleep 5

    log_info "Re-authenticating CLI client..."
    if multipass version >/dev/null 2>&1; then
        log_info "Multipass daemon restarted successfully and keys are re-established!"
    else
        log_error "Connection failed. Run '$0 --health' to diagnose."
    fi
}

# --- 2) CLEAN REINSTALL VIA HOMEBREW ---
do_reinstall() {
    if ! command -v brew >/dev/null 2>&1; then
        log_error "Homebrew is not installed. Please install Homebrew first."
        exit 1
    fi

    require_sudo
    log_warn "WARNING: This will completely erase all Multipass VMs, configs, and certificates."
    read -p "Are you sure you want to continue? (y/N): " confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        log_info "Reinstallation aborted."
        exit 0
    fi

    log_info "Unloading Multipass service..."
    sudo launchctl unload "$PLIST_PATH" 2>/dev/null

    log_info "Uninstalling Multipass cask via Homebrew..."
    brew uninstall --cask --zap multipass 2>/dev/null || true

    log_info "Wiping residual data and system artifacts..."
    sudo rm -rf "$DAEMON_CERT_DIR"
    sudo rm -rf "/var/root/Library/Caches/multipassd"
    sudo rm -rf "$CLIENT_CERT_DIR"
    sudo rm -rf "$HOME/Library/Caches/multipass"
    sudo rm -f "$SOCKET_PATH"

    log_info "Reinstalling Multipass via Homebrew..."
    brew install --cask multipass

    log_info "Waiting for newly installed daemon to spin up..."
    sleep 5

    log_info "Testing installation state..."
    multipass list
}

# --- 3) HEALTH & DIAGNOSTICS ---
do_health() {
    echo "=========================================="
    echo "       MULTIPASS DIAGNOSTICS LOG          "
    echo "=========================================="
    
    # 1. Check process status
    echo -n "[?] Multipass Daemon Process: "
    if pgrep -x "multipassd" >/dev/null; then
        echo -e "${GREEN}RUNNING${NC}"
    else
        echo -e "${RED}NOT RUNNING${NC}"
        echo "    -> Recommendation: Run 'sudo launchctl load $PLIST_PATH'"
    fi

    # 2. Check LaunchDaemon plist
    echo -n "[?] LaunchDaemon Plist Exists: "
    if [ -f "$PLIST_PATH" ]; then
        echo -e "${GREEN}YES${NC}"
    else
        echo -e "${RED}NO${NC}"
        echo "    -> Recommendation: Multipass may not be installed properly."
    fi

    # 3. Check Socket Existence
    echo -n "[?] Socket File ($SOCKET_PATH): "
    if [ -S "$SOCKET_PATH" ]; then
        echo -e "${GREEN}PRESENT${NC}"
    else
        echo -e "${RED}MISSING${NC}"
        echo "    -> Recommendation: Restart daemon to regenerate socket."
    fi

    # 4. Driver Setting
    echo -n "[?] Default Driver Configuration: "
    DRIVER=$(multipass get local.driver 2>/dev/null || echo "Unknown/Failed")
    echo "$DRIVER"
    if [[ "$DRIVER" == "Unknown/Failed" ]] && [[ $(uname -m) == "arm64" ]]; then
        echo -e "${YELLOW}    -> Note (Apple Silicon): If daemon crashes, force driver: 'sudo multipass set local.driver=qemu'${NC}"
    fi

    # 5. Socket Connection / SSL Test
    echo -n "[?] CLI Connection Test: "
    OUTPUT=$(multipass list 2>&1)
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}SUCCESSFUL${NC}"
    else
        echo -e "${RED}FAILED${NC}"
        echo "------------------------------------------"
        echo "Error detail:"
        echo "$OUTPUT"
        echo "------------------------------------------"
        if echo "$OUTPUT" | grep -q "certificate verify failed"; then
            echo -e "${YELLOW}RECOMMENDATION:${NC} Broken SSL certificates detected."
            echo "Run: sudo $0 --restart"
        elif echo "$OUTPUT" | grep -q "cannot connect to the multipass socket"; then
            echo -e "${YELLOW}RECOMMENDATION:${NC} Daemon is uncommunicative or socket is missing."
            echo "Run: sudo $0 --restart"
        fi
    fi
}

# --- Main Entrypoint ---
case "$1" in
    --restart)
        do_restart
        ;;
    --reinstall)
        do_reinstall
        ;;
    --health)
        do_health
        ;;
    *)
        usage
        ;;
esac
