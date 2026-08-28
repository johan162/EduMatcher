#!/usr/bin/env bash
# Update the multipass with latest dev-version of EduMatcher runtime.
# Requires: multipass on the host machine.
#
# NEW|SYM=AAPL|QTY=300|PRICE=123.90|TYPE=LIMIT|SMP=CANCEL_AGGRESSOR|SIDE=BUY
#
# Loading


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Two levels up: this script lives in deployment/vm/, so the repository root —
# holding pyproject.toml and the dist/ wheel — is $SCRIPT_DIR/../..
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VM_NAME="ems"
VERSION=$(grep '^version' "$REPO_ROOT/pyproject.toml" | head -1 | cut -d'"' -f2)

PACKAGE_NAME="edumatcher"
VENV_DIR="/opt/edumatcher/.venv"
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
echo "VENV_DIR: $VENV_DIR"
echo "WHEEL_SOURCE: $WHEEL_SOURCE"
echo "REPO_ROOT: $REPO_ROOT"
echo "SCRIPT_DIR: $SCRIPT_DIR"
echo "----------------------------------------"

if ! multipass transfer "$WHEEL_SOURCE" "$VM_NAME":/tmp/; then
  echo "Failed to transfer wheel file to VM. Ensure the VM is running and multipass is installed."
  exit 1
fi

echo "Wheel file transferred to VM. Installing the package..."

multipass exec "$VM_NAME" -- sudo bash -c "source $VENV_DIR/bin/activate && pip install --upgrade --force-reinstall $PACKAGE_NAME > /tmp/edumatcher_update.log 2>&1"

if [ ! $? -eq 0 ]; then
  echo "Failed to update the package in the VM."
  exit 1
fi

echo "EduMatcher runtime updated to latest build of version $VERSION."