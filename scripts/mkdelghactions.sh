#!/bin/bash
# mkdelghactions.sh
# List or delete GitHub Actions workflow runs, keeping only the latest N runs.
#
# Default mode is LIST (no deletions).
# Use --delete to remove runs older than the most recent --keep N runs.

set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

MODE="list"
KEEP_N=20
LIMIT=200
REPO=""
WORKFLOW=""
BRANCH=""
INCLUDE_DISABLED=false
DRY_RUN=false

show_help() {
    cat <<'EOF'
Usage:
  ./scripts/mkdelghactions.sh [OPTIONS]

Description:
  Lists or deletes GitHub Actions workflow runs while keeping the latest N runs.
  The script operates on workflow runs (gh run list / gh run delete).

Options:
  -n, --keep N          Keep the latest N runs (default: 20)
  -L, --limit N         Max runs to fetch from GitHub API (default: 200)
  -R, --repo OWNER/REPO Target another repository
  -w, --workflow NAME   Filter by workflow name
  -b, --branch BRANCH   Filter by branch
  -a, --all             Include disabled workflows when used with --workflow
  --delete              Delete runs older than the kept N runs
  --list                List only (default mode)
  --dry-run             Show what would be deleted without deleting
  -h, --help            Show this help message

Examples:
  # List runs and show which would be deleted if keeping last 30
  ./scripts/mkdelghactions.sh --keep 30

  # Delete all but the latest 25 runs in this repo
  ./scripts/mkdelghactions.sh --delete --keep 25

  # Delete all but latest 15 runs for one workflow in another repo
  ./scripts/mkdelghactions.sh --delete -n 15 -w ci.yml -R owner/repo
EOF
}

print_error() {
    echo -e "${RED}✗ $1${NC}" >&2
}

print_info() {
    echo -e "${BLUE}==>${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

is_non_negative_int() {
    [[ "$1" =~ ^[0-9]+$ ]]
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -n|--keep)
            KEEP_N="${2:-}"
            shift 2
            ;;
        -L|--limit)
            LIMIT="${2:-}"
            shift 2
            ;;
        -R|--repo)
            REPO="${2:-}"
            shift 2
            ;;
        -w|--workflow)
            WORKFLOW="${2:-}"
            shift 2
            ;;
        -b|--branch)
            BRANCH="${2:-}"
            shift 2
            ;;
        -a|--all)
            INCLUDE_DISABLED=true
            shift
            ;;
        --delete)
            MODE="delete"
            shift
            ;;
        --list)
            MODE="list"
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            print_error "Unknown argument: $1"
            echo "Use --help for usage."
            exit 1
            ;;
    esac
done

if ! is_non_negative_int "$KEEP_N"; then
    print_error "--keep must be a non-negative integer"
    exit 1
fi

if ! is_non_negative_int "$LIMIT" || [[ "$LIMIT" -eq 0 ]]; then
    print_error "--limit must be a positive integer"
    exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
    print_error "gh CLI is not installed or not on PATH"
    exit 1
fi

# Build optional args for gh invocations.
GH_OPTS=()
if [[ -n "$REPO" ]]; then
    GH_OPTS+=("--repo" "$REPO")
fi
if [[ -n "$WORKFLOW" ]]; then
    GH_OPTS+=("--workflow" "$WORKFLOW")
fi
if [[ -n "$BRANCH" ]]; then
    GH_OPTS+=("--branch" "$BRANCH")
fi
if [[ "$INCLUDE_DISABLED" == "true" ]]; then
    GH_OPTS+=("--all")
fi

print_info "Fetching up to ${LIMIT} workflow runs"
if [[ -n "$REPO" ]]; then
    print_info "Repository: ${REPO}"
fi
if [[ -n "$WORKFLOW" ]]; then
    print_info "Workflow filter: ${WORKFLOW}"
fi
if [[ -n "$BRANCH" ]]; then
    print_info "Branch filter: ${BRANCH}"
fi

RUN_ROWS=()
if [[ ${#GH_OPTS[@]} -gt 0 ]]; then
    while IFS= read -r line; do
        RUN_ROWS+=("$line")
    done < <(
        gh run list "${GH_OPTS[@]}" \
            --limit "$LIMIT" \
            --json databaseId,workflowName,name,createdAt,status,conclusion,headBranch,event,url \
            --jq 'sort_by(.createdAt) | reverse | .[] | [(.databaseId|tostring), (.workflowName // .name // "-"), .createdAt, .status, (.conclusion // "-"), (.headBranch // "-"), (.event // "-"), .url] | @tsv'
    )
else
    while IFS= read -r line; do
        RUN_ROWS+=("$line")
    done < <(
        gh run list \
            --limit "$LIMIT" \
            --json databaseId,workflowName,name,createdAt,status,conclusion,headBranch,event,url \
            --jq 'sort_by(.createdAt) | reverse | .[] | [(.databaseId|tostring), (.workflowName // .name // "-"), .createdAt, .status, (.conclusion // "-"), (.headBranch // "-"), (.event // "-"), .url] | @tsv'
    )
fi

TOTAL="${#RUN_ROWS[@]}"
if [[ "$TOTAL" -eq 0 ]]; then
    print_success "No workflow runs found for the selected filters"
    exit 0
fi

if [[ "$KEEP_N" -gt "$TOTAL" ]]; then
    KEEP_N="$TOTAL"
fi

DELETE_COUNT=$((TOTAL - KEEP_N))

print_info "Total runs found: ${TOTAL}"
print_info "Keeping latest: ${KEEP_N}"
print_info "Candidates to delete: ${DELETE_COUNT}"

if [[ "$DELETE_COUNT" -eq 0 ]]; then
    print_success "Nothing to delete"
    exit 0
fi

printf "\n%-12s %-30s %-20s %-12s %-12s\n" "Run ID" "Workflow" "Created" "Status" "Conclusion"
printf "%s\n" "-----------------------------------------------------------------------------------------------"
for ((i=KEEP_N; i<TOTAL; i++)); do
    IFS=$'\t' read -r run_id wf created status conclusion head_branch event url <<< "${RUN_ROWS[$i]}"
    printf "%-12s %-30.30s %-20s %-12s %-12s\n" "$run_id" "$wf" "$created" "$status" "$conclusion"
done
printf "\n"

if [[ "$MODE" == "list" ]]; then
    print_success "List mode only. No runs deleted"
    exit 0
fi

if [[ "$DRY_RUN" == "true" ]]; then
    print_info "Dry-run enabled. No runs deleted"
    exit 0
fi

print_info "Deleting ${DELETE_COUNT} workflow runs"
DELETED=0
for ((i=KEEP_N; i<TOTAL; i++)); do
    IFS=$'\t' read -r run_id wf created status conclusion head_branch event url <<< "${RUN_ROWS[$i]}"
    echo -e "${YELLOW}Deleting run ${run_id}${NC} (${wf}, ${created})"
    if [[ ${#GH_OPTS[@]} -gt 0 ]]; then
        gh run delete "$run_id" "${GH_OPTS[@]}"
    else
        gh run delete "$run_id"
    fi
    DELETED=$((DELETED + 1))
done

print_success "Deleted ${DELETED} workflow runs"
