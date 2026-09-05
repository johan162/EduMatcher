#!/usr/bin/env bash

# Colors for output readability
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PLIST_PATH="/Library/LaunchDaemons/com.canonical.multipassd.plist"
CLIENT_DIR="$HOME/Library/Application Support/multipass"
DAEMON_DIR="/var/root/Library/Application Support/multipassd"
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
    echo "  --restart    Unloads daemon, purges all leaf certs/keychains, resets keys, and restarts service."
    echo "  --reinstall  Thorough cleanup of all data/configs and fresh reinstall via Homebrew."
    echo "  --health     Runs diagnostics on Multipass process, sockets, and driver status."
    echo "  --logs       Stream or query recent macOS unified logs for multipassd."
    echo "  --help       Show this help message."
    exit 1
}

# --- 1) RESTART & DEEP PURGE EXPIRED LEAF CERTS ---
do_restart() {
    require_sudo
    log_info "Unloading Multipass service and killing lingering daemon processes..."
    sudo launchctl unload "$PLIST_PATH" 2>/dev/null
    sudo pkill -9 multipassd 2>/dev/null || true

    log_info "Purging root Keychains and Security framework caches for multipassd..."
    sudo security delete-certificate -c "multipass" /Library/Keychains/System.keychain 2>/dev/null || true
    sudo security delete-certificate -c "multipassd" /Library/Keychains/System.keychain 2>/dev/null || true

    log_info "Wiping all daemon certificates, CAs, and authenticated sessions in /var/root..."
    sudo rm -rf "$DAEMON_DIR/authenticated"
    sudo rm -rf "$DAEMON_DIR/vault/certs" 2>/dev/null || true
    sudo rm -rf "$DAEMON_DIR/vault/instances/certs" 2>/dev/null || true
    sudo rm -f "$DAEMON_DIR/"*.pem 2>/dev/null || true
    sudo rm -f "$DAEMON_DIR/"*.crt 2>/dev/null || true

    log_info "Wiping client certificate caches and socket locks..."
    sudo rm -rf "$CLIENT_DIR/authenticated"
    sudo rm -f "$CLIENT_DIR/"*.pem 2>/dev/null || true
    sudo rm -f "$SOCKET_PATH"
    sudo rm -f /var/run/multipass*

    log_info "Reloading Multipass service to regenerate PKI hierarchy..."
    sudo launchctl load "$PLIST_PATH"

    log_info "Waiting for daemon initialization and certificate generation..."
    sleep 5

    log_info "Testing CLI connection..."
    if multipass list >/dev/null 2>&1; then
        log_info "Multipass daemon restarted successfully with valid certificates!"
    else
        log_error "CLI connection test failed. Checking latest log entry:"
        sudo log show --predicate 'process == "multipassd"' --style compact --last 1m | tail -n 15
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
    sudo pkill -9 multipassd 2>/dev/null || true

    log_info "Uninstalling Multipass cask via Homebrew..."
    brew uninstall --cask --zap multipass 2>/dev/null || true

    log_info "Wiping all residual daemon data, leaf certs, and system artifacts..."
    sudo rm -rf "$DAEMON_DIR"
    sudo rm -rf "/var/root/Library/Caches/multipassd"
    sudo rm -rf "$CLIENT_DIR"
    sudo rm -rf "$HOME/Library/Caches/multipass"
    sudo rm -f "$SOCKET_PATH"
    sudo rm -f /var/run/multipass*

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
        echo "    -> Recommendation: Daemon failed during boot/cert initialization."
    fi

    # 4. Check Daemon Leaf Cert Directory
    echo -n "[?] Daemon Cert Directory (/var/root): "
    if [ -d "$DAEMON_DIR/authenticated" ]; then
        echo -e "${GREEN}PRESENT${NC}"
    else
        echo -e "${YELLOW}MISSING OR CLEARED${NC}"
    fi

    # 5. Driver Setting
    echo -n "[?] Default Driver Configuration: "
    DRIVER=$(multipass get local.driver 2>/dev/null || echo "Unknown/Failed")
    echo "$DRIVER"
    if [[ "$DRIVER" == "Unknown/Failed" ]] && [[ $(uname -m) == "arm64" ]]; then
        echo -e "${YELLOW}    -> Note (Apple Silicon): If driver fails, set via defaults:${NC}"
        echo "       sudo defaults write /Library/Preferences/com.canonical.multipassd.plist local.driver qemu"
    fi

    # 6. Socket Connection / SSL Test
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
            echo -e "${YELLOW}RECOMMENDATION:${NC} Expired or untrusted leaf certificate detected."
            echo "Run: sudo $0 --restart"
        elif echo "$OUTPUT" | grep -q "cannot connect to the multipass socket"; then
            echo -e "${YELLOW}RECOMMENDATION:${NC} Daemon is uncommunicative or socket is missing."
            echo "Run: sudo $0 --restart"
        fi
    fi
}

# --- 4) VIEW SYSTEM LOGS ---
do_logs() {
    require_sudo
    log_info "Querying macOS Unified Log for 'multipassd' (Last 15 minutes)..."
    echo "================================================================================"
    sudo log show --predicate 'process == "multipassd"' --style compact --last 15m
    echo "================================================================================"
    log_info "To stream live logs in real time, run:"
    echo "  sudo log stream --predicate 'process == \"multipassd\"' --level debug"
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
    --logs)
        do_logs
        ;;
    *)
        usage
        ;;
esac

