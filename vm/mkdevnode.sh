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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

source ${REPO_ROOT}/scripts/print_funcs.inc

NODE_NAME="pm-devnode"
NODE_IMAGE="lts"
NODE_CPUS="8"
NODE_MEMORY="10G"
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

multi_exec_shell() {
  local cmd="$1"
  multipass exec "$NODE_NAME" -- bash -lc "${cmd}"
}

multi_cp() {
  local src="$1"
  local dest="$2"
  multipass transfer ${src} "${NODE_NAME}:${dest}" > /dev/null
}

multi_stop() {
  multipass stop "$NODE_NAME"
}

multi_start() {
  multipass start "$NODE_NAME"
}

multi_delete() {
  multipass delete --purge "$NODE_NAME"
}

multi_launch() {
  local cmd="$1"
  multipass launch "${cmd}"
}

multi_snap() {
  multipass snapshot "${NODE_NAME}" --name "${SNAPSHOT_NAME}" --comment "Core dev-node state with verify_setup.sh applied" > /dev/null
}

multi_info() {
  multipass info "${NODE_NAME}"
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
    --delete)
      multi_delete
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
  print_error_colored "verify setup script not found: $VERIFY_SETUP_SCRIPT"
  exit 1
fi

if multi_info > /dev/null 2>&1; then
  print_error_colored "A node named '$NODE_NAME' already exists. Delete it or choose another --name."
  exit 1
fi

mkdir -p "$(dirname "$SSH_KEY_PATH")"

# if [[ -f "$SSH_KEY_PATH" || -f "${SSH_KEY_PATH}.pub" ]]; then
#   echo "❌ SSH key path already exists: $SSH_KEY_PATH" >&2
#   echo "   Choose another --ssh-key path or remove the existing key files." >&2
#   exit 1
# fi

print_header "EduMatcher Multipass Dev Node Setup"
print_plain ""
print_plain "Node name : $NODE_NAME"
print_plain "Image     : $NODE_IMAGE"
print_plain "CPUs      : $NODE_CPUS"
print_plain "Memory    : $NODE_MEMORY"
print_plain "Disk      : $NODE_DISK"
print_plain "User      : $NODE_USER"
print_plain "SSH key   : $SSH_KEY_PATH"
print_plain ""
print_header "Starting setup process"
print_plain ""
print_plain "This will take about 10-15 minutes depending on your system and how many updates are available."
print_plain "So grab a coffee and please wait..."
print_plain ""

print_step_colored "1/5" "Launching a new Multipass node \"$NODE_NAME\"..."
if ! multipass launch "$NODE_IMAGE" \
  --name "$NODE_NAME" \
  --cpus "$NODE_CPUS" \
  --memory "$NODE_MEMORY" \
  --disk "$NODE_DISK" > /dev/null ; then
  print_error_colored "Failed to launch Multipass node '$NODE_NAME' from image '$NODE_IMAGE'."
  exit 1
fi

print_step_colored "2/5" "Generating a fresh SSH key pair in the node..."
multi_exec_shell 'ssh-keygen -t ed25519 -f /home/ubuntu/.ssh/id_ed25519 -N "" > /home/ubuntu/ssh-keygen.log'
if [ $? -ne 0 ]; then
  print_error_colored "Failed to generate SSH key pair in the node."
  exit 1
fi

print_step_colored "3/5" "Installing the host SSH public key for passwordless login for user '$NODE_USER'..."
multi_cp "${SSH_KEY_PATH}.pub" "/tmp/${NODE_NAME}.pub"
if [ $? -ne 0 ]; then
  print_error_colored "Failed to install the host SSH public key in the node."
  exit 1
fi

multi_exec_shell "
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
  print_error_colored "Failed to set up the authorized_keys for user '$NODE_USER'."
  exit 1
fi

VERIFY_SETUP_REMOTE_PATH="/home/$NODE_USER/verify_setup.sh"
VERIFY_LOG_REMOTE_PATH="/home/$NODE_USER/${NODE_NAME}_verify_setup.log"

print_step_colored "4/5" "Running installation script."
print_plain "    Will install poetry, xetex, pandoc, nodejs, npm, and Google Chrome."
print_plain "    Logging process to '$VERIFY_LOG_REMOTE_PATH' in the node."
print_plain "    This will take 5-10min. Please hang on..."

multi_cp "$VERIFY_SETUP_SCRIPT" "$VERIFY_SETUP_REMOTE_PATH" 
if [ $? -ne 0 ]; then
  print_error_colored "Failed to copy verify_setup.sh to the node."
  exit 1
fi

multi_exec_shell "
  set -euo pipefail
  sudo chown '$NODE_USER:$NODE_USER' '$VERIFY_SETUP_REMOTE_PATH'
  chmod +x '$VERIFY_SETUP_REMOTE_PATH'
  '$VERIFY_SETUP_REMOTE_PATH' --yes > '$VERIFY_LOG_REMOTE_PATH' 2>&1"

if [ $? -ne 0 ]; then
  print_error_colored "verify_setup.sh failed. Check the log at '$VERIFY_LOG_REMOTE_PATH' on the node."
  exit 1
fi

print_step_colored "5/5" "Restarting and creating a snapshot of the node..."
print_plain "    Stopping the node..."
multi_stop 
sleep 2  # Wait a few seconds for the node to stop

SNAPSHOT_NAME="pm-devnode-core"

print_plain "    Creating snapshot '${SNAPSHOT_NAME}'..."
multi_snap 

if [ $? -eq 0 ]; then
  print_success_colored "    Snapshot '${SNAPSHOT_NAME}' created."
else
  print_error_colored "Failed to create snapshot '${SNAPSHOT_NAME}'."
  exit 1
fi

print_plain "    Starting the node..."
multi_start

if [ $? -ne 0 ]; then
  print_error_colored "Failed to start the node '${NODE_NAME}' after snapshotting."
  exit 1
fi

print_plain ""
print_success_colored "Multipass development node '${NODE_NAME}' is ready."
print_plain ""
print_plain "Connect with:"
print_plain "  multipass shell ${NODE_NAME}"
print_plain ""
print_plain "SSH with:"
print_plain "  ssh -i $SSH_KEY_PATH $NODE_USER@$(multipass info ${NODE_NAME} | awk '/IPv4/ {print $2; exit}')"


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