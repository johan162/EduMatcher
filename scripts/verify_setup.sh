#!/bin/bash
# Setup and verification script for EduMatcher
# Purpose: prepare a local development environment and verify prerequisites
# CI/CD Support: Yes. Can be run in CI environments.
# Usage: ./scripts/verify_setup.sh

set -e

# Detect OS/distribution to provide package-manager specific guidance.
OS_KERNEL="$(uname -s)"
OS_ID=""
OS_ID_LIKE=""
if [ -f /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    OS_ID="${ID:-}"
    OS_ID_LIKE="${ID_LIKE:-}"
fi

is_linux() {
    [ "${OS_KERNEL}" = "Linux" ]
}

is_fedora() {
    is_linux && { [ "${OS_ID}" = "fedora" ] || [[ " ${OS_ID_LIKE} " == *" fedora "* ]]; }
}

print_linux_manual_help() {
    echo "ℹ️  Auto-install on Linux is currently implemented only for Fedora."
    echo "   For other Linux distributions, install prerequisites manually, then re-run this script."
    echo ""
    echo "Example commands for Debian/Ubuntu (apt):"
    echo "  sudo apt update"
    echo "  sudo apt install poetry fonts-dejavu-core fonts-noto-core"
    echo ""
    echo "After installing the packages, run: ./scripts/verify_setup.sh"
}

echo "=== EduMatcher Dev Environment Setup & Verification ==="
echo ""

# Ensure Poetry is available.
if ! command -v poetry &> /dev/null; then
    echo "❌ Poetry not found"
    if is_fedora; then
        read -p "Would you like to install Poetry now via dnf? (y/n) " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            sudo dnf install -y poetry
        else
            echo "❌ Poetry is required to continue"
            exit 1
        fi
    elif is_linux; then
        print_linux_manual_help
        exit 1
    else
        echo "Install with: pip install poetry"
        read -p "Would you like to install Poetry now? (y/n) " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            pip install poetry
        else
            echo "❌ Poetry is required to continue"
            exit 1
        fi
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

    if is_fedora; then
        if [[ " ${missing_fonts[*]} " == *" ${MONO_FONT_NAME} "* ]]; then
            read -p "Would you like to install ${MONO_FONT_NAME} now via dnf? (y/n) " -n 1 -r
            echo ""
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                sudo dnf install -y dejavu-sans-mono-fonts || sudo dnf install -y dejavu-sans-mono
            else
                echo "❌ ${MONO_FONT_NAME} is required for expected monospace PDF output"
                echo "   Install it manually and re-run this script"
                exit 1
            fi
        fi

        if [[ " ${missing_fonts[*]} " == *" ${BODY_FONT_NAME} "* ]]; then
            read -p "Would you like to install fallback ${BODY_FONT_FALLBACK_NAME} now via dnf? (y/n) " -n 1 -r
            echo ""
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                sudo dnf install -y google-noto-sans-fonts
            else
                echo "❌ ${BODY_FONT_NAME} (or fallback ${BODY_FONT_FALLBACK_NAME}) is required for expected PDF body font output"
                echo "   Install it manually and re-run this script"
                exit 1
            fi
        fi
    elif is_linux; then
        echo "ℹ️  Auto-install for fonts is currently implemented only for Fedora Linux."
        echo "   Install the missing fonts manually, then re-run this script."
        echo ""
        echo "Example commands for Debian/Ubuntu (apt):"
        echo "  sudo apt update"
        if [[ " ${missing_fonts[*]} " == *" ${MONO_FONT_NAME} "* ]] && [[ " ${missing_fonts[*]} " == *" ${BODY_FONT_NAME} "* ]]; then
            echo "  sudo apt install fonts-dejavu-core fonts-noto-core"
        elif [[ " ${missing_fonts[*]} " == *" ${MONO_FONT_NAME} "* ]]; then
            echo "  sudo apt install fonts-dejavu-core"
        else
            echo "  sudo apt install fonts-noto-core"
        fi
        echo ""
        echo "After installing the fonts, run: ./scripts/verify_setup.sh"
        exit 1
    else
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
                echo "   Install it manually and re-run this script"
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
                        echo "   Install a compatible body font and re-run this script"
                        exit 1
                    fi
                fi
            else
                echo "❌ ${BODY_FONT_NAME} (or fallback ${BODY_FONT_FALLBACK_NAME}) is required for expected PDF body font output"
                echo "   Install it manually and re-run this script"
                exit 1
            fi
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
        echo "   Please install them before continuing, then re-run this script"
        exit 1
    fi
fi

if has_font "${BODY_FONT_NAME}"; then
    resolved_body_font="${BODY_FONT_NAME}"
else
    resolved_body_font="${BODY_FONT_FALLBACK_NAME}"
fi

echo "✅ Required fonts are available: ${MONO_FONT_NAME}, ${resolved_body_font}"



# Ensure we are running inside an active virtual environment.
if [ -z "$VIRTUAL_ENV" ]; then
    echo "❌ No active virtual environment detected (VIRTUAL_ENV is unset)."
    echo "   Recommended: python -m venv .venv"
    # If the user accepts, recreate the Poetry-managed in-project environment.
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
        echo "❌ An active virtual environment is required to continue"
        exit 1  
    fi
fi
echo "✅ Activated virtual environment detected"

# Install project dependencies via Poetry.
echo "Installing dependencies with Poetry (this can take a few minutes)..."
poetry lock 
poetry install --with dev,docs
echo "✅ Dependencies installed"

# Verify CLI entrypoint is available after install.
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

