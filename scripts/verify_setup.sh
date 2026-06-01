#!/bin/bash
# Setup & Verification script for EduMatcher
# Purpose: Do all necessary steps to setup a local development environment and verify installation
# CI/CD Support: Yes. Can be run in CI environments.
# Usage: ./scripts/verify_setup.sh

set -e

echo "=== EduMatcher Dev Environment Setup & Verification ==="
echo ""

# Ensure Poetry is available
if ! command -v poetry &> /dev/null; then
    echo "❌ Poetry not found. Install with: pip install poetry"
    # Asks user if he wants to install poetry if not found
    read -p "Would you like to install Poetry now? (y/n) " -n -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        pip install poetry
    else
        exit 1
    fi
fi
echo "✅ Poetry is available"


# Ensure required fonts are available for PDF rendering.
MONO_FONT_NAME="DejaVu Sans Mono"
BODY_FONT_NAME="Arial Unicode MS"
BODY_FONT_CASK_NAME="font-arial-unicode-ms"
BODY_FONT_FALLBACK_NAME="Noto Sans"

has_font() {
    local font_name="$1"
    if command -v fc-list &> /dev/null; then
        fc-list | grep -qi "${font_name}"
    else
        system_profiler SPFontsDataType 2>/dev/null | grep -qi "${font_name}"
    fi
}

has_body_font() {
    has_font "${BODY_FONT_NAME}" || has_font "${BODY_FONT_FALLBACK_NAME}"
}

missing_fonts=()
if ! has_font "${MONO_FONT_NAME}"; then
    missing_fonts+=("${MONO_FONT_NAME}")
fi
if ! has_body_font; then
    missing_fonts+=("${BODY_FONT_NAME}")
fi

if [ ${#missing_fonts[@]} -gt 0 ]; then
    echo "❌ Missing required fonts: ${missing_fonts[*]}"

    if [[ " ${missing_fonts[*]} " == *" ${MONO_FONT_NAME} "* ]]; then
        read -p "Would you like to install ${MONO_FONT_NAME} now via Homebrew? (y/n) " -n 1 -r
        echo ""

        if [[ $REPLY =~ ^[Yy]$ ]]; then
            if ! command -v brew &> /dev/null; then
                echo "❌ Homebrew not found. Install Homebrew first, then run:"
                echo "   brew install --cask font-dejavu"
                exit 1
            fi

            brew install --cask font-dejavu
        else
            echo "❌ ${MONO_FONT_NAME} is required for expected monospace PDF output"
            exit 1
        fi
    fi

    if [[ " ${missing_fonts[*]} " == *" ${BODY_FONT_NAME} "* ]]; then
        read -p "Would you like to install ${BODY_FONT_NAME} now via Homebrew? (y/n) " -n 1 -r
        echo ""

        if [[ $REPLY =~ ^[Yy]$ ]]; then
            if ! command -v brew &> /dev/null; then
                echo "❌ Homebrew not found. Install Homebrew first, then run:"
                echo "   brew install --cask ${BODY_FONT_CASK_NAME}"
                exit 1
            fi

            if brew info --cask "${BODY_FONT_CASK_NAME}" &> /dev/null; then
                brew install --cask "${BODY_FONT_CASK_NAME}"
            else
                echo "⚠️  ${BODY_FONT_CASK_NAME} is not available in Homebrew casks."
                read -p "Install fallback ${BODY_FONT_FALLBACK_NAME} instead? (y/n) " -n 1 -r
                echo ""
                if [[ $REPLY =~ ^[Yy]$ ]]; then
                    brew install --cask font-noto-sans
                else
                    echo "❌ ${BODY_FONT_NAME} is still missing and fallback was declined"
                    exit 1
                fi
            fi
        else
            echo "❌ ${BODY_FONT_NAME} (or fallback ${BODY_FONT_FALLBACK_NAME}) is required for expected PDF body font output"
            exit 1
        fi
    fi

    # Re-check both fonts after any attempted installation.
    missing_fonts=()
    if ! has_font "${MONO_FONT_NAME}"; then
        missing_fonts+=("${MONO_FONT_NAME}")
    fi
    if ! has_body_font; then
        missing_fonts+=("${BODY_FONT_NAME}")
    fi

    if [ ${#missing_fonts[@]} -gt 0 ]; then
        echo "❌ Missing required fonts after installation attempt: ${missing_fonts[*]}"
        echo "   Please install them before continuing."
        exit 1
    fi
fi

if has_font "${BODY_FONT_NAME}"; then
    resolved_body_font="${BODY_FONT_NAME}"
else
    resolved_body_font="${BODY_FONT_FALLBACK_NAME}"
fi

echo "✅ Required fonts are available: ${MONO_FONT_NAME}, ${resolved_body_font}"



# Make sure a local virtual environment is used
if [ -z "$VIRTUAL_ENV" ]; then
    echo "❌ No virtual environment detected. Please create one with: python -m venv .venv"
    # Automatically create and activate a virtual environment if not present
    # If user answers "y", we will create and activate a virtual environment
    read -p "Would you like to create and activate a virtual environment now? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        poetry config virtualenvs.in-project true --local
        poetry env remove --all
        rm -rf .venv
        poetry install
        source .venv/bin/activate
        echo "✅ Virtual environment created and activated"
    else
        exit 1  
    fi
fi
echo "✅ Activated virtual environment detected"

# Install project dependencies via Poetry
echo "Installing dependencies with Poetry..."
poetry lock 
poetry install --with dev,docs
echo "✅ Dependencies installed"

# Check if package is installed
if ! poetry run edumatcher --version &> /dev/null; then
    echo "❌ edumatcher command not found after poetry install"
    exit 1
fi
echo "✅ edumatcher command available"

echo ""
echo "==================================="
echo "✅ All checks passed!"
echo "==================================="
echo ""
echo "Full development environment for EduMatcher is ready to use!"
echo ""
echo "See development.md for more information on how to contribute and run tests."

# End of script

