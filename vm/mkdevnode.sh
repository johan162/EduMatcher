#!/usr/bin/env bash
# Create and provision a Multipass development node for EduMatcher. 
# This creates a fresh Multipass development node suitable for development and 
# testing of the EduMatcher platform. It sets up a standard user, generates SSH keys, 
# and runs a verification script to ensure the node is properly configured.
#
# *****
# NOTE:
# *****
# This script does NOT install EduMatcher; either as a cloned repo or via pipx. 
# It only sets up a Multipass node with all necessary development tools, a standard 
# user, and SSH access.
# To be able to push changes, you must have write access to the repository which is 
# controlled by the repository owner via GitHub permissions and SSH keys.
# If you do not have write access, you can still clone the repository in READ mode.
# 
# Requires: multipass, ssh-keygen, and access to this repository checkout.

set -uo pipefail

# Color codes for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
LIGHT_BLUE='\033[1;34m'
LIGHT_CYAN='\033[1;36m'
LIGHT_GREEN='\033[1;32m'
LIGHT_RED='\033[1;31m'
LIGHT_YELLOW='\033[1;33m'
LIGHT_MAGENTA='\033[1;35m'
NC='\033[0m' # No Color


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

NODE_NAME="pm-devnode"
NODE_IMAGE="lts"
NODE_CPUS="8"
NODE_MEMORY="8G"
NODE_DISK="12G"
NODE_USER="ubuntu"
VERIFY_SETUP_SCRIPT="$REPO_ROOT/scripts/verify_setup.sh"

SSH_KEY_PATH="${HOME}/.ssh/${NODE_NAME}_ed25519"
SSH_KEY_COMMENT="${NODE_NAME}@$(hostname -s 2>/dev/null || hostname)"

usage() {
  cat <<EOF
Usage:
  $0 [options]

Summary:
  Create and provision a Multipass development node for EduMatcher with all necessary development tools, 
  a standard user, and SSH access. The script does NOT install EduMatcher; either as a cloned repo or via pipx.

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
    echo -e "❌ ${RED}Required command not found: $cmd${NC}" >&2
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
  echo -e "❌ ${RED}verify setup script not found: $VERIFY_SETUP_SCRIPT${NC}" >&2
  exit 1
fi

if multipass info "$NODE_NAME" >/dev/null 2>&1; then
  echo -e "❌ ${RED}A node named '$NODE_NAME' already exists. Delete it or choose another --name.${NC}" >&2
  exit 1
fi

mkdir -p "$(dirname "$SSH_KEY_PATH")"

# if [[ -f "$SSH_KEY_PATH" || -f "${SSH_KEY_PATH}.pub" ]]; then
#   echo "❌ SSH key path already exists: $SSH_KEY_PATH" >&2
#   echo "   Choose another --ssh-key path or remove the existing key files." >&2
#   exit 1
# fi

echo -e "${LIGHT_CYAN}=== EduMatcher Multipass Dev Node Setup ===${NC}"
echo ##
echo "Node name : $NODE_NAME"
echo "Image     : $NODE_IMAGE"
echo "CPUs      : $NODE_CPUS"
echo "Memory    : $NODE_MEMORY"
echo "Disk      : $NODE_DISK"
echo "User      : $NODE_USER"
echo "SSH key   : $SSH_KEY_PATH"
echo ""
echo -e "${LIGHT_CYAN}=== Starting setup process ===${NC}"
echo ""
echo "This will take about 10-15 minutes depending on your system and how many updates are available."
echo "So grab a coffee and please wait..."
echo ""

echo -e "${LIGHT_CYAN}1/5${NC} Launching a new Multipass node '$NODE_NAME'...${NC}"
if ! multipass launch "$NODE_IMAGE" \
  --name "$NODE_NAME" \
  --cpus "$NODE_CPUS" \
  --memory "$NODE_MEMORY" \
  --disk "$NODE_DISK"; then
  echo -e "❌ ${RED}Failed to launch Multipass node '$NODE_NAME' from image '$NODE_IMAGE'.${NC}" >&2
  echo -e "   ${YELLOW}Run 'multipass find' to list valid images on your host.${NC}" >&2
  exit 1
fi

echo -e "${LIGHT_CYAN}2/5${NC} Generating a fresh SSH key pair in the node..."
multipass exec ${NODE_NAME} -- bash -lc "ssh-keygen -t ed25519 -f \"/home/ubuntu/.ssh/id_ed25519\" -N \"\"" 
if [ $? -ne 0 ]; then
  echo -e "❌ ${RED}Failed to generate SSH key pair in the node.${NC}" >&2
  exit 1
fi

echo -e "${LIGHT_CYAN}3/5${NC} Installing the host SSH public key for passwordless login for user '$NODE_USER'..."

# Check that the host unique key for this instance exists
if [ ! -f ${SSH_KEY_PATH} ]; then
  echo -e "❌ ${RED}No host SSH key exists${NC}. Will create a new key-pair as in ${HOME}/.ssh/${NODE_NAME}" >&2
  ssh-keygen -f ${SSH_KEY_PATH} -t ed25519 -N ""  
fi

multipass transfer "${SSH_KEY_PATH}.pub" "$NODE_NAME:/tmp/${NODE_NAME}.pub" > /dev/null 
if [ $? -ne 0 ]; then
  echo -e "❌ ${RED}Failed to install the host SSH public key in the node.${NC}" >&2
  exit 1
fi

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
if [ $? -ne 0 ]; then
  echo -e "❌ ${RED}Failed to set up the authorized_keys for user '$NODE_USER'.${NC}" >&2
  exit 1
fi

VERIFY_SETUP_REMOTE_PATH="/home/$NODE_USER/verify_setup.sh"
VERIFY_LOG_REMOTE_PATH="/home/$NODE_USER/${NODE_NAME}_verify_setup.log"

echo -e "${LIGHT_CYAN}4/5${NC} Copying verify_setup.sh as the standard user..."
echo -e "    Will install poetry, xetex, pandoc, nodejs, npm, and Google Chrome."
echo -e "    Logging to '$VERIFY_LOG_REMOTE_PATH' on the node."
echo -e "    This will take some time..."

multipass transfer "$VERIFY_SETUP_SCRIPT" "$NODE_NAME:$VERIFY_SETUP_REMOTE_PATH" > /dev/null 
if [ $? -ne 0 ]; then
  echo -e "❌ ${RED}Failed to copy verify_setup.sh to the node.${NC}" >&2 
  exit 1
fi

echo "    Copied to: $VERIFY_SETUP_REMOTE_PATH"
multipass exec "$NODE_NAME" -- bash -lc "
  set -euo pipefail
  sudo chown '$NODE_USER:$NODE_USER' '$VERIFY_SETUP_REMOTE_PATH'
  chmod +x '$VERIFY_SETUP_REMOTE_PATH'
  '$VERIFY_SETUP_REMOTE_PATH' --yes > '$VERIFY_LOG_REMOTE_PATH' 2>&1"

if [ $? -ne 0 ]; then
  echo -e "❌ ${RED}verify_setup.sh failed. Check the log at '$VERIFY_LOG_REMOTE_PATH' on the node.${NC}" >&2
  exit 1
fi

echo -e "${LIGHT_CYAN}5/5${NC} Restarting and creating a snapshot of the node..."
echo "    Stopping the node..."
multipass stop "$NODE_NAME"
sleep 2  # Wait a few seconds for the node to stop

SNAPSHOT_NAME="pm-devnode-core"


#if multipass list --snapshots | grep "$SNAPSHOT_NAME" ; then
#  echo "    Deleting existing snapshot '$SNAPSHOT_NAME'..."
#  multipass delete "$SNAPSHOT_NAME" 
#  if [ $? -eq 0 ]; then
#    echo "    Existing snapshot '$SNAPSHOT_NAME' deleted."
#  else
#    echo -e "❌ ${RED}Failed to delete existing snapshot '$SNAPSHOT_NAME'.${NC}"
#    exit 1
#  fi
#fi

echo "    Creating snapshot '${SNAPSHOT_NAME}'..."
multipass snapshot "${NODE_NAME}" --name "${SNAPSHOT_NAME}" --comment "Core dev-node state with verify_setup.sh applied" > /dev/null

if [ $? -eq 0 ]; then
  echo "    Snapshot '${SNAPSHOT_NAME}' created successfully."
else
  echo -e "❌ ${RED}Failed to create snapshot '${SNAPSHOT_NAME}'.${NC}" >&2
  exit 1
fi

echo "    Starting the node..."
multipass start "$NODE_NAME"

if [ $? -ne 0 ]; then
  echo -e "❌ ${RED}Failed to start the node '${NODE_NAME}' after snapshotting.${NC}" >&2
  exit 1
fi

echo ""
echo "✅ Multipass development node '${NODE_NAME}' is ready."
echo ""
echo "Connect with:"
echo "  multipass shell ${NODE_NAME}"
echo ""
echo "SSH with:"
echo "  ssh -i $SSH_KEY_PATH $NODE_USER@$(multipass info ${NODE_NAME} | awk '/IPv4/ {print $2; exit}')"


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