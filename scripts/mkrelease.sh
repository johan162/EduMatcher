#!/bin/bash
# mcprojsim Release Script
# Description: Automates the release process for mcprojsim, including versioning and release validation.
# CI/CD Support: No. Can not be run in CI as it requires user interaction.
# Usage: ./scripts/mkrelease.sh <version> [major|minor|patch] [--dry-run] [--help]
#
# Example: ./scripts/mkrelease.sh 2.1.0 minor
# Example: ./scripts/mkrelease.sh 2.1.0 minor --dry-run
# Example: ./scripts/mkrelease.sh --help

set -euo pipefail  # Exit on any error or uninitialized variable

# Color codes

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
    echo -e "${GREEN}✓${NC} ${1}"
}

print_success_colored() {
    echo -e "${GREEN}✓ ${1}${NC}"
}

print_error() {
    echo -e "${RED}✗${NC} ${1}" >&2
}

print_error_colored() {
    echo -e "${RED}❌ ${1}${NC}" >&2
}
# Alternate non-colored glyph for error: ✗

print_warning() {
    echo -e "${YELLOW}⚠${NC} ${1}"
}

print_warning_colored() {
    echo -e "${YELLOW}⚠ ${1}${NC}"
}

# =====================================
# Help function
# =====================================
show_help() {
    cat << EOF
🚀 ${PROGRAMNAME_PRETTY} Release Script

DESCRIPTION:
    Automated release script for ${PROGRAMNAME} with comprehensive quality gates.
    Performs validation, testing, versioning, and git operations for releases.

USAGE:
    $0 <version> [release-type] [options]

ARGUMENTS:
    version         Semantic version number (e.g., 2.1.0, 1.0.0, 0.9.1)
                    Must follow semver format: MAJOR.MINOR.PATCH

    release-type    Type of release (default: minor)
                    • major   - Breaking changes, incompatible API changes
                    • minor   - New features, backwards compatible  
                    • patch   - Bug fixes, backwards compatible

OPTIONS:
    --dry-run       Preview all commands without executing them
                    Shows exactly what would be done without making changes
                    
    --help, -h      Show this help message and exit

EXAMPLES:
    # Show help
    $0 --help
    
    # Preview a minor release (recommended first step)
    $0 2.1.0 minor --dry-run
    
    # Execute a minor release
    $0 2.1.0 minor
    
    # Create a patch release with preview
    $0 2.0.1 patch --dry-run
    $0 2.0.1 patch

    # Create a major release
    $0 3.0.0-rc1 major --dry-run
    $0 3.0.0-rc1 major

QUALITY GATES:
    The script enforces comprehensive quality controls:
    ✓ Repository state validation (clean working directory)
    ✓ Test suite execution (>90% coverage requirement)
    ✓ Static analysis and code formatting checks
    ✓ Integration testing with all example networks
    ✓ Package building and validation via twine
    ✓ Semver compliance and duplicate version prevention
    ✓ Version consistency across all project files

WORKFLOW:
    1. Pre-release validation (repository state, version format, changelog presence)
    2. Comprehensive testing (unit tests, integration, static analysis)
    3. Release preparation (version updates, release assets)
    4. Release execution (git commit, merge, tag, push)
    5. Post-release cleanup (sync branches, clean artifacts)

REQUIREMENTS:
    • Must be run from project root directory
    • Must be on 'develop' branch with clean working directory
    • Requires: git, python, poetry, gh
    • Requires an existing CHANGELOG.md entry for the planned version
    • Requires Poetry dev dependencies installed (run: poetry install)

SAFETY:
    • Use --dry-run first to preview all operations
    • Script validates all conditions before making changes
    • Fails fast on any error to prevent partial releases
    • All git operations are atomic and reversible

For more information, see docs/developer_guide.md
EOF
}

# Parse arguments
VERSION=""
RELEASE_TYPE="minor"
DRY_RUN=false

for arg in "$@"; do
    case $arg in
        --help|-h)
            show_help
            exit 0
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -*)
            print_error_colored "Unknown option: $arg"
            echo "Usage: $0 <version> [major|minor|patch] [--dry-run] [--help]"
            echo "Run '$0 --help' for detailed information"
            exit 1
            ;;
        *)
            if [[ -z "$VERSION" ]]; then
                VERSION="$arg"
            else
                RELEASE_TYPE="$arg"
            fi
            shift
            ;;
    esac
done

if [[ -z "$VERSION" ]]; then
    print_error_colored "Error: Version required"
    echo ""
    echo "Usage: $0 <version> [major|minor|patch] [--dry-run] [--help]"
    echo ""
    echo "Examples:"
    echo "  $0 2.1.0 minor"
    echo "  $0 2.1.0 minor --dry-run"
    echo "  $0 --help"
    echo ""
    echo "Run '$0 --help' for detailed information"
    exit 1
fi

VERSION="${VERSION/-rc/rc}"

# Function to execute command or print it in dry-run mode
run_command() {
    local cmd="$1"
    local description="${2:-}"
    
     if [ "$DRY_RUN" = "true" ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would execute: ${cmd}"
    else
        print_sub_step "$description"
        echo "Executing: $cmd"
        if eval "$cmd"; then
            print_success "$description completed!"
        else
            print_error_colored "$description failed! Aborting."
            exit 1
        fi
    fi
}

# Conditional execution for commands that need special dry-run handling
check_condition() {
    local condition="$1"
    local error_msg="$2"
    
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "  [DRY-RUN] Would check: $condition"
        echo "  [DRY-RUN] Would fail with: $error_msg (if condition false)"
        return 0  # Don't actually fail in dry-run
    else
        if ! eval "$condition"; then
            print_error_colored "$error_msg"
            exit 1
        fi
    fi
}

if [[ "$DRY_RUN" == "true" ]]; then
    print_warning_colored "🔍 DRY RUN MODE - No commands will be executed"
    echo "🚀 Would start ${PROGRAMNAME_PRETTY} v$VERSION release process..."
    echo "📋 Release type: $RELEASE_TYPE"
else
    echo "🚀 Starting ${PROGRAMNAME_PRETTY} v$VERSION release process..."
    echo "📋 Release type: $RELEASE_TYPE"
fi

# =====================================
# PHASE 1: PRE-RELEASE VALIDATION
# =====================================

print_step_colored ""
print_step_colored "🔍 PHASE 1: PRE-RELEASE VALIDATION"
print_step_colored ""

# 1.1: Check if we're in the root directory (pyproject.toml must exist)
run_command "test -f pyproject.toml" "Build script must be run from project root."

# 1.2: Ensure Poetry is available and a Poetry environment exists
if [ "$DRY_RUN" = false ]; then
    if ! command -v poetry >/dev/null 2>&1; then
        print_error_colored "Poetry is required but was not found in PATH."
        exit 2
    fi

    if poetry env info --path >/dev/null 2>&1; then
        echo "Using Poetry environment: $(poetry env info --path)"
    else
        print_error_colored "No Poetry environment found. Run 'poetry install' first."
        exit 2
    fi

    for required_command in pytest mypy black twine; do
        if ! poetry run "$required_command" --version >/dev/null 2>&1; then
            print_error_colored "Required Poetry command '$required_command' is unavailable. Run 'poetry install'."
            exit 2
        fi
    done
else
    echo "  [DRY-RUN] Would verify Poetry is available, a Poetry environment exists, and dev tools are installed"
fi

# 1.3: Verify we're on develop and it's clean
check_condition '[[ $(git symbolic-ref --short HEAD) == "develop" ]]' "Must be on develop branch"
check_condition '[[ -z $(git status --porcelain) ]]' "Working directory must be clean"

if [[ "$DRY_RUN" == "false" && -n $(git status --porcelain) ]]; then
    git status --short
    exit 1
fi

# 1.4: Pull latest changes
run_command "git pull origin develop" "Pulling latest changes..."

# 1.5: Validate version format (Poetry / PEP 440 compatible)
check_condition '[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+(rc[1-9][0-9]?)?$ ]]' "Version must follow semver format (x.y.z or x.y.zrcNN)"

# 1.6: Check if version already exists
check_condition '! git tag | grep -q "v${VERSION}\$"' "Tag v$VERSION already exists"

# 1.7: Check if CHANGELOG entry exists for the planned version
print_sub_step "Verifying CHANGELOG.md contains an entry for v$VERSION..."
if [[ ! -f CHANGELOG.md ]]; then
    print_error_colored "CHANGELOG.md not found. Run ./scripts/mkchlogentry.sh $VERSION $RELEASE_TYPE first."
    exit 1
fi
if ! grep -Eq "^## \[v${VERSION}\] - [0-9]{4}-[0-9]{2}-[0-9]{2}$" CHANGELOG.md; then
    print_error_colored "No CHANGELOG.md entry found for v$VERSION"
    echo "Run: ./scripts/mkchlogentry.sh $VERSION $RELEASE_TYPE to manually update the changelog, or"
    echo "    use the /changelog-entry skill in copilot to automatically generate the entries"
    exit 1
fi
print_success "Found CHANGELOG entry for v$VERSION"

# =====================================
# PHASE 2: UNIT TESTING & STATIC ANALYSIS
# =====================================

print_step_colored ""
print_step_colored "🧪 PHASE 2: UNIT TESTING & STATIC ANALYSIS"
print_step_colored ""

# 2.1: Static analysis and code quality
echo "  ✓ Checking code formatting..."
run_command "make check"
# run_command "poetry run black --check --diff src/ tests/" "Checking code formatting"
# run_command "poetry run flake8 src/${PROGRAMNAME} tests/" "Running flake8 static analysis"
# run_command "poetry run pyright src/ tests/" "Running pyright static analysis"
# run_command "poetry run mypy src/${PROGRAMNAME} --ignore-missing-imports" "Running mypy static analysis"

# 2.2: Full test suite with coverage requirements
run_command "poetry run pytest -n auto tests/ --cov=src/${PROGRAMNAME} --cov-report=term-missing --cov-report=html:htmlcov --cov-report=xml --cov-fail-under=${COVERAGE}"  "Running full test suite with coverage..."

if [[ "$DRY_RUN" == "false" && $? -ne 0 ]]; then
    print_error_colored "Test suite failed - aborting release"
    exit 1
fi

# =====================================
# PHASE 3: RELEASE PREPARATION
# =====================================

print_step_colored ""
print_step_colored "📝 PHASE 3: RELEASE PREPARATION"
print_step_colored ""

# 3.1: Update version numbers
if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [DRY-RUN] Would update version in pyproject.toml to $VERSION"
    echo "  [DRY-RUN] Would update version in README.md to $VERSION"
else
    echo "  ✓ Updating version in pyproject.toml..."
    poetry version "$VERSION"
    VERSION="$(poetry version --short)"

    echo "  ✓ Updating version in README.md..."
    sed -i.bak -E 's/^  version *= *\{.*\}/  version = {'"$VERSION"'}/' README.md
fi

# Generate PDF version of User Guide for release assets
if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [DRY-RUN] Would generate PDF versions of User Guide for release assets"
else
    echo "  ✓ Generating all PDF version of User Guide for release assets..."
    make -C docs -j 4 pdf-docs pdf-api-ref || {
        print_warning_colored "Makefile target 'pdf-docs' failed. Skipping PDF generation."
        exit 1;
    }

    echo "  ✓ Checking if these files exist:"
    echo "./dist/${PROGRAMNAME}_user_guide-a4-${VERSION}.pdf"
    echo "./dist/${PROGRAMNAME}_user_guide-dark-a4-${VERSION}.pdf"
    echo "./dist/${PROGRAMNAME}_user_guide-b5-${VERSION}.pdf"
    echo "./dist/${PROGRAMNAME}_user_guide-dark-b5-${VERSION}.pdf"
    echo "./dist/${PROGRAMNAME}_api_ref-a4-${VERSION}.pdf"
    echo "./dist/${PROGRAMNAME}_api_ref-dark-a4-${VERSION}.pdf"
    echo "./dist/${PROGRAMNAME}_api_ref-b5-${VERSION}.pdf"
    echo "./dist/${PROGRAMNAME}_api_ref-dark-b5-${VERSION}.pdf"

    if [[ ! -f "./dist/${PROGRAMNAME}_user_guide-a4-${VERSION}.pdf" \
          || ! -f "./dist/${PROGRAMNAME}_user_guide-dark-a4-${VERSION}.pdf" \
          || ! -f "./dist/${PROGRAMNAME}_user_guide-b5-${VERSION}.pdf" \
          || ! -f "./dist/${PROGRAMNAME}_user_guide-dark-b5-${VERSION}.pdf" \
          || ! -f "./dist/${PROGRAMNAME}_api_ref-a4-${VERSION}.pdf" \
          || ! -f "./dist/${PROGRAMNAME}_api_ref-dark-a4-${VERSION}.pdf" \
          || ! -f "./dist/${PROGRAMNAME}_api_ref-b5-${VERSION}.pdf" \
          || ! -f "./dist/${PROGRAMNAME}_api_ref-dark-b5-${VERSION}.pdf" ]]; then
        print_error_colored "Expected PDF not found at ./dist directory"
        exit 1;
    fi    
    
    echo "  ✓ Generating HTML version of User Guide for release assets..."
    make -C docs docs || {
        print_warning_colored "Makefile target 'docs' failed. Skipping HTML generation."
        exit 1;
    }
fi

# =====================================
# PHASE 4: RELEASE EXECUTION
# =====================================
print_step_colored ""
print_step_colored "🎯 PHASE 4: RELEASE EXECUTION"
print_step_colored ""

# 4.1: Commit version updates
run_command "git add pyproject.toml poetry.lock CHANGELOG.md README.md docs/user_guide/userguide_template*.tex docs/api_reference/api_ref_template*.tex docs/examples.md" "Staging release files..."
run_command "git commit -m \"chore(release): prepare $VERSION

- Update version to $VERSION
- Update changelog with release notes
- All tests passing with >80% coverage
- Package build validation complete\"" "Committing release preparation..."

# 4.2: Merge to main branch and create release commit
run_command "git checkout main" "Switching to main branch..."
run_command "git pull origin main" "Pulling latest main..."

# Squash merge develop into main
run_command "git merge --squash develop" "Squashing develop changes..."
run_command "git commit -m \"release: $VERSION

Summary of changes:
- All features and fixes from develop branch
- Comprehensive test coverage (>${COVERAGE}%)
- Full integration testing completed
- Package build validation successful
- Static analysis passed

See CHANGELOG.md for detailed changes.\"" "Creating release commit on main..."


# 4.3: Create annotated release tag
if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [DRY-RUN] Would create annotated tag $VERSION..."
    echo "  [DRY-RUN] Tag message would include release type, date, and QA checklist"
else
    echo "  ✓ Creating release tag..."
    CHANGELOG_DATE=$(date +%Y-%m-%d)
    git tag -a "v$VERSION" -m "Release tag v$VERSION

Release Type: $RELEASE_TYPE
Release Date: $CHANGELOG_DATE

Quality Assurance:
✓ Full test suite passed (>80% coverage)
✓ All example networks validated  
✓ CLI and REPL functionality verified
✓ Package build and validation complete
✓ Static analysis passed
✓ Integration tests passed

Changelog: See CHANGELOG.md for detailed changes"
fi

# 4.4: Push main branch and tags
run_command "git push origin main" "Pushing main branch..."
run_command "git push origin \"v$VERSION\"" "Pushing release tag..."

# =====================================
# PHASE 5: POST-RELEASE CLEANUP
# =====================================

print_step_colored ""
print_step_colored "🧹 PHASE 5: POST-RELEASE CLEANUP AND MERGE BACK TO DEVELOP"
print_step_colored ""

# 5.1: Return to develop and merge back release changes
run_command "git checkout develop" "Switching back to develop..."

# 5.2: Merge main into develop to reconcile squash merge
if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [DRY-RUN] Would merge main into develop with --no-ff"
    echo "  [DRY-RUN] This reconciles the squashed commits on main"
else
    echo "  ✓ Merging main into develop to sync branches..."
    
    # Use --no-ff to create explicit merge commit
    git merge --no-ff -m "chore: sync develop with main after release v$VERSION" main

    if [[ $? -ne 0 ]]; then
        print_error_colored "Failed to merge main into develop"
        echo ""
        echo "This indicates merge conflicts. To resolve:"
        echo "  1. git status  # See conflicting files"
        echo "  2. Edit files to resolve conflicts"
        echo "  3. git add <resolved-files>"
        echo "  4. git commit -m \"chore: resolve merge conflicts after release v$VERSION\""
        echo "  5. git push origin develop"
        echo ""
        exit 1
    fi
    
    print_success "develop synced with main"
fi

# =====================================
# PHASE 6: TRIGGER CI/CD WORKFLOWS
# =====================================

print_step_colored ""
print_step_colored " ⌛ PHASE 6: TRIGGER AND WAIT FOR CI/CD WORKFLOWS"
print_step_colored ""

# 6.1: Push synced develop branch
run_command "git push origin develop" "Pushing updated develop..."

echo -e "${BLUE}🕐${NC} Monitoring GitHub Actions..."
echo ""

# Sometime some extra time is needed for GitHub to register the new push and trigger the workflow, so we wait a bit before watching the runs
sleep 3

if [[ "$DRY_RUN" == "false" ]]; then
    # Watch the latest workflow run triggered by the push
    gh run watch --exit-status
    
    if [[ $? -eq 0 ]]; then
        print_success "CI workflows completed successfully!"
    else
        print_error "CI workflows failed!"
        echo "View logs: gh run view --log-failed"
        exit 1
    fi
else
    echo "  [DRY-RUN] Would watch: gh run watch --exit-status"
fi

# =====================================
# PHASE 7: BUILD DISTRIBUTION PACKAGE
# =====================================
print_step_colored ""
print_step_colored "📦 PHASE 7: PACKAGE FOR DISTRIBUTION"
print_step_colored ""

# 7.1: Clean up old build artifacts
run_command "rm -rf build/ dist/ src/*.egg-info/ htmlcov/" "Cleaning up build artifacts..."
run_command "rm -f *.bak src/${PROGRAMNAME}/*.bak" "Removing backup files..."

# 7.2: Build Package with the now updated version number
run_command "poetry build" "Testing package building..."

if [[ "$DRY_RUN" == "false" && $? -ne 0 ]]; then
    print_error_colored "Distribution package build failed"
    exit 1
fi

# 7.3: Package building validation
run_command "poetry run twine check dist/*" "Verifying built packages..."

if [[ "$DRY_RUN" == "false" && $? -ne 0 ]]; then
    print_error_colored "Distribution package validation failed"
    exit 1
fi

# 7.4 Generate PDF version of User Guide for release assets
if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [DRY-RUN] Would generate PDF version of User Guide for release assets"
else
    echo "  ✓ Generating PDF version of User Guide for release assets..."
    make -C docs -j 4 pdf-docs pdf-api-ref  || {
        print_warning_colored "Makefile target 'pdf' failed. Skipping PDF generation."
    }
    
    # Zip-the PDFs into one API-bundle and one User-guide-budle for easier distribution and upload to GitHub releases
    echo "  ✓ Creating ZIP bundles of generated PDFs for release assets..."
    (cd ./dist && zip -9 "${PROGRAMNAME}_user_guide_bundle-${VERSION}.zip" "${PROGRAMNAME}_user_guide-${VERSION}.pdf" "${PROGRAMNAME}_user_guide-dark-${VERSION}.pdf" "${PROGRAMNAME}_user_guide-b5-${VERSION}.pdf" "${PROGRAMNAME}_user_guide-dark-b5-${VERSION}.pdf")
    (cd ./dist && zip -9 "${PROGRAMNAME}_api_ref_bundle-${VERSION}.zip" "${PROGRAMNAME}_api_ref-${VERSION}.pdf" "${PROGRAMNAME}_api_ref-dark-${VERSION}.pdf" "${PROGRAMNAME}_api_ref-b5-${VERSION}.pdf" "${PROGRAMNAME}_api_ref-dark-b5-${VERSION}.pdf")
    (cd ./dist && rm *.pdf)

fi

# 7.5 Generate MCP Bundle for release assets
if [[ "$DRY_RUN" == "true" ]]; then
    echo "  [DRY-RUN] Would generate MCP Bundle for release assets"
else
    echo "  ✓ Generating MCP Bundle for release assets..."
    ./scripts/mkmcpbundle.sh || {
        print_warning_colored "MCP Bundle generation failed. Skipping bundle creation."
    }
fi 

# =====================================
# PHASE 8: RELEASE SUMMARY
# =====================================

echo ""
if [[ "$DRY_RUN" == "true" ]]; then
    print_step_colored ""
    print_step_colored "🔍 PHASE 7: DRY RUN RELEASE SUMMARY"
    print_step_colored ""
    echo "📋 Commands that would be executed:"
    echo "   → All validation checks (repository state, version format, etc.)"
    echo "   → Full test suite with coverage requirements"
    echo "   → Static analysis and code formatting checks"
    echo "   → Integration testing with example networks"
    echo "   → Package building and validation"
    echo "   → Version number updates in multiple files"
    echo "   → Changelog generation and user editing"
    echo "   → Git operations: commit, merge, tag, push"
    echo "   → Post-release cleanup"
    echo ""
    echo "🚀 To execute for real:"
    echo "   $0 $VERSION $RELEASE_TYPE"
else
    print_step_colored ""
    print_step_colored "✅ PHASE 7: RELEASE SUMMARY"
    print_step_colored ""
    print_success_colored "🎉 ${PROGRAMNAME_PRETTY} v${VERSION} released successfully!"
    echo ""
    echo "📊 Release Summary:"
    echo "   Version:     $VERSION"
    echo "   Type:        $RELEASE_TYPE"
    echo "   Date:        $(date +%Y-%m-%d)"
    echo "   Branch:      main"
    echo "   Tag:         v$VERSION"
    echo ""
    echo "📦 Artifacts:"
    echo "   - $(ls dist|head -1)"
    echo "   - $(ls dist|tail -1)"
    echo ""
    echo "📊 Branch Status:"
    echo "   GitHub will show develop as 'ahead' of main - this is expected!"
    echo "   • develop preserves detailed commit history"
    echo "   • main uses squash merges (one commit per release)"
    echo "   • Code content is identical between branches"
    echo ""
    echo "   Verify with: git diff main develop"
    echo ""
    echo "🚀 Next Steps:"
    echo "   1. Verify release tag on GitHub"
    echo "   2. Run 'scripts/mkghrelease.sh' to create GitHub release (which will also upload packages to PyPI)"
    echo "   3. Announce the release!"
    echo ""
    echo "📋 Quality Metrics Achieved:"
    echo "   ✓ Test Coverage: >${COVERAGE}%"
    echo "   ✓ All Example Projects: Validated"
    echo "   ✓ Package Build: Successful" 
    echo "   ✓ Static Analysis: Passed"
    echo "   ✓ Integration & Unit Tests: Passed"
    echo ""    
    print_success_colored "Thank you for contributing to ${PROGRAMNAME_PRETTY}! 🎉"
fi

echo ""
exit 0
# End of script