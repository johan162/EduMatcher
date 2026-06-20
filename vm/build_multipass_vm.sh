#!/usr/bin/env bash
# Build and provision a VM with a pinned EduMatcher runtime.
# Requires: multipass on the host machine.

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

VM_NAME="edumatcher-vm"
VM_IMAGE="lts"
VM_CPUS="2"
VM_MEMORY="3G"
VM_DISK="10G"
CREATE_SNAPSHOT="true"
SNAPSHOT_NAME="clean-runtime"

if [[ -f "$REPO_ROOT/pyproject.toml" ]]; then
  DEFAULT_VERSION="$(grep '^version\s*=\s*"' "$REPO_ROOT/pyproject.toml" | head -1 | cut -d '"' -f2)"
else
  DEFAULT_VERSION="latest"
fi
EDUMATCHER_VERSION="$DEFAULT_VERSION"

usage() {
  cat <<EOF
Usage:
  $0 [options]

Options:
  --name <vm-name>             VM name (default: $VM_NAME)
  --image <image>              Multipass image (default: $VM_IMAGE)
  --cpus <count>               CPU count (default: $VM_CPUS)
  --memory <size>              RAM size, ex: 2G (default: $VM_MEMORY)
  --disk <size>                Disk size, ex: 12G (default: $VM_DISK)
  --version <pypi-version>     EduMatcher version (default: $DEFAULT_VERSION)
  --snapshot                   Create a snapshot after provisioning (default: $CREATE_SNAPSHOT)
  --snapshot-name <name>       Snapshot name (default: $SNAPSHOT_NAME)
  --help                       Show this help text

Example:
  $0 --name edumatcher-071 --version 0.7.1 --snapshot
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)
      VM_NAME="${2:-}"
      shift 2
      ;;
    --image)
      VM_IMAGE="${2:-}"
      shift 2
      ;;
    --cpus)
      VM_CPUS="${2:-}"
      shift 2
      ;;
    --memory)
      VM_MEMORY="${2:-}"
      shift 2
      ;;
    --disk)
      VM_DISK="${2:-}"
      shift 2
      ;;
    --version)
      EDUMATCHER_VERSION="${2:-}"
      shift 2
      ;;
    --snapshot)
      CREATE_SNAPSHOT="true"
      shift
      ;;
    --snapshot-name)
      SNAPSHOT_NAME="${2:-}"
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

if ! command -v multipass >/dev/null 2>&1; then
  echo "multipass is required but not installed" >&2
  exit 1
fi

if multipass info "$VM_NAME" >/dev/null 2>&1; then
  echo "A VM named '$VM_NAME' already exists. Delete or use another --name." >&2
  exit 1
fi

echo -e "${BLUE}Launching VM '$VM_NAME' from image '$VM_IMAGE'...${NC}"

# multipass Command Line:
echo "Using multipass with the following options:"
cat <<EOF
--name $VM_NAME
--image $VM_IMAGE
--cpus $VM_CPUS
--memory $VM_MEMORY
--disk $VM_DISK
EOF

# --name edumatcher-vm
# --image lts
# --cpus 2
# --memory 3G
# --disk 10G

if ! multipass launch "$VM_IMAGE" \
  --name "$VM_NAME" \
  --cpus "$VM_CPUS" \
  --memory "$VM_MEMORY" \
  --disk "$VM_DISK"; then
  echo -e "${RED}Failed to launch image '$VM_IMAGE'.${NC}" >&2
  echo -e "${RED}Run 'multipass find' to list valid image names on your host.${NC}" >&2
  exit 1
fi

echo -e "${BLUE}Copying provisioning script...${NC}"
multipass transfer "$SCRIPT_DIR/install_edumatcher_runtime.sh" "$VM_NAME:/tmp/install_edumatcher_runtime.sh"

echo -e "${BLUE}Provisioning EduMatcher $EDUMATCHER_VERSION...${NC}"

# Start by upgrading the VM's packages
multipass exec "$VM_NAME" -- sudo apt-get upgrade -y

# Run the provisioning script with the specified version. 
# The script will install Python, create a virtual environment, 
# install the specified version of edumatcher, and symlink the console scripts.
multipass exec "$VM_NAME" -- sudo chmod +x /tmp/install_edumatcher_runtime.sh
if [[ "$EDUMATCHER_VERSION" == "latest" ]]; then
  multipass exec "$VM_NAME" -- sudo /tmp/install_edumatcher_runtime.sh
else
  multipass exec "$VM_NAME" -- sudo /tmp/install_edumatcher_runtime.sh --version "$EDUMATCHER_VERSION"
fi

# Setup a session directory with a sample session file for testing.
multipass exec "$VM_NAME" -- mkdir -p /home/ubuntu/session

# Run pm-setup to create a sample session file. This also verifies that the installed runtime is working.
multipass exec "$VM_NAME" -- bash -c "cd /home/ubuntu/session && pm-setup --force"

# Add EDUMATCHER_DATA_DIR, and EDUMATCHER_CONFIG to the default .bashrc for convenience.
multipass exec "$VM_NAME" -- bash -c "echo 'export EDUMATCHER_DATA_DIR=\"/home/ubuntu/.local/share/edumatcher\"' >> ~/.bashrc"
multipass exec "$VM_NAME" -- bash -c "echo 'export EDUMATCHER_CONFIG=\"/home/ubuntu/session/engine_config.yaml\"' >> ~/.bashrc"

if [[ "$CREATE_SNAPSHOT" == "true" ]]; then
  echo -e "${BLUE}Stopping VM '$VM_NAME' before snapshot...${NC}"
  multipass stop "$VM_NAME"

  echo -e "${BLUE}Creating snapshot '$SNAPSHOT_NAME'...${NC}"
  multipass snapshot "$VM_NAME" --name "$SNAPSHOT_NAME"

  echo -e "${BLUE}Starting VM '$VM_NAME' after snapshot...${NC}"
  multipass start "$VM_NAME"
fi

echo -e "${GREEN}VM '$VM_NAME' is ready with EduMatcher $EDUMATCHER_VERSION installed.${NC}"

echo -e "${BLUE}You can now open a shell into the VM and start using EduMatcher:${NC}"
echo -e "${YELLOW}multipass shell $VM_NAME${NC}"
echo -e "${BLUE}Inside the VM, you can check the installed pm-* commands:${NC}"
echo -e "${YELLOW}ls -1 /usr/local/bin/pm-*${NC}"
echo -e "${BLUE}And start a minimal session:${NC}"
echo -e "${YELLOW}cd /home/ubuntu/session${NC}"
echo -e "${YELLOW}pm-engine --verbose${NC}"


