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
UNAME_S      := $(shell uname -s)
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
	check-npm check-container check-container-env \
	install build build-debug typecheck test lint format \
	dev serve \
	cnt-build proxy-up up down restart logs ps \
	dist \
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

check-container:
	@if [[ -z "$(CONTAINER_RUNTIME)" ]]; then \
		echo -e "$(RED)✗ neither podman nor docker found in PATH$(NC)"; \
		exit 1; \
	fi
	@$(DOCKER_COMPOSE) version >/dev/null 2>&1 || { \
		echo -e "$(RED)✗ compose support is not available for $(CONTAINER_RUNTIME)$(NC)"; \
		exit 1; \
	}

check-container-env: check-container ## Ensure container runtime environment is running
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@if [[ "$(CONTAINER_RUNTIME)" == "podman" ]]; then \
		if podman info >/dev/null 2>&1; then \
			echo -e "$(GREEN)✓ Podman environment is running$(NC)"; \
		elif [[ "$(UNAME_S)" == "Darwin" ]]; then \
			echo -e "$(YELLOW)- Podman machine is not running. Starting it...$(NC)"; \
			podman machine start >/dev/null 2>&1 || { \
				echo -e "$(RED)✗ Failed to start podman machine$(NC)"; \
				exit 1; \
			}; \
			echo -e "$(GREEN)✓ Podman machine started$(NC)"; \
		else \
			echo -e "$(RED)✗ Podman is installed but not ready (podman info failed)$(NC)"; \
			exit 1; \
		fi; \
	else \
		docker info >/dev/null 2>&1 || { \
			echo -e "$(RED)✗ Docker daemon is not running$(NC)"; \
			echo -e "$(YELLOW)  Start Docker Desktop or the docker service, then retry$(NC)"; \
			exit 1; \
		}; \
		echo -e "$(GREEN)✓ Docker daemon is running$(NC)"; \
	fi

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
# Container workflow
# --------------------------------------------------------------------------------------------
cnt-build: check-container ## Build container image via compose (podman/docker)
	@echo -e "$(YELLOW)- Building container image...$(NC)"
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@$(DOCKER_COMPOSE) build --build-arg NPM_STRICT_SSL=false \
	    --build-arg HTTP_PROXY="$${HTTP_PROXY:-}" \
	    --build-arg HTTPS_PROXY="$${HTTPS_PROXY:-}" \
	    --build-arg NO_PROXY="$${NO_PROXY:-}"
	@echo -e "$(GREEN)✓ Container image built$(NC)"

proxy-up: check-container-env ## Start the stack through a local dev proxy (optional)
	@echo -e "$(YELLOW)- Starting container stack via local proxy...$(NC)"
	HTTP_PROXY=http://host.containers.internal:9000 HTTPS_PROXY=http://host.containers.internal:9000 NO_PROXY=localhost,127.0.0.1  $(MAKE) up

up: check-container-env ## Start container stack (detached) with build
	@echo -e "$(YELLOW)- Starting container stack...$(NC)"
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@$(DOCKER_COMPOSE) up -d --build \
	    --build-arg NPM_STRICT_SSL=false \
	    --build-arg HTTP_PROXY="$${HTTP_PROXY:-}" \
	    --build-arg HTTPS_PROXY="$${HTTPS_PROXY:-}" \
	    --build-arg NO_PROXY="$${NO_PROXY:-}"
	@echo -e "$(GREEN)✓ Container stack is up$(NC)"

down: check-container ## Stop and remove container stack
	@echo -e "$(YELLOW)- Stopping container stack...$(NC)"
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@$(DOCKER_COMPOSE) down
	@echo -e "$(GREEN)✓ Container stack is down$(NC)"

restart: check-container-env ## Restart container stack
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@$(DOCKER_COMPOSE) down
	@$(DOCKER_COMPOSE) up -d --build \
	    --build-arg NPM_STRICT_SSL=false \
	    --build-arg HTTP_PROXY="$${HTTP_PROXY:-}" \
	    --build-arg HTTPS_PROXY="$${HTTPS_PROXY:-}" \
	    --build-arg NO_PROXY="$${NO_PROXY:-}"

logs: check-container ## Follow container logs
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@$(DOCKER_COMPOSE) logs -f $(SERVICE_NAME)

ps: check-container ## Show container stack status
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@$(DOCKER_COMPOSE) ps

# --------------------------------------------------------------------------------------------
# Distributable package
# --------------------------------------------------------------------------------------------
dist: check-container-env ## Build a distributable: container image + exported OCI tarball in dist
	@echo -e "$(YELLOW)- Building distributable package v$(VERSION)...$(NC)"
	@echo -e "$(BLUE)- Runtime:  $(CONTAINER_RUNTIME)$(NC)"
	@echo -e "$(BLUE)- Image:    $(IMAGE)$(NC)"
	@echo -e "$(BLUE)- Output:   $(DIST_DIR)/$(APP_NAME)-$(VERSION).tar$(NC)"
	@$(DOCKER_COMPOSE) build \
	    --build-arg NPM_STRICT_SSL=false \
		--build-arg HTTP_PROXY="$${HTTP_PROXY:-}" \
		--build-arg HTTPS_PROXY="$${HTTPS_PROXY:-}" \
		--build-arg NO_PROXY="$${NO_PROXY:-}"
	@$(CONTAINER_RUNTIME) tag $(APP_NAME):latest $(IMAGE)
	@mkdir -p $(DIST_DIR)
	@$(CONTAINER_RUNTIME) save --output $(DIST_DIR)/$(APP_NAME)-$(VERSION).tar $(IMAGE)
	@gzip -f $(DIST_DIR)/$(APP_NAME)-$(VERSION).tar
	@echo -e "$(GREEN)✓ Distributable ready: $(DIST_DIR)/$(APP_NAME)-$(VERSION).tar.gz$(NC)"
	@echo -e "$(BLUE)  Load on another host:$(NC)"
	@echo -e "$(BLUE)    $(CONTAINER_RUNTIME) load --input $(DIST_DIR)/$(APP_NAME)-$(VERSION).tar.gz$(NC)"
	@echo -e "$(BLUE)  Then run: $(CONTAINER_RUNTIME) run -p 4173:4173 $(IMAGE)$(NC)"

# --------------------------------------------------------------------------------------------
# Clean
# --------------------------------------------------------------------------------------------
clean: ## Remove build artefacts and node_modules
	@echo -e "$(YELLOW)→ Cleaning…$(NC)"
	rm -rf apps/web/$(DIST_DIR) node_modules apps/web/node_modules
	@echo -e "$(GREEN)✓ Clean$(NC)"
