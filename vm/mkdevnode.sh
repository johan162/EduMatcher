#!/usr/bin/env bash
# Create and provision a Multipass development node for EduMatcher.
# Requires: multipass, ssh-keygen, and access to this repository checkout.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

NODE_NAME="pm-devnode"
NODE_IMAGE="lts"
NODE_CPUS="6"
NODE_MEMORY="12G"
NODE_DISK="50G"
NODE_USER="ubuntu"
VERIFY_SETUP_SCRIPT="$REPO_ROOT/scripts/verify_setup.sh"

SSH_KEY_PATH="${HOME}/.ssh/${NODE_NAME}_ed25519"
SSH_KEY_COMMENT="${NODE_NAME}@$(hostname -s 2>/dev/null || hostname)"

usage() {
  cat <<EOF
Usage:
  $0 [options]

Options:
  --name <node-name>           Multipass node name (default: $NODE_NAME)
  --image <image>              Multipass image (default: $NODE_IMAGE)
  --cpus <count>               CPU count (default: $NODE_CPUS)
  --memory <size>              RAM size, for example 8G (default: $NODE_MEMORY)
  --disk <size>                Disk size, for example 40G (default: $NODE_DISK)
  --user <name>                Standard user inside the VM (default: $NODE_USER)
  --ssh-key <path>             Private key path to create/use (default: $SSH_KEY_PATH)
  --verify-script <path>       Host path to verify_setup.sh (default: $VERIFY_SETUP_SCRIPT)
  --help                       Show this help text

Examples:
  $0
  $0 --name pm-devnode-02 --cpus 4 --memory 16G --disk 80G
EOF
}

require_command() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "❌ Required command not found: $cmd" >&2
    exit 1
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)
      NODE_NAME="${2:-}"
      shift 2
      ;;
    --image)
      NODE_IMAGE="${2:-}"
      shift 2
      ;;
    --cpus)
      NODE_CPUS="${2:-}"
      shift 2
      ;;
    --memory)
      NODE_MEMORY="${2:-}"
      shift 2
      ;;
    --disk)
      NODE_DISK="${2:-}"
      shift 2
      ;;
    --user)
      NODE_USER="${2:-}"
      shift 2
      ;;
    --ssh-key)
      SSH_KEY_PATH="${2:-}"
      shift 2
      ;;
    --verify-script)
      VERIFY_SETUP_SCRIPT="${2:-}"
      shift 2
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

require_command multipass
require_command ssh-keygen

if [[ ! -f "$VERIFY_SETUP_SCRIPT" ]]; then
  echo "❌ verify setup script not found: $VERIFY_SETUP_SCRIPT" >&2
  exit 1
fi

if multipass info "$NODE_NAME" >/dev/null 2>&1; then
  echo "❌ A node named '$NODE_NAME' already exists. Delete it or choose another --name." >&2
  exit 1
fi

mkdir -p "$(dirname "$SSH_KEY_PATH")"

# if [[ -f "$SSH_KEY_PATH" || -f "${SSH_KEY_PATH}.pub" ]]; then
#   echo "❌ SSH key path already exists: $SSH_KEY_PATH" >&2
#   echo "   Choose another --ssh-key path or remove the existing key files." >&2
#   exit 1
# fi

echo "=== EduMatcher Multipass Dev Node Setup ==="
echo "Node name : $NODE_NAME"
echo "Image     : $NODE_IMAGE"
echo "CPUs      : $NODE_CPUS"
echo "Memory    : $NODE_MEMORY"
echo "Disk      : $NODE_DISK"
echo "User      : $NODE_USER"
echo "SSH key   : $SSH_KEY_PATH"
echo ""

echo "1/4 Launching Multipass node '$NODE_NAME'..."
if ! multipass launch "$NODE_IMAGE" \
  --name "$NODE_NAME" \
  --cpus "$NODE_CPUS" \
  --memory "$NODE_MEMORY" \
  --disk "$NODE_DISK"; then
  echo "❌ Failed to launch Multipass node '$NODE_NAME' from image '$NODE_IMAGE'." >&2
  echo "   Run 'multipass find' to list valid images on your host." >&2
  exit 1
fi

echo "2/4 Generating a fresh SSH key pair in the node..."
multipass exec "$NODE_NAME" -- bash -lc "ssh-keygen -t ed25519 -f \"/home/ubuntu/.ssh/id_ed25519\" -N \"\""

echo "3/4 Installing the host SSH public key for user '$NODE_USER'..."
multipass transfer "${SSH_KEY_PATH}.pub" "$NODE_NAME:/tmp/${NODE_NAME}.pub"
multipass exec "$NODE_NAME" -- bash -lc "
  set -euo pipefail
  sudo install -d -m 700 -o '$NODE_USER' -g '$NODE_USER' '/home/$NODE_USER/.ssh'
  sudo touch '/home/$NODE_USER/.ssh/authorized_keys'
  sudo chown '$NODE_USER:$NODE_USER' '/home/$NODE_USER/.ssh/authorized_keys'
  sudo chmod 600 '/home/$NODE_USER/.ssh/authorized_keys'
  cat '/tmp/${NODE_NAME}.pub' | sudo tee -a '/home/$NODE_USER/.ssh/authorized_keys' >/dev/null
  sudo chown '$NODE_USER:$NODE_USER' '/home/$NODE_USER/.ssh/authorized_keys'
  rm -f '/tmp/${NODE_NAME}.pub'
"

echo "4/4 Copying verify_setup.sh as the standard user..."
VERIFY_SETUP_REMOTE_PATH="/home/$NODE_USER/verify_setup.sh"
multipass transfer "$VERIFY_SETUP_SCRIPT" "$NODE_NAME:$VERIFY_SETUP_REMOTE_PATH"
echo "   Copied to: $VERIFY_SETUP_REMOTE_PATH"
multipass exec "$NODE_NAME" -- bash -lc "
  set -euo pipefail
  sudo chown '$NODE_USER:$NODE_USER' '$VERIFY_SETUP_REMOTE_PATH'
  chmod +x '$VERIFY_SETUP_REMOTE_PATH'
  '$VERIFY_SETUP_REMOTE_PATH' --yes
"

echo "Restarting and snapshotting the node to ensure all changes take effect..."
multipass stop "$NODE_NAME"
sleep 3  # Wait a few seconds for the node to stop

echo "Making a snapshot of core dev-node state..."
SNAPSHOT_NAME="pm-devnode-core"
if multipass info "$NODE_NAME" | grep -q "Snapshots"; then
  echo "   Deleting existing snapshot '$SNAPSHOT_NAME'..."
  multipass delete "$SNAPSHOT_NAME" > /dev/null 2>&1 || true
fi
multipass snapshot "$NODE_NAME" --name "$SNAPSHOT_NAME" -comment "Core dev-node state with verify_setup.sh applied"

multipass start "$NODE_NAME"

echo ""
echo "✅ Multipass development node '$NODE_NAME' is ready."
echo ""
echo "Connect with:"
echo "  multipass shell $NODE_NAME"
echo ""
echo "SSH with:"
echo "  ssh -i $SSH_KEY_PATH $NODE_USER@$(multipass info $NODE_NAME | awk '/IPv4/ {print $2; exit}')"


# Notes:
# Standard updates
# sudo apt update -y
# sudo apt upgrade -y
# sudo apt install -y pipx
# pipx install poetry
# pipx ensurepath
# sudo apt install -y make gcc libreadline-dev readline-common
# sudo apt install -y texlive-latex-base texlive-fonts-recommended texlive-xetex
# curl -LO https://github.com/jgm/pandoc/releases/download/3.10.1/pandoc-3.10.1-linux-amd64.tar.gz
# tar -xzf pandoc-3.10.1-linux-amd64.tar.gz
# mkdir -p ~/.local/bin
# install -m 0755 pandoc-3.10.1/bin/pandoc ~/.local/bin/pandoc
# install -m 0755 pandoc-3.10.1/bin/pandoc-lua ~/.local/bin/pandoc-lua
# sudo apt install -y nodejs npm
# wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
# mv google-chrome-stable_current_amd64.deb /tmp/
# sudo apt install -y /tmp/google-chrome-stable_current_amd64.deb