# EduMatcher container control surface.
#
#   make build             build the image from a freshly built local wheel
#   make build PYPI=1      ... from the latest PyPI release instead
#   make build VERSION=x.y.z  ... pin a specific PyPI release
#   make up                start the exchange
#   make up ZMQ=1 SSH=1    ... also exposing the ZeroMQ bus and sshd
#   make shell             get a root shell inside the running container
#   make down              stop and remove the container
#
# Podman is preferred when both engines are installed; override with
# `make up CONTAINER_ENGINE=docker`.
#
# `make build`'s default builds from your local source checkout (see
# "Build" below) — this is deliberate: a plain rebuild after editing source
# should always pick up that edit. Silently falling back to whatever's on
# PyPI here previously cost real debugging time chasing "my fix isn't
# taking effect" as if it were a runtime/networking bug.

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

# The whole system — the exchange plus the web GUIs — in one compose project,
# which is what puts them on one network and lets the GUIs reach the backend
# by the hostname 'edumatcher'. config-gui talks to nothing and is opt-in.
ALL_COMPOSE_FILES := $(COMPOSE_FILES) -f compose.guis.yaml
ifeq ($(CONFIG_GUI),1)
ALL_COMPOSE_FILES += -f compose.config-gui.yaml
endif
DOWN_COMPOSE_FILES := $(COMPOSE_FILES) -f compose.guis.yaml
# Publishing covers every image, config-gui included — it is a released
# application even though `up-all` leaves it opt-in.
PUBLISH_COMPOSE_FILES := -f compose.yaml -f compose.guis.yaml -f compose.config-gui.yaml

# --- Publishing to GHCR ----------------------------------------------------
# The release path is .github/workflows/publish-images.yml, which builds each
# image natively on amd64 and arm64 and joins them into one manifest list.
# `make ghcr-push` is the manual escape hatch for when that is unavailable, and
# it can only produce an image for the architecture you are standing on.
GHCR_REGISTRY ?= ghcr.io
PROJECT_VERSION := $(shell awk -F'"' '/^version =/ {print $$2; exit}' ../../pyproject.toml)
# Not VERSION: that already means "which PyPI release to install" for `make build`.
TAG ?= dev
GUI_IMAGES := edumatcher-config-gui edumatcher-log-gui edumatcher-terminal-gui edumatcher-trader-gui

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
DC_ALL := $(COMPOSE) $(ALL_COMPOSE_FILES)

# Reads the deployed configuration and prints "<port> <api_key>" for the first
# read-only credential (gateway_id: null). terminal-gui's history endpoints
# need it, and it is generated per configuration — different in every bundled
# example — and lives on the 'dashboards' instance (8081), not 'desk' (8080).
define READONLY_CREDENTIAL_PY
import json
try:
    cfg = json.load(open("/data/ref_data/engine_config.json"))
except OSError:
    raise SystemExit(1)
for name, gw in sorted((cfg.get("api_gateways") or {}).items()):
    if not gw.get("enabled", True):
        continue
    for cred in gw.get("credentials") or []:
        if cred.get("gateway_id") is None:
            print(gw.get("port", 8080), cred["api_key"])
            raise SystemExit(0)
raise SystemExit(1)
endef
export READONLY_CREDENTIAL_PY

.PHONY: help info check build up up-all down down-all restart shell logs \
	proc-logs status health ssh keys config-deploy config-show ports \
	ghcr-push clean clean-data

help:
	@echo "EduMatcher container — targets:"
	@echo ""
	@echo "  make build              Build the image from a freshly built local wheel"
	@echo "  make build PYPI=1       ... from the latest PyPI release instead"
	@echo "  make build VERSION=x.y.z  ... pin a specific PyPI release"
	@echo "  make up                 Start the exchange (CONFIG=..., PROFILE=...)"
	@echo "  make up ZMQ=1           ... and publish the raw ZeroMQ bus ports"
	@echo "  make up SSH=1           ... and run sshd on port $${SSH_PORT:-2222}"
	@echo "  make down               Stop and remove the container"
	@echo ""
	@echo "  make up-all             Start the exchange AND the web GUIs together"
	@echo "  make up-all CONFIG=ten-nominal        ... on a bundled example"
	@echo "  make up-all CONFIG=./my_config.yaml   ... on a configuration of your own"
	@echo "  make up-all CONFIG_GUI=1              ... and the config builder too"
	@echo "  make down-all           Stop and remove every container"
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
	@echo ""
	@echo "  make ghcr-push          Push all five images to GHCR as :dev (this arch only)"
	@echo "  make ghcr-push TAG=x.y.z FORCE=1   ... as a release tag (see the warning)"
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
# Default: build from a freshly built local wheel (what DEV=1 used to mean —
# DEV=1 is still accepted for anyone's muscle memory, but is now a no-op).
# PYPI=1 installs the latest PyPI release instead; VERSION=x.y.z pins one
# (and implies PyPI, so PYPI=1 alongside it is redundant but harmless).
build: check .env
	@if [ -n "$(VERSION)" ] && [ "$(PYPI)" = "1" ]; then \
		echo "==> building from PyPI, pinned to $(VERSION)"; \
		rm -f .wheel/*.whl; \
	elif [ -n "$(VERSION)" ]; then \
		echo "==> building from PyPI, pinned to $(VERSION)"; \
		rm -f .wheel/*.whl; \
	elif [ "$(PYPI)" = "1" ]; then \
		echo "==> building from PyPI (latest)"; \
		rm -f .wheel/*.whl; \
	else \
		echo "==> building wheel from the repository checkout"; \
		(cd ../.. && poetry build --format wheel) && \
		rm -f .wheel/*.whl && \
		cp "$$(ls -t ../../dist/*.whl | head -1)" .wheel/ && \
		echo "==> using $$(ls .wheel/*.whl)"; \
	fi
	$(DC) build

# --- Lifecycle -------------------------------------------------------------
up: check .env
ifeq ($(SSH),1)
	@$(MAKE) --no-print-directory keys
endif
	@mkdir -p data config
	$(DC) up -d
	@echo ""
	@echo "Started. 'make status' for the process table, 'make shell' to log in."

# --- The whole system ------------------------------------------------------
# Two phases, deliberately: terminal-gui's read-only API key does not exist
# until the exchange has deployed its configuration, so the backend has to be
# up before the GUIs can be given their environment.
up-all: check .env
ifeq ($(SSH),1)
	@$(MAKE) --no-print-directory keys
endif
	@mkdir -p data config
	@set -eu; \
	if [ -n "$(CONFIG)" ] && [ -f "$(CONFIG)" ]; then \
		cp "$(CONFIG)" config/engine_config.yaml; \
		EM_CONFIG_FILE=/config/engine_config.yaml; export EM_CONFIG_FILE; \
		echo "==> engine config: $(CONFIG)"; \
	elif [ -n "$(CONFIG)" ]; then \
		EM_CONFIG="$(CONFIG)"; export EM_CONFIG; \
		echo "==> engine config: bundled example '$(CONFIG)'"; \
	fi; \
	if [ -n "$(PROFILE)" ]; then EM_PROFILE="$(PROFILE)"; export EM_PROFILE; fi; \
	$(DC_ALL) up -d edumatcher; \
	printf '==> waiting for the exchange to deploy its configuration'; \
	for _ in $$(seq 1 60); do \
		if $(CONTAINER_ENGINE) exec $(CONTAINER_NAME) \
		   test -f /data/ref_data/engine_config.json >/dev/null 2>&1; then break; fi; \
		printf '.'; sleep 1; \
	done; echo; \
	cred=$$($(CONTAINER_ENGINE) exec $(CONTAINER_NAME) \
	        python3 -c "$$READONLY_CREDENTIAL_PY" 2>/dev/null || true); \
	if [ -n "$$cred" ]; then \
		set -- $$cred; \
		API_GATEWAY_URL="http://edumatcher:$$1"; export API_GATEWAY_URL; \
		PM_TERMINAL_API_KEY="$$2"; export PM_TERMINAL_API_KEY; \
		echo "==> terminal-gui history: $$API_GATEWAY_URL (read-only key from the deployed config)"; \
	else \
		echo "==> WARNING: no read-only credential (gateway_id: null) in the deployed"; \
		echo "    configuration — terminal-gui's history endpoints will be unavailable."; \
	fi; \
	$(DC_ALL) up -d
	@echo ""
	@echo "Started. Open:"
	@echo "  terminal-gui  http://localhost:$${TERMINAL_GUI_PORT:-8090}"
	@echo "  log-gui       http://localhost:$${LOG_GUI_PORT:-8091}"
	@echo "  trader-gui    http://localhost:$${TRADER_GUI_PORT:-8093}"
ifeq ($(CONFIG_GUI),1)
	@echo "  config-gui    http://localhost:$${CONFIG_GUI_PORT:-8092}"
endif

# podman-compose removes what the named files declare, so an overlay naming a
# container that was never started is an error rather than a no-op. Name the
# config-gui overlay only when there is something to remove.
down-all: check
	@set -eu; \
	files="$(DOWN_COMPOSE_FILES)"; \
	if [ "$(CONFIG_GUI)" = "1" ] || \
	   $(CONTAINER_ENGINE) container inspect $(CONTAINER_NAME)-config-gui >/dev/null 2>&1; then \
		files="$$files -f compose.config-gui.yaml"; \
	fi; \
	$(COMPOSE) $$files down

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

# --- Publishing ------------------------------------------------------------
# Builds all five images from this checkout and pushes them to GHCR under one
# tag. Needs GITHUB_USER and GHCR_TOKEN.
#
#   make ghcr-push                       -> :dev
#   make ghcr-push TAG=0.20.6 FORCE=1    -> :0.20.6
#   make ghcr-push TAG=0.20.6 FORCE=1 LATEST=1   -> also moves :latest
#
# This publishes a SINGLE-ARCHITECTURE image. Pushing a release tag here
# replaces the multi-arch manifest list the workflow published for that tag,
# which silently breaks every user on the other architecture — so a release-
# looking tag requires FORCE=1, and `latest` is never moved unless asked.
ghcr-push: check
	@set -eu; \
	if [ -z "$${GITHUB_USER:-}" ]; then \
		echo "ERROR: GITHUB_USER is not set." >&2; exit 1; fi; \
	if [ -z "$${GHCR_TOKEN:-}" ]; then \
		echo "ERROR: GHCR_TOKEN is not set (a GitHub token with write:packages)." >&2; exit 1; fi; \
	case "$(TAG)" in \
		[0-9]*.[0-9]*.[0-9]*) \
			if [ "$(FORCE)" != "1" ]; then \
				echo "REFUSING to push '$(TAG)': that looks like a release tag." >&2; \
				echo "  The release images are multi-arch; this pushes $$(uname -m) only," >&2; \
				echo "  which would replace the manifest list and break the other architecture." >&2; \
				echo "  Prefer: gh workflow run publish-images.yml -f tag=v$(TAG)" >&2; \
				echo "  Override with FORCE=1 if you know the workflow cannot run." >&2; \
				exit 1; \
			fi; \
			echo "==> WARNING: pushing single-arch ($$(uname -m)) images as '$(TAG)'";; \
	esac; \
	echo "==> building all five images from this checkout"; \
	$(COMPOSE) $(PUBLISH_COMPOSE_FILES) build; \
	echo "$$GHCR_TOKEN" | $(CONTAINER_ENGINE) login $(GHCR_REGISTRY) \
		-u "$$GITHUB_USER" --password-stdin; \
	for pair in "$(IMAGE_NAME):$(IMAGE_TAG) edumatcher" \
	            $(foreach g,$(GUI_IMAGES),"$(g):latest $(g)"); do \
		set -- $$pair; local_ref="$$1"; remote="$(GHCR_REGISTRY)/$$GITHUB_USER/$$2"; \
		echo "==> $$local_ref -> $$remote:$(TAG)"; \
		$(CONTAINER_ENGINE) tag "$$local_ref" "$$remote:$(TAG)"; \
		$(CONTAINER_ENGINE) push "$$remote:$(TAG)"; \
		if [ "$(LATEST)" = "1" ]; then \
			$(CONTAINER_ENGINE) tag "$$local_ref" "$$remote:latest"; \
			$(CONTAINER_ENGINE) push "$$remote:latest"; \
		fi; \
	done; \
	echo ""; \
	echo "Pushed as :$(TAG) (project version is $(PROJECT_VERSION))."; \
	echo "New packages are PRIVATE — make each one public in its GitHub package settings,"; \
	echo "or nobody but you can pull them."

# --- Cleanup ---------------------------------------------------------------
clean: check
	-@$(DC) down 2>/dev/null || true
	-@$(CONTAINER_ENGINE) rmi $(IMAGE_NAME):$(IMAGE_TAG) 2>/dev/null || true

clean-data:
	@read -p "Delete ./data and every trade, log and database in it? [y/N] " ans; \
	if [ "$$ans" = "y" ]; then rm -rf data && echo "data/ removed"; else echo "kept"; fi

clean-all: clean clean-data
	@echo "Cleaned all."