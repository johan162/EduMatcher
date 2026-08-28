# web-apps/Makefile — orchestrate log-gui, terminal-gui, and trader-gui together.
#
# The key variable is VM_BACKEND_IP: set it to the IP of the VM (or host)
# running the EduMatcher backend processes. Every GUI container is then
# pointed at that IP automatically. Without it, each app falls back to its
# own default (host.docker.internal), which is correct for Docker Desktop.
#
# Usage:
#
#   # All three GUIs, backend on Docker Desktop host (default):
#   make up
#
#   # All three GUIs, backend in a separate VM:
#   make up VM_BACKEND_IP=192.168.64.10
#
#   # Or export once for the shell session:
#   export VM_BACKEND_IP=192.168.64.10
#   make up
#   make down
#   make logs
#
# Individual apps can still be driven from their own directories; this
# Makefile is purely additive.

# --------------------------------------------------------------------------------------------
# Make behaviour
# --------------------------------------------------------------------------------------------
.DEFAULT_GOAL := help
.DELETE_ON_ERROR:
SHELL        := $(shell which bash)
.SHELLFLAGS  := -euo pipefail -c
.ONESHELL:

# --------------------------------------------------------------------------------------------
# Variables
# --------------------------------------------------------------------------------------------

# IP of the VM (or host) running the EduMatcher backend processes.
# Override on the command line or via the environment:
#   make up VM_BACKEND_IP=192.168.64.10
VM_BACKEND_IP ?= $(shell multipass info edumatcher-vm | grep IP |  grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+')

# Print IP Address of backend
print-backend-ip: ## Print the IP address of the backend VM (if any)
	@if [[ -n "$(VM_BACKEND_IP)" ]]; then \
		echo -e "$(YELLOW)- EduMatcher backend VM IP: $(VM_BACKEND_IP)$(NC)"; \
	else \
		echo -e "$(RED)- EduMatcher backend VM IP not set; using host.docker.internal$(NC)"; \
	fi

# Derive per-app environment variables from VM_BACKEND_IP when set.
# When not set, each compose file's own default (host.docker.internal) applies.
ifdef VM_BACKEND_IP
  # log-gui: pm-log-srv host
  LOG_GUI_ENV := LOG_SRV_HOST=$(VM_BACKEND_IP)
  # terminal-gui: pm-md-gwy (CALF), pm-api-gwy (REST), pm-log-srv
  TERMINAL_GUI_ENV := CALF_HOST=$(VM_BACKEND_IP) \
                      API_GATEWAY_URL=http://$(VM_BACKEND_IP):8081 \
                      LOG_SRV_HOST=$(VM_BACKEND_IP)
  # trader-gui: pm-api-gwy REST/WS proxy target
  TRADER_GUI_ENV := API_PROXY_TARGET=http://$(VM_BACKEND_IP):8080
else
  LOG_GUI_ENV      :=
  TERMINAL_GUI_ENV :=
  TRADER_GUI_ENV   :=
endif

# Directories
LOG_GUI_DIR      := log-gui
TERMINAL_GUI_DIR := terminal-gui
TRADER_GUI_DIR   := trader-gui

# Colours
RED       := \033[0;31m
GREEN     := \033[0;32m
YELLOW    := \033[1;33m
BLUE      := \033[0;34m
CYAN      := \033[1;36m
NC        := \033[0m

.PHONY: help up down restart logs-log logs-terminal logs-trader ps \
        up-log up-terminal up-trader \
        down-log down-terminal down-trader

# --------------------------------------------------------------------------------------------
# Help
# --------------------------------------------------------------------------------------------
help: ## Show this help
	@echo ""
	@echo -e "$(CYAN)EduMatcher web-apps orchestration$(NC)"
	@echo ""
	@echo -e "$(YELLOW)Key variable:$(NC)"
	@echo -e "  $(BLUE)VM_BACKEND_IP$(NC)   IP of the VM running the EduMatcher backend."
	@echo -e "               Leave unset for Docker Desktop (uses host.docker.internal)."
	@echo -e "               Example: make up VM_BACKEND_IP=192.168.64.10"
	@echo ""
	@echo -e "$(YELLOW)Targets:$(NC)"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(BLUE)%-18s$(NC) %s\n", $$1, $$2}' \
	  | sort
	@echo ""

# --------------------------------------------------------------------------------------------
# All-at-once targets
# --------------------------------------------------------------------------------------------
up: up-log up-terminal up-trader ## Start all three GUI containers (set VM_BACKEND_IP for a remote VM)

down: down-log down-terminal down-trader ## Stop and remove all three GUI containers

restart: down up ## Restart all three GUI containers

ps: ## Show container status for all three apps
	@echo -e "$(CYAN)--- log-gui ---$(NC)"
	@$(MAKE) -C $(LOG_GUI_DIR) ps
	@echo -e "$(CYAN)--- terminal-gui ---$(NC)"
	@$(MAKE) -C $(TERMINAL_GUI_DIR) ps
	@echo -e "$(CYAN)--- trader-gui ---$(NC)"
	@$(MAKE) -C $(TRADER_GUI_DIR) ps

# --------------------------------------------------------------------------------------------
# Per-app targets
# --------------------------------------------------------------------------------------------
up-log: ## Start log-gui container
	@if [[ -n "$(VM_BACKEND_IP)" ]]; then \
		echo -e "$(YELLOW)- log-gui backend: $(VM_BACKEND_IP)$(NC)"; \
	fi
	@env $(LOG_GUI_ENV) $(MAKE) -C $(LOG_GUI_DIR) up

up-terminal: ## Start terminal-gui container
	@if [[ -n "$(VM_BACKEND_IP)" ]]; then \
		echo -e "$(YELLOW)- terminal-gui backend: $(VM_BACKEND_IP)$(NC)"; \
	fi
	@env $(TERMINAL_GUI_ENV) $(MAKE) -C $(TERMINAL_GUI_DIR) up

up-trader: ## Start trader-gui container
	@if [[ -n "$(VM_BACKEND_IP)" ]]; then \
		echo -e "$(YELLOW)- trader-gui backend: $(VM_BACKEND_IP)$(NC)"; \
	fi
	@env $(TRADER_GUI_ENV) $(MAKE) -C $(TRADER_GUI_DIR) up

down-log: ## Stop log-gui container
	@$(MAKE) -C $(LOG_GUI_DIR) down

down-terminal: ## Stop terminal-gui container
	@$(MAKE) -C $(TERMINAL_GUI_DIR) down

down-trader: ## Stop trader-gui container
	@$(MAKE) -C $(TRADER_GUI_DIR) down

# --------------------------------------------------------------------------------------------
# Log tailing (each in its own invocation — use separate terminals for live tailing)
# --------------------------------------------------------------------------------------------
logs-log: ## Follow log-gui container logs
	@$(MAKE) -C $(LOG_GUI_DIR) logs

logs-terminal: ## Follow terminal-gui container logs
	@$(MAKE) -C $(TERMINAL_GUI_DIR) logs

logs-trader: ## Follow trader-gui container logs
	@$(MAKE) -C $(TRADER_GUI_DIR) logs
