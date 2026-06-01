# Makefile for building Documentation for the MCProjSim project

.PHONY: docs gen-examples update-version pdf-docs docs-serve \
 container-engine-check docs-container-build docs-container-start docs-container-stop \
 docs-container-restart docs-container-status docs-container-logs docs-deploy help clean really-clean \
 pdf-api-ref pdfs pdf-docs cover cover-light cover-dark \
 cover-user-guide-a4-light cover-user-guide-a4-dark cover-user-guide-b5-light cover-user-guide-b5-dark


# Makefile itself as a dependency to ensure it is re-evaluated when changed
# NOTE: This requires GNU Make 4.3+ and MacOS ships with vGNU Make 3.81 due to licensing issues
# and then this line will be silently ignored.´unless you have upgrade make via brew or similar.	
.EXTRA_PREREQS := $(firstword $(MAKEFILE_LIST))

# Make behavior
.DEFAULT_GOAL := docs

# Get full path to bash
SHELL := $(shell which bash)

# Delete target files on error to prevent stale timestamps
.DELETE_ON_ERROR:

# Use a single shell for each target to allow multi-line commands and better error handling
.ONESHELL:

# Colors for output
BLACK := \033[0;30m
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[1;33m
BLUE := \033[0;34m
MAGENTA := \033[0;35m
CYAN := \033[0;36m
WHITE := \033[1;37m

# Variations
DARKGRAY := \033[1;30m
BRIGHTRED := \033[1;31m
BRIGHTGREEN := \033[1;32m
DARKYELLOW := \033[0;33m
BRIGHTBLUE := \033[1;34m
BRIGHTMAGENTA := \033[1;35m
BRIGHTCYAN := \033[1;36m
LIGHTGRAY := \033[0;37m
NC := \033[0m # No Color

# Formatting
BOLD := \033[1m
UNDERLINE := \033[4m

# ============================================================================================
# Tool availability checks
# ============================================================================================

POETRY := $(shell command -v poetry 2>/dev/null)
PODMAN := $(shell command -v podman 2>/dev/null)
PODMAN_COMPOSE := $(shell command -v podman-compose 2>/dev/null)
DOCKER := $(shell command -v docker 2>/dev/null)
DOCKER_COMPOSE := $(shell command -v docker-compose 2>/dev/null)

ifeq ($(POETRY),)
    $(error poetry not found. MacOS Install with: pip install poetry)
endif

# If both podman and docker are missing, raise an error
ifeq ($(PODMAN),)
    ifeq ($(DOCKER),)
        $(error Neither podman nor docker found. Please install one of them.)
    endif
endif

ifeq ($(PODMAN_COMPOSE),)
    ifeq ($(DOCKER_COMPOSE),)
        $(error Neither podman-compose nor docker-compose found. Please install one of them.)
    endif
endif

# Check which container engine is running and set the appropriate tool
PODMAN_RUNNING := $(shell podman info >/dev/null 2>&1 && echo "yes" || echo "no")
DOCKER_RUNNING := $(shell docker info >/dev/null 2>&1 && echo "yes" || echo "no")
NO_CONTAINER_ENGINE := $(shell if [ "$(PODMAN_RUNNING)" = "no" ] && [ "$(DOCKER_RUNNING)" = "no" ]; then echo "yes"; else echo "no"; fi)

ifeq ($(PODMAN_RUNNING),yes)
    CONTAINER_CMD := ${PODMAN}
    CONTAINER_COMPOSE_CMD := ${PODMAN_COMPOSE}
    $(info Using Podman as the container engine)
else ifeq ($(DOCKER_RUNNING),yes)
    CONTAINER_CMD := ${DOCKER}
    CONTAINER_COMPOSE_CMD := ${DOCKER_COMPOSE}
    $(info Using Docker as the container engine)
else
    $(info **WARNING** Neither Podman nor Docker engine is running. Please start one of them to use container-related targets.)
endif

# Check if we're behind a proxy (detect proxy environment variables and CA cert)
PROXY_DETECTED := no
ifneq ($(HTTP_PROXY)$(HTTPS_PROXY)$(http_proxy)$(https_proxy),)
    PROXY_DETECTED := yes
endif
ifeq ($(shell [ -f ${PROXY_CA_FILE} ] && [ -s ${PROXY_CA_FILE} ] && echo "yes"),yes)
    PROXY_DETECTED := yes
endif

ifeq ($(PROXY_DETECTED),yes)
    $(info Proxy environment detected - will use proxy CA certificate for container builds)
    DEFAULT_CONTAINER_BUILD := container-build-proxy
else
    $(info No proxy detected - will use standard container build)
    DEFAULT_CONTAINER_BUILD := container-build-standard
endif

# ============================================================================================
# Timestamp file targets
# ============================================================================================
$(DOC_STAMP): $(DOC_FILES)
	@echo -e "$(DARKYELLOW)- Building documentation...$(NC)"
	@if poetry run mkdocs build -q; then \
		touch $(DOC_STAMP); \
		echo -e "$(GREEN)✓ Documentation built successfully$(NC)"; \
	else \
		echo -e "$(RED)✗ Error: Documentation build failed$(NC)"; \
		exit 1; \
	fi

# ============================================================================================
# Variable configurations
# ============================================================================================

# Directories
DOCS_DIR := .
DIST_DIR := ../dist
BUILD_DIR := ../.build
SCRIPTS_DIR := ../scripts

# Documentation Container Server configuration
SERVER_HOST := 0.0.0.0
DOCS_PORT := 8100
DOCS_CONTAINER_SCRIPT := ../scripts/docs-contctl.sh

# Project settings
PROJECT := edumatcher
VERSION := $(shell grep '^version' ../pyproject.toml | head -1 | cut -d'"' -f2)

# Container related settings
CONTAINER_NAME := $(PROJECT)

# Temporary build directory for user guide PDF generation
USER_GUIDE_BUILD_DIR := $(BUILD_DIR)/user-guide
API_REF_BUILD_DIR := $(BUILD_DIR)/api-reference

# User guide PDF output paths and templates
# Variant-specific paths are derived by DEFINE_USER_GUIDE_VARS below.
# USER_GUIDE_LUA_FILTER is shared across all variants.
USER_GUIDE_LUA_FILTER := $(DOCS_DIR)/user-guide/pagebreaks.lua
API_REF_LUA_FILTER := $(DOCS_DIR)/user-guide/pagebreaks.lua
ADMONITIONS_LUA_FILTER := $(DOCS_DIR)/admonitions.lua
USER_GUIDE_LUA_FILTER_FLAGS := --lua-filter $(USER_GUIDE_LUA_FILTER) --lua-filter $(ADMONITIONS_LUA_FILTER)
API_REF_LUA_FILTER_FLAGS := --lua-filter $(API_REF_LUA_FILTER) --lua-filter $(ADMONITIONS_LUA_FILTER)

# Markdown sources that are concatenated into the User Guide PDF body.
# Keep this list markdown-only; non-markdown assets are tracked separately
# via USER_GUIDE_PDF_DEPS so they trigger rebuilds without polluting content.
USER_GUIDE_MD_SOURCES := \
	$(sort $(wildcard $(DOCS_DIR)/user-guide/[0-9][0-9]_*.md))

# Non-markdown assets that should still trigger a rebuild when changed.
USER_GUIDE_PDF_DEPS := \
	$(DOCS_DIR)/user-guide/pagebreaks.lua \
	$(DOCS_DIR)/admonitions.lua \
	$(DOCS_DIR)/user-guide/template_a4.tex \
	$(DOCS_DIR)/user-guide/template_dark_a4.tex \
	$(DOCS_DIR)/user-guide/template_b5.tex \
	$(DOCS_DIR)/user-guide/template_dark_b5.tex 


# ============================================================================================
# Macro: DEFINE_USER_GUIDE_VARS
# Derives all variant-specific file-path variables from the base name alone.
# $(1) = USER_GUIDE | USER_GUIDE_B5 | USER_GUIDE_DARK | USER_GUIDE_DARK_B5
#
# The suffix is extracted by stripping the USER_GUIDE prefix from $(1):
#   tex_sfx  — lowercase with underscores (_b5, _dark, _dark_b5)  for LaTeX template names
#   file_sfx — lowercase with hyphens    (-b5, -dark, -dark-b5)   for all other file names
# ============================================================================================
define DEFINE_USER_GUIDE_VARS
$(1)_TEMPLATE     := $$(DOCS_DIR)/user-guide/userguide_template$(shell printf '%s' '$(patsubst USER_GUIDE%,%,$(1))' | tr '[:upper:]' '[:lower:]').tex
$(1)_PDF          := $$(DIST_DIR)/$$(PROJECT)_user-guide$(shell printf '%s' '$(patsubst USER_GUIDE%,%,$(1))' | tr '[:upper:]_' '[:lower:]-')-$$(VERSION).pdf
$(1)_CONCAT_MD    := $$(USER_GUIDE_BUILD_DIR)/user-guide_concat$(shell printf '%s' '$(patsubst USER_GUIDE%,%,$(1))' | tr '[:upper:]_' '[:lower:]-').md
$(1)_BODY_TEX     := $$(USER_GUIDE_BUILD_DIR)/user-guide_body$(shell printf '%s' '$(patsubst USER_GUIDE%,%,$(1))' | tr '[:upper:]_' '[:lower:]-').tex
$(1)_TEX          := $$(USER_GUIDE_BUILD_DIR)/user-guide_report$(shell printf '%s' '$(patsubst USER_GUIDE%,%,$(1))' | tr '[:upper:]_' '[:lower:]-').tex
$(1)_PDF_BUILT    := $$(USER_GUIDE_BUILD_DIR)/user-guide_report$(shell printf '%s' '$(patsubst USER_GUIDE%,%,$(1))' | tr '[:upper:]_' '[:lower:]-').pdf
$(1)_EXPANDED_DIR := $$(USER_GUIDE_BUILD_DIR)/expanded$(shell printf '%s' '$(patsubst USER_GUIDE%,%,$(1))' | tr '[:upper:]_' '[:lower:]-')
endef

$(eval $(call DEFINE_USER_GUIDE_VARS,USER_GUIDE_A4))
$(eval $(call DEFINE_USER_GUIDE_VARS,USER_GUIDE_B5))
$(eval $(call DEFINE_USER_GUIDE_VARS,USER_GUIDE_DARK_A4))
$(eval $(call DEFINE_USER_GUIDE_VARS,USER_GUIDE_DARK_B5))


# Source and Test Files
DOC_FILES := ../mkdocs.yml $(shell find $(DOCS_DIR) -name '*.md' -o -name '*.yml' -o -name '*.yaml' -o -name '*.lua' -o -name '*.tex') 

# Timestamp files
STAMP_DIR := .makefile-stamps
$(shell mkdir -p $(STAMP_DIR))

DOC_STAMP := $(STAMP_DIR)/docs-stamp

$(DOC_STAMP): $(DOC_FILES)
	@echo -e "$(DARKYELLOW)- Building documentation...$(NC)"
	@if poetry run mkdocs build -f ../mkdocs.yml -q; then \
		touch $(DOC_STAMP); \
		echo -e "$(GREEN)✓ Documentation built successfully$(NC)"; \
	else \
		echo -e "$(RED)✗ Error: Documentation build failed$(NC)"; \
		exit 1; \
	fi

# ============================================================================================
# Help Target
# ============================================================================================

# Defines a function to print a section of the help message.
# Arg 1: Section title
# Arg 2: A pipe-separated list of targets for the section
define print_section
	@echo ""
	@echo -e "$(BRIGHTCYAN)$1:$(NC)"
	@grep -E '^($(2)):.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(BLUE)%-22s$(NC) %s\n", $$1, $$2}' | sort
endef

help: ## Show this help message
	@echo -e "$(DARKYELLOW)OneSelect - Makefile Targets$(NC)"
	@$(call print_section,Documentation,docs|pdf-docs)
	@$(call print_section,Container,docs-container-build|docs-container-start|docs-container-stop|docs-container-restart|docs-container-status|docs-container-logs)
	@echo ""


# ============================================================================================
# Documentation Targets
# ============================================================================================
docs: $(DOC_STAMP) ## Build the HTML project documentation with MkDocs
	@:

pdfs: pdf-docs ## Build all PDF documentation variants in parallel
	@:

pdf-docs:  ## Build the user guide in all PDF variants (A4 light/dark, B5 light/dark) in parallel
	@rm -rf $(USER_GUIDE_BUILD_DIR)  # Clean build dir to ensure no stale files interfere
	@rm $(DIST_DIR)/$(PROJECT)_user_guide-*.pdf 2>/dev/null || true  # Remove old PDFs to prevent confusion
	@$(MAKE) -j4 $(USER_GUIDE_A4_PDF) $(USER_GUIDE_DARK_A4_PDF) $(USER_GUIDE_B5_PDF) $(USER_GUIDE_DARK_B5_PDF)
	@$(MAKE) -j4 cover  # Adjust PDFs with cover image after all variants are built

# ============================================================================================
# Macro: BUILD_USER_GUIDE_PDF
# Shared recipe for every User Guide PDF variant. Call via $(eval $(call BUILD_USER_GUIDE_PDF,...)).
# $(1) = variable name prefix (e.g. USER_GUIDE, USER_GUIDE_B5)
# $(2) = paper format: a4 or b5  (passed to the pandoc Lua filter)
# Note: Make variables used inside recipe lines are escaped as $$(VAR) so they survive
# $(call) expansion and are resolved at recipe-execution time.
# ============================================================================================
define BUILD_USER_GUIDE_PDF
$$($1_PDF): $$(USER_GUIDE_MD_SOURCES) $$(USER_GUIDE_PDF_DEPS) $$($1_TEMPLATE) $$(USER_GUIDE_LUA_FILTER)
	@echo -e "$(DARKYELLOW)- Updating version number $(BRIGHTCYAN)v$(VERSION)$(DARKYELLOW) in LaTeX template $$(BRIGHTCYAN)\"$$(notdir $$($1_TEMPLATE))\"$(DARKYELLOW)...$(NC)"
	@sed -i.bak -E 's/Version: [0-9.]+/Version: $(VERSION)/g' $$($1_TEMPLATE)
	@rm -f $$($1_TEMPLATE).bak
	@echo -e "$$(DARKYELLOW)- Building $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(DARKYELLOW) via LaTeX report pipeline...$$(NC)"
	@mkdir -p $$(USER_GUIDE_BUILD_DIR)
	@echo -e "$$(DARKYELLOW)  - Expanding shell command outputs in markdown sources...$$(NC)"
	@mkdir -p $$($1_EXPANDED_DIR)
	@poetry run python $$(SCRIPTS_DIR)/expand-shell-outputs.py \
		--output-dir $$($1_EXPANDED_DIR) \
		--cwd $$(SCRIPTS_DIR)/.. \
		--format $(2) \
		$$(USER_GUIDE_MD_SOURCES)
	@echo -e "$$(DARKYELLOW)  - Concatenating markdown sources...$$(NC)"
	@cat $$(foreach f,$$(USER_GUIDE_MD_SOURCES),$$($1_EXPANDED_DIR)/$$(notdir $$f)) > $$($1_CONCAT_MD)
	@echo -e "$$(DARKYELLOW)  - Converting concatenated markdown to LaTeX body...$$(NC)"
	@pandoc --from=markdown --to=latex --top-level-division=chapter --syntax-highlighting=none $$(USER_GUIDE_LUA_FILTER_FLAGS) --metadata paper_format=$(2) $$($1_CONCAT_MD) -o $$($1_BODY_TEX)
	@sed -i.bak 's/\\def\\LTcaptype{none}/\\def\\LTcaptype{table}/g' $$($1_BODY_TEX)
	@rm -f $$($1_BODY_TEX).bak
	@echo -e "$$(DARKYELLOW)  - Injecting body into handcrafted LaTeX template $$(BRIGHTCYAN)\"$$(notdir $$($1_TEMPLATE))\"$(DARKYELLOW) ...$$(NC)"
	@awk -v body="$$($1_BODY_TEX)" '\
		/%%__USER_GUIDE_CONTENT__%%/ { while ((getline line < body) > 0) print line; close(body); inserted=1; next } \
		{ print } \
		END { if (!inserted) { print "Template placeholder %%__USER_GUIDE_CONTENT__%% not found" > "/dev/stderr"; exit 2 } }' \
		$$($1_TEMPLATE) > $$($1_TEX)
	@echo -e "$$(DARKYELLOW)  - Compiling $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(DARKYELLOW) with xelatex (2 passes for references/TOC)...$$(NC)"
	@xelatex -interaction=nonstopmode -halt-on-error -output-directory $$(USER_GUIDE_BUILD_DIR) $$($1_TEX) \
		> $$($1_PDF_BUILT:.pdf=-xelatex-pass1.log) 2>&1 \
		|| { echo -e "$$(RED)✗ xelatex pass 1 failed for $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(RED).$$(NC)" >&2; \
		     echo -e "$$(RED)  Last 30 lines of $$($1_PDF_BUILT:.pdf=-xelatex-pass1.log):$$(NC)" >&2; \
		     tail -30 $$($1_PDF_BUILT:.pdf=-xelatex-pass1.log) >&2; exit 1; }
	@xelatex -interaction=nonstopmode -halt-on-error -output-directory $$(USER_GUIDE_BUILD_DIR) $$($1_TEX) \
		> $$($1_PDF_BUILT:.pdf=-xelatex-pass2.log) 2>&1 \
		|| { echo -e "$$(RED)✗ xelatex pass 2 failed for $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(RED).$$(NC)" >&2; \
		     echo -e "$$(RED)  Last 30 lines of $$($1_PDF_BUILT:.pdf=-xelatex-pass2.log):$$(NC)" >&2; \
		     tail -30 $$($1_PDF_BUILT:.pdf=-xelatex-pass2.log) >&2; exit 1; }
	@cp $$($1_PDF_BUILT) $$($1_PDF)
	@echo -e "$$(GREEN)✓ User guide PDF built: $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(GREEN)$$(NC)"
endef


# ============================================================================================
# User Guide PDF targets — A4 light, A4 dark, B5 light, B5 dark
# ============================================================================================
$(eval $(call BUILD_USER_GUIDE_PDF,USER_GUIDE_A4,a4))
$(eval $(call BUILD_USER_GUIDE_PDF,USER_GUIDE_B5,b5))
$(eval $(call BUILD_USER_GUIDE_PDF,USER_GUIDE_DARK_A4,a4))
$(eval $(call BUILD_USER_GUIDE_PDF,USER_GUIDE_DARK_B5,b5))


# Echo all User Guide Variables for debugging Makefile variable generation. 
# $(info USER_GUIDE_PDF_DEPS: $(USER_GUIDE_PDF_DEPS))
# $(info USER_GUIDE_MD_SOURCES: $(USER_GUIDE_MD_SOURCES))
# $(info USER_GUIDE_LUA_FILTER: $(USER_GUIDE_LUA_FILTER))
# $(info USER_GUIDE_BUILD_DIR: $(USER_GUIDE_BUILD_DIR))

# $(info USER_GUIDE_DARK_B5_TEMPLATE: $(USER_GUIDE_DARK_B5_TEMPLATE))
# $(info USER_GUIDE_DARK_B5_PDF: $(USER_GUIDE_DARK_B5_PDF))
# $(info USER_GUIDE_DARK_B5_CONCAT_MD: $(USER_GUIDE_DARK_B5_CONCAT_MD))
# $(info USER_GUIDE_DARK_B5_BODY_TEX: $(USER_GUIDE_DARK_B5_BODY_TEX))
# $(info USER_GUIDE_DARK_B5_TEX: $(USER_GUIDE_DARK_B5_TEX))
# $(info USER_GUIDE_DARK_B5_PDF_BUILT: $(USER_GUIDE_DARK_B5_PDF_BUILT))

# ============================================================================================
# Adjust the User Guide PDF by adding cover image to the user guide PDFs. 
# This is done as a separate step after PDF generation to avoid triggering a full rebuild of 
# the PDF when the cover image changes, and to allow parallel builds of all PDF variants 
# before applying the cover.
# ============================================================================================
USER_GUIDE_COVER_IMAGE := ../assets/cover-user-guide.png
USER_GUIDE_B5_PDF := ../dist/$(PROJECT)_user_guide-b5-$(VERSION).pdf
USER_GUIDE_DARK_B5_PDF := ../dist/$(PROJECT)_user_guide-dark-b5-$(VERSION).pdf
USER_GUIDE_A4_PDF := ../dist/$(PROJECT)_user_guide-a4-$(VERSION).pdf
USER_GUIDE_DARK_A4_PDF := ../dist/$(PROJECT)_user_guide-dark-a4-$(VERSION).pdf

cover: cover-b5-light cover-b5-dark cover-a4-light cover-a4-dark ## Adjust all user guide PDFs with cover image in parallel
	@:

cover-b5-light: ## Adjust the PDF by adding cover image
	@echo -e "$(DARKYELLOW)- Adjusting $(BRIGHTCYAN)\"$(notdir $(USER_GUIDE_B5_PDF))\"$(DARKYELLOW) with cover image...$(NC)"
	@../scripts/mkcover.sh -q --dpi 300 $(USER_GUIDE_COVER_IMAGE) $(USER_GUIDE_B5_PDF)
	@echo -e "$(GREEN)✓ PDF $(BRIGHTCYAN)\"$(notdir $(USER_GUIDE_B5_PDF))\"$(GREEN) adjusted with cover image$(NC)"

cover-b5-dark: ## Adjust the PDF by adding cover image
	@echo -e "$(DARKYELLOW)- Adjusting $(BRIGHTCYAN)\"$(notdir $(USER_GUIDE_DARK_B5_PDF))\"$(DARKYELLOW) with cover image...$(NC)"
	@../scripts/mkcover.sh -q --dpi 300 $(USER_GUIDE_COVER_IMAGE) $(USER_GUIDE_DARK_B5_PDF)
	@echo -e "$(GREEN)✓ PDF $(BRIGHTCYAN)\"$(notdir $(USER_GUIDE_DARK_B5_PDF))\"$(GREEN) adjusted with cover image$(NC)"

cover-a4-light: ## Adjust the PDF by adding cover image
	@echo -e "$(DARKYELLOW)- Adjusting $(BRIGHTCYAN)\"$(notdir $(USER_GUIDE_A4_PDF))\"$(DARKYELLOW) with cover image...$(NC)"
	@../scripts/mkcover.sh -q --dpi 300 $(USER_GUIDE_COVER_IMAGE) $(USER_GUIDE_A4_PDF)
	@echo -e "$(GREEN)✓ PDF $(BRIGHTCYAN)\"$(notdir $(USER_GUIDE_A4_PDF))\"$(GREEN) adjusted with cover image$(NC)"

cover-a4-dark: ## Adjust the PDF by adding cover image
	@echo -e "$(DARKYELLOW)- Adjusting $(BRIGHTCYAN)\"$(notdir $(USER_GUIDE_DARK_A4_PDF))\"$(DARKYELLOW) with cover image...$(NC)"
	@../scripts/mkcover.sh -q --dpi 300 $(USER_GUIDE_COVER_IMAGE) $(USER_GUIDE_DARK_A4_PDF)
	@echo -e "$(GREEN)✓ PDF $(BRIGHTCYAN)\"$(notdir $(USER_GUIDE_DARK_A4_PDF))\"$(GREEN) adjusted with cover image$(NC)"


# ============================================================================================
# Doc-server
# ============================================================================================
serve: docs ## Serve the project documentation locally with MkDocs
	@echo -e "$(BLUE)Serving documentation on http://localhost:$(DOCS_PORT)$(NC)"
	@poetry run mkdocs serve -f ../mkdocs.yml -a localhost:$(DOCS_PORT)


# ============================================================================================
# Container handling
# ============================================================================================
container-engine-check:
	@if [ "$(NO_CONTAINER_ENGINE)" = "yes" ]; then \
        echo -e "$(YELLOW)⚠️  Warning: No container engine detected. Skipping container operation. Please start Podman or Docker.$(NC)"; \
        exit 1; \
    fi

docs-container-build: | container-engine-check ## Build the containerized documentation image
	@MCPROJSIM_DOCS_PORT=$(DOCS_PORT) $(DOCS_CONTAINER_SCRIPT) build 

docs-container-start: | container-engine-check ## Start the containerized documentation server
	@MCPROJSIM_DOCS_PORT=$(DOCS_PORT) $(DOCS_CONTAINER_SCRIPT) start

docs-container-stop: | container-engine-check ## Stop the containerized documentation server
	@MCPROJSIM_DOCS_PORT=$(DOCS_PORT) $(DOCS_CONTAINER_SCRIPT) stop

docs-container-restart: | container-engine-check ## Restart the containerized documentation server
	@MCPROJSIM_DOCS_PORT=$(DOCS_PORT) $(DOCS_CONTAINER_SCRIPT) restart

docs-container-status: | container-engine-check ## Show status for the containerized documentation server
	@MCPROJSIM_DOCS_PORT=$(DOCS_PORT) $(DOCS_CONTAINER_SCRIPT) status

docs-container-logs: | container-engine-check ## Show logs for the containerized documentation server
	@MCPROJSIM_DOCS_PORT=$(DOCS_PORT) $(DOCS_CONTAINER_SCRIPT) logs --follow

docs-deploy: ## Build and deploy documentation to GitHub Pages
	@echo -e "$(DARKYELLOW)- Deploying documentation to GitHub Pages...$(NC)"
	@if poetry run mkdocs gh-deploy --force; then \
		echo -e "$(GREEN)✓ Documentation deployed successfully$(NC)"; \
	else \
		echo -e "$(RED)✗ Error: Documentation deployment failed$(NC)"; \
		exit 1; \
	fi

# EOF

