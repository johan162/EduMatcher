# Makefile for EduMatcher Config GUI (npm workspaces + container workflow)

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

# Auto-detect container runtime (prefer podman when both are installed)
CONTAINER_RUNTIME := $(shell if command -v podman >/dev/null 2>&1; then echo podman; elif command -v docker >/dev/null 2>&1; then echo docker; fi)
ifeq ($(CONTAINER_RUNTIME),podman)
	DOCKER_COMPOSE := podman-compose
else ifeq ($(CONTAINER_RUNTIME),docker)
	DOCKER_COMPOSE := docker compose
else
	DOCKER_COMPOSE :=
endif

APP_NAME := edumatcher-config-gui
SERVICE_NAME := config-gui
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
	dev dev-web dev-server \
	cnt-build up down restart logs ps \
	dist \
	clean

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
	@echo -e "$(YELLOW)EduMatcher Config GUI - Makefile Targets$(NC)"
	@$(call print_section,Setup,install|clean)
	@$(call print_section,Build and Checks,build|build-debug|typecheck|test|lint|format)
	@$(call print_section,Development,dev|dev-web|dev-server)
	@$(call print_section,Container,check-container-env|cnt-build|up|down|restart|logs|ps)
	@$(call print_section,Distribute,dist)
	@echo ""

# --------------------------------------------------------------------------------------------
# Local npm workflow
# --------------------------------------------------------------------------------------------
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
	@echo -e "$(YELLOW)- Building packages...$(NC)"
	@$(NPM) run build --workspaces --if-present --workspace @edumatcher/schema \
		--workspace @edumatcher/yaml-codec \
		--workspace @edumatcher/diagnostics 2>/dev/null || true
	@echo -e "$(YELLOW)- Building web (debug)...$(NC)"
	@$(NPM) exec --workspace @edumatcher/web -- \
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

dev: check-npm ## Run server and web dev processes together
	@$(NPM) run dev

dev-web: check-npm ## Run only web dev server (Vite)
	@$(NPM) run dev:web

dev-server: check-npm ## Run only backend dev server (Fastify)
	@$(NPM) run dev:server

# --------------------------------------------------------------------------------------------
# Container workflow
# --------------------------------------------------------------------------------------------
cnt-build: check-container ## Build container image via compose (podman/docker)
	@echo -e "$(YELLOW)- Building container image...$(NC)"
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@$(DOCKER_COMPOSE) build
	@echo -e "$(GREEN)✓ Container image built$(NC)"

up: check-container-env ## Start container stack (detached) with build
	@echo -e "$(YELLOW)- Starting container stack...$(NC)"
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@$(DOCKER_COMPOSE) up -d --build
	@echo -e "$(GREEN)✓ Container stack is up$(NC)"

down: check-container ## Stop and remove container stack
	@echo -e "$(YELLOW)- Stopping container stack...$(NC)"
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@$(DOCKER_COMPOSE) down
	@echo -e "$(GREEN)✓ Container stack is down$(NC)"

restart: check-container-env ## Restart container stack
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@$(DOCKER_COMPOSE) down
	@$(DOCKER_COMPOSE) up -d --build

logs: check-container ## Follow container logs
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@$(DOCKER_COMPOSE) logs -f $(SERVICE_NAME)

ps: check-container ## Show container stack status
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@$(DOCKER_COMPOSE) ps

# --------------------------------------------------------------------------------------------
# Distributable package
# --------------------------------------------------------------------------------------------
dist: check-container-env ## Build a distributable: container image + exported OCI tarball in dist/
	@echo -e "$(YELLOW)- Building distributable package v$(VERSION)...$(NC)"
	@echo -e "$(BLUE)- Runtime:  $(CONTAINER_RUNTIME)$(NC)"
	@echo -e "$(BLUE)- Image:    $(IMAGE)$(NC)"
	@echo -e "$(BLUE)- Output:   $(DIST_DIR)/$(APP_NAME)-$(VERSION).tar$(NC)"
	@# Build (or rebuild) the container image tagged with the version
	@$(DOCKER_COMPOSE) build \
		--build-arg HTTP_PROXY="$${HTTP_PROXY:-}" \
		--build-arg HTTPS_PROXY="$${HTTPS_PROXY:-}" \
		--build-arg NO_PROXY="$${NO_PROXY:-}" \
		--build-arg NPM_REGISTRY="$${NPM_REGISTRY:-}" \
		--build-arg NPM_STRICT_SSL="$${NPM_STRICT_SSL:-true}"
	@# Also tag the image with the version so the tarball carries a useful name
	@$(CONTAINER_RUNTIME) tag $(APP_NAME):latest $(IMAGE)
	@# Export the image to a tar archive for offline distribution
	@mkdir -p $(DIST_DIR)
	@$(CONTAINER_RUNTIME) save --output $(DIST_DIR)/$(APP_NAME)-$(VERSION).tar $(IMAGE)
	@echo -e "$(GREEN)✓ Distributable ready: $(DIST_DIR)/$(APP_NAME)-$(VERSION).tar$(NC)"
	@echo -e "$(BLUE)  Load on another host:$(NC)"
	@echo -e "$(BLUE)    $(CONTAINER_RUNTIME) load --input $(DIST_DIR)/$(APP_NAME)-$(VERSION).tar$(NC)"
	@echo -e "$(BLUE)  Then run: $(CONTAINER_RUNTIME) run -p 8080:8080 $(IMAGE)$(NC)"

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