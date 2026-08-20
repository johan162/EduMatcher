#!/usr/bin/env bash
# Update the multipass with latest dev-version of EduMatcher runtime.
# Requires: multipass on the host machine.
#
# NEW|SYM=AAPL|QTY=300|PRICE=123.90|TYPE=LIMIT|SMP=CANCEL_AGGRESSOR|SIDE=BUY
#
# Loading

# Design a.utility pm-show-config (create the script under src/edumatcher/config-show/) and add a short-link in pyproject.toml . The application shows by default shows the essential information from the current engine_configuration.yaml in the available space in the terminal it is running in. It should dynamially adapt to make maximum use of the space and use colors and ASCII line-drawing as needed to highlight the key information.
# The python script is only to read the engine_config.yaml and make no data modifications. The following options shoud at minimum be supported

# "---file, -f" Possibility to specify which *.yaml file should be read
# "--more, -m" Show more information than the default making use of every available space.
# "--all, -a" Show all information most likely force vertical scrolling

# There is a lot of information and everything will not fit on screen. Be clever, could we use a double buffer of the terminal to smoothly switch screen buffers?

# A good logical layout makeing use of available space requires carefull planning. If the terminal is really small we ahould just show some basic summary.

# The default engine config should be read from the current data directory (under ref_data/ as is resolved by the `config.py:_resolve_data_dir()
# 

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
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