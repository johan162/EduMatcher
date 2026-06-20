#!/usr/bin/env bash
# Install a pinned EduMatcher runtime inside a VM.
# - Creates /opt/edumatcher/.venv
# - Installs edumatcher==<version>
# - Symlinks every pm-* console script to /usr/local/bin

set -euo pipefail

PACKAGE_NAME="edumatcher"
VENV_DIR="/opt/edumatcher/.venv"
RUNTIME_USER="edumatcher"
VERSION=""
PYTHON_BIN=""

usage() {
  cat <<'EOF'
Usage:
  sudo ./install_edumatcher_runtime.sh [--version <pypi-version>]

Options:
  --version   Optional. PyPI version to install, for example 0.7.1
              If omitted, installs latest available release.
  --help      Show this help text
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="${2:-}"
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

if [[ "${EUID}" -ne 0 ]]; then
  echo "This script must be run as root" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates \
  python3 \
  python3-venv \
  python3-pip

for candidate in python3.13 python3.14 python3.15 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" - <<'PY'
import sys
sys.exit(0 if sys.version_info >= (3, 13) else 1)
PY
    then
      PYTHON_BIN="$candidate"
      break
    fi
  fi
done

if [[ -z "$PYTHON_BIN" ]]; then
  echo "Python >= 3.13 is required but was not found in this VM image." >&2
  echo "Use a newer Multipass image (for example 'lts' or '26.04')." >&2
  exit 1
fi

if ! id -u "$RUNTIME_USER" >/dev/null 2>&1; then
  useradd -m -s /bin/bash "$RUNTIME_USER"
fi

mkdir -p /opt/edumatcher
"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
if [[ -n "$VERSION" && "$VERSION" != "latest" ]]; then
  "$VENV_DIR/bin/pip" install "${PACKAGE_NAME}==${VERSION}"
else
  "$VENV_DIR/bin/pip" install "${PACKAGE_NAME}"
fi

mapfile -t PM_COMMANDS < <("$VENV_DIR/bin/python" - <<'PY'
from importlib.metadata import distribution

entry_points = distribution("edumatcher").entry_points
pm_commands = sorted(
    ep.name for ep in entry_points
    if ep.group == "console_scripts" and ep.name.startswith("pm-")
)
for command_name in pm_commands:
    print(command_name)
PY
)

if [[ ${#PM_COMMANDS[@]} -eq 0 ]]; then
  echo "No pm-* commands discovered in installed edumatcher distribution" >&2
  exit 1
fi

for command_name in "${PM_COMMANDS[@]}"; do
  source_path="$VENV_DIR/bin/$command_name"
  target_path="/usr/local/bin/$command_name"
  if [[ ! -x "$source_path" ]]; then
    echo "Expected executable not found: $source_path" >&2
    exit 1
  fi
  ln -sf "$source_path" "$target_path"
done

INSTALLED_VERSION="$("$VENV_DIR/bin/python" - <<'PY'
from importlib.metadata import version
print(version("edumatcher"))
PY
)"

chown -R "$RUNTIME_USER:$RUNTIME_USER" /opt/edumatcher
printf '%s\n' "$INSTALLED_VERSION" > /opt/edumatcher/EDUMATCHER_VERSION

echo "Installed ${PACKAGE_NAME}==${INSTALLED_VERSION}"
echo "Linked pm-* commands in /usr/local/bin:"
printf '  - %s\n' "${PM_COMMANDS[@]}"
