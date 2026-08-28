#!/usr/bin/env bash
# Build and provision a multipass VM with a pinned EduMatcher runtime.
# Requires: multipass on the host machine.

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
WHITE='\033[1;37m'
TEAL='\033[0;36m'
GRAY='\033[0;37m'
DARK_GREY='\033[90m'
LIGHT_GRAY='\033[0;37m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Two levels up: this script lives in deployment/vm/, so the repository root —
# and the dist/ directory Poetry writes wheels into — is $SCRIPT_DIR/../..
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
INSTALL_SCRIPT="install_edumatcher.sh"

VM_NAME="ems"
VM_IMAGE="lts"
VM_CPUS="4"
VM_MEMORY="4G"
VM_DISK="6G"
CREATE_SNAPSHOT="true"
SNAPSHOT_NAME="clean"
VM_USER="ubuntu"
SSH_KEY_PATH="${HOME}/.ssh/${VM_NAME}_ed25519"
SSH_KEY_PATH_SET="false"

DEFAULT_VERSION="dev"
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
  --dev                        Install the local wheel file from /tmp/*.whl instead of downloading from PyPI.
  --snapshot                   Create a snapshot after provisioning (default: $CREATE_SNAPSHOT)
  --snapshot-name <name>       Snapshot name (default: $SNAPSHOT_NAME)
  --ssh-key <path>             Private key whose public half is installed for passwordless
                                login (default: \$HOME/.ssh/<vm-name>_ed25519)
  --help                       Show this help text

Example:
  $0 --name ems --version 0.20.1 --snapshot
  $0 --name ems --ssh-key ~/.ssh/id_ed25519
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
    --dev)
      EDUMATCHER_VERSION="dev"
      echo -e "${BLUE}Checking for local wheel file in $REPO_ROOT/dist/*.whl.${NC}"
      count=$(ls -1 "$REPO_ROOT/dist/"*.whl 2> /dev/null | wc -l)
      if [ $count -eq 0 ]; then
        echo -e "${RED}No local wheel file found in $REPO_ROOT/dist/*.whl for --dev installation.${NC}" 
        exit 1
      fi
      echo -e "${GREEN}Found $count wheel file(s) in $REPO_ROOT/dist/*.whl.${NC}"
      shift
      ;;
    --snapshot)
      CREATE_SNAPSHOT="true"
      shift
      ;;
    --snapshot-name)
      SNAPSHOT_NAME="${2:-}"
      shift 2
      ;;
    --ssh-key)
      SSH_KEY_PATH="${2:-}"
      SSH_KEY_PATH_SET="true"
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

if [[ "$SSH_KEY_PATH_SET" != "true" ]]; then
  SSH_KEY_PATH="${HOME}/.ssh/${VM_NAME}_ed25519"
fi

if ! command -v multipass >/dev/null 2>&1; then
  echo "multipass is required but not installed" >&2
  exit 1
fi

if multipass info "$VM_NAME" >/dev/null 2>&1; then
  echo "A VM named '$VM_NAME' already exists. Delete or use another --name." >&2
  exit 1
fi

if [[ ! -f "${SSH_KEY_PATH}.pub" ]]; then
  echo -e "${YELLOW}SSH public key not found: ${SSH_KEY_PATH}.pub${NC}. Will create it now." >&2
  ssh-keygen -t ed25519 -f "${SSH_KEY_PATH}" -N "" || exit 1
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
# --disk 8G

if ! multipass launch "$VM_IMAGE" \
  --name "$VM_NAME" \
  --cpus "$VM_CPUS" \
  --memory "$VM_MEMORY" \
  --disk "$VM_DISK"; then
  echo -e "${RED}Failed to launch image '$VM_IMAGE'.${NC}" >&2
  echo -e "${RED}Run 'multipass find' to list valid image names on your host.${NC}" >&2
  exit 1
fi

echo -e "${BLUE}Installing the host SSH public key for passwordless login for user '$VM_USER'...${NC}"
multipass transfer "${SSH_KEY_PATH}.pub" "$VM_NAME:/tmp/${VM_NAME}.pub"
multipass exec "$VM_NAME" -- bash -c "
  set -euo pipefail
  sudo install -d -m 700 -o '$VM_USER' -g '$VM_USER' '/home/$VM_USER/.ssh'
  sudo touch '/home/$VM_USER/.ssh/authorized_keys'
  sudo chown '$VM_USER:$VM_USER' '/home/$VM_USER/.ssh/authorized_keys'
  sudo chmod 600 '/home/$VM_USER/.ssh/authorized_keys'
  cat '/tmp/${VM_NAME}.pub' | sudo tee -a '/home/$VM_USER/.ssh/authorized_keys' >/dev/null
  sudo chown '$VM_USER:$VM_USER' '/home/$VM_USER/.ssh/authorized_keys'
  rm -f '/tmp/${VM_NAME}.pub'
"
if [[ $? -ne 0 ]]; then
  echo -e "${RED}Failed to install the host SSH public key in the VM.${NC}" >&2
  multipass delete --purge "$VM_NAME"
  exit 1
fi

echo -e "${BLUE}Installing provisioning script...${NC}"
multipass transfer "$SCRIPT_DIR/$INSTALL_SCRIPT" "$VM_NAME:/tmp/$INSTALL_SCRIPT"

echo -e "${BLUE}Now provisioning EduMatcher $EDUMATCHER_VERSION...${NC}"

# Start by upgrading the VM's packages
multipass exec "$VM_NAME" -- sudo apt-get upgrade -y

# Run the provisioning script with the specified version. 
# The script will install Python, create a virtual environment, 
# install the specified version of edumatcher, and symlink the console scripts.
multipass exec "$VM_NAME" -- sudo chmod +x /tmp/"$INSTALL_SCRIPT"
if [[ "$EDUMATCHER_VERSION" == "latest" ]]; then
  multipass exec "$VM_NAME" -- sudo /tmp/"$INSTALL_SCRIPT"
elif [[ "$EDUMATCHER_VERSION" == "dev" ]]; then
  echo -e "${BLUE}Transferring local wheel file to VM for dev installation...${NC}"
  echo -e "${BLUE}Looking for wheel file in \"$REPO_ROOT/dist/*.whl\" to \"$VM_NAME:/tmp/\"...${NC}"
  multipass transfer $REPO_ROOT/dist/*.whl $VM_NAME:/tmp/
  echo -e "${GREEN}Installing local wheel file DONE.${NC}"
  multipass exec "$VM_NAME" -- sudo /tmp/"$INSTALL_SCRIPT" --dev
else
  multipass exec "$VM_NAME" -- sudo /tmp/"$INSTALL_SCRIPT" --version "$EDUMATCHER_VERSION"
fi

if [[ $? -ne 0 ]]; then
  echo -e "${RED}Provisioning failed. Please check the output above for errors.${NC}" >&2
  multipass delete --purge "$VM_NAME"
  exit 1
fi

# Setup a session directory with a sample session file for testing.
multipass exec "$VM_NAME" -- mkdir -p /home/ubuntu/session

# Run pm-setup to create a sample session file. This also verifies that the installed runtime is working.
multipass exec "$VM_NAME" -- bash -c "cd /home/ubuntu/session && pm-setup --force"

# Add EDUMATCHER_DATA_DIR to the default .bashrc for convenience. It is the only
# location variable: pm-setup has already deployed the sample configuration to
# <DATA_DIR>/ref_data/engine_config.yaml, which is where every process reads it.
multipass exec "$VM_NAME" -- bash -c "echo 'export EDUMATCHER_DATA_DIR=\"/home/ubuntu/.local/share/edumatcher\"' >> ~/.bashrc"

if [[ "$CREATE_SNAPSHOT" == "true" ]]; then
  echo -e "${BLUE}Stopping VM '$VM_NAME' before snapshot...${NC}"
  multipass stop "$VM_NAME"

  echo -e "${BLUE}Creating snapshot '$SNAPSHOT_NAME'...${NC}"
  multipass snapshot "$VM_NAME" --name "$SNAPSHOT_NAME"

  echo -e "${BLUE}Starting VM '$VM_NAME' after snapshot...${NC}"
  multipass start "$VM_NAME"
fi

sleep 2 # Give the VM a moment to start and get an IP address

VM_IP=$(multipass info "$VM_NAME" | grep IP |  grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+')

# Exatract the ADMIN (operator) API_KEY from the VM's .local/share/edumatcher directory. This is the key that can be used to access the API Gateway.
# grep -E "^[ ]+\- api_key: [a-z0-9-]+" .local/share/edumatcher/ref_data/engine_config.yaml  |  grep "ops01" | awk -F ':' '{print $2}'| cut -c 2-
ADMIN_API_KEY=$(multipass exec "$VM_NAME" -- bash -c "cat /home/ubuntu/.local/share/edumatcher/ref_data/engine_config.yaml | grep -E '^[ ]+\- api_key: [a-z0-9-]+' | grep 'ops01' | awk -F ':' '{print \$2}' | cut -c 2-")
TRADER01_API_KEY=$(multipass exec "$VM_NAME" -- bash -c "cat /home/ubuntu/.local/share/edumatcher/ref_data/engine_config.yaml | grep -E '^[ ]+\- api_key: [a-z0-9-]+' | grep 'trader01' | awk -F ':' '{print \$2}' | cut -c 2-")
TRADER02_API_KEY=$(multipass exec "$VM_NAME" -- bash -c "cat /home/ubuntu/.local/share/edumatcher/ref_data/engine_config.yaml | grep -E '^[ ]+\- api_key: [a-z0-9-]+' | grep 'trader02' | awk -F ':' '{print \$2}' | cut -c 2-")
MM01_API_KEY=$(multipass exec "$VM_NAME" -- bash -c "cat /home/ubuntu/.local/share/edumatcher/ref_data/engine_config.yaml | grep -E '^[ ]+\- api_key: [a-z0-9-]+' | grep 'mm01' | awk -F ':' '{print \$2}' | cut -c 2-")

echo -e "--------------------------------------------------------------------------"
echo -e "${GREEN}VM '$VM_NAME' is ready with EduMatcher $EDUMATCHER_VERSION installed.${NC}"
echo ""
echo -e "${DARK_GRAY}Open a shell into the VM:${NC}" "\t\t${WHITE}multipass shell $VM_NAME${NC}"
echo -e "${DARK_GRAY}Change to the session directory:${NC}" "\t${WHITE}cd /home/ubuntu/session${NC}"
echo ""
echo -e "${DARK_GRAY}Start the system:${NC}" "\t\t\t${WHITE}pm-opctl-cli start${NC}"
echo -e "${DARK_GRAY}Stop the system:${NC}" "\t\t\t${WHITE}pm-opctl-cli stop${NC}"
echo ""
echo -e "${DARK_GRAY}Check the installed pm-* commands:${NC}" "\t${WHITE}ls -1 /usr/local/bin/pm-*${NC}"
echo -e "${DARK_GRAY}To list all running processes:${NC}" "\t\t${WHITE}pm-opctl-cli list${NC}"
echo -e "${DARK_GRAY}Restore snapshot:${NC}" "\t\t\t${WHITE}multipass restore -d $VM_NAME.$SNAPSHOT_NAME${NC}"
echo -e "${DARK_GRAY}Delete VM:${NC}" "\t\t\t\t${WHITE}multipass delete --purge $VM_NAME${NC}"
echo -e "${DARK_GRAY}List all VMs:${NC}" "\t\t\t\t${WHITE}multipass list${NC}"
echo -e "${DARK_GRAY}List all snapshots:${NC}" "\t\t\t${WHITE}multipass list --snapshots${NC}"
echo -e "${DARK_GRAY}Delete snapshot:${NC}" "\t\t\t${WHITE}multipass delete --purge $VM_NAME.$SNAPSHOT_NAME${NC}"
echo -e ""
echo -e "${DARK_GRAY}The VM is running as non-root user: \t${YELLOW}ubuntu${NC}"
echo -e "${DARK_GRAY}VM IP address: \t\t\t\t${YELLOW}$VM_IP${NC}"
echo ""
echo -e "${DARK_GRAY}To connect to the VM via SSH:${NC}" "\t\t${WHITE}ssh -i $SSH_KEY_PATH ubuntu@$VM_IP${NC}"
echo ""
echo -e "${DARK_GRAY}Admin API Key: \t\t\t\t${YELLOW}$ADMIN_API_KEY${NC}"
echo -e "${DARK_GRAY}Trader01 API Key: \t\t\t${YELLOW}$TRADER01_API_KEY${NC}"
echo -e "${DARK_GRAY}Trader02 API Key: \t\t\t${YELLOW}$TRADER02_API_KEY${NC}"
echo -e "${DARK_GRAY}MM01 API Key: \t\t\t\t${YELLOW}$MM01_API_KEY${NC}"
echo ""
echo -e "${DARK_GRAY}To access the EduMatcher API Gateway:${NC}" "\t${WHITE}curl -s -H \"Authorization: Bearer <token>\" http://$VM_IP:8080/api/v1/${NC}"
echo -e "${DARK_GRAY}For example:${NC}"
echo -e "${WHITE}curl -s -H \"Authorization: Bearer ${ADMIN_API_KEY}\" http://$VM_IP:8080/api/v1/symbols${NC}"
echo -e "${WHITE}curl -s -H \"Authorization: Bearer ${ADMIN_API_KEY}\" http://$VM_IP:8080/api/v1/status${NC}"
echo -e "--------------------------------------------------------------------------"
echo "" 
exit 0