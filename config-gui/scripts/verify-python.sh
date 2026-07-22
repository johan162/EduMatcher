#!/usr/bin/env bash
#
# Golden-file cross-language check (design §12.4 / §18).
#
# Generates representative configs through the GUI codec and pipes each through
# the real Python `load_engine_config()` to guarantee GUI output stays
# parser-valid. Run from the config-gui directory. Requires the edumatcher
# Python environment (poetry) to be installed at the repo root.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"
OUT_DIR="$HERE/.fixtures"

echo "Generating fixtures -> $OUT_DIR"
(cd "$HERE" && npx tsx scripts/generate-fixtures.ts "$OUT_DIR")

echo "Validating with load_engine_config()"
status=0
for f in "$OUT_DIR"/*.yaml; do
  printf '  %-32s ' "$(basename "$f")"
  if (cd "$REPO_ROOT" && poetry run python -c "
from pathlib import Path
from edumatcher.engine.config_loader import load_engine_config
load_engine_config(Path('$f'))
print('OK')
"); then
    :
  else
    status=1
  fi
done

exit "$status"
