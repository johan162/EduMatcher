#!/usr/bin/env bash
# =============================================================================
# docs-contctl.sh - Container control for the mcprojsim documentation server
#
# This script controls the containerized documentation server that serves the
# mcprojsim documentation via a web server.
#
# Usage:
#   ./scripts/docs-contctl.sh [command] [options]
#
# Commands:
#   start   - Start the docs server container (default)
#   stop    - Stop the docs server container
#   restart - Restart the docs server container
#   status  - Show docs container status
#   logs    - Show docs container logs
#   build   - Rebuild the docs container image
#
# Options:
#   -p, --port PORT    - Port to serve documentation on (default: 9090)
#   -n, --name NAME    - Container name (default: mcprojsim-docs)
#   -d, --detach       - Run in background (default for start)
#   -f, --foreground   - Run in foreground
#   -h, --help         - Show this help message
#
# Examples:
#   ./scripts/docs-contctl.sh                     # Start docs container on port 9090
#   ./scripts/docs-contctl.sh start -p 8080       # Start on port 8080
#   ./scripts/docs-contctl.sh stop                # Stop the container
#   ./scripts/docs-contctl.sh restart -p 9000     # Restart on different port
#   ./scripts/docs-contctl.sh logs -f             # Follow container logs
#   MCPROJSIM_USE_PROXY_CA=true ./scripts/docs-contctl.sh build # Build image with proxy CA support
#   ./scripts/docs-contctl.sh build		   		  # Build image without proxy CA support
#
# Environment Variables:
#   MCPROJSIM_DOCS_IMAGE      - Container image name (default: mcprojsim-docs:latest)
#   MCPROJSIM_DOCS_PORT       - Default port (default: 9090)
#   MCPROJSIM_USE_PROXY_CA    - Set to "true" to build with proxy CA cert (default: false)
# =============================================================================

set -euo pipefail

# Paths
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly SCRIPT_PATH="${PROJECT_ROOT}/scripts/docs-contctl.sh"
# Proxy file for build (if needed)
PROXY_CA_FILE="${PROJECT_ROOT}/CA_proxy_fw_all.pem"

# Configuration
readonly DEFAULT_PORT="${MCPROJSIM_DOCS_PORT:-9090}"
readonly DEFAULT_IMAGE="${MCPROJSIM_DOCS_IMAGE:-mcprojsim-docs:latest}"
readonly DEFAULT_CONTAINER_NAME="mcprojsim-docs"
readonly USE_PROXY_CA="${MCPROJSIM_USE_PROXY_CA:-false}"

# State
PORT="${DEFAULT_PORT}"
IMAGE_NAME="${DEFAULT_IMAGE}"
CONTAINER_NAME="${DEFAULT_CONTAINER_NAME}"
DETACH=true

# Colors for output (disabled if not a terminal)
if [[ -t 1 ]]; then
	readonly RED='\033[0;31m'
	readonly GREEN='\033[0;32m'
	readonly YELLOW='\033[0;33m'
	readonly BLUE='\033[0;34m'
	readonly NC='\033[0m' # No Color
else
	readonly RED=''
	readonly GREEN=''
	readonly YELLOW=''
	readonly BLUE=''
	readonly NC=''
fi

# Print error message and exit
error() {
	echo -e "${RED}Error: $*${NC}" >&2
	exit 1
}

# Print warning message
warn() {
	echo -e "${YELLOW}Warning: $*${NC}" >&2
}

# Print info message
info() {
	echo -e "${GREEN}$*${NC}" >&2
}

# Print status message
status_msg() {
	echo -e "${BLUE}$*${NC}"
}

# Show help message
show_help() {
	head -42 "${BASH_SOURCE[0]}" | tail -40 | sed 's/^# \?//'
	exit 0
}

# Check if podman is available
check_podman() {
	if ! command -v podman &>/dev/null; then
		error "Podman is not installed. Please install Podman first."
	fi
}

# Build the documentation image
build_image() {
	local dockerfile="${PROJECT_ROOT}/Dockerfile.docs"

	if [[ ! -f "${dockerfile}" ]]; then
		error "Dockerfile.docs not found at ${dockerfile}"
	fi

	info "Building documentation image..."

	# Build command with optional proxy CA support
	local build_cmd=(podman build -f "${dockerfile}" -t "${IMAGE_NAME}")

	if [[ "${USE_PROXY_CA}" == "true" ]]; then
		if [ ! -s "${PROXY_CA_FILE}" ]; then 
			echo -e "${RED}✗ Error: ${PROXY_CA_FILE} not found or empty${NC}"; 
			echo -e "${YELLOW}  Copy your proxy CA certificate to the project root as ${PROXY_CA_FILE}${NC}"; 
			exit 1; 
		fi
		info "Building with proxy CA certificate support..."
		build_cmd+=(--build-arg USE_PROXY_CA=true --secret id=proxy_ca,src="${PROXY_CA_FILE}")
	fi

	build_cmd+=("${PROJECT_ROOT}")

	# echo "USE_PROXY_CA=${USE_PROXY_CA}"
	# echo "PROXY_CA_FILE=${PROXY_CA_FILE}"
	# echo "Building image with command: ${build_cmd[*]}"

	"${build_cmd[@]}" || error "Failed to build documentation image"
	info "Documentation image built successfully."
}

# Check if the image exists, build if not
ensure_image() {
	if ! podman image exists "${IMAGE_NAME}" 2>/dev/null; then
		warn "Image '${IMAGE_NAME}' not found."
		build_image
	fi
}

# Check if container is running
is_running() {
	podman container exists "${CONTAINER_NAME}" 2>/dev/null && \
	podman inspect --format '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null | grep -q true
}

# Start the documentation server
cmd_start() {
	ensure_image

	if is_running; then
		warn "Documentation server is already running on port $(get_port)"
		status_msg "Access documentation at: http://localhost:$(get_port)"
		return 0
	fi

	# Remove existing stopped container if exists
	if podman container exists "${CONTAINER_NAME}" 2>/dev/null; then
		podman rm "${CONTAINER_NAME}" &>/dev/null || true
	fi

	info "Starting documentation server on port ${PORT}..."

	local run_opts=(
		--name "${CONTAINER_NAME}"
		--publish "${PORT}:80"
		--restart unless-stopped
	)

	if [[ "${DETACH}" == true ]]; then
		run_opts+=(--detach)
	fi

	podman run "${run_opts[@]}" "${IMAGE_NAME}" || \
		error "Failed to start documentation server"

	if [[ "${DETACH}" == true ]]; then
		info "Documentation server started successfully."
		status_msg "Access documentation at: http://localhost:${PORT}"
		status_msg "Stop with: ${SCRIPT_PATH} stop"
	fi
}

# Stop the documentation server
cmd_stop() {
	if ! podman container exists "${CONTAINER_NAME}" 2>/dev/null; then
		warn "Documentation server is not running."
		return 0
	fi

	info "Stopping documentation server..."
	podman stop "${CONTAINER_NAME}" &>/dev/null || true
	podman rm "${CONTAINER_NAME}" &>/dev/null || true
	info "Documentation server stopped."
}

# Restart the documentation server
cmd_restart() {
	cmd_stop
	cmd_start
}

# Get the port the container is running on
get_port() {
	podman port "${CONTAINER_NAME}" 80 2>/dev/null | head -1 | cut -d: -f2
}

# Show server status
cmd_status() {
	if is_running; then
		local running_port
		running_port=$(get_port)
		status_msg "Documentation server is running"
		echo "  Container: ${CONTAINER_NAME}"
		echo "  Image:     ${IMAGE_NAME}"
		echo "  Port:      ${running_port}"
		echo "  URL:       http://localhost:${running_port}"

		# Show container stats
		echo ""
		podman ps --filter "name=${CONTAINER_NAME}" --format \
			"table {{.Names}}\t{{.Status}}\t{{.Ports}}"
	else
		warn "Documentation server is not running."
		return 1
	fi
}

# Show server logs
cmd_logs() {
	if ! podman container exists "${CONTAINER_NAME}" 2>/dev/null; then
		error "Documentation server container does not exist."
	fi

	podman logs "$@" "${CONTAINER_NAME}"
}

# Parse command line arguments
parse_args() {
	local command=""
	local log_args=()

	while [[ $# -gt 0 ]]; do
		case "$1" in
			start|stop|restart|status|logs|build)
				command="$1"
				shift
				;;
			-p|--port)
				PORT="$2"
				shift 2
				;;
			-n|--name)
				CONTAINER_NAME="$2"
				shift 2
				;;
			-d|--detach)
				DETACH=true
				shift
				;;
			-f|--foreground)
				DETACH=false
				shift
				;;
			--follow)
				# For logs command
				log_args+=("--follow")
				shift
				;;
			-h|--help)
				show_help
				;;
			*)
				# Pass unknown args to logs command
				if [[ "${command}" == "logs" ]]; then
					log_args+=("$1")
				else
					error "Unknown option: $1"
				fi
				shift
				;;
		esac
	done

	# Default command is start
	command="${command:-start}"

	# Execute command
	case "${command}" in
		start)
			cmd_start
			;;
		stop)
			cmd_stop
			;;
		restart)
			cmd_restart
			;;
		status)
			cmd_status
			;;
		logs)
			cmd_logs "${log_args[@]}"
			;;
		build)
			build_image
			;;
		*)
			error "Unknown command: ${command}"
			;;
	esac
}

# Main function
main() {
	check_podman
	parse_args "$@"
}

# Run main function with all arguments
main "$@"