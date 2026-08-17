# Detect CI environment
if [ -n "${CI:-}" ] || [ -n "${GITHUB_ACTIONS:-}" ]; then
    echo "🔧 Running in CI mode"
    CI_MODE=true
else
    echo "🔧 Running in local mode"
    CI_MODE=false
fi

# ===================================
# Color codes for terminal output
# ===================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BLUE='\033[0;34m'
LIGHT_BLUE='\033[1;34m'
LIGHT_CYAN='\033[1;36m'
LIGHT_GREEN='\033[1;32m'
LIGHT_RED='\033[1;31m'
LIGHT_YELLOW='\033[1;33m'
LIGHT_MAGENTA='\033[1;35m'
NC='\033[0m' # No Color

# =====================================
# Functions to print colored output in scripts
# =====================================

print_step() {
    echo -e "${BLUE}==>${NC} ${1}"
}

print_step_colored() {
    echo -e "${BLUE}==>${NC} ${YELLOW}${1} ${BLUE}${2}${NC}"
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

print_plain() {
    echo -e "${1}"
}

print_error_colored() {
    if [ "$CI_MODE" = true ]; then
        echo -e "✗ Error: ${1}"
    else
        echo -e "${RED}❌ Error: ${1}${NC}" >&2
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

print_header() {
    echo -e "${LIGHT_CYAN}=== ${1} ===${NC}"
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

# Function to execute two commands in parallel when both are required
run_parallel_commands() {
    local cmd1="$1"
    local description1="$2"
    local cmd2="$3"
    local description2="$4"

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY-RUN]${NC} Would execute in parallel: ${cmd1}"
        echo -e "${YELLOW}[DRY-RUN]${NC} Would execute in parallel: ${cmd2}"
        return 0
    fi

    print_sub_step "Running PDF bundle builds in parallel"
    echo "Executing (background): $cmd1"
    eval "$cmd1" &
    local pid1=$!

    echo "Executing (background): $cmd2"
    eval "$cmd2" &
    local pid2=$!

    local status1=0
    local status2=0

    wait "$pid1" || status1=$?
    wait "$pid2" || status2=$?

    if [ "$status1" -eq 0 ]; then
        print_success_colored "$description1 completed"
    else
        print_error_colored "$description1 failed"
    fi

    if [ "$status2" -eq 0 ]; then
        print_success_colored "$description2 completed"
    else
        print_error_colored "$description2 failed"
    fi

    if [ "$status1" -ne 0 ] || [ "$status2" -ne 0 ]; then
        exit 1
    fi
}
