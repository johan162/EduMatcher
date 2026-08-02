#!/bin/bash
# Setup and verification script for EduMatcher
# Purpose: prepare a local development environment and verify prerequisites
# CI/CD Support: Yes. Can be run in CI environments.
# Usage: ./scripts/verify_setup.sh [--non-interactive]

set -e

NON_INTERACTIVE=0
for arg in "$@"; do
    case "$arg" in
        --non-interactive)
            NON_INTERACTIVE=1
            ;;
        -h|--help)
            echo "Usage: ./scripts/verify_setup.sh [--non-interactive]"
            echo "  --non-interactive  Do not prompt; fail fast with guidance"
            exit 0
            ;;
        *)
            echo "❌ Unknown option: $arg"
            echo "Usage: ./scripts/verify_setup.sh [--non-interactive]"
            exit 1
            ;;
    esac
done

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
    echo "  sudo apt install poetry nodejs npm pandoc fonts-dejavu-core fonts-noto-core build-essential libreadline-dev texlive-xetex"
    echo "  sudo apt install chromium-browser  # or package name 'chromium' on some distros"
    echo ""
    echo "After installing the packages, run: ./scripts/verify_setup.sh"
}

confirm_action() {
    local prompt="$1"
    if [ "${NON_INTERACTIVE}" -eq 1 ]; then
        return 1
    fi
    read -p "${prompt} (y/n) " -n 1 -r
    echo ""
    [[ $REPLY =~ ^[Yy]$ ]]
}

print_non_interactive_install_hint() {
    echo "   Re-run without --non-interactive to allow this script to install it for you"
}

has_chrome() {
    command -v google-chrome &> /dev/null || \
    command -v google-chrome-stable &> /dev/null || \
    command -v chrome &> /dev/null || \
    command -v chromium &> /dev/null || \
    command -v chromium-browser &> /dev/null
}

has_readline_dev() {
    if is_fedora; then
        rpm -q readline-devel &> /dev/null
        return $?
    fi

    pkg-config --exists readline 2>/dev/null || \
    [ -f /usr/include/readline/readline.h ] || \
    [ -f /usr/local/include/readline/readline.h ] || \
    [ -f /opt/homebrew/opt/readline/include/readline/readline.h ] || \
    [ -f /usr/local/opt/readline/include/readline/readline.h ]
}

readline_detection_source() {
    if is_fedora && rpm -q readline-devel &> /dev/null; then
        echo "rpm:readline-devel"
    elif pkg-config --exists readline 2>/dev/null; then
        echo "pkg-config:readline"
    elif [ -f /usr/include/readline/readline.h ]; then
        echo "/usr/include/readline/readline.h"
    elif [ -f /usr/local/include/readline/readline.h ]; then
        echo "/usr/local/include/readline/readline.h"
    elif [ -f /opt/homebrew/opt/readline/include/readline/readline.h ]; then
        echo "/opt/homebrew/opt/readline/include/readline/readline.h"
    elif [ -f /usr/local/opt/readline/include/readline/readline.h ]; then
        echo "/usr/local/opt/readline/include/readline/readline.h"
    else
        echo "unknown"
    fi
}

version_ge() {
    # Returns success when $1 >= $2 using semantic version sort.
    local lhs="$1"
    local rhs="$2"
    [ "$(printf '%s\n' "${rhs}" "${lhs}" | sort -V | head -n 1)" = "${rhs}" ]
}

pandoc_version() {
    pandoc --version 2>/dev/null | awk 'NR==1 {for (i=1; i<=NF; i++) if ($i ~ /^[0-9]+(\.[0-9]+)+$/) {print $i; exit}}'
}

echo "=== EduMatcher Dev Environment Setup & Verification ==="
echo ""

# Ensure Poetry is available.
if ! command -v poetry &> /dev/null; then
    echo "❌ Poetry not found"
    if is_fedora; then
        if confirm_action "Would you like to install Poetry now via dnf?"; then
            sudo dnf install -y poetry
        else
            echo "❌ Poetry is required to continue"
            if [ "${NON_INTERACTIVE}" -eq 1 ]; then
                print_non_interactive_install_hint
            fi
            exit 1
        fi
    elif is_linux; then
        print_linux_manual_help
        exit 1
    else
        echo "Install with: pip install poetry"
        if confirm_action "Would you like to install Poetry now?"; then
            pip install poetry
        else
            echo "❌ Poetry is required to continue"
            if [ "${NON_INTERACTIVE}" -eq 1 ]; then
                print_non_interactive_install_hint
            fi
            exit 1
        fi
    fi
fi
echo "✅ Poetry is available"

# Ensure Node.js and npm are available.
if ! command -v node &> /dev/null || ! command -v npm &> /dev/null; then
    echo "❌ Node.js and npm are required but not fully available"
    if is_fedora; then
        if confirm_action "Would you like to install Node.js and npm now via dnf?"; then
            sudo dnf install -y nodejs npm
        else
            echo "❌ Node.js and npm are required to continue"
            if [ "${NON_INTERACTIVE}" -eq 1 ]; then
                print_non_interactive_install_hint
            fi
            exit 1
        fi
    elif is_linux; then
        echo "ℹ️  Auto-install for Node.js/npm is currently implemented only for Fedora Linux."
        echo "   Install Node.js and npm manually, then re-run this script."
        echo ""
        echo "Example commands for Debian/Ubuntu (apt):"
        echo "  sudo apt update"
        echo "  sudo apt install nodejs npm"
        echo ""
        echo "After installing Node.js/npm, run: ./scripts/verify_setup.sh"
        exit 1
    elif [ "${OS_KERNEL}" = "Darwin" ]; then
        if confirm_action "Would you like to install Node.js (includes npm) now via Homebrew?"; then
            if ! command -v brew &> /dev/null; then
                echo "❌ Homebrew not found. Install Homebrew first, then run:"
                echo "   brew install node"
                exit 1
            fi
            brew install node
        else
            echo "❌ Node.js and npm are required to continue"
            echo "   Install Node.js (for example: brew install node) and re-run this script"
            if [ "${NON_INTERACTIVE}" -eq 1 ]; then
                print_non_interactive_install_hint
            fi
            exit 1
        fi
    else
        echo "❌ Node.js and npm are required to continue"
        echo "   Install them with your system package manager, then re-run this script"
        exit 1
    fi
fi
echo "✅ Node.js and npm are available"

# Ensure native build tools are available.
required_tools=(gcc make)
missing_tools=()
for tool in "${required_tools[@]}"; do
    if ! command -v "${tool}" &> /dev/null; then
        missing_tools+=("${tool}")
    fi
done

if [ ${#missing_tools[@]} -gt 0 ]; then
    echo "❌ Missing required build tools: ${missing_tools[*]}"
    if is_fedora; then
        if confirm_action "Would you like to install missing build tools now via dnf?"; then
            sudo dnf install -y gcc make
        else
            echo "❌ Build tools (${missing_tools[*]}) are required to continue"
            if [ "${NON_INTERACTIVE}" -eq 1 ]; then
                print_non_interactive_install_hint
            fi
            exit 1
        fi
    elif is_linux; then
        echo "ℹ️  Auto-install for build tools is currently implemented only for Fedora Linux."
        echo "   Install the missing tools manually, then re-run this script."
        echo ""
        echo "Example commands for Debian/Ubuntu (apt):"
        echo "  sudo apt update"
        echo "  sudo apt install build-essential"
        echo ""
        echo "After installing the tools, run: ./scripts/verify_setup.sh"
        exit 1
    elif [ "${OS_KERNEL}" = "Darwin" ]; then
        if confirm_action "Would you like to install Xcode Command Line Tools now?"; then
            xcode-select --install || true
            echo "ℹ️  Complete the Xcode Command Line Tools installation, then re-run this script."
            exit 1
        else
            echo "❌ Build tools (${missing_tools[*]}) are required to continue"
            echo "   Install Xcode Command Line Tools and re-run this script"
            if [ "${NON_INTERACTIVE}" -eq 1 ]; then
                print_non_interactive_install_hint
            fi
            exit 1
        fi
    else
        echo "❌ Build tools (${missing_tools[*]}) are required to continue"
        echo "   Install gcc and make with your system package manager, then re-run this script"
        exit 1
    fi
fi
echo "✅ Required build tools are available: gcc, make"

# Ensure readline development headers/library are available.
if ! has_readline_dev; then
    echo "❌ Readline development library not found"
    if is_fedora; then
        if confirm_action "Would you like to install readline development headers now via dnf?"; then
            sudo dnf install -y readline-devel
        else
            echo "❌ Readline development library is required to continue"
            if [ "${NON_INTERACTIVE}" -eq 1 ]; then
                print_non_interactive_install_hint
            fi
            exit 1
        fi
    elif is_linux; then
        echo "ℹ️  Auto-install for readline development headers is currently implemented only for Fedora Linux."
        echo "   Install readline development headers manually, then re-run this script."
        echo ""
        echo "Example commands for Debian/Ubuntu (apt):"
        echo "  sudo apt update"
        echo "  sudo apt install libreadline-dev"
        echo ""
        echo "After installing libreadline-dev, run: ./scripts/verify_setup.sh"
        exit 1
    elif [ "${OS_KERNEL}" = "Darwin" ]; then
        if confirm_action "Would you like to install readline now via Homebrew?"; then
            if ! command -v brew &> /dev/null; then
                echo "❌ Homebrew not found. Install Homebrew first, then run:"
                echo "   brew install readline"
                exit 1
            fi
            brew install readline
        else
            echo "❌ Readline development library is required to continue"
            echo "   Install readline (for example: brew install readline) and re-run this script"
            if [ "${NON_INTERACTIVE}" -eq 1 ]; then
                print_non_interactive_install_hint
            fi
            exit 1
        fi
    else
        echo "❌ Readline development library is required to continue"
        echo "   Install readline development headers with your system package manager, then re-run this script"
        exit 1
    fi
fi
echo "✅ Readline development library is available"
echo "   Detected via: $(readline_detection_source)"

# Ensure Chrome/Chromium browser is available.
if ! has_chrome; then
    echo "❌ Chrome/Chromium not found"
    if is_fedora; then
        if confirm_action "Would you like to install Google Chrome now via dnf?"; then
            sudo dnf install -y google-chrome-stable || {
                echo "⚠️  google-chrome-stable install failed."
                echo "   Install Chrome manually or install Chromium, then re-run this script"
                exit 1
            }
        else
            echo "❌ Chrome/Chromium is required to continue"
            if [ "${NON_INTERACTIVE}" -eq 1 ]; then
                print_non_interactive_install_hint
            fi
            exit 1
        fi
    elif is_linux; then
        echo "ℹ️  Auto-install for Chrome is currently implemented only for Fedora Linux."
        echo "   Install Chrome/Chromium manually, then re-run this script."
        echo ""
        echo "Example commands for Debian/Ubuntu (apt):"
        echo "  sudo apt update"
        echo "  sudo apt install chromium-browser  # or package name 'chromium' on some distros"
        echo ""
        echo "After installing Chrome/Chromium, run: ./scripts/verify_setup.sh"
        exit 1
    elif [ "${OS_KERNEL}" = "Darwin" ]; then
        if confirm_action "Google Chrome was not found. Continue anyway?"; then
            echo "⚠️  Continuing without Chrome may cause browser-based steps to fail"
        else
            echo "❌ Chrome/Chromium is required to continue"
            echo "   Install Google Chrome and re-run this script"
            if [ "${NON_INTERACTIVE}" -eq 1 ]; then
                print_non_interactive_install_hint
            fi
            exit 1
        fi
    else
        echo "❌ Chrome/Chromium is required to continue"
        echo "   Install it with your system package manager and re-run this script"
        exit 1
    fi
fi
echo "✅ Chrome/Chromium is available"

# Ensure xelatex is available for PDF generation.
if ! command -v xelatex &> /dev/null; then
    echo "❌ xelatex not found"
    if is_fedora; then
        if confirm_action "Would you like to install TeX Live XeLaTeX now via dnf?"; then
            sudo dnf install -y texlive-xetex
        else
            echo "❌ xelatex is required to continue"
            if [ "${NON_INTERACTIVE}" -eq 1 ]; then
                print_non_interactive_install_hint
            fi
            exit 1
        fi
    elif is_linux; then
        echo "ℹ️  Auto-install for xelatex is currently implemented only for Fedora Linux."
        echo "   Install TeX Live/XeLaTeX manually, then re-run this script."
        echo ""
        echo "Example commands for Debian/Ubuntu (apt):"
        echo "  sudo apt update"
        echo "  sudo apt install texlive-xetex"
        echo ""
        echo "After installing xelatex, run: ./scripts/verify_setup.sh"
        exit 1
    elif [ "${OS_KERNEL}" = "Darwin" ]; then
        echo "❌ xelatex is required to continue"
        echo "   Install MacTeX or BasicTeX, then re-run this script"
        exit 1
    else
        echo "❌ xelatex is required to continue"
        echo "   Install TeX Live (with xelatex) using your system package manager, then re-run this script"
        exit 1
    fi
fi
echo "✅ xelatex is available"

# Ensure pandoc is available.
MIN_PANDOC_VERSION="3.10.0"
if ! command -v pandoc &> /dev/null; then
    echo "❌ Missing required documentation tool: pandoc"
    if is_fedora; then
        if confirm_action "Would you like to install pandoc now via dnf?"; then
            sudo dnf install -y pandoc-cli
        else
            echo "❌ pandoc is required to continue"
            if [ "${NON_INTERACTIVE}" -eq 1 ]; then
                print_non_interactive_install_hint
            fi
            exit 1
        fi
    elif is_linux; then
        echo "ℹ️  Auto-install for pandoc is currently implemented only for Fedora Linux."
        echo "   Install pandoc manually, then re-run this script."
        echo ""
        echo "Example commands for Debian/Ubuntu (apt):"
        echo "  sudo apt update"
        echo "  sudo apt install pandoc"
        echo ""
        echo "After installing pandoc, run: ./scripts/verify_setup.sh"
        exit 1
    elif [ "${OS_KERNEL}" = "Darwin" ]; then
        if confirm_action "Would you like to install pandoc now via Homebrew?"; then
            if ! command -v brew &> /dev/null; then
                echo "❌ Homebrew not found. Install Homebrew first, then run:"
                echo "   brew install pandoc"
                exit 1
            fi
            brew install pandoc
        else
            echo "❌ pandoc is required to continue"
            if [ "${NON_INTERACTIVE}" -eq 1 ]; then
                print_non_interactive_install_hint
            fi
            exit 1
        fi
    else
        echo "❌ pandoc is required to continue"
        echo "   Install it with your system package manager, then re-run this script"
        exit 1
    fi
fi

pandoc_ver="$(pandoc_version)"
if [ -z "${pandoc_ver}" ]; then
    echo "❌ Could not determine pandoc version"
    echo "   Ensure pandoc is correctly installed and on PATH, then re-run this script"
    exit 1
fi

if ! version_ge "${pandoc_ver}" "${MIN_PANDOC_VERSION}"; then
    echo "❌ Pandoc version ${pandoc_ver} is too old (required: >= ${MIN_PANDOC_VERSION})"
    if is_fedora; then
        echo "   Fedora repositories may provide an older pandoc by default."
        echo "   Install a newer upstream binary in ~/.local/bin to avoid changing the global install:"
        echo "   curl -LO https://github.com/jgm/pandoc/releases/download/3.10.1/pandoc-3.10.1-linux-amd64.tar.gz"
        echo "   tar -xzf pandoc-3.10.1-linux-amd64.tar.gz"
        echo "   mkdir -p ~/.local/bin"
        echo "   install -m 0755 pandoc-3.10.1/bin/pandoc ~/.local/bin/pandoc"
        echo "   export PATH=\"$HOME/.local/bin:$PATH\""
        echo "   Then re-run this script"
    elif is_linux; then
        echo "   Install a newer pandoc release (>= ${MIN_PANDOC_VERSION}) and re-run this script"
    else
        echo "   Upgrade pandoc to >= ${MIN_PANDOC_VERSION} and re-run this script"
    fi
    exit 1
fi
echo "✅ Pandoc is available"
echo "   Detected pandoc version: ${pandoc_ver}"


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
            if confirm_action "Would you like to install ${MONO_FONT_NAME} now via dnf?"; then
                sudo dnf install -y dejavu-sans-mono-fonts || sudo dnf install -y dejavu-sans-mono
            else
                echo "❌ ${MONO_FONT_NAME} is required for expected monospace PDF output"
                echo "   Install it manually and re-run this script"
                if [ "${NON_INTERACTIVE}" -eq 1 ]; then
                    print_non_interactive_install_hint
                fi
                exit 1
            fi
        fi

        if [[ " ${missing_fonts[*]} " == *" ${BODY_FONT_NAME} "* ]]; then
            if confirm_action "Would you like to install fallback ${BODY_FONT_FALLBACK_NAME} now via dnf?"; then
                sudo dnf install -y google-noto-sans-fonts
            else
                echo "❌ ${BODY_FONT_NAME} (or fallback ${BODY_FONT_FALLBACK_NAME}) is required for expected PDF body font output"
                echo "   Install it manually and re-run this script"
                if [ "${NON_INTERACTIVE}" -eq 1 ]; then
                    print_non_interactive_install_hint
                fi
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
            if confirm_action "Would you like to install ${MONO_FONT_NAME} now via Homebrew?"; then
                if ! command -v brew &> /dev/null; then
                    echo "❌ Homebrew not found. Install Homebrew first, then run:"
                    echo "   brew install --cask font-dejavu"
                    exit 1
                fi

                brew install --cask font-dejavu
            else
                echo "❌ ${MONO_FONT_NAME} is required for expected monospace PDF output"
                echo "   Install it manually and re-run this script"
                if [ "${NON_INTERACTIVE}" -eq 1 ]; then
                    print_non_interactive_install_hint
                fi
                exit 1
            fi
        fi

        if [[ " ${missing_fonts[*]} " == *" ${BODY_FONT_NAME} "* ]]; then
            if confirm_action "Would you like to install ${BODY_FONT_NAME} now via Homebrew?"; then
                if ! command -v brew &> /dev/null; then
                    echo "❌ Homebrew not found. Install Homebrew first, then run:"
                    echo "   brew install --cask ${BODY_FONT_CASK_NAME}"
                    exit 1
                fi

                if brew info --cask "${BODY_FONT_CASK_NAME}" &> /dev/null; then
                    brew install --cask "${BODY_FONT_CASK_NAME}"
                else
                    echo "⚠️  ${BODY_FONT_CASK_NAME} is not available in Homebrew casks."
                    if confirm_action "Install fallback ${BODY_FONT_FALLBACK_NAME} instead?"; then
                        brew install --cask font-noto-sans
                    else
                        echo "❌ ${BODY_FONT_NAME} is still missing and fallback was declined"
                        echo "   Install a compatible body font and re-run this script"
                        if [ "${NON_INTERACTIVE}" -eq 1 ]; then
                            print_non_interactive_install_hint
                        fi
                        exit 1
                    fi
                fi
            else
                echo "❌ ${BODY_FONT_NAME} (or fallback ${BODY_FONT_FALLBACK_NAME}) is required for expected PDF body font output"
                echo "   Install it manually and re-run this script"
                if [ "${NON_INTERACTIVE}" -eq 1 ]; then
                    print_non_interactive_install_hint
                fi
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
    if confirm_action "Would you like to create and activate a virtual environment now?"; then
        poetry config virtualenvs.in-project true --local
        poetry env remove --all
        rm -rf .venv
        poetry install
        source .venv/bin/activate
        echo "✅ Virtual environment created and activated"
    else
        echo "❌ An active virtual environment is required to continue"
        if [ "${NON_INTERACTIVE}" -eq 1 ]; then
            print_non_interactive_install_hint
        fi
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
if ! poetry run pm-engine --version &> /dev/null; then
    echo "❌ pm-engine command not found after poetry install"
    exit 1
fi
echo "✅ pm-engine command available"

echo ""
echo "==================================="
echo "✅ All checks passed!"
echo "==================================="
echo ""
echo "Full development environment for EduMatcher is ready to use!"
echo ""
echo "See development.md for more information on how to contribute and run tests."

# End of script

