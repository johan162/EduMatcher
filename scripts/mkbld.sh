#!/bin/bash
# Build Script
# Description: Automates testing, static analysis, formatting checks, and package building.
# CI/CD Support: Yes. Can be run in CI environments.
# Usage: ./scripts/mkbld.sh [--dry-run] [--help]
#
# Example: ./scripts/mkbld.sh
# Example: ./scripts/mkbld.sh --dry-run
# Example: ./scripts/mkbld.sh --help

set -euo pipefail # Exit on any error or uninitialized variable

# =====================================
# CONFIGURATION
# =====================================

declare GITHUB_USER="johan162"
declare SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
declare PROGRAMNAME="edumatcher"
declare PROGRAMNAME_PRETTY="EduMatcher"
declare COVERAGE="80"

# Detect CI environment
if [ -n "${CI:-}" ] || [ -n "${GITHUB_ACTIONS:-}" ]; then
    echo "🔧 Running in CI mode"
    CI_MODE=true
else
    echo "🔧 Running in local mode"
    CI_MODE=false
fi

# Color codes (disabled in CI)
if [ "$CI_MODE" = true ]; then
    GREEN=""
    RED=""
    YELLOW=""
    BLUE=""
    NC=""
else
    GREEN='\033[0;32m'
    RED='\033[0;31m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m'
fi

# Default options
DRY_RUN=false
HELP=false

# =====================================
# Functions to print colored output
# =====================================
print_step() {
    echo -e "${BLUE}==>${NC} ${1}"
}

print_step_colored() {
    echo -e "${BLUE}==> ${1}${NC}"
}

print_sub_step() {
    echo -e "${BLUE}  ->${1}${NC}"
}

print_success() {
    echo -e "${GREEN}✓ Success: ${1}${NC}"
}

print_success_colored() {
    if [ "$CI_MODE" = true ]; then
        echo -e "✓ Success: ${1}"
    else
        echo -e "${GREEN}✅ Success: ${1}${NC}"
    fi
}

print_error() {
    echo -e "${RED}✗ Error: ${NC} ${1}" >&2
}

print_error_colored() {
    if [ "$CI_MODE" = true ]; then
        echo -e "✗ Error: ${1}"
    else
        echo -e "${RED}❌ Error: ${1}${NC}"
    fi
}

print_warning() {
    echo -e "${YELLOW}⚠ Warning:${NC} ${1}"
}

print_warning_colored() {
    if [ "$CI_MODE" = true ]; then
        echo -e "⚠ Warning: ${1}"
    else
        echo -e "${YELLOW}⚠️  Warning: ${1}${NC}"
    fi
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_info_colored() {
    if [ "$CI_MODE" = true ]; then
        echo -e "ℹ $1"
    else
        echo -e "${BLUE}ℹ️  ${1}${NC}"
    fi
}

# Function to execute command or print it in dry-run mode
run_command() {
    local cmd="$1"
    local description="$2"
    
    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would execute: ${cmd}"
    else
        print_sub_step "$description"
        echo "Executing: $cmd"
        if eval "$cmd"; then
            print_success_colored "$description completed"
        else
            print_error_colored "$description failed"
            exit 1
        fi
    fi
}

# Help function
show_help() {
    cat << EOF
🚀 ${PROGRAMNAME_PRETTY} Build Script

DESCRIPTION:
    This script automates the build and validation process for the ${PROGRAMNAME_PRETTY} project.
    It runs tests, performs static analysis, checks code formatting, builds the package,
    and validates the built package.
    
    This script performs a complete build and validation process:
    1. Runs pytest with coverage reporting
    2. Performs static analysis with flake8 and mypy
    3. Checks code formatting with black
    4. Builds the Python package
    5. Validates the built package with twine 

USAGE: 
    $0 [OPTIONS]

OPTIONS:
    --dry-run       Print commands that would be executed without running them
    --help          Show this help message and exit

REQUIREMENTS:
    - Poetry must be installed and available on PATH
    - Development dependencies must be installed: poetry install --with dev
    - Must be run from the project root directory

EXAMPLES:
    $0                  # Run full build process
    $0 --dry-run        # Show what would be executed
    $0 --help           # Show this help

EXIT CODES:
    0    Success
    1    Build failure (tests, linting, or package build failed)
    2    Usage error
EOF
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help)
            HELP=true
            shift
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Use --help for usage information" >&2
            exit 2
            ;;
    esac
done

# Show help if requested
if [ "$HELP" = true ]; then
    show_help
    exit 0
fi



echo "=========================================="
echo "  ${PROGRAMNAME_PRETTY} Build Script"
echo "=========================================="
echo "Branch: $(git branch --show-current)"
echo "Commit: $(git rev-parse --short HEAD)"
if [ "$DRY_RUN" = true ]; then
    print_warning ""
    print_warning_colored "DRY-RUN MODE: Commands will be printed but not executed!"
    print_warning ""
fi
echo ""

# =====================================
# PHASE 1: PRE-BUILD VALIDATION
# =====================================

print_step_colored ""
print_step_colored "🔍 PHASE 1: PRE-BUILD VALIDATION"
print_step_colored ""

# 1.1 Check if we're in the root directory (pyproject.toml must exist)
run_command "test -f pyproject.toml" "Build script must be run from project root."

# Check if Poetry and required dev dependencies are available
if [ "$DRY_RUN" = false ]; then
    if ! command -v poetry &> /dev/null; then
        print_error "Poetry not found. Please install Poetry and try again."
        exit 2
    fi

    if ! poetry env info --path >/dev/null 2>&1; then
        print_error "Poetry environment not found. Please run: poetry install --with dev"
        exit 2
    fi

    POETRY_ENV_PATH="$(poetry env info --path)"
    print_sub_step "Using Poetry environment: ${POETRY_ENV_PATH}"

    for required_command in pytest flake8 mypy black twine; do
        if ! poetry run "$required_command" --version >/dev/null 2>&1; then
            print_error "Required Poetry command '$required_command' not found. Please run: poetry install --with dev"
            exit 2
        fi
    done
else
    print_sub_step "Would verify Poetry environment and required dev tools"
fi

# 1.3 Clean previous build and coverage artifacts
run_command "rm -rf dist/ build/ src/*.egg-info/ htmlcov/" "Cleaning previous build and coverage artifacts"

# =======================================
# PHASE 2: STATIC ANALYSIS AND FORMATTING
# =======================================

echo ""
print_step_colored ""
print_step_colored "🧪 PHASE 2: STATIC ANALYSIS WITH FLAKE8, MYPY, AND BLACK"
print_step_colored ""

# Step 2.1: Code formatting check with black
run_command "poetry run black --check --diff src/ tests/" "Checking code formatting with black"

# Step 2.2: Static analysis with flake8
run_command "poetry run flake8 src/${PROGRAMNAME} tests/" "Running flake8 static analysis"

# Step 2.3: Type checking with mypy
run_command "poetry run mypy src/ tests/ --strict --ignore-missing-imports" "Running mypy type checking"

# Step 2.4: Run pyright for additional static analysis (optional, can be added if pyright is set up)
if command -v pyright >/dev/null 2>&1; then
    run_command "poetry run pyright src/ tests/" "Running pyright static analysis"
else
    print_warning "Pyright not found, skipping pyright static analysis. Install with 'pip install pyright' for enhanced linting."
fi


# =====================================
# PHASE 3: RUN TESTS WITH COVERAGE
# =====================================

echo ""
print_step_colored ""
print_step_colored "🧪 PHASE 3: CHECKING UNIT TESTS & COVERAGE"
print_step_colored ""

previous_coverage_checksum=""
if [ "$DRY_RUN" = false ] && [ -f "coverage.xml" ]; then
    previous_coverage_checksum="$(shasum -a 256 coverage.xml | awk '{print $1}')"
    print_sub_step "Recorded existing coverage.xml checksum"
fi

# Build the quiet flag for CI
if [ "$CI_MODE" = true ]; then
    PYTEST_QUIET="-q"
else
    PYTEST_QUIET=""
fi

# Step 3.1: Run tests with coverage
run_command "poetry run pytest -n auto tests/ ${PYTEST_QUIET} --cov-fail-under=${COVERAGE}" "Running tests with coverage"

# Step 3.2: Update coverage badge in README
if [ "$CI_MODE" = false ] && [ "$DRY_RUN" = false ]; then
    current_coverage_checksum=""
    if [ -f "coverage.xml" ]; then
        current_coverage_checksum="$(shasum -a 256 coverage.xml | awk '{print $1}')"
    fi

    if [ ! -f "coverage.xml" ]; then
        print_warning "coverage.xml not found after tests; skipping coverage badge update"
    elif [ "$current_coverage_checksum" = "$previous_coverage_checksum" ]; then
        print_info_colored "coverage.xml unchanged; skipping coverage badge update"
    else
        print_sub_step "Updating coverage badge in README.md"
        if [ -f "scripts/mkcovupd.sh" ]; then
            ./scripts/mkcovupd.sh
        else
            print_warning "Coverage badge update script not found"
        fi
    fi
elif [ "$CI_MODE" = false ] && [ "$DRY_RUN" = true ]; then
    print_sub_step "Would compare coverage.xml checksum before updating README badge"
fi


# =======================================
# PHASE 4: BUILD AND VALIDATE PACKAGE
# =======================================

echo ""
print_step_colored ""
print_step_colored "📦 PHASE 4: PACKAGE BUILD & VALIDATION"
print_step_colored ""

# Step 4.1: Clean previous builds
run_command "rm -rf dist/ build/ src/*.egg-info/" "Cleaning previous builds"

# Step 4.2: Build package
run_command "poetry build" "Building package"

# Step 4.3: Check package with twine
run_command "poetry run twine check dist/*" "Validating package with twine"

# Step 4.4: Build Exchange Intro PDF (if applicable)
if [ -d "docs-exchange-intro" ]; then
    print_sub_step "Building Exchange Intro Booklet"
    run_command "make -C docs-exchange-intro -j4" "Building Exchange Intro Booklet"
else
    print_warning "docs-exchange-intro directory not found; skipping Exchange Intro PDF build"
fi

# =======================================
# PHASE 5: BUILD SUMMARY
# =======================================

if [ "$DRY_RUN" = false ]; then
    LAST_COMMIT_SHORT=$(git rev-parse --short HEAD)
    TIMESTAMP=$(git log -1 --format=%ct)
    LAST_COMMIT_DATE_TIME=$(TZ=UTC git log -1 --format=%cd --date=format-local:'%Y-%m-%d %H:%M:%S UTC')
    LAST_COMMIT_BRANCH_NAME=$(git rev-parse --abbrev-ref HEAD)
    echo ""
    print_step_colored "=========================================="
    print_success_colored "BUILD COMPLETED SUCCESSFULLY!"
    print_step_colored "=========================================="
    echo ""
    echo "📊 Build Summary:"
    echo "     Last commit: ${LAST_COMMIT_SHORT} on ${LAST_COMMIT_BRANCH_NAME}"
    echo "     Date:        ${LAST_COMMIT_DATE_TIME}"
    echo "     Build date:  $(date -u +"%Y-%m-%d %H:%M:%S UTC")"
    echo ""
    echo "📦 Artifacts:"
    if [ -d "dist" ] && [ "$(ls -A dist)" ]; then
        for file in dist/*; do
            if [ -f "$file" ]; then
                FILENAME=$(basename "$file")
                SIZE=$(ls -lh "$file" | awk '{print $5}')
                echo -e "     - ${FILENAME}: ${BLUE}${SIZE}${NC}"
            fi
        done
    else
        print_warning "No artifacts found in 'dist/'!"
    fi
    echo ""
    echo "📊 Coverage report:"
    echo "     - [htmlcov/index.html](htmlcov/index.html)"
else
    echo ""
    print_warning_colored "DRY-RUN completed. No commands were executed."
fi

echo ""
exit 0
# End of script
