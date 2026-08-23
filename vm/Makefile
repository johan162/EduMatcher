# EduMatcher VM control surface.
#
#   make build             create the runtime VM (vm/mknode.sh, name: ems)
#   make build DEV=1       ... installing the local wheel from ../dist instead of PyPI
#   make up                start the VM
#   make down               stop the VM
#   make shell              interactive shell inside the VM
#   make clean               delete the VM
#
# The VM name is chosen by 'make build' (NAME=... to override the default
# 'ems') and remembered in .vm-name so later targets don't need to repeat it.

SHELL := /bin/bash
.DEFAULT_GOAL := help

SCRIPT_DIR := $(shell cd "$(dir $(lastword $(MAKEFILE_LIST)))" && pwd)
NAME_FILE := $(SCRIPT_DIR)/.vm-name

DEFAULT_NAME := ems
NAME ?= $(DEFAULT_NAME)

# Every target but 'build' operates on the VM recorded in .vm-name, falling
# back to NAME/DEFAULT_NAME so a fresh checkout still works before the first
# build.
VM_NAME := $(strip $(shell cat "$(NAME_FILE)" 2>/dev/null))
ifeq ($(VM_NAME),)
VM_NAME := $(NAME)
endif

.PHONY: help check build up down restart shell ssh status health info clean

help:
	@echo "EduMatcher VM — targets:"
	@echo ""
	@echo "  make build              Create the VM (NAME=... to override '$(DEFAULT_NAME)')"
	@echo "  make build DEV=1        ... installing the local wheel from ../dist"
	@echo "  make build VERSION=x.y.z ... pinning a specific PyPI release"
	@echo "  make up                 Start the VM"
	@echo "  make down               Stop the VM"
	@echo "  make restart            Restart the VM"
	@echo "  make shell              Interactive shell inside the VM"
	@echo "  make ssh                Log in over ssh as 'ubuntu'"
	@echo "  make status             pm-opctl-cli list — one row per process"
	@echo "  make health             pm-opctl-cli health — exit code 0 when all OK"
	@echo "  make info               Show the VM name and multipass state"
	@echo "  make clean              Delete the VM (multipass delete --purge)"
	@echo ""
	@echo "  vm: $(VM_NAME)"

check:
	@if ! command -v multipass >/dev/null 2>&1; then \
		echo "ERROR: multipass not found on PATH." >&2; exit 1; fi

info: check
	@echo "vm:    $(VM_NAME)"
	@multipass info "$(VM_NAME)" 2>/dev/null || echo "state: not created — run 'make build'"

# --- Build -------------------------------------------------------------
build: check
	@args="--name $(NAME)"; \
	if [ "$(DEV)" = "1" ]; then args="$$args --dev"; fi; \
	if [ -n "$(VERSION)" ]; then args="$$args --version $(VERSION)"; fi; \
	if [ -n "$(IMAGE)" ]; then args="$$args --image $(IMAGE)"; fi; \
	if [ -n "$(CPUS)" ]; then args="$$args --cpus $(CPUS)"; fi; \
	if [ -n "$(MEMORY)" ]; then args="$$args --memory $(MEMORY)"; fi; \
	if [ -n "$(DISK)" ]; then args="$$args --disk $(DISK)"; fi; \
	if [ "$(SNAPSHOT)" = "1" ]; then args="$$args --snapshot"; fi; \
	echo "$(SCRIPT_DIR)/mknode.sh $$args"; \
	"$(SCRIPT_DIR)/mknode.sh" $$args
	@echo "$(NAME)" > "$(NAME_FILE)"

# --- Lifecycle -----------------------------------------------------------
up: check
	multipass start "$(VM_NAME)"

down: check
	multipass stop "$(VM_NAME)"

restart: check
	multipass restart "$(VM_NAME)"

# --- Access ----------------------------------------------------------------
shell: check
	multipass shell "$(VM_NAME)"

ssh: check
	@ip="$$(multipass info "$(VM_NAME)" | grep IPv4 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -1)"; \
	if [ -z "$$ip" ]; then \
		echo "ERROR: could not determine the IP of '$(VM_NAME)' — is it running? ('make up')" >&2; \
		exit 1; fi; \
	ssh -o StrictHostKeyChecking=accept-new "ubuntu@$$ip"

# --- Observation -------------------------------------------------------------
status: check
	multipass exec "$(VM_NAME)" -- pm-opctl-cli list --no-restart

health: check
	multipass exec "$(VM_NAME)" -- pm-opctl-cli health

# --- Cleanup -----------------------------------------------------------------
clean: check
	-multipass delete --purge "$(VM_NAME)"
	@rm -f "$(NAME_FILE)"
