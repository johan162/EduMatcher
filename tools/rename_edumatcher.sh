#!/usr/bin/env bash
# EduMatcher -> Tirnex rename helper.
#
# SAFE BY DEFAULT: with no arguments (or --dry-run), this script only
# REPORTS what it would do. It never writes, moves, or deletes anything
# unless you pass --apply explicitly.
#
# Usage:
#   ./rename_edumatcher.sh                 # dry run, full report
#   ./rename_edumatcher.sh --apply         # actually rename files + rewrite content
#   ./rename_edumatcher.sh --apply --files-only   # only git mv the files, skip content rewrite
#   ./rename_edumatcher.sh --apply --content-only # only rewrite content, skip file renames
#
# Run from the repo root. Requires: git, grep, sed (GNU or BSD), find.
#
# What it does NOT do (see rename_plan.md for why):
#   - Does not touch CHANGELOG.md or TODO.md (historical record).
#   - Does not touch dist/, site/, .venv/, caches (rebuild these instead).
#   - Does not regenerate docs/examples/generated/* (run pm-msgen after).
#   - Does not touch PyPI, TestPyPI, or GHCR (external services; see plan).
#   - Does not rename the GitHub repo (do that via GitHub UI/API last).
#   - Does not rename EDUMATCHER_* env vars unless RENAME_ENV=1 (separate
#     decision from the plan re: backward-compat shim).

set -euo pipefail

# ---- Configuration: the new names --------------------------------------
# Confirm these before running with --apply. Override via env vars if needed.
OLD_PASCAL="${OLD_PASCAL:-EduMatcher}"
OLD_LOWER="${OLD_LOWER:-edumatcher}"
OLD_UPPER="${OLD_UPPER:-EDUMATCHER}"

NEW_PASCAL="${NEW_PASCAL:-Tirnex}"
NEW_LOWER="${NEW_LOWER:-tirnex}"
NEW_UPPER="${NEW_UPPER:-TIRNEX}"

APPLY=0
DO_FILES=1
DO_CONTENT=1
RENAME_ENV="${RENAME_ENV:-0}"   # set to 1 to also rewrite EDUMATCHER_* env vars

for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --dry-run) APPLY=0 ;;
    --files-only) DO_CONTENT=0 ;;
    --content-only) DO_FILES=0 ;;
    --rename-env) RENAME_ENV=1 ;;
    -h|--help)
      sed -n '2,25p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 1
      ;;
  esac
done

if [ ! -d .git ]; then
  echo "Run this from the repository root (no .git found here)." >&2
  exit 1
fi

# Paths excluded from content rewriting: historical records and generated/
# derived artifacts that should be regenerated instead of hand-edited.
EXCLUDE_PATHSPECS=(
  ':!CHANGELOG.md'
  ':!TODO.md'
  ':!dist/*'
  ':!site/*'
  ':!build-tools/node_modules/*'
  ':!docs/examples/generated/*'
  ':!poetry.lock'
)

echo "=== EduMatcher -> Tirnex rename helper ==="
echo "Mode: $([ "$APPLY" -eq 1 ] && echo APPLY || echo DRY-RUN)"
echo "Files: $DO_FILES   Content: $DO_CONTENT   Rename env vars: $RENAME_ENV"
echo

# -------------------------------------------------------------------------
# Step 1: file/directory renames
# -------------------------------------------------------------------------
if [ "$DO_FILES" -eq 1 ]; then
  echo "--- File/directory renames ---"

  # 1a. The package directory itself (highest-risk rename).
  if [ -d "src/${OLD_LOWER}" ]; then
    echo "DIR   src/${OLD_LOWER}/  ->  src/${NEW_LOWER}/  (entire package, ~280 files)"
    if [ "$APPLY" -eq 1 ]; then
      git mv "src/${OLD_LOWER}" "src/${NEW_LOWER}"
    fi
  fi

  # 1b. docs-design/EduMatcher-*.md and docs-design/reviews/EduMatcher-*.md
  while IFS= read -r f; do
    dir=$(dirname "$f")
    base=$(basename "$f")
    newbase="${base/#${OLD_PASCAL}-/${NEW_PASCAL}-}"
    if [ "$base" != "$newbase" ]; then
      echo "FILE  $f  ->  $dir/$newbase"
      if [ "$APPLY" -eq 1 ]; then
        git mv "$f" "$dir/$newbase"
      fi
    fi
  done < <(git ls-files -- 'docs-design/*' | grep -E "/${OLD_PASCAL}-[^/]*$" || true)

  # 1c. deployment/curl/edumatcher.sh, deployment/vm/install_edumatcher.sh
  #     and any other lowercase-named files/scripts (excluding the package dir,
  #     already handled, and generated/ which is regenerated not renamed).
  while IFS= read -r f; do
    case "$f" in
      "src/${OLD_LOWER}"/*) continue ;;             # handled in 1a
      docs/examples/generated/*) continue ;;         # regenerate, don't rename
      docs-design/*) continue ;;                     # handled in 1b
    esac
    dir=$(dirname "$f")
    base=$(basename "$f")
    newbase="$base"
    newbase="${newbase//${OLD_LOWER}/${NEW_LOWER}}"
    newbase="${newbase//${OLD_PASCAL}/${NEW_PASCAL}}"
    newbase="${newbase//${OLD_UPPER}/${NEW_UPPER}}"
    if [ "$base" != "$newbase" ]; then
      echo "FILE  $f  ->  $dir/$newbase"
      if [ "$APPLY" -eq 1 ]; then
        git mv "$f" "$dir/$newbase"
      fi
    fi
  done < <(git ls-files | grep -iE "(^|/)[^/]*${OLD_LOWER}[^/]*" || true)

  echo
fi

# -------------------------------------------------------------------------
# Step 2: content rewrite
# -------------------------------------------------------------------------
if [ "$DO_CONTENT" -eq 1 ]; then
  echo "--- Content rewrite (case-preserving: PascalCase, lowercase, UPPERCASE) ---"

  # Re-list files AFTER any renames above, so we edit content at final paths.
  # Exclusion is done via git grep's own pathspec (EXCLUDE_PATHSPECS) so it
  # matches git's path matching exactly rather than an approximate regex.
  mapfile -t FILES < <(git grep -ilI -- "${OLD_LOWER}" -- . "${EXCLUDE_PATHSPECS[@]}" 2>/dev/null || true)
  mapfile -t FILES_PASCAL < <(git grep -ilI -- "${OLD_PASCAL}" -- . "${EXCLUDE_PATHSPECS[@]}" 2>/dev/null || true)
  mapfile -t FILES_UPPER < <(git grep -ilI -- "${OLD_UPPER}" -- . "${EXCLUDE_PATHSPECS[@]}" 2>/dev/null || true)

  ALL_FILES=$(printf '%s\n' "${FILES[@]}" "${FILES_PASCAL[@]}" "${FILES_UPPER[@]}" | sort -u | sed '/^$/d')
  COUNT=$(printf '%s\n' "$ALL_FILES" | sed '/^$/d' | wc -l | tr -d ' ')
  echo "Files with content to rewrite: $COUNT"
  echo "(excluded: CHANGELOG.md, TODO.md, dist/, site/, build-tools/node_modules/, docs/examples/generated/, poetry.lock)"
  echo

  if [ "$APPLY" -eq 1 ]; then
    while IFS= read -r f; do
      [ -z "$f" ] && continue
      if [ "$RENAME_ENV" -eq 0 ]; then
        # Protect EDUMATCHER_ env-var-looking tokens from the UPPER pass by
        # doing UPPER replacement only where it's NOT immediately followed
        # by an underscore-plus-identifier-char pattern typical of env vars.
        # Simplest safe approach: skip EDUMATCHER_* tokens entirely, replace
        # everything else.
        sed -i.bak \
          -e "s/${OLD_PASCAL}/${NEW_PASCAL}/g" \
          -e "s/${OLD_LOWER}/${NEW_LOWER}/g" \
          "$f"
        # UPPER pass, but restore any EDUMATCHER_<IDENT> that got touched:
        # (only meaningful if OLD_UPPER appears standalone, e.g. in prose)
        perl -pi -e "s/\b${OLD_UPPER}\b(?!_)/${NEW_UPPER}/g" "$f" 2>/dev/null || \
          sed -i.bak2 -E "s/${OLD_UPPER}([^_A-Za-z0-9]|\$)/${NEW_UPPER}\1/g" "$f"
        rm -f "$f.bak" "$f.bak2"
      else
        sed -i.bak \
          -e "s/${OLD_PASCAL}/${NEW_PASCAL}/g" \
          -e "s/${OLD_LOWER}/${NEW_LOWER}/g" \
          -e "s/${OLD_UPPER}/${NEW_UPPER}/g" \
          "$f"
        rm -f "$f.bak"
      fi
      echo "  rewrote: $f"
    done <<< "$ALL_FILES"
  else
    printf '%s\n' "$ALL_FILES" | sed 's/^/  would rewrite: /'
  fi
  echo
fi

# -------------------------------------------------------------------------
# Step 3: env var report (always separate from the RENAME_ENV content pass,
# printed so you can see exactly what's affected either way)
# -------------------------------------------------------------------------
echo "--- EDUMATCHER_* identifiers found (env vars + a few C header guards) ---"
git grep -ohE "${OLD_UPPER}_[A-Z0-9_]*" -- . "${EXCLUDE_PATHSPECS[@]}" 2>/dev/null | sort -u | sed 's/^/  /'
echo
if [ "$RENAME_ENV" -eq 0 ]; then
  echo "NOTE: --rename-env was not passed, so EDUMATCHER_* identifiers above were"
  echo "      left untouched by the content rewrite. Re-run with --rename-env"
  echo "      once you've decided clean-break vs. deprecation-shim (see plan §2.C)."
fi
echo

# -------------------------------------------------------------------------
# Step 4: things this script deliberately does NOT touch
# -------------------------------------------------------------------------
cat <<'EOF'
--- NOT handled by this script (do these separately, see rename_plan.md) ---
  - pyproject.toml entry-point wiring is covered by the content rewrite
    (it's a text substitution), but verify `poetry check` / `poetry build`
    afterwards -- this is the highest-risk single step.
  - docs/examples/generated/*.{c,h} -- regenerate via pm-msgen, don't hand-edit.
  - docs/presentations/*.{pdf,pptx} -- filename only; slide/doc CONTENT needs
    manual re-export if it mentions the old name internally.
  - PyPI / TestPyPI project registration under the new name.
  - GHCR image names / publish-images.yml push targets.
  - GitHub repository rename (github.com/johan162/EduMatcher -> Tirnex).
  - CHANGELOG.md / TODO.md history (left as-is on purpose).
  - dist/, site/, .venv/, .mypy_cache/, .pytest_cache/, htmlcov/, coverage
    files -- delete and regenerate rather than edit.
EOF
