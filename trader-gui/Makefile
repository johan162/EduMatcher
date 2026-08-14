# Makefile for EduMatcher Trading GUI (pm-trading-ui)
# Mirrors terminal-gui/Makefile so both frontends are driven identically.
#
# For building the container behind a proxy:
#
#   HTTP_PROXY=http://host.containers.internal:9000 \
#   HTTPS_PROXY=http://host.containers.internal:9000 \
#   NO_PROXY=localhost,127.0.0.1  make dist

# --------------------------------------------------------------------------------------------
# Make behaviour
# --------------------------------------------------------------------------------------------
.DEFAULT_GOAL := help
.DELETE_ON_ERROR:

SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c
.ONESHELL:

# --------------------------------------------------------------------------------------------
# Variables
# --------------------------------------------------------------------------------------------
NPM          ?= npm
APP_NAME     := edumatcher-trader-gui
SERVICE_NAME := trader-gui
VERSION      ?= $(shell node -p "require('./package.json').version" 2>/dev/null || echo "0.0.0")
IMAGE        ?= $(APP_NAME):$(VERSION)
DIST_DIR     ?= dist

# Auto-detect container runtime (prefer podman)
CONTAINER_RUNTIME := $(shell \
  if command -v podman >/dev/null 2>&1; then echo podman; \
  elif command -v docker >/dev/null 2>&1; then echo docker; \
  fi)

ifeq ($(CONTAINER_RUNTIME),podman)
  DOCKER_COMPOSE := podman-compose
else ifeq ($(CONTAINER_RUNTIME),docker)
  DOCKER_COMPOSE := docker compose
else
  DOCKER_COMPOSE :=
endif

# Colour codes
RED       := \033[0;31m
GREEN     := \033[0;32m
YELLOW    := \033[1;33m
BLUE      := \033[0;34m
CYAN      := \033[1;36m
NC        := \033[0m

.PHONY: \
	help \
	check-npm \
	install build build-debug typecheck test lint format \
	dev serve \
	clean

# --------------------------------------------------------------------------------------------
# Help
# --------------------------------------------------------------------------------------------
help: ## Show this help
	@echo ""
	@echo -e "$(CYAN)EduMatcher Trading GUI$(NC) — development targets"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(BLUE)%-20s$(NC) %s\n", $$1, $$2}'
	@echo ""

# --------------------------------------------------------------------------------------------
# Tool checks
# --------------------------------------------------------------------------------------------
check-npm:
	@command -v "$(NPM)" >/dev/null 2>&1 || { \
		echo -e "$(RED)✗ npm not found in PATH$(NC)"; exit 1; \
	}

# --------------------------------------------------------------------------------------------
# Install / build
# --------------------------------------------------------------------------------------------
install: check-npm ## Install all workspace dependencies
	@echo -e "$(BLUE)→ Installing dependencies…$(NC)"
	$(NPM) install
	@echo -e "$(GREEN)✓ Dependencies installed$(NC)"

build: check-npm ## Typecheck + production build (apps/web/dist/)
	@echo -e "$(BLUE)→ Building…$(NC)"
	$(NPM) run build
	@echo -e "$(GREEN)✓ Build complete$(NC)"

build-debug: check-npm ## Build with source maps (no typecheck)
	$(NPM) run build --workspace @edumatcher/trader-web -- --mode development

typecheck: check-npm ## Run TypeScript type-checking across all workspaces
	@echo -e "$(BLUE)→ Type-checking…$(NC)"
	$(NPM) run typecheck
	@echo -e "$(GREEN)✓ Typecheck passed$(NC)"

# --------------------------------------------------------------------------------------------
# Test / lint / format
# --------------------------------------------------------------------------------------------
test: check-npm ## Run Vitest test suite
	@echo -e "$(BLUE)→ Running tests…$(NC)"
	$(NPM) test
	@echo -e "$(GREEN)✓ Tests passed$(NC)"

lint: typecheck ## Alias for typecheck (TypeScript is the linter)

format: check-npm ## Format all source files with Prettier
	$(NPM) run format

# --------------------------------------------------------------------------------------------
# Development server
# --------------------------------------------------------------------------------------------
dev: check-npm ## Start the Vite dev server (hot-reload on :5173)
	@echo -e "$(CYAN)→ Starting dev server on http://localhost:5173$(NC)"
	$(NPM) run dev

# --------------------------------------------------------------------------------------------
# Production serve
# --------------------------------------------------------------------------------------------
serve: check-npm ## Serve the production build (apps/web/dist/) on :4173
	@echo -e "$(CYAN)→ Serving production build on http://localhost:4173$(NC)"
	@echo -e "$(YELLOW)   Set PORT / HOST / API_PROXY_TARGET to override defaults.$(NC)"
	$(NPM) run pm-trading-ui-serve

# --------------------------------------------------------------------------------------------
# Clean
# --------------------------------------------------------------------------------------------
clean: ## Remove build artefacts and node_modules
	@echo -e "$(YELLOW)→ Cleaning…$(NC)"
	rm -rf apps/web/$(DIST_DIR) node_modules apps/web/node_modules
	@echo -e "$(GREEN)✓ Clean$(NC)"
