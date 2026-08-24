# EduMatcher container control surface.
#
#   make build            build the image (EduMatcher from PyPI)
#   make build DEV=1      build it from the wheel in ../dist instead
#   make up               start the exchange
#   make up ZMQ=1 SSH=1   ... also exposing the ZeroMQ bus and sshd
#   make shell            get a root shell inside the running container
#   make down             stop and remove the container
#
# Podman is preferred when both engines are installed; override with
# `make up CONTAINER_ENGINE=docker`.

SHELL := /bin/bash
.DEFAULT_GOAL := help

# --- Engine and compose detection -----------------------------------------
CONTAINER_ENGINE ?= $(shell \
	if command -v podman >/dev/null 2>&1; then echo podman; \
	elif command -v docker >/dev/null 2>&1; then echo docker; fi)

COMPOSE ?= $(shell \
	if [ "$(CONTAINER_ENGINE)" = "podman" ]; then \
		if command -v podman-compose >/dev/null 2>&1; then echo "podman-compose"; \
		elif podman compose version >/dev/null 2>&1; then echo "podman compose"; fi; \
	elif [ "$(CONTAINER_ENGINE)" = "docker" ]; then \
		if docker compose version >/dev/null 2>&1; then echo "docker compose"; \
		elif command -v docker-compose >/dev/null 2>&1; then echo "docker-compose"; fi; \
	fi)

env_value = $(shell grep -E '^$(1)=' .env 2>/dev/null | cut -d= -f2)
CONTAINER_NAME ?= $(or $(call env_value,CONTAINER_NAME),edumatcher)
IMAGE_NAME ?= $(or $(call env_value,IMAGE_NAME),edumatcher)
IMAGE_TAG ?= $(or $(call env_value,IMAGE_TAG),local)
SSH_PORT ?= $(or $(call env_value,SSH_PORT),2222)

EXEC := $(CONTAINER_ENGINE) exec
EXEC_TTY := $(CONTAINER_ENGINE) exec -it

# --- Optional overlays -----------------------------------------------------
COMPOSE_FILES := -f compose.yaml
ifeq ($(ZMQ),1)
COMPOSE_FILES += -f compose.zmq.yaml
endif
ifeq ($(SSH),1)
COMPOSE_FILES += -f compose.ssh.yaml
endif

# Command-line overrides win over .env for this invocation only.
RUN_ENV :=
ifdef CONFIG
RUN_ENV += EM_CONFIG=$(CONFIG)
endif
ifdef PROFILE
RUN_ENV += EM_PROFILE=$(PROFILE)
endif
ifdef VERSION
RUN_ENV += EDUMATCHER_VERSION=$(VERSION)
endif

DC := $(RUN_ENV) $(COMPOSE) $(COMPOSE_FILES)

.PHONY: help info check build up down restart shell logs proc-logs \
	status health ssh keys config-deploy config-show ports clean clean-data

help:
	@echo "EduMatcher container — targets:"
	@echo ""
	@echo "  make build              Build the image from PyPI (VERSION=x.y.z to pin)"
	@echo "  make build DEV=1        Build it from a freshly built local wheel"
	@echo "  make up                 Start the exchange (CONFIG=..., PROFILE=...)"
	@echo "  make up ZMQ=1           ... and publish the raw ZeroMQ bus ports"
	@echo "  make up SSH=1           ... and run sshd on port $${SSH_PORT:-2222}"
	@echo "  make down               Stop and remove the container"
	@echo "  make restart            Restart the container"
	@echo "  make shell              Interactive shell inside the container"
	@echo "  make ssh                Log in over ssh (needs 'make up SSH=1')"
	@echo "  make status             pm-opctl-cli list — one row per process"
	@echo "  make health             pm-opctl-cli health — exit code 0 when all OK"
	@echo "  make logs               Follow the container (entrypoint) output"
	@echo "  make proc-logs P=engine Follow one process log from data/emo/"
	@echo "  make config-deploy      Recompile data/ref_data/engine_config.yaml"
	@echo "  make config-show        Show the deployed configuration"
	@echo "  make ports              List the published ports"
	@echo "  make clean              Remove the container and the image"
	@echo "  make clean-data         Delete ./data (the whole exchange state)"
	@echo "  make info               Show the detected engine and image names"
	@echo ""
	@echo "  engine: $(CONTAINER_ENGINE)   compose: $(COMPOSE)"

check:
	@if [ -z "$(CONTAINER_ENGINE)" ]; then \
		echo "ERROR: neither podman nor docker found on PATH." >&2; exit 1; fi
	@if [ -z "$(COMPOSE)" ]; then \
		echo "ERROR: $(CONTAINER_ENGINE) found, but no compose implementation." >&2; \
		echo "       Install 'podman-compose' or Docker Compose v2." >&2; exit 1; fi

info: check
	@echo "engine:  $(CONTAINER_ENGINE)"
	@echo "compose: $(COMPOSE)"
	@echo "image:   $(IMAGE_NAME):$(IMAGE_TAG)"
	@echo "name:    $(CONTAINER_NAME)"

.env:
	@cp .env.example .env
	@echo "Created .env from .env.example"

init: .env
	@echo "Initialized the container control surface. Edit .env to customize."


# --- Build -----------------------------------------------------------------
build: check .env
ifeq ($(DEV),1)
	@echo "==> building wheel from the repository checkout"
	@cd .. && poetry build --format wheel
	@rm -f .wheel/*.whl
	@cp "$$(ls -t ../dist/*.whl | head -1)" .wheel/
	@echo "==> using $$(ls .wheel/*.whl)"
else
	@rm -f .wheel/*.whl
endif
	$(DC) build

# --- Lifecycle -------------------------------------------------------------
up: check .env
ifeq ($(SSH),1)
	@$(MAKE) --no-print-directory keys
endif
	@mkdir -p data
	$(DC) up -d
	@echo ""
	@echo "Started. 'make status' for the process table, 'make shell' to log in."

down: check
	$(DC) down

restart: check
	$(DC) restart

# --- Access ----------------------------------------------------------------
shell: check
	$(EXEC_TTY) -e TERM=$${TERM:-xterm-256color} $(CONTAINER_NAME) bash

ssh: check
	ssh -o StrictHostKeyChecking=accept-new -p $(SSH_PORT) root@localhost

keys:
	@mkdir -p .ssh
	@cat $${HOME}/.ssh/*.pub > .ssh/authorized_keys 2>/dev/null || true
	@if [ ! -s .ssh/authorized_keys ]; then \
		echo "ERROR: no public keys in ~/.ssh/*.pub — run 'ssh-keygen -t ed25519' first." >&2; \
		exit 1; fi
	@chmod 600 .ssh/authorized_keys
	@echo "Authorized keys: $$(wc -l < .ssh/authorized_keys) key(s) from ~/.ssh"

# --- Observation -----------------------------------------------------------
logs: check
	$(CONTAINER_ENGINE) logs -f $(CONTAINER_NAME)

P ?= engine
proc-logs:
	@tail -f data/emo/$(P).log

status: check
	$(EXEC_TTY) $(CONTAINER_NAME) pm-opctl-cli list --no-restart

health: check
	$(EXEC) $(CONTAINER_NAME) pm-opctl-cli health

ports: check
	$(CONTAINER_ENGINE) port $(CONTAINER_NAME)

# --- Configuration ---------------------------------------------------------
config-deploy: check
	$(EXEC) $(CONTAINER_NAME) pm-config-deploy /data/ref_data/engine_config.yaml
	@echo "Deployed. Restart the stack to pick it up: make restart"

config-show: check
	$(EXEC_TTY) $(CONTAINER_NAME) pm-config-show

# --- Cleanup ---------------------------------------------------------------
clean: check
	-$(DC) down
	-$(CONTAINER_ENGINE) rmi $(IMAGE_NAME):$(IMAGE_TAG)

clean-data:
	@read -p "Delete ./data and every trade, log and database in it? [y/N] " ans; \
	if [ "$$ans" = "y" ]; then rm -rf data && echo "data/ removed"; else echo "kept"; fi
