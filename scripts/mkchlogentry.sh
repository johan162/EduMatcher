#!/bin/bash
# CHANGELOG Entry Script
# Description: Creates a new CHANGELOG.md entry template for a planned release.
# CI/CD Support: No. Intended for local use before mkrelease.sh.
# Usage: ./scripts/mkchlogentry.sh <version> [major|minor|patch] [--dry-run] [--help]

set -euo pipefail

declare GITHUB_USER="johan162"
declare SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
declare PROGRAMNAME="mcprojsim"
declare PROGRAMNAME_PRETTY="MCProjSim"

if [ -n "${CI:-}" ] || [ -n "${GITHUB_ACTIONS:-}" ]; then
    echo "🔧 Running in CI mode"
    CI_MODE=true
else
    echo "🔧 Running in local mode"
    CI_MODE=false
fi

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

VERSION=""
RELEASE_TYPE="minor"
DRY_RUN=false
HELP=false

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

show_help() {
    cat << EOF
🚀 ${PROGRAMNAME_PRETTY} CHANGELOG Entry Script

DESCRIPTION:
    Creates and prepends a new CHANGELOG.md template entry for a planned release.
    Use this before running mkrelease.sh.

USAGE:
    $0 <version> [release-type] [OPTIONS]

ARGUMENTS:
    version         Semantic version number (e.g., 0.7.2, 1.0.0, 2.0.0rc1)
    release-type    Type of release (default: minor)
                    • major   - Breaking changes, incompatible API changes
                    • minor   - New features, backwards compatible
                    • patch   - Bug fixes, docs, or internal changes

OPTIONS:
    --dry-run       Show what would be written without modifying files
    --help, -h      Show this help message and exit

OUTPUT:
    Prepends a new version section to CHANGELOG.md using the established layout:
    Summary, Breaking Changes, Additions, Improvements, Bug Fixes,
    Documentation, and Internal.

SAFETY:
    • Refuses to create a duplicate entry if the version already exists
    • Must be run from the project root
    • Use --dry-run first to preview the action

EXAMPLES:
    $0 0.7.2 patch
    $0 0.8.0 minor --dry-run
    $0 1.0.0 major
EOF
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help|-h)
            HELP=true
            shift
            ;;
        -*)
            print_error_colored "Unknown option: $1"
            echo "Use --help for usage information"
            exit 2
            ;;
        *)
            if [[ -z "$VERSION" ]]; then
                VERSION="$1"
            else
                RELEASE_TYPE="$1"
            fi
            shift
            ;;
    esac
done

if [ "$HELP" = true ]; then
    show_help
    exit 0
fi

if [[ -z "$VERSION" ]]; then
    print_error_colored "Version is required"
    echo "Use --help for usage information"
    exit 2
fi

VERSION="${VERSION/-rc/rc}"

if [[ "$RELEASE_TYPE" != "major" && "$RELEASE_TYPE" != "minor" && "$RELEASE_TYPE" != "patch" ]]; then
    print_error_colored "Release type must be one of: major, minor, patch"
    exit 2
fi

echo ""
echo "=========================================="
echo "  ${PROGRAMNAME_PRETTY} CHANGELOG Entry Script"
echo "=========================================="
echo "Branch: $(git branch --show-current)"
echo "Commit: $(git rev-parse --short HEAD)"
if [ "$DRY_RUN" = true ]; then
    print_warning ""
    print_warning_colored "DRY-RUN MODE: CHANGELOG.md will not be modified"
    print_warning ""
fi
echo ""

print_step_colored ""
print_step_colored "📝 PHASE 1: VALIDATION"
print_step_colored ""

if [[ ! -f pyproject.toml ]]; then
    print_error_colored "Script must be run from the project root"
    exit 2
fi
print_success_colored "Project root detected"

if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(rc[1-9][0-9]?)?$ ]]; then
    print_error_colored "Version must follow semver format (x.y.z or x.y.zrcNN)"
    exit 2
fi
print_success_colored "Version format valid: $VERSION"

if [[ -f CHANGELOG.md ]] && grep -Eq "^## \[v${VERSION}\] - [0-9]{4}-[0-9]{2}-[0-9]{2}$" CHANGELOG.md; then
    print_error_colored "CHANGELOG.md already contains an entry for v$VERSION"
    exit 1
fi
print_success_colored "No existing CHANGELOG entry found for v$VERSION"

print_step_colored ""
print_step_colored "🛠 PHASE 2: CREATE ENTRY"
print_step_colored ""

CHANGELOG_DATE="$(date +%Y-%m-%d)"

if [ "$DRY_RUN" = true ]; then
    print_warning "[DRY-RUN] Would prepend a new CHANGELOG.md entry for v$VERSION"
    cat << EOF

## [v$VERSION] - $CHANGELOG_DATE

Release Type: $RELEASE_TYPE

### 📋 Summary
- [Brief summary of the release]

### ⚠️ Breaking Changes
- [Breaking changes]

### ✨ Additions
- [New features]

### 🚀 Improvements
- [Improvements]

### 🐛 Bug Fixes
- [Bug fixes]

### 📚 Documentation
- [Documentation changes]

### 🛠 Internal
- [Internal changes]

EOF
    exit 0
fi

TMP_ENTRY="$(mktemp)"
trap 'rm -f "$TMP_ENTRY"' EXIT

cat > "$TMP_ENTRY" << EOF
## [v$VERSION] - $CHANGELOG_DATE

Release Type: $RELEASE_TYPE

### 📋 Summary
- [Brief summary of the release]

### ⚠️ Breaking Changes
- [Breaking changes]

### ✨ Additions
- [New features]

### 🚀 Improvements
- [Improvements]

### 🐛 Bug Fixes
- [Bug fixes]

### 📚 Documentation
- [Documentation changes]

### 🛠 Internal
- [Internal changes]

EOF

if [[ -f CHANGELOG.md ]]; then
    cat "$TMP_ENTRY" CHANGELOG.md > CHANGELOG_NEW.tmp
    mv CHANGELOG_NEW.tmp CHANGELOG.md
else
    mv "$TMP_ENTRY" CHANGELOG.md
    trap - EXIT
fi

print_success_colored "Created CHANGELOG entry for v$VERSION"
print_warning_colored "Edit CHANGELOG.md and replace the placeholder bullets before running mkrelease.sh"

echo ""
echo "Next steps:"
echo "  1. Update CHANGELOG.md with the actual release notes"
echo "  2. Run ./scripts/mkrelease.sh $VERSION $RELEASE_TYPE"
echo ""