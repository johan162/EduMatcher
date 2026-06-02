#!/usr/bin/env bash
# mkcover.sh — Insert an image as the first page of a PDF.
#
# Usage:
#   mkcover.sh [-q] [--dpi N] [-o FILE] <image> <pdf>
#
# Options:
#   -q        Quiet mode — suppress all normal output (errors still go to stderr).
#   --dpi N   Output resolution in DPI (default: 72). Use 300 for print-ready output.
#   -o, --output FILE
#             Write merged output to FILE instead of overwriting <pdf>.
#
# Arguments:
#   image   Path to the cover image (PNG, JPG, etc.)
#   pdf     Path to the target PDF to modify in-place.
#
# The image is stretched to fill the first page exactly (no borders, no padding).
# The page dimensions are read from the target PDF.
# The original PDF is replaced with the new one (cover + interior).
#
# Requirements (in order of preference for merging):
#   - ImageMagick (magick or convert) — for image-to-PDF conversion
#   - ghostscript (gs), pdftk, or pdfunite — for PDF merging
#   - pdfinfo (poppler) or ghostscript — for reading page dimensions
#
# Example:
#   ./scripts/mkcover.sh --dpi 300 assets/fig-user-guide-cover.png \
#       dist/mcprojsim_user_guide-b5-0.15.1.pdf
#   ./scripts/mkcover.sh --dpi 300 -o dist/book-with-cover.pdf \
#       assets/fig-user-guide-cover.png dist/mcprojsim_user_guide-b5-0.15.1.pdf

set -euo pipefail

show_help() {
        cat << EOF
Usage: $0 [-q] [--dpi N] <image> <pdf>

Insert an image as the first page of a PDF.

Options:
    -q, --quiet   Quiet mode (suppress normal output)
    --dpi N       Output DPI for the generated cover page (default: 72)
    -o, --output  Write merged output PDF to this file (do not overwrite input)
    -h, --help    Show this help message and exit

Arguments:
    image         Path to the cover image (PNG, JPG, etc.)
    pdf           Path to the target PDF to modify in-place

Examples:
    $0 assets/fig-user-guide-cover.png dist/book.pdf
    $0 --dpi 300 assets/fig-user-guide-cover.png dist/book.pdf
    $0 --dpi 300 -o dist/book-with-cover.pdf assets/fig-user-guide-cover.png dist/book.pdf
    $0 -q --dpi 300 assets/fig-user-guide-cover.png dist/book.pdf
EOF
}

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------
QUIET=false
DPI=72
OUTPUT_PDF=""

while [[ $# -gt 0 ]]; do
    case "$1" in
                -q|--quiet) QUIET=true; shift ;;
                -h|--help)  show_help; exit 0 ;;
        --dpi)     DPI="$2"; shift 2 ;;
        --dpi=*)   DPI="${1#--dpi=}"; shift ;;
                -o|--output) OUTPUT_PDF="$2"; shift 2 ;;
                --output=*) OUTPUT_PDF="${1#--output=}"; shift ;;
        --)        shift; break ;;
        -*)        echo "Error: unknown option: $1" >&2; exit 1 ;;
        *)         break ;;
    esac
done

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 [-q] [--dpi N] [-o FILE] <image> <pdf>" >&2
    exit 1
fi

IMAGE="$1"
PDF="$2"

if [[ -n "$OUTPUT_PDF" ]]; then
    mkdir -p "$(dirname "$OUTPUT_PDF")"
fi

[[ -f "$IMAGE" ]] || { echo "Error: image not found: $IMAGE" >&2; exit 1; }
[[ -f "$PDF"   ]] || { echo "Error: PDF not found: $PDF"   >&2; exit 1; }

# ---------------------------------------------------------------------------
# Temp directory — always cleaned up
# ---------------------------------------------------------------------------
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

COVER_PDF="$WORK/cover.pdf"
MERGED_PDF="$WORK/merged.pdf"

# ---------------------------------------------------------------------------
# Step 1: Read page dimensions (in points) from the first page of the PDF
# ---------------------------------------------------------------------------
W_PT=""
H_PT=""

if command -v pdfinfo >/dev/null 2>&1; then
    read -r W_PT H_PT < <(
        pdfinfo "$PDF" \
        | awk '/^Page size:/ { print $3, $5; exit }'
    )
fi

if [[ -z "$W_PT" ]] && command -v gs >/dev/null 2>&1; then
    read -r W_PT H_PT < <(
        gs -q -dNOPAUSE -dBATCH -dNOSAFER -sDEVICE=nullpage \
            -c "($PDF) (r) file runpdfbegin
                1 pdfgetpage /MediaBox pget pop aload pop
                4 2 roll pop pop
                = = quit" 2>/dev/null \
        | awk 'NR==1{h=$1} NR==2{w=$1} END{print w, h}'
    )
fi

if [[ -z "$W_PT" || -z "$H_PT" ]]; then
    echo "Warning: could not read page size from PDF — assuming B5 (498.9 x 708.7 pt)" >&2
    W_PT=498.9
    H_PT=708.7
fi

# Scale page dimensions from points (at 72 DPI) to pixels at the target DPI.
# 1 point = 1/72 inch, so pixels = points * (DPI / 72).
W_PX=$(LC_ALL=C awk -v w="$W_PT" -v d="$DPI" 'BEGIN { printf "%.0f", w * d / 72 }')
H_PX=$(LC_ALL=C awk -v h="$H_PT" -v d="$DPI" 'BEGIN { printf "%.0f", h * d / 72 }')

# ---------------------------------------------------------------------------
# Step 2: Convert image → single-page PDF at the target page size
# ---------------------------------------------------------------------------
if command -v magick >/dev/null 2>&1; then
    IM="magick"
elif command -v convert >/dev/null 2>&1; then
    IM="convert"
else
    echo "Error: ImageMagick not found (need 'magick' or 'convert')" >&2
    exit 1
fi

"$IM" "$IMAGE" \
    -resize "${W_PX}x${H_PX}!" \
    -units PixelsPerInch \
    -density "$DPI" \
    "$COVER_PDF"

# ---------------------------------------------------------------------------
# Step 3: Merge cover PDF + interior PDF
# ---------------------------------------------------------------------------
if command -v pdftk >/dev/null 2>&1; then
    pdftk "$COVER_PDF" "$PDF" cat output "$MERGED_PDF"
elif command -v gs >/dev/null 2>&1; then
    gs -q -dNOPAUSE -dBATCH -dNOSAFER \
        -sDEVICE=pdfwrite \
        -sOutputFile="$MERGED_PDF" \
        "$COVER_PDF" "$PDF"
elif command -v pdfunite >/dev/null 2>&1; then
    pdfunite "$COVER_PDF" "$PDF" "$MERGED_PDF"
else
    echo "Error: no PDF merge tool found — install pdftk, ghostscript, or poppler (pdfunite)" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 4: Write final PDF
# ---------------------------------------------------------------------------
if [[ -n "$OUTPUT_PDF" ]]; then
    mv "$MERGED_PDF" "$OUTPUT_PDF"
    [[ "$QUIET" == true ]] || echo "Cover inserted: $OUTPUT_PDF"
else
    mv "$MERGED_PDF" "$PDF"
    [[ "$QUIET" == true ]] || echo "Cover inserted: $PDF"
fi
