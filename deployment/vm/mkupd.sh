#!/usr/bin/env bash
# Update the multipass with latest dev-version of EduMatcher runtime.
# Requires: multipass on the host machine.
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Two levels up: this script lives in deployment/vm/, so the repository root —
# holding pyproject.toml and the dist/ wheel — is $SCRIPT_DIR/../..
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VM_NAME="ems"
VERSION=$(grep '^version' "$REPO_ROOT/pyproject.toml" | head -1 | cut -d'"' -f2)

PACKAGE_NAME="edumatcher"
INSTALL_SCRIPT="install_edumatcher.sh"
WHEEL_SOURCE="$REPO_ROOT/dist/${PACKAGE_NAME}-${VERSION}-py3-none-any.whl"

usage() {
  echo "Usage: $0 [--vm-name <name>] [--help]"
  echo ""
  echo "Update the Edu´Matcher release in the given VM to latest build of version $VERSION."
  echo ""
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --help)
      usage
      exit 0
      ;;
    --vm-name)
      VM_NAME="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

# Print all variables for debugging
echo "----------------------------------------"
echo "VERSION: $VERSION"
echo "PACKAGE_NAME: $PACKAGE_NAME"
echo "INSTALL_SCRIPT: $INSTALL_SCRIPT"
echo "WHEEL_SOURCE: $WHEEL_SOURCE"
echo "REPO_ROOT: $REPO_ROOT"
echo "SCRIPT_DIR: $SCRIPT_DIR"
echo "----------------------------------------"

# Make sure the WHEEL_SOURCE file actually exists before attempting to transfer it.
if [[ ! -f "$WHEEL_SOURCE" ]]; then
  echo "** Wheel file not found: $WHEEL_SOURCE" >&2
  exit 1
fi


# Clear any wheel left behind by an earlier build so the --dev glob resolves
# to exactly the wheel transferred below.
multipass exec "$VM_NAME" -- sudo bash -c 'rm -f /tmp/*.whl'

if ! multipass transfer "$WHEEL_SOURCE" "$VM_NAME":/tmp/; then
  echo "** Failed to transfer wheel file to VM. Ensure the VM is running and multipass is installed."
  exit 1
fi

echo "Wheel file transferred to VM. Installing the package..."

# Re-run the provisioning script rather than calling pip directly: it installs
# the transferred wheel and refreshes the /usr/local/bin/pm-* symlinks, so
# commands added by a new build become available.
# We always re-install the INSTALL_SCRIPT so we pick up any changes to it.
multipass transfer "$SCRIPT_DIR/$INSTALL_SCRIPT" "$VM_NAME:/opt/$INSTALL_SCRIPT"

if ! multipass exec "$VM_NAME" -- sudo bash /opt/"$INSTALL_SCRIPT" --dev; then
  echo "Failed to update the package in the VM."
  exit 1
fi

echo "EduMatcher runtime updated to latest build of version $VERSION."