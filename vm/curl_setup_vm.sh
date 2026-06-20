#!/usr/bin/env bash
# Bootstrap EduMatcher VM build without cloning the full repository.
# This script is intended to be executed via curl | bash.

set -euo pipefail

REPO_OWNER="${REPO_OWNER:-johan162}"
REPO_NAME="${REPO_NAME:-EduMatcher}"
REPO_REF="${REPO_REF:-main}"
WORK_DIR="${WORK_DIR:-$(mktemp -d)}"
KEEP_WORK_DIR="${KEEP_WORK_DIR:-0}"

BASE_URL="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/${REPO_REF}/vm"
BUILD_SCRIPT_PATH="$WORK_DIR/build_multipass_vm.sh"
INSTALL_SCRIPT_PATH="$WORK_DIR/install_edumatcher_runtime.sh"

cleanup() {
  if [[ "$KEEP_WORK_DIR" != "1" ]]; then
    rm -rf "$WORK_DIR"
  else
    echo "Keeping downloaded files in: $WORK_DIR"
  fi
}
trap cleanup EXIT

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required but not installed" >&2
  exit 1
fi

if ! command -v multipass >/dev/null 2>&1; then
  echo "multipass is required but not installed" >&2
  exit 1
fi

echo "Downloading VM scripts from ${REPO_OWNER}/${REPO_NAME}@${REPO_REF}..."
curl -fsSL "${BASE_URL}/build_multipass_vm.sh" -o "$BUILD_SCRIPT_PATH"
curl -fsSL "${BASE_URL}/install_edumatcher_runtime.sh" -o "$INSTALL_SCRIPT_PATH"
chmod +x "$BUILD_SCRIPT_PATH" "$INSTALL_SCRIPT_PATH"

echo "Starting VM build..."
"$BUILD_SCRIPT_PATH" "$@"
