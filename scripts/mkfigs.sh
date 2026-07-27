#!/usr/bin/env bash
# mkfigs.sh — Render fig-*.html files to PNG images using headless Chrome.
#
# Usage:
#   mkfigs.sh -o <output_directory> [-s <source_directory>] [-q] [BASENAME]
#
# Options:
#   -s DIR     Source directory containing fig-*.html files.
#              Defaults to the current working directory.
#   -o DIR     Output directory for PNG images (required).
#   -q         Quiet mode — suppress all normal output (errors still go to stderr).
#   BASENAME   Optional file base-name (e.g. fig-lognormal-graph) to process
#              only that single HTML file.
#
# Each fig-<name>.html is rendered to <output_directory>/fig-<name>.png.
# A progress message is printed for each image.

set -euo pipefail

show_help() {
        cat << EOF
Usage:
    mkfigs.sh -o <output_directory> [-s <source_directory>] [-q] [BASENAME]

Options:
    -s DIR     Source directory containing fig-*.html files.
                         Defaults to the current working directory.
    -o DIR     Output directory for PNG images (required).
    -q         Quiet mode - suppress all normal output (errors still go to stderr).
    -h, --help Show this help message and exit.

Arguments:
    BASENAME   Optional file base-name (e.g. fig-lognormal-graph) to process
                         only that single HTML file.

Examples:
    mkfigs.sh -s assets -o assets
    mkfigs.sh -s assets -o assets fig-user-guide-cover
    mkfigs.sh -q -s assets -o assets fig-user-guide-cover
EOF
}

# ---------------------------------------------------------------------------
# Locate headless Chrome/Chromium
# ---------------------------------------------------------------------------
_find_chrome() {
    local candidates=(
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
        "/Applications/Chromium.app/Contents/MacOS/Chromium"
        "google-chrome"
        "google-chrome-stable"
        "chromium-browser"
        "chromium"
        "chrome"
    )
    for c in "${candidates[@]}"; do
        if command -v "$c" &>/dev/null 2>&1 || [ -x "$c" ]; then
            printf '%s' "$c"
            return 0
        fi
    done
    return 1
}

# ---------------------------------------------------------------------------
# Locate ImageMagick (v6: convert/identify, v7: magick)
# ---------------------------------------------------------------------------
IM_CONVERT_CMD=()
IM_IDENTIFY_CMD=()

if command -v magick >/dev/null 2>&1; then
    IM_CONVERT_CMD=("magick" "convert")
    IM_IDENTIFY_CMD=("magick" "identify")
elif command -v convert >/dev/null 2>&1 && command -v identify >/dev/null 2>&1; then
    IM_CONVERT_CMD=("convert")
    IM_IDENTIFY_CMD=("identify")
fi

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
SOURCE_DIR=""
OUTPUT_DIR=""
QUIET=0

for arg in "$@"; do
    case "$arg" in
        -h|--help)
            show_help
            exit 0
            ;;
    esac
done

while getopts ":s:o:qh" opt; do
    case "$opt" in
        s) SOURCE_DIR="$OPTARG" ;;
        o) OUTPUT_DIR="$OPTARG" ;;
        q) QUIET=1 ;;
        h) show_help; exit 0 ;;
        :) echo "ERROR: option -$OPTARG requires an argument." >&2; exit 1 ;;
        \?) echo "ERROR: unknown option -$OPTARG." >&2; exit 1 ;;
    esac
done

# Helper: print to stdout unless quiet
_say() { [[ $QUIET -eq 0 ]] && echo "$@" || true; }
_printf() { [[ $QUIET -eq 0 ]] && printf "$@" || true; }

if [[ -z "$OUTPUT_DIR" ]]; then
    echo "ERROR: -o <output_directory> is required." >&2
    echo "Usage: mkfigs.sh -o <output_directory> [-s <source_directory>] [-q] [BASENAME]" >&2
    exit 1
fi

# Optional positional argument: single base-name to process
shift $(( OPTIND - 1 ))
FILTER_NAME="${1:-}"

# Default source to cwd
if [[ -z "$SOURCE_DIR" ]]; then
    SOURCE_DIR="$PWD"
fi

SOURCE_DIR="${SOURCE_DIR%/}"

# Resolve to absolute path so file:// URLs are valid
SOURCE_DIR="$(cd "$SOURCE_DIR" && pwd)"
# ---------------------------------------------------------------------------
if [[ ! -d "$SOURCE_DIR" ]]; then
    echo "ERROR: source directory does not exist: $SOURCE_DIR" >&2
    exit 1
fi

CHROME="$(_find_chrome)" || {
    echo "ERROR: could not find Chrome or Chromium. Install Google Chrome or Chromium." >&2
    exit 1
}

mkdir -p "$OUTPUT_DIR"

# ---------------------------------------------------------------------------
# Collect HTML files (portable: macOS ships bash 3.2 which lacks mapfile)
# ---------------------------------------------------------------------------
HTML_FILES=()
if [[ -n "$FILTER_NAME" ]]; then
    # Strip any .html suffix the user may have included
    FILTER_NAME="${FILTER_NAME%.html}"
    SINGLE="$SOURCE_DIR/${FILTER_NAME}.html"
    if [[ ! -f "$SINGLE" ]]; then
        echo "ERROR: $SINGLE not found." >&2
        exit 1
    fi
    HTML_FILES=("$SINGLE")
else
    while IFS= read -r -d '' f; do
        HTML_FILES+=("$f")
    done < <(find "$SOURCE_DIR" -maxdepth 1 -name 'fig-*.html' -name 'cover-*.html' -print0 | sort -z)
fi

if [[ ${#HTML_FILES[@]} -eq 0 ]]; then
    _say "No fig-/cover-*.html files found in $SOURCE_DIR"
    exit 0
fi

TOTAL=${#HTML_FILES[@]}
_say "Rendering $TOTAL figure(s) from $SOURCE_DIR → $OUTPUT_DIR"
_say ""

WARNED_NO_IM=0

# ---------------------------------------------------------------------------
# Render each file
# ---------------------------------------------------------------------------
COUNT=0
ERRORS=0

for html in "${HTML_FILES[@]}"; do
    BASENAME=$(basename "$html" .html)
    OUTPUT_PNG="$OUTPUT_DIR/${BASENAME}.png"
    COUNT=$(( COUNT + 1 ))

    _printf "[%d/%d] %s … " "$COUNT" "$TOTAL" "$BASENAME"

    TRIM_FILE="${html%.html}.trim"

    if "$CHROME" \
        --headless=new \
        --disable-gpu \
        --no-sandbox \
        --disable-dev-shm-usage \
        --hide-scrollbars \
        --window-size=2560,4096 \
        --screenshot="$OUTPUT_PNG" \
        "file://${html}" \
        2>/dev/null; then

        # Always auto-trim browser margins first so trim-file coordinates
        # are relative to the visible content, not the raw viewport.
        if [[ ${#IM_CONVERT_CMD[@]} -gt 0 ]]; then
            "${IM_CONVERT_CMD[@]}" "$OUTPUT_PNG" -trim +repage "$OUTPUT_PNG" 2>/dev/null || true
        elif [[ $WARNED_NO_IM -eq 0 && $QUIET -eq 0 ]]; then
            echo "WARN: ImageMagick not found (convert/identify or magick). Skipping trim/crop steps." >&2
            WARNED_NO_IM=1
        fi

        if [[ -f "$TRIM_FILE" ]]; then
            # Read "bl_x, bl_y, width, height" — bottom-left origin coordinates.
            # Convert to ImageMagick top-left origin: top_y = img_height - bl_y - height
            IFS=', ' read -r bl_x bl_y crop_w crop_h < "$TRIM_FILE" || true
            if [[ ${#IM_CONVERT_CMD[@]} -gt 0 && ${#IM_IDENTIFY_CMD[@]} -gt 0 ]]; then
                img_h=$("${IM_IDENTIFY_CMD[@]}" -format "%h" "$OUTPUT_PNG" 2>/dev/null || printf '0')
                # Convert bottom-left origin → ImageMagick top-left origin.
                # bottom_from_top is the fixed anchor; clamp crop_h if it overshoots.
                bottom_from_top=$(( img_h - bl_y ))
                top_y=$(( bottom_from_top - crop_h ))
                if [[ $top_y -lt 0 ]]; then
                    top_y=0
                    crop_h=$bottom_from_top
                fi
                "${IM_CONVERT_CMD[@]}" "$OUTPUT_PNG" -crop "${crop_w}x${crop_h}+${bl_x}+${top_y}" +repage "$OUTPUT_PNG" 2>/dev/null || true
            fi
        fi

        _say "done → $(basename "$OUTPUT_PNG")"
    else
        _say "FAILED"
        echo "ERROR: rendering failed for $html" >&2
        ERRORS=$(( ERRORS + 1 ))
    fi
done

_say ""
if [[ $ERRORS -eq 0 ]]; then
    _say "All $TOTAL figure(s) rendered successfully."
else
    echo "$ERRORS of $TOTAL figure(s) failed." >&2
    exit 1
fi
