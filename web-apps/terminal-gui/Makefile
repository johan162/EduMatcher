# Makefile for EduMatcher Market Data Terminal (npm workspaces + container workflow)
#
# Target set mirrors log-gui/Makefile so both frontends are driven the same way.
#
# For building the container behind a proxy set the environment on the command line
# before calling make, i.e. adjust the proxy host and port to your local setup:
#
# Note: The special use of `host.containers.internal` is a Docker/Podman feature that resolves
# to the host machine from inside the container and is equivalent to "localhost" on the host.
# This is useful for accessing a local proxy or mirror from within the container.
#
# HTTP_PROXY=http://host.containers.internal:9000 \
# HTTPS_PROXY=http://host.containers.internal:9000 \
# NO_PROXY=localhost,127.0.0.1  make dist
#
# or
#
# HTTP_PROXY=http://host.containers.internal:9000 HTTPS_PROXY=http://host.containers.internal:9000 NO_PROXY=localhost,127.0.0.1  make up

# --------------------------------------------------------------------------------------------
# Make behavior
# --------------------------------------------------------------------------------------------
.DEFAULT_GOAL := help
.DELETE_ON_ERROR:

# Use bash with strict mode (same style as docs/Makefile)
SHELL := $(shell which bash)
.SHELLFLAGS := -euo pipefail -c
.ONESHELL:

# --------------------------------------------------------------------------------------------
# Variables
# --------------------------------------------------------------------------------------------
NPM ?= npm
UNAME_S := $(shell uname -s)

# If https_proxy is set, use it; otherwise use the default host.containers.internal proxy for builds
# HTTP_PROXY_DEFAULT := $(if $(http_proxy),$(http_proxy),http://host.containers.internal:9000)
# HTTPS_PROXY_DEFAULT := $(if $(https_proxy),$(https_proxy),http://host.containers.internal:9000)
# NO_PROXY_DEFAULT := $(if $(no_proxy),$(no_proxy),localhost,127.0.0.1)
HTTP_PROXY_DEFAULT := http://host.containers.internal:9000
HTTPS_PROXY_DEFAULT := http://host.containers.internal:9000
NO_PROXY_DEFAULT := localhost,127.0.0.1

# Auto-detect container runtime (prefer podman when both are installed)
CONTAINER_RUNTIME := $(shell if command -v podman >/dev/null 2>&1; then echo podman; elif command -v docker >/dev/null 2>&1; then echo docker; fi)
ifeq ($(CONTAINER_RUNTIME),podman)
	DOCKER_COMPOSE := podman-compose
else ifeq ($(CONTAINER_RUNTIME),docker)
	# On Linux, Docker needs the extra_hosts override (host-gateway injection).
	# Docker Desktop on macOS/Windows provides host.docker.internal natively.
	ifeq ($(UNAME_S),Linux)
		DOCKER_COMPOSE := docker compose -f docker-compose.yml -f docker-compose.linux.yml
	else
		DOCKER_COMPOSE := docker compose
	endif
else
	DOCKER_COMPOSE :=
endif

APP_NAME := edumatcher-terminal-gui
SERVICE_NAME := terminal-gui
VERSION ?= $(shell node -p "require('./package.json').version" 2>/dev/null || echo "0.0.0")
IMAGE ?= $(APP_NAME):$(VERSION)
DIST_DIR ?= dist

# Colors for output
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[1;33m
BLUE := \033[0;34m
BRIGHTCYAN := \033[1;36m
NC := \033[0m

.PHONY: \
	help \
	check-npm check-container check-container-env \
	install build build-debug typecheck test lint format \
	dev dev-web dev-bridge \
	cnt-build proxy-up up down restart logs ps \
	dist \
	clean distclean

# --------------------------------------------------------------------------------------------
# Tool checks
# --------------------------------------------------------------------------------------------
check-npm:
	@command -v "$(NPM)" >/dev/null 2>&1 || { \
		echo -e "$(RED)✗ npm not found in PATH$(NC)"; \
		exit 1; \
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
# Help
# --------------------------------------------------------------------------------------------
define print_section
	@echo ""
	@echo -e "$(BRIGHTCYAN)$1:$(NC)"
	@grep -E '^($(2)):.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(BLUE)%-16s$(NC) %s\n", $$1, $$2}' | sort
endef

help: ## Show this help message
	@echo -e "$(YELLOW)EduMatcher Market Data Terminal - Makefile Targets$(NC)"
	@$(call print_section,Setup,install|clean|distclean)
	@$(call print_section,Build and Checks,build|build-debug|typecheck|test|lint|format)
	@$(call print_section,Development,dev|dev-web|dev-bridge)
	@$(call print_section,Container,check-container-env|cnt-build|proxy-up|up|down|restart|logs|ps)
	@$(call print_section,Distribute,dist)
	@echo ""

# --------------------------------------------------------------------------------------------
# Local npm workflow
# --------------------------------------------------------------------------------------------
# Unlike log-gui's equivalent target, this deliberately does NOT pass
# --no-dedupe. That flag works around an npm arborist crash specific to
# log-gui's duplicated vite; here it instead nests fastify under apps/bridge
# while hoisting the @fastify/* plugins to the root, which breaks their
# `declare module "fastify"` type augmentation.
install: check-npm ## Install a full local npm workspace environment
	@echo -e "$(YELLOW)- Installing Node workspace dependencies...$(NC)"
	@if [[ -f package-lock.json ]]; then \
		$(NPM) ci; \
	else \
		$(NPM) install; \
	fi
	@echo -e "$(GREEN)✓ Environment ready$(NC)"

build: check-npm ## Build all workspaces (production — minified, no sourcemaps)
	@echo -e "$(YELLOW)- Building all workspaces...$(NC)"
	@$(NPM) run build
	@echo -e "$(GREEN)✓ Build completed$(NC)"

build-debug: check-npm ## Build frontend in development mode (sourcemaps, no minification)
	@if [[ ! -d apps/web ]]; then \
		echo -e "$(YELLOW)- apps/web does not exist yet; nothing to build in debug mode$(NC)"; \
		exit 0; \
	fi
	@echo -e "$(YELLOW)- Building packages...$(NC)"
	@$(NPM) run build --workspaces --if-present --workspace @edumatcher/terminal-types \
		--workspace @edumatcher/calf-protocol --workspace @edumatcher/lalf-client 2>/dev/null || true
	@echo -e "$(YELLOW)- Building web (debug)...$(NC)"
	@$(NPM) exec --workspace @edumatcher/terminal-web -- \
		vite build --mode development --minify false --sourcemap true
	@echo -e "$(GREEN)✓ Debug build completed — output: apps/web/dist$(NC)"
	@echo -e "$(BLUE)  Sourcemaps included; NODE_ENV stays 'development'$(NC)"

typecheck: check-npm ## Run TypeScript checks for all workspaces
	@$(NPM) run typecheck

test: check-npm ## Run test suite
	@$(NPM) test

lint: check-npm ## Run lint command
	@$(NPM) run lint

format: check-npm ## Format source files with Prettier
	@$(NPM) run format

dev: check-npm ## Run bridge and web dev processes together
	@$(NPM) run dev

dev-web: check-npm ## Run only web dev server (Vite)
	@$(NPM) run dev:web

dev-bridge: check-npm ## Run only the Fastify bridge (CALF uplink + WS + history proxy)
	@$(NPM) run dev:bridge

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
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@echo -e "$(BLUE)- Using proxy settings:$(NC)"
	@echo -e "$(BLUE)  HTTP_PROXY: $(HTTP_PROXY_DEFAULT)$(NC)"
	@echo -e "$(BLUE)  HTTPS_PROXY: $(HTTPS_PROXY_DEFAULT)$(NC)"
	@echo -e "$(BLUE)  NO_PROXY: $(NO_PROXY_DEFAULT)$(NC)"
	HTTP_PROXY="$(HTTP_PROXY_DEFAULT)" HTTPS_PROXY="$(HTTPS_PROXY_DEFAULT)" NO_PROXY="$(NO_PROXY_DEFAULT)" $(MAKE) up

up: check-container-env ## Start container stack (detached) with build
	@echo -e "$(YELLOW)- Starting container stack...$(NC)"
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@mkdir -p logs
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
	@echo -e "$(BLUE)  Then run: $(CONTAINER_RUNTIME) run -p 8090:8090 $(IMAGE)$(NC)"

# --------------------------------------------------------------------------------------------
# Cleanup
# --------------------------------------------------------------------------------------------
clean: ## Remove local Node build artifacts and dist/
	@echo -e "$(YELLOW)- Cleaning build artifacts...$(NC)"
	@rm -rf apps/web/dist
	@find apps packages -type d -name dist -prune -exec rm -rf {} +
	@find apps packages -type f -name '*.tsbuildinfo' -delete
	@rm -rf $(DIST_DIR)
	@echo -e "$(GREEN)✓ Clean completed$(NC)"

distclean: clean ## Remove node_modules and package-lock.json for a pristine `make install`
	@echo -e "$(YELLOW)- Removing installed dependencies and lockfile...$(NC)"
	@rm -rf node_modules
	@find apps packages -type d -name node_modules -prune -exec rm -rf {} +
	@rm -f package-lock.json
	@echo -e "$(GREEN)✓ Distclean completed — run 'make install' for a pristine environment$(NC)"
