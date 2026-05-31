#!/bin/bash

# mkghrelease.sh - Create GitHub release using gh CLI
# 
# This script should be run AFTER mkrelease.sh has completed successfully
# and all GitHub workflows have finished.
#
# Usage: ./scripts/mkghrelease.sh [OPTIONS]
#
# Options:
#   --help          Show this help message
#   --pre-release   Force marking the release as a pre-release
#   --dry-run       Show commands without executing them

set -e

# =====================================
# COLOR CODES
# =====================================

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# =====================================
# CONFIGURATION
# =====================================

declare GITHUB_USER="johan162"
declare SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
declare PROGRAMNAME="mcprojsim"
declare PROGRAMNAME_PRETTY="MCProjSim"
declare PROGRAM_ENTRYPOINT="mcprojsim.cli"
declare SMOKE_TEST_FILE="tests/test_simulation.py"
declare COVERAGE="80"


REQUIRED_GH_VERSION="2.0.0"
DIST_DIR="dist"
CHANGELOG_FILE="CHANGELOG.md"
RELEASE_NOTES_FILE=".github_release_notes.tmp"

# =====================================
# COMMAND LINE OPTIONS
# =====================================

DRY_RUN=false
FORCE_PRE_RELEASE=false
SHOW_HELP=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --help)
            SHOW_HELP=true
            shift
            ;;
        --pre-release)
            FORCE_PRE_RELEASE=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo -e "${RED}❌ Unknown option: $1${NC}"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# =====================================
# HELPER FUNCTIONS
# =====================================

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

show_help() {
    cat << EOF
🚀 GitHub Release Creator for ${PROGRAMNAME_PRETTY}

DESCRIPTION:
    Creates a GitHub release using the gh CLI tool. This script should be run
    AFTER mkrelease.sh has completed successfully and all GitHub Actions 
    workflows have finished.

USAGE:
    $0 [OPTIONS]

OPTIONS:
    --help          Show this help message and exit
    --pre-release   Force the release to be marked as a pre-release
                    (overrides automatic detection based on tag name)
    --dry-run       Show what commands would be executed without actually
                    running them

PREREQUISITES:
    1. GitHub CLI (gh) version ${REQUIRED_GH_VERSION} or higher installed
    2. Authenticated with GitHub (gh auth login)
    3. mkrelease.sh completed successfully
    4. All GitHub Actions workflows completed
    5. On the 'main' branch with latest tag pushed

AUTOMATIC PRE-RELEASE DETECTION:
    If --pre-release is NOT specified, the script automatically determines
    pre-release status based on the tag name:
    
    - Tags ending with -rc1, -rc2, etc. → Pre-release
    - All other tags (e.g., v1.0.0)     → Stable release

WHAT THIS SCRIPT DOES:
    1. Validates gh CLI is installed and authenticated
    2. Checks that no workflows are currently running
    3. Identifies the latest tag on main branch
    4. Validates tag format (vX.Y.Z or vX.Y.Z-rcN)
    5. Extracts release notes from CHANGELOG.md
    6. Opens editor for you to review/edit release notes
    7. Validates artifacts in dist/ directory
    8. Creates GitHub release with artifacts
    9. Cleans up temporary files

EXAMPLES:
    # Create a stable release (tag: v1.0.0)
    $0

    # Create a release candidate (tag: v1.0.0-rc1)
    $0

    # Force as pre-release regardless of tag
    $0 --pre-release

    # Preview what would be done
    $0 --dry-run

SEE ALSO:
    - scripts/mkrelease.sh    (Run this first to create the release)
    - scripts/mkbld.sh        (Build and test the package)

EOF
}

check_command_exists() {
    local cmd=$1
    if ! command -v "$cmd" &> /dev/null; then
        print_error "$cmd is not installed"
        return 1
    fi
    return 0
}

compare_versions() {
    # Compare two semantic versions
    # Returns: 0 if $1 >= $2, 1 otherwise
    local ver1=$1
    local ver2=$2
    
    if [[ "$ver1" == "$ver2" ]]; then
        return 0
    fi
    
    local IFS=.
    local i ver1_array=($ver1) ver2_array=($ver2)
    
    # Fill empty positions with zeros
    for ((i=${#ver1_array[@]}; i<${#ver2_array[@]}; i++)); do
        ver1_array[i]=0
    done
    
    for ((i=0; i<${#ver1_array[@]}; i++)); do
        if [[ -z ${ver2_array[i]} ]]; then
            ver2_array[i]=0
        fi
        if ((10#${ver1_array[i]} > 10#${ver2_array[i]})); then
            return 0
        fi
        if ((10#${ver1_array[i]} < 10#${ver2_array[i]})); then
            return 1
        fi
    done
    return 0
}

run_command() {
    local cmd=$1
    local description=$2
    
    if [[ "$DRY_RUN" == "true" ]]; then
        print_warning "[DRY-RUN] Would execute: $cmd"
        if [[ -n "$description" ]]; then
            echo "  Description: $description"
        fi
        return 0
    else
        if [[ -n "$description" ]]; then
            print_sub_step "$description"
        fi
        if eval "$cmd"; then
            return 0
        else
            print_error_colored "$description failed"
            return 1
        fi
    fi
}

# =====================================
# MAIN SCRIPT
# =====================================

if [[ "$SHOW_HELP" == "true" ]]; then
    show_help
    exit 0
fi

echo ""
echo "=========================================="
echo "  GitHub Release Creator for ${PROGRAMNAME_PRETTY}"
echo "=========================================="
echo "Repository: ${PROGRAMNAME}"
echo "Branch: $(git branch --show-current)"
echo "Commit: $(git rev-parse --short HEAD)"
if [[ "$DRY_RUN" == "true" ]]; then
    print_warning "DRY-RUN MODE: Commands will be printed but not executed"
fi
if [[ "$FORCE_PRE_RELEASE" == "true" ]]; then
    print_info "Pre-release mode: FORCED"
fi
echo ""

# =====================================
# PHASE 1: PREREQUISITES CHECK
# =====================================

print_step_colored ""
print_step_colored "🔍 PHASE 1: Prerequisites Check"
print_step_colored ""

# Check if we're in the root directory (pyproject.toml must exist)
run_command "test -f pyproject.toml" "Build script must be run from project root."

# 1.1: Check if gh CLI is installed
print_sub_step "Checking for GitHub CLI (gh)..."
if ! check_command_exists gh; then
    print_error "GitHub CLI (gh) is not installed"
    echo ""
    echo "Install instructions:"
    echo "  macOS:   brew install gh"
    echo "  Linux:   See https://github.com/cli/cli/blob/trunk/docs/install_linux.md"
    echo "  Windows: See https://github.com/cli/cli#installation"
    exit 1
fi
print_success "GitHub CLI found: $(gh --version | head -1)"

# 1.2: Check gh version
print_sub_step "Checking gh version..."
GH_VERSION=$(gh --version | head -1 | awk '{print $3}')
if ! compare_versions "$GH_VERSION" "$REQUIRED_GH_VERSION"; then
    print_error "GitHub CLI version $GH_VERSION is too old (need >= $REQUIRED_GH_VERSION)"
    echo "Update with: brew upgrade gh (macOS) or see https://github.com/cli/cli#installation"
    exit 1
fi
print_success "Version $GH_VERSION meets requirements"

# 1.3: Check gh authentication
print_sub_step "Checking GitHub authentication..."
if ! gh auth status &> /dev/null; then
    print_error "Not authenticated with GitHub"
    echo ""
    echo "Please authenticate with: gh auth login"
    echo "Then run this script again"
    exit 1
fi
print_success "Authenticated with GitHub"

# 1.4: Verify we're on main branch
print_sub_step "Verifying branch..."
CURRENT_BRANCH=$(git branch --show-current)
if [[ "$CURRENT_BRANCH" != "main" ]]; then
    print_error "Must be on 'main' branch (currently on '$CURRENT_BRANCH')"
    echo "Run: git checkout main"
    exit 1
fi
print_success "On main branch"

# 1.5: Check for uncommitted changes
print_sub_step "Checking for uncommitted changes..."
if [[ -n $(git status --porcelain) ]]; then
    print_error "Working directory has uncommitted changes"
    echo ""
    git status --short
    echo ""
    echo "Commit or stash changes before creating release"
    exit 1
fi
print_success "Working directory clean"

# 1.6: Check if we're up to date with remote
print_sub_step "Checking sync with remote..."
git fetch origin main --quiet
LOCAL_COMMIT=$(git rev-parse main)
REMOTE_COMMIT=$(git rev-parse origin/main)
if [[ "$LOCAL_COMMIT" != "$REMOTE_COMMIT" ]]; then
    print_error "Local main branch is not in sync with origin/main"
    echo "Local:  $LOCAL_COMMIT"
    echo "Remote: $REMOTE_COMMIT"
    echo ""
    echo "Run: git pull origin main"
    exit 1
fi
print_success "In sync with origin/main"

# =====================================
# PHASE 2: WORKFLOW STATUS CHECK
# =====================================

echo ""
print_step_colored ""
print_step_colored "⚙️  PHASE 2: GitHub Workflows Check"
print_step_colored ""

print_sub_step "Checking for running workflows..."
RUNNING_WORKFLOWS=$(gh run list --branch main --limit 5 --json status,conclusion | jq -r '.[] | select(.status=="in_progress" or .status=="queued") | .status' | wc -l)

# if [[ "$RUNNING_WORKFLOWS" -gt 0 ]]; then
#     print_error "There are $RUNNING_WORKFLOWS workflow(s) currently running on main branch"
#     echo ""
#     echo "Running workflows:"
#     gh run list --branch main --limit 4
#     echo ""
#     echo "Wait for workflows to complete before creating release"
#     echo "Check status: gh run list --branch main --limit 4"
#     exit 1
# fi
# print_success "No workflows currently running"

# print_sub_step "Checking latest workflow status..."
# LATEST_WORKFLOW_STATUS=$(gh run list --branch main --limit 1 --json conclusion | jq -r '.[0].conclusion')
# if [[ "$LATEST_WORKFLOW_STATUS" != "success" ]]; then
#     print_error "Latest workflow did not succeed (status: $LATEST_WORKFLOW_STATUS)"
#     echo ""
#     echo "Recent runs:"
#     gh run list --branch main --limit 5
#     echo ""
#     echo "Fix workflow failures before creating release"
#     exit 1
# fi
# print_success "Latest workflow succeeded"

# =====================================
# PHASE 3: VERSION VALIDATION
# =====================================

echo ""
print_step_colored ""
print_step_colored "🏷️  PHASE 3: Version Validation"
print_step_colored ""

# 3.1: Get latest tag
print_sub_step "Getting latest tag on main branch..."
LATEST_TAG=$(git describe --tags --abbrev=0 main 2>/dev/null || echo "")
if [[ -z "$LATEST_TAG" ]]; then
    print_error "No tags found on main branch"
    echo "Run mkrelease.sh first to create a release tag"
    exit 1
fi
print_success "Latest tag: $LATEST_TAG"

# 3.2: Validate tag format
print_sub_step "Validating tag format..."
if [[ ! "$LATEST_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(rc[0-9]{1,2})?$ ]]; then
    print_error "Invalid tag format: $LATEST_TAG"
    echo "Expected format: vX.Y.Z or vX.Y.ZrcN"
    echo "Examples: v1.0.0, v2.1.3rc1, v1.5.0rc12"
    exit 1
fi
print_success "Tag format valid"

# 3.3: Determine if pre-release
print_sub_step "Determining release type..."
IS_PRE_RELEASE=false
if [[ "$FORCE_PRE_RELEASE" == "true" ]]; then
    IS_PRE_RELEASE=true
    RELEASE_TYPE="pre-release (forced)"
elif [[ "$LATEST_TAG" =~ rc[0-9]+$ ]]; then
    IS_PRE_RELEASE=true
    RELEASE_TYPE="pre-release (auto-detected from tag)"
else
    IS_PRE_RELEASE=false
    RELEASE_TYPE="stable release"
fi
print_success "Release type: $RELEASE_TYPE"

# 3.4: Check if release already exists
print_sub_step "Checking if release already exists..."
if gh release view "$LATEST_TAG" &> /dev/null; then
    print_error "Release $LATEST_TAG already exists on GitHub"
    echo ""
    echo "View release: gh release view $LATEST_TAG"
    echo "Delete release: gh release delete $LATEST_TAG"
    echo ""
    exit 1
fi
print_success "Release does not exist yet"

# =====================================
# PHASE 4: ARTIFACTS VALIDATION
# =====================================

echo ""
print_step_colored ""
print_step_colored "📦 PHASE 4: Artifacts Validation"
print_step_colored ""


# 4.1: Check dist directory exists
print_sub_step "Checking dist directory..."
if [[ ! -d "$DIST_DIR" ]]; then
    print_error "$DIST_DIR directory not found"
    echo "Run mkrelease.sh first to build the package"
    exit 1
fi
print_success "$DIST_DIR directory exists"

# 4.2: Extract version from tag (without 'v' prefix)
VERSION_NUMBER=${LATEST_TAG#v}

# 4.3: Define expected artifact names

# For pre-release tags we must modify the version as the python build tools
# strip the "-rcN" to loose the '-' sign and appends it directly on the nuber, e.g. 1.0.0rc1

# Strip the '-' from the version for pre-releases
FILE_VERSION_NUMBER=${VERSION_NUMBER//-rc/rc}
EXPECTED_BUNDLE_FILE="${DIST_DIR}/${PROGRAMNAME}-mcp-bundle-${FILE_VERSION_NUMBER}.zip"
EXPECTED_USER_GUIDE_BUNDLE_ZIP="${DIST_DIR}/${PROGRAMNAME}_user_guide_bundle-${FILE_VERSION_NUMBER}.zip"
EXPECTED_API_REF_BUNDLE_ZIP="${DIST_DIR}/${PROGRAMNAME}_api_ref_bundle-${FILE_VERSION_NUMBER}.zip"

# 4.4: Fail fast if required release artifacts are missing
print_sub_step "Checking required release artifacts..."
if [[ ! -f "$EXPECTED_BUNDLE_FILE" ]]; then
    print_error "Required MCP bundle is missing: $EXPECTED_BUNDLE_FILE"
    exit 1
fi
if [[ ! -f "$EXPECTED_USER_GUIDE_BUNDLE_ZIP" ]]; then
    print_error "Required user guide bundle is missing: $EXPECTED_USER_GUIDE_BUNDLE_ZIP"
    exit 1
fi
if [[ ! -f "$EXPECTED_API_REF_BUNDLE_ZIP" ]]; then
    print_error "Required API reference bundle is missing: $EXPECTED_API_REF_BUNDLE_ZIP"
    exit 1
fi
print_success "Required artifacts found: $(basename "$EXPECTED_BUNDLE_FILE"), $(basename "$EXPECTED_USER_GUIDE_BUNDLE_ZIP"), $(basename "$EXPECTED_API_REF_BUNDLE_ZIP")"

# 4.5: Find expected artifacts
print_sub_step "Locating artifacts with version $FILE_VERSION_NUMBER..."
WHEEL_FILE=$(find "$DIST_DIR" -name "${PROGRAMNAME}-${FILE_VERSION_NUMBER}-*.whl" | head -1)
SDIST_FILE=$(find "$DIST_DIR" -name "${PROGRAMNAME}-${FILE_VERSION_NUMBER}.tar.gz" | head -1)
MCP_BUNDLE_ZIP="$EXPECTED_BUNDLE_FILE"
USER_GUIDE_BUNDLE_ZIP="$EXPECTED_USER_GUIDE_BUNDLE_ZIP"
API_REF_BUNDLE_ZIP="$EXPECTED_API_REF_BUNDLE_ZIP"

if [[ -z "$WHEEL_FILE" ]]; then
    print_error "Wheel file not found for version $VERSION_NUMBER"
    echo "Expected: dist/${PROGRAMNAME}-${FILE_VERSION_NUMBER}-*.whl"
    echo ""
    echo "Files in dist/:"
    ls -la "$DIST_DIR"
    exit 1
fi
print_success "Found wheel: $(basename "$WHEEL_FILE")"

if [[ -z "$SDIST_FILE" ]]; then
    print_error "Source distribution not found for version $VERSION_NUMBER"
    echo "Expected: dist/${PROGRAMNAME}-${FILE_VERSION_NUMBER}.tar.gz"
    echo ""
    echo "Files in dist/:"
    ls -la "$DIST_DIR"
    exit 1
fi
print_success "Found sdist: $(basename "$SDIST_FILE")"
print_success "Found MCP bundle: $(basename "$MCP_BUNDLE_ZIP")"
print_success "Found user guide bundle: $(basename "$USER_GUIDE_BUNDLE_ZIP")"
print_success "Found API reference bundle: $(basename "$API_REF_BUNDLE_ZIP")"

# 4.6: Validate artifact sizes
print_sub_step "Validating artifact sizes..."
WHEEL_SIZE=$(stat -f%z "$WHEEL_FILE" 2>/dev/null || stat -c%s "$WHEEL_FILE" 2>/dev/null)
SDIST_SIZE=$(stat -f%z "$SDIST_FILE" 2>/dev/null || stat -c%s "$SDIST_FILE" 2>/dev/null)
BUNDLE_SIZE=$(stat -f%z "$MCP_BUNDLE_ZIP" 2>/dev/null || stat -c%s "$MCP_BUNDLE_ZIP" 2>/dev/null || echo 1)
USER_GUIDE_BUNDLE_SIZE=$(stat -f%z "$USER_GUIDE_BUNDLE_ZIP" 2>/dev/null || stat -c%s "$USER_GUIDE_BUNDLE_ZIP" 2>/dev/null || echo 1)
API_REF_BUNDLE_SIZE=$(stat -f%z "$API_REF_BUNDLE_ZIP" 2>/dev/null || stat -c%s "$API_REF_BUNDLE_ZIP" 2>/dev/null || echo 1)

if [[ "$WHEEL_SIZE" -lt 1000 ]]; then
    print_error "Wheel file suspiciously small: $WHEEL_SIZE bytes"
    exit 1
fi

if [[ "$SDIST_SIZE" -lt 1000 ]]; then
    print_error "Source distribution suspiciously small: $SDIST_SIZE bytes"
    exit 1
fi

if [[ "$DRY_RUN" == "false" && "$BUNDLE_SIZE" -lt 1000 ]]; then
    print_error "MCP bundle suspiciously small: $BUNDLE_SIZE bytes"
    exit 1
fi

if [[ "$USER_GUIDE_BUNDLE_SIZE" -lt 1000 ]]; then
    print_error "User guide bundle suspiciously small: $USER_GUIDE_BUNDLE_SIZE bytes"
    exit 1
fi

if [[ "$API_REF_BUNDLE_SIZE" -lt 1000 ]]; then
    print_error "API reference bundle suspiciously small: $API_REF_BUNDLE_SIZE bytes"
    exit 1
fi

print_success "Wheel size:  $(numfmt --to=iec-i --suffix=B "$WHEEL_SIZE" 2>/dev/null || echo "$WHEEL_SIZE bytes")"
print_success "Sdist size:  $(numfmt --to=iec-i --suffix=B "$SDIST_SIZE" 2>/dev/null || echo "$SDIST_SIZE bytes")"
print_success "Bundle size: $(numfmt --to=iec-i --suffix=B "$BUNDLE_SIZE" 2>/dev/null || echo "$BUNDLE_SIZE bytes")"
print_success "User Guide size:  $(numfmt --to=iec-i --suffix=B "$USER_GUIDE_BUNDLE_SIZE" 2>/dev/null || echo "$USER_GUIDE_BUNDLE_SIZE bytes")"
print_success "API reference size:  $(numfmt --to=iec-i --suffix=B "$API_REF_BUNDLE_SIZE" 2>/dev/null || echo "$API_REF_BUNDLE_SIZE bytes")"

# =====================================
# PHASE 5: RELEASE NOTES PREPARATION
# =====================================

echo ""
print_step_colored ""
print_step_colored "📝 PHASE 5: Release Notes Preparation"
print_step_colored ""

# 5.1: Extract release notes from CHANGELOG.md
print_sub_step "Extracting release notes from CHANGELOG.md..."
if [[ ! -f "$CHANGELOG_FILE" ]]; then
    print_error "CHANGELOG.md not found"
    exit 1
fi

# Extract the section for this version from CHANGELOG.md
# Looks for ## [$VERSION] and captures until next ## or EOF
sed -n "/^## \[$LATEST_TAG\]/,/^## \[/p" "$CHANGELOG_FILE" | sed '$d' > "$RELEASE_NOTES_FILE"

EXTRACT_STATUS=$?

if [[ $EXTRACT_STATUS -ne 0 ]] || [[ ! -s "$RELEASE_NOTES_FILE" ]]; then
    print_error "Could not extract release notes for $LATEST_TAG from CHANGELOG.md"
    exit 1
fi


# =====================================
# PHASE 6: CREATE GITHUB RELEASE
# =====================================

echo ""
print_step_colored ""
print_step_colored "🚀 PHASE 6: Creating GitHub Release"
print_step_colored ""

# 6.1: Construct gh release create command
GH_RELEASE_CMD="gh release create \"$LATEST_TAG\" \
    --title \"${PROGRAMNAME_PRETTY} $LATEST_TAG\" \
    --notes-file \"$RELEASE_NOTES_FILE\" \
    \"$WHEEL_FILE\" \
    \"$SDIST_FILE\" \\
    \"$MCP_BUNDLE_ZIP\" \
    \"$USER_GUIDE_BUNDLE_ZIP\" \
    \"$API_REF_BUNDLE_ZIP\""

if [[ "$IS_PRE_RELEASE" == "true" ]]; then
    GH_RELEASE_CMD="$GH_RELEASE_CMD --prerelease"
fi

# 6.2: Create the release
print_sub_step "Creating GitHub release $LATEST_TAG..."
if [[ "$DRY_RUN" == "true" ]]; then
    print_warning "[DRY-RUN] Would execute:"
    echo "$GH_RELEASE_CMD"
    echo ""
    print_warning "[DRY-RUN] Release notes content:"
    cat "$RELEASE_NOTES_FILE"
else
    if eval "$GH_RELEASE_CMD"; then
        print_success "GitHub release created successfully!"
    else
        print_error "Failed to create GitHub release"
        print_warning "Release notes file preserved at: $RELEASE_NOTES_FILE"
        exit 1
    fi
fi

# =====================================
# PHASE 7: CLEANUP
# =====================================

echo ""
print_step_colored ""
print_step_colored "🧹 PHASE 7: Cleanup"
print_step_colored ""


if [[ "$DRY_RUN" == "false" ]]; then
    print_step "Removing temporary release notes file..."
    rm -f "$RELEASE_NOTES_FILE"
    print_success "Cleanup complete"
else
    print_warning "[DRY-RUN] Would remove: $RELEASE_NOTES_FILE"
fi

git checkout develop

# =====================================
# RELEASE COMPLETE
# =====================================

echo ""
if [[ "$DRY_RUN" == "true" ]]; then
    echo "=========================================="
    echo "  DRY-RUN COMPLETE"
    echo "=========================================="
    echo ""
    echo "No changes were made. Review the output above."
    echo "Run without --dry-run to create the actual release."
else
    echo "=========================================="
    echo "  ✅ GITHUB RELEASE COMPLETE!"
    echo "=========================================="
    echo ""
    echo "Release: $LATEST_TAG ($RELEASE_TYPE)"
    echo "View:    gh release view $LATEST_TAG"
    echo "URL:     https://github.com/${GITHUB_USER}/${PROGRAMNAME}/releases/tag/$LATEST_TAG"
    echo ""
    echo "Artifacts uploaded:"
    echo "  - $(basename "$WHEEL_FILE")"
    echo "  - $(basename "$SDIST_FILE")"
    echo "  - $(basename "$MCP_BUNDLE_ZIP")"
    echo "  - $(basename "$USER_GUIDE_BUNDLE_ZIP")"
    echo "  - $(basename "$API_REF_BUNDLE_ZIP")"
    echo ""
    echo "Next steps:"
    echo "  1. Verify release on GitHub:"
    echo "     https://github.com/${GITHUB_USER}/${PROGRAMNAME}/releases"
    echo "  2. Verify that PyPI upload has been done or is in progress (via GitHub Actions):"
    echo "     https://github.com/${GITHUB_USER}/${PROGRAMNAME}/actions"
    echo "  3. Announce release to users"
    echo ""
fi

# End of script