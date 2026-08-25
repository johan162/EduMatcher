# Makefile for EduMatcher Config GUI (npm workspaces + container workflow)
#
# For building the container behind a proxy use environament set the environmant on the command line
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

# --------------------------------------------------------------------------------------------
# Rewrite HTTP_PROXY from http_proxy 
# Rules:
# 1) localhost -> host.containers.internal
# 2) other hostnames unchanged
# 3) extract port to PORT
# Example: http_proxy=http://localhost:9000 -> HTTP_PROXY=http://host.containers.internal:9000
# --------------------------------------------------------------------------------------------
PROXY_INPUT := $(strip $(http_proxy))
ifneq ($(PROXY_INPUT),)
PROXY_SCHEME := $(if $(filter https://%,$(PROXY_INPUT)),https,http)
PROXY_NO_SCHEME := $(patsubst http://%,%,$(patsubst https://%,%,$(PROXY_INPUT)))
PROXY_HOSTPORT := $(firstword $(subst /, ,$(PROXY_NO_SCHEME)))
HOSTNAME := $(word 1,$(subst :, ,$(PROXY_HOSTPORT)))
PORT := $(if $(word 2,$(subst :, ,$(PROXY_HOSTPORT))),$(word 2,$(subst :, ,$(PROXY_HOSTPORT))),9000)
NEW_HOSTNAME := $(if $(filter localhost,$(HOSTNAME)),host.containers.internal,$(HOSTNAME))
HTTP_PROXY := $(PROXY_SCHEME)://$(NEW_HOSTNAME):$(PORT)
else
HTTP_PROXY :=
endif
HTTPS_PROXY := $(HTTP_PROXY)
NO_PROXY := $(if $(no_proxy),$(no_proxy),localhost,127.0.0.1,::1,host.containers.internal)


# Print the proxy settings for debugging
print-proxy:
	@echo -e "$(YELLOW)- Proxy settings for container build:$(NC)"
	@echo -e "$(BLUE)  HOSTNAME: $(HOSTNAME)$(NC)"
	@echo -e "$(BLUE)  PORT: $(PORT)$(NC)"
	@echo -e "$(BLUE)  NEW_HOSTNAME: $(NEW_HOSTNAME)$(NC)"
	@echo -e "$(BLUE)  HTTP_PROXY: $(HTTP_PROXY)$(NC)"
	@echo -e "$(BLUE)  HTTPS_PROXY: $(HTTPS_PROXY)$(NC)"
	@echo -e "$(BLUE)  NO_PROXY: $(NO_PROXY)$(NC)"

# HTTP_PROXY_DEFAULT := http://host.containers.internal:9000
# HTTPS_PROXY_DEFAULT := http://host.containers.internal:9000
# NO_PROXY_DEFAULT := localhost,127.0.0.1


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
CONTAINER_NAME := $(APP_NAME)
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
	@echo -e "$(YELLOW)EduMatcher Config GUI - Makefile Targets$(NC)"
	@$(call print_section,Setup,install|clean|distclean)
	@$(call print_section,Build and Checks,build|build-debug|typecheck|test|lint|format)
	@$(call print_section,Development,dev|dev-web|dev-server)
	@$(call print_section,Container,check-container-env|cnt-build|up|down|restart|logs|ps)
	@$(call print_section,Distribute,dist)
	@echo ""

# Bump version in "TopBar.tsx" file (for display in the GUI) when updating the version in package.json
bump-version: ## Update version in TopBar.tsx to match package.json
	@echo -e "$(YELLOW)- Bumping version in TopBar.tsx to match package.json...$(NC)"
	@TOPBAR_FILE=apps/web/src/components/layout/TopBar.tsx; \
	VERSION=$(shell node -p "require('./package.json').version" 2>/dev/null || echo "0.0.0"); \
	sed -i.bak -E "s/v[0-9]+\.[0-9]+\.[0-9]+/v$$VERSION/" "$$TOPBAR_FILE" && rm -f "$$TOPBAR_FILE.bak"
	@echo -e "$(GREEN)✓ Version updated in TopBar.tsx to v$(VERSION)$(NC)"

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

build: check-npm bump-version  ## Build all workspaces (production — minified, no sourcemaps)
	@echo -e "$(YELLOW)- Building all workspaces...$(NC)"
	@$(NPM) run build
	@echo -e "$(GREEN)✓ Build completed$(NC)"

build-debug: check-npm bump-version ## Build frontend in development mode (sourcemaps, no minification)
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

dev: check-npm bump-version ## Run server and web dev processes together
	@$(NPM) run dev

dev-web: check-npm bump-version ## Run only web dev server (Vite)
	@$(NPM) run dev:web

dev-server: check-npm bump-version ## Run only backend dev server (Fastify)
	@$(NPM) run dev:server

# Timestamp files
TIMESTAMP_DIR := .timestamps
CONTAINER_STAMP := $(TIMESTAMP_DIR)/.container-stamp
GHCR_LOGIN_STAMP := $(TIMESTAMP_DIR)/.ghcr-login-stamp
CDIST_STAMP := $(TIMESTAMP_DIR)/.cdist-stamp


$(TIMESTAMP_DIR):
	@mkdir -p $(TIMESTAMP_DIR)



# --------------------------------------------------------------------------------------------
# Container workflow
# --------------------------------------------------------------------------------------------
cbuild: check-container | $(TIMESTAMP_DIR) ## Build container image via compose (podman/docker)
	@echo -e "$(YELLOW)- Building container image...$(NC)"
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@$(DOCKER_COMPOSE) build --build-arg USE_PROXY_CA=false \
	    --build-arg NPM_STRICT_SSL=false \
	    --build-arg CA_CERT_FILE="$${CA_CERT_FILE:-}" \
	    --build-arg HTTP_PROXY="$${HTTP_PROXY:-}" \
	    --build-arg HTTPS_PROXY="$${HTTPS_PROXY:-}" \
	    --build-arg NO_PROXY="$${NO_PROXY:-}"
	@touch $(CONTAINER_STAMP)
	@echo -e "$(GREEN)✓ Container image built$(NC)"


# proxy-up: check-container-env ## Start the stack through a local dev proxy (optional)
# 	@echo -e "$(YELLOW)- Starting container stack via local proxy...$(NC)"
# 	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
# 	@echo -e "$(BLUE)- Using proxy settings:$(NC)"
# 	@echo -e "$(BLUE)  HTTP_PROXY: $(HTTP_PROXY_DEFAULT)$(NC)"
# 	@echo -e "$(BLUE)  HTTPS_PROXY: $(HTTPS_PROXY_DEFAULT)$(NC)"
# 	@echo -e "$(BLUE)  NO_PROXY: $(NO_PROXY_DEFAULT)$(NC)"
# 	HTTP_PROXY="$(HTTP_PROXY_DEFAULT)" HTTPS_PROXY="$(HTTPS_PROXY_DEFAULT)" NO_PROXY="$(NO_PROXY_DEFAULT)" $(MAKE) up

up: check-container-env bump-version ## Start container stack (detached) with build
	@echo -e "$(YELLOW)- Starting container stack...$(NC)"
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@$(DOCKER_COMPOSE) up -d --build \
	    --build-arg USE_PROXY_CA=false \
	    --build-arg NPM_STRICT_SSL=false \
	    --build-arg CA_CERT_FILE="$${CA_CERT_FILE:-}" \
	    --build-arg HTTP_PROXY="$${HTTP_PROXY:-}" \
	    --build-arg HTTPS_PROXY="$${HTTPS_PROXY:-}" \
	    --build-arg NO_PROXY="$${NO_PROXY:-}"
	@echo -e "$(GREEN)✓ Container stack is up$(NC)"

down: check-container | $(TIMESTAMP_DIR) ## Stop and remove container stack
	@echo -e "$(YELLOW)- Stopping container stack...$(NC)"
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@$(DOCKER_COMPOSE) down
	@echo -e "$(GREEN)✓ Container stack is down$(NC)"

restart: check-container-env | $(TIMESTAMP_DIR) ## Restart container stack
	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
	@$(DOCKER_COMPOSE) down
	@$(DOCKER_COMPOSE) up -d --build \
	    --build-arg USE_PROXY_CA=false \
	    --build-arg NPM_STRICT_SSL=false \
	    --build-arg CA_CERT_FILE="$${CA_CERT_FILE:-}" \
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
# | check-container-env bump-version
# --------------------------------------------------------------------------------------------
$(CDIST_STAMP): $(CONTAINER_STAMP)   ## Build a distributable: container image + exported OCI tarball in dist
	@echo -e "$(YELLOW)- Building distributable package v$(VERSION)...$(NC)"
	@echo -e "$(BLUE)- Runtime:  $(CONTAINER_RUNTIME)$(NC)"
	@echo -e "$(BLUE)- Image:    $(IMAGE)$(NC)"
	@echo -e "$(BLUE)- Output:   $(DIST_DIR)/$(APP_NAME)-$(VERSION).tar$(NC)"
	@# Build (or rebuild) the container image tagged with the version
	@$(DOCKER_COMPOSE) build \
	    --build-arg USE_PROXY_CA=false \
		--build-arg NPM_STRICT_SSL=false \
		--build-arg CA_CERT_FILE="$${CA_CERT_FILE:-}" \
		--build-arg HTTP_PROXY="$${HTTP_PROXY:-}" \
		--build-arg HTTPS_PROXY="$${HTTPS_PROXY:-}" \
		--build-arg NO_PROXY="$${NO_PROXY:-}" \
	# Also tag the image with the version so the tarball carries a useful name
	@$(CONTAINER_RUNTIME) tag $(APP_NAME):latest $(IMAGE)
	# Export the image to a tar archive for offline distribution
	@mkdir -p $(DIST_DIR)
	@echo -e "$(YELLOW)- Packaging distributable...$(NC)"
	@$(CONTAINER_RUNTIME) save --format docker-archive $(IMAGE) | xz -9e > $(DIST_DIR)/$(APP_NAME)-$(VERSION).tar.xz
	# tar -cI 'xz -9e' -f image.tar.xz /path/to/image
	@echo -e "$(GREEN)✓ Distributable ready: $(DIST_DIR)/$(APP_NAME)-$(VERSION).tar.xz$(NC)"
	@echo -e "$(BLUE)- Load on another host:$(NC)"
	@echo -e "$(WHITE)    $(CONTAINER_RUNTIME) load --input $(DIST_DIR)/$(APP_NAME)-$(VERSION).tar.xz$(NC)"
	@echo -e "$(BLUE)- Then run:$(NC)"
	@echo -e "$(WHITE)    $(CONTAINER_RUNTIME) run -p 8092:8092 $(IMAGE)$(NC)"

cdist: $(CDIST_STAMP) check-container-env bump-version ## Build a distributable package (container image + exported OCI tarball in dist)
	@:

# --------------------------------------------------------------------------------------------
# Cleanup
# --------------------------------------------------------------------------------------------
clean: ## Remove local Node build artifacts and dist/
	@echo -e "$(YELLOW)- Cleaning build artifacts...$(NC)"
	@rm -rf apps/web/dist dist
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

# --------------------------------------------------------------------------------------------
# Targets to push to ghcr
# --------------------------------------------------------------------------------------------
# push-ghcr: check-container-env ## Push the container image to GitHub Container Registry (ghcr.io)
# 	@echo -e "$(YELLOW)- Pushing container image to GitHub Container Registry (ghcr.io)...$(NC)"
# 	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
# 	@echo -e "$(BLUE)- Image:   $(IMAGE)$(NC)"
# 	@$(CONTAINER_RUNTIME) push ghcr.io/edumatcher/$(APP_NAME):$(VERSION)
# 	@echo -e "$(GREEN)✓ Container image pushed to ghcr.io/edumatcher/$(APP_NAME):$(VERSION)$(NC)"

# # Login to ghcr.io (GitHub Container Registry) using a personal access token (PAT)
# login-ghcr: check-container-env ## Log in to GitHub Container Registry (ghcr.io) using a personal access token (PAT)
# 	@echo -e "$(YELLOW)- Logging in to GitHub Container Registry (ghcr.io)...$(NC)"
# 	@echo -e "$(BLUE)- Runtime: $(CONTAINER_RUNTIME)$(NC)"
# 	@echo -e "$(BLUE)- Image:   $(IMAGE)$(NC)"
# 	@echo -e "$(YELLOW)- Please enter your GitHub username and personal access token (PAT) when prompted.$(NC)"
# 	@$(CONTAINER_RUNTIME) login ghcr.io
# 	@echo -e "$(GREEN)✓ Logged in to GitHub Container Registry (ghcr.io)$(NC)"


# ============================================================================================
# GitHub Container Registry Targets
# ============================================================================================


$(GHCR_LOGIN_STAMP): | $(TIMESTAMP_DIR)
	@if [ -z "$(GHCR_TOKEN)" ]; then \
		echo -e "$(RED)✗ Error: GHCR_TOKEN environment variable is not set. Please set GHCR_TOKEN with a valid GitHub Personal Access Token.$(NC)"; \
		exit 1; \
	fi
	@if [ -f $(GHCR_LOGIN_STAMP) ] && [ $$(find $(GHCR_LOGIN_STAMP) -mmin -120) ]; then \
		echo -e "$(GREEN)✓ Already logged in to GHCR recently.$(NC)"; \
		exit 0; \
	else \
		echo -e "$(DARKYELLOW)- Logging in to GitHub Container Registry...$(NC)"; \
		if $(CONTAINER_RUNTIME) login ghcr.io -u $(GITHUB_USER) -p $(GHCR_TOKEN) >/dev/null 2>&1; then \
			echo -e "$(GREEN)✓ Login to GitHub successful!$(NC)"; \
			touch $(GHCR_LOGIN_STAMP) ; \
		else \
			echo -e "$(RED)✗ Login failed. Please check your GHCR_TOKEN.$(NC)"; \
			rm -f $(GHCR_LOGIN_STAMP); \
			exit 1; \
		fi \
	fi	

ghcr-login: $(GHCR_LOGIN_STAMP) ## Login to GitHub Container Registry via Podman/Docker
	@:

cpush: $(GHCR_LOGIN_STAMP) $(CONTAINER_STAMP)  ## Push container image to GitHub Container Registry
	@if [ -z "$(GITHUB_USER)" ]; then \
        echo -e "$(RED)✗ Error: GITHUB_USER environment variable is not set."; \
        echo -e "  Please set GITHUB_USER as an environment variable or add as argument: make container-push GITHUB_USER=\"XXXXX\"$(NC)"; \
        exit 1; \
	fi
	@echo -e "$(DARKYELLOW)- Checking if image version $(VERSION) already exists on GHCR...$(NC)"
	@if $(CONTAINER_RUNTIME) manifest inspect ghcr.io/$(GITHUB_USER)/$(CONTAINER_NAME):$(VERSION) >/dev/null 2>&1; then \
        echo -e "$(YELLOW)⚠️  Warning: Image $(CONTAINER_NAME):$(VERSION) already exists in the registry. Skipping push.$(NC)"; \
        exit 1; \
    fi
	@echo -e "$(DARKYELLOW)- Pushing image $(CONTAINER_NAME):$(VERSION) and tagging as latest to GitHub Container Registry...$(NC)"
	@$(CONTAINER_RUNTIME) tag $(CONTAINER_NAME):$(VERSION) ghcr.io/$(GITHUB_USER)/$(CONTAINER_NAME):$(VERSION)
	@$(CONTAINER_RUNTIME) tag $(CONTAINER_NAME):$(VERSION) ghcr.io/$(GITHUB_USER)/$(CONTAINER_NAME):latest
	@if $(CONTAINER_RUNTIME) push ghcr.io/$(GITHUB_USER)/$(CONTAINER_NAME):$(VERSION) && $(CONTAINER_RUNTIME) push ghcr.io/$(GITHUB_USER)/$(CONTAINER_NAME):latest; then \
        echo -e "$(GREEN)✓ Image pushed successfully.$(NC)"; \
	else \
        echo -e "$(RED)✗ Error: Failed to push image to GHCR.$(NC)"; \
        exit 1; \
    fi

ghcr-logout: ## Logout from GitHub Container Registry
	@if [ ! -f $(GHCR_LOGIN_STAMP) ]; then \
		echo -e "$(YELLOW)⚠️  Warning: Not logged in to GHCR. Skipping logout.$(NC)"; \
		exit 1; \
	fi
	@echo -e "$(DARKYELLOW)- Logging out from GitHub Container Registry...$(NC)"
	@$(CONTAINER_RUNTIME) logout ghcr.io
	@rm -f $(GHCR_LOGIN_STAMP)
	@echo -e "$(GREEN)✓ Logged out from GHCR$(NC)"

ghcr-clean: ghcr-logout container-clean-images ## Clean up GHCR login and local images
	@:

