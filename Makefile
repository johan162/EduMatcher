# Makefile for building EduMatcher Documentation (user-guide,training-guide,chapters,site) and related artifacts.
# For mermaid rendering we use a mermaid Node filter, installed once in a
# shared top-level tools directory used by all doc builds.
# npm install --prefix ../build-tools --save-dev mermaid-filter @mermaid-js/mermaid-cli

NODE_TOOLS_DIR := ../build-tools
NODE_MODULES_PATH := $(NODE_TOOLS_DIR)/node_modules
# Vendored, cache-enabled wrapper around the npm mermaid-filter package (see
# scripts/mermaid-filter-cached.js for why this isn't the installed binary).
MERMAID_FILTER := ../scripts/mermaid-filter-cached.js
MERMAID_FILTER_FORMAT ?= pdf
MERMAID_FILTER_WIDTH ?= 600

# Display width of every figure in the EPUB (a CSS max-width percentage,
# substituted into epub.css). Figures are Mermaid diagrams rendered to SVG
# at a fixed pixel width (MERMAID_FILTER_WIDTH); this is the separate knob
# that controls how large they then display on the page. Lower it if
# diagrams still run too large on a given e-reader.
EPUB_FIGURE_MAX_WIDTH ?= 85%

UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
    PUPPETEER_EXECUTABLE_PATH ?= /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
	SED_INPLACE := -i ''
else
    PUPPETEER_EXECUTABLE_PATH ?= /usr/bin/google-chrome
	SED_INPLACE := -i
endif

.PHONY: docs pdf-docs pdf-training chapters-pdf-a4 epub-docs epub-docs-verify clean really-clean serve check-latex-engine \
	cover-user-guide cover-training-guide covers \
	docs-container-build docs-container-start docs-container-stop docs-container-restart docs-container-status docs-container-logs \
	help _covers covers cover-user-guide cover-training-guide

# Makefile itself as a dependency to ensure it is re-evaluated when changed
# NOTE: This requires GNU Make 4.3+ and MacOS ships with vGNU Make 3.81 due to licensing issues
# and then this line will be silently ignored.´unless you have upgrade make via brew or similar.	
.EXTRA_PREREQS := $(firstword $(MAKEFILE_LIST))

# Make behavior
.DEFAULT_GOAL := pdf-docs

# Get full path to bash
SHELL := $(shell which bash)
.SHELLFLAGS := -euo pipefail -c

# LaTeX engine configuration (macOS TeX binaries commonly live under /Library/TeX/texbin)
LATEX_ENGINE ?= xelatex
TEXBIN_FALLBACK := /Library/TeX/texbin

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
ifeq ($(POETRY),)
    $(error poetry not found. MacOS Install with: pip install poetry)
endif

# ============================================================================================
# Variable configurations
# ============================================================================================

# Directories
DOCS_DIR := .
DIST_DIR := ./dist
BUILD_DIR := .build
SCRIPTS_DIR := ../scripts
SITE_DIR := ../site
ASSETS_DIR := $(DOCS_DIR)/assets


# Timestamp files
STAMP_DIR := .makefile-stamps
$(shell mkdir -p $(STAMP_DIR))
DOC_STAMP := $(STAMP_DIR)/docs-stamp

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
TRAINING_GUIDE_BUILD_DIR := $(BUILD_DIR)/training-guide

# User guide PDF output paths and templates
# Variant-specific paths are derived by DEFINE_USER_GUIDE_VARS below.
# USER_GUIDE_LUA_FILTER is shared across all variants.
USER_GUIDE_LUA_FILTER := $(DOCS_DIR)/user-guide/pagebreaks.lua
USER_GUIDE_ADMONITIONS_LUA_FILTER := $(DOCS_DIR)/admonitions.lua
USER_GUIDE_LUA_FILTER_FLAGS := --lua-filter $(USER_GUIDE_LUA_FILTER) --lua-filter $(USER_GUIDE_ADMONITIONS_LUA_FILTER)

# Markdown sources that are concatenated into the User Guide PDF body.
# Keep this list markdown-only; non-markdown assets are tracked separately
# via USER_GUIDE_PDF_DEPS so they trigger rebuilds without polluting content.
USER_GUIDE_MD_SOURCES := \
	$(sort $(wildcard $(DOCS_DIR)/user-guide/[0-9][0-9][0-9]-*.md))

# $(info USER_GUIDE_MD_SOURCES: $(USER_GUIDE_MD_SOURCES))

# Non-markdown assets that should still trigger a rebuild when changed.
USER_GUIDE_TEMPLATE_DEPS := \
	$(DOCS_DIR)/user-guide/template_a4.tex.in \
	$(DOCS_DIR)/user-guide/template_dark_a4.tex.in \
	$(DOCS_DIR)/user-guide/template_b5.tex.in \
	$(DOCS_DIR)/user-guide/template_dark_b5.tex.in

# User Guide EPUB output path, source CSS template, and generated CSS
# (EPUB_FIGURE_MAX_WIDTH is substituted into the latter, same @@VAR@@
# pattern as the LaTeX templates' @@VERSION@@).
USER_GUIDE_EPUB     := $(DIST_DIR)/$(PROJECT)_user_guide-$(VERSION).epub
EPUB_CSS_IN         := $(DOCS_DIR)/user-guide/epub.css.in
EPUB_CSS            := $(USER_GUIDE_BUILD_DIR)/epub.css
EPUB_CONCAT_MD      := $(USER_GUIDE_BUILD_DIR)/user-guide_concat-epub.md
EPUB_EXPANDED_DIR   := $(USER_GUIDE_BUILD_DIR)/expanded-epub
EPUB_COVER          := $(ASSETS_DIR)/cover-user-guide.png
EPUB_DEPS           := \
	$(DOCS_DIR)/user-guide/pagebreaks.lua \
	$(DOCS_DIR)/admonitions.lua \
	$(EPUB_CSS_IN)

TRAINING_GUIDE_MD_SOURCES := \
	$(sort $(wildcard $(DOCS_DIR)/training/[0-9][0-9][0-9]-*.md))

TRAINING_GUIDE_TEMPLATE_DEPS := \
	$(DOCS_DIR)/training/template_a4.tex.in \
	$(DOCS_DIR)/training/template_dark_a4.tex.in \
	$(DOCS_DIR)/training/template_b5.tex.in \
	$(DOCS_DIR)/training/template_dark_b5.tex.in \
	$(DOCS_DIR)/assets/cover-training-guide.png

CONCEPTS_MD_SOURCES := \
	$(sort $(wildcard $(DOCS_DIR)/concepts/[0-9][0-9]-*.md))

# $(info CONCEPTS_MD_SOURCES: $(CONCEPTS_MD_SOURCES))

ARCHITECTURE_MD_SOURCES := \
	$(sort $(wildcard $(DOCS_DIR)/architecture/[0-9][0-9]-*.md))

# $(info ARCHITECTURE_MD_SOURCES: $(ARCHITECTURE_MD_SOURCES))

DEVELOPER_MD_SOURCES := \
	$(sort $(wildcard $(DOCS_DIR)/developer/[0-9][0-9]-*.md))

# $(info DEVELOPER_MD_SOURCES: $(DEVELOPER_MD_SOURCES))

# Source and Test Files for building HTML documentation
HTML_DOCS_DEPS := ../mkdocs.yml $(USER_GUIDE_MD_SOURCES) $(TRAINING_GUIDE_MD_SOURCES) $(CONCEPTS_MD_SOURCES) $(ARCHITECTURE_MD_SOURCES) $(DEVELOPER_MD_SOURCES)

# $(info HTML_DOCS_DEPS: $(HTML_DOCS_DEPS))

# ============================================================================================
# Timestamp file targets
# ============================================================================================

$(DOC_STAMP): $(HTML_DOCS_DEPS)
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
	@$(call print_section,Documentation,docs|pdf-docs|epub-docs|epub-docs-verify|chapters-pdf-a4|exchange-intro)
	@$(call print_section,Container,docs-container-build|docs-container-start|docs-container-stop|docs-container-restart|docs-container-status|docs-container-logs)
	@echo ""


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
$(1)_TEMPLATE     := $$(DOCS_DIR)/user-guide/template$(shell printf '%s' '$(patsubst USER_GUIDE%,%,$(1))' | tr '[:upper:]' '[:lower:]').tex
$(1)_PDF          := $$(DIST_DIR)/$$(PROJECT)_user_guide$(shell printf '%s' '$(patsubst USER_GUIDE%,%,$(1))' | tr '[:upper:]_' '[:lower:]_')-$$(VERSION).pdf
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

# ============================================================================================
# Macro: DEFINE_TRAINING_GUIDE_VARS
# Derives all variant-specific file-path variables from the base name alone.
# $(1) = TRAINING_GUIDE_A4 | TRAINING_GUIDE_B5 | TRAINING_GUIDE_DARK_A4 | TRAINING_GUIDE_DARK_B5
# ============================================================================================
define DEFINE_TRAINING_GUIDE_VARS
$(1)_TEMPLATE     := $$(DOCS_DIR)/training/template$(shell printf '%s' '$(patsubst TRAINING_GUIDE%,%,$(1))' | tr '[:upper:]' '[:lower:]').tex
$(1)_PDF          := $$(DIST_DIR)/$$(PROJECT)_training-guide$(shell printf '%s' '$(patsubst TRAINING_GUIDE%,%,$(1))' | tr '[:upper:]_' '[:lower:]_')-$$(VERSION).pdf
$(1)_CONCAT_MD    := $$(TRAINING_GUIDE_BUILD_DIR)/training-guide_concat$(shell printf '%s' '$(patsubst TRAINING_GUIDE%,%,$(1))' | tr '[:upper:]_' '[:lower:]-').md
$(1)_BODY_TEX     := $$(TRAINING_GUIDE_BUILD_DIR)/training-guide_body$(shell printf '%s' '$(patsubst TRAINING_GUIDE%,%,$(1))' | tr '[:upper:]_' '[:lower:]-').tex
$(1)_TEX          := $$(TRAINING_GUIDE_BUILD_DIR)/training-guide_report$(shell printf '%s' '$(patsubst TRAINING_GUIDE%,%,$(1))' | tr '[:upper:]_' '[:lower:]-').tex
$(1)_PDF_BUILT    := $$(TRAINING_GUIDE_BUILD_DIR)/training-guide_report$(shell printf '%s' '$(patsubst TRAINING_GUIDE%,%,$(1))' | tr '[:upper:]_' '[:lower:]-').pdf
$(1)_EXPANDED_DIR := $$(TRAINING_GUIDE_BUILD_DIR)/expanded$(shell printf '%s' '$(patsubst TRAINING_GUIDE%,%,$(1))' | tr '[:upper:]_' '[:lower:]-')
endef

$(eval $(call DEFINE_TRAINING_GUIDE_VARS,TRAINING_GUIDE_A4))
$(eval $(call DEFINE_TRAINING_GUIDE_VARS,TRAINING_GUIDE_B5))
$(eval $(call DEFINE_TRAINING_GUIDE_VARS,TRAINING_GUIDE_DARK_A4))
$(eval $(call DEFINE_TRAINING_GUIDE_VARS,TRAINING_GUIDE_DARK_B5))


# ============================================================================================
# Macro: BUILD_USER_GUIDE_PDF
# Shared recipe for every User Guide PDF variant. Call via $(eval $(call BUILD_USER_GUIDE_PDF,...)).
# $(1) = variable name prefix (e.g. USER_GUIDE, USER_GUIDE_B5)
# $(2) = paper format: a4 or b5  (passed to the pandoc Lua filter)
# Note: Make variables used inside recipe lines are escaped as $$(VAR) so they survive
# $(call) expansion and are resolved at recipe-execution time.
# # @sed -i.bak -E 's/Version: [0-9]+(\.[0-9]+)*(rc[0-9]{1,2})?/Version: $(VERSION)/g' $$($1_TEMPLATE)
# $$(USER_GUIDE_PDF_DEPS) $$(USER_GUIDE_LUA_FILTER)
# ============================================================================================
define BUILD_USER_GUIDE_PDF
$$($1_PDF): $$(USER_GUIDE_MD_SOURCES) $$(USER_GUIDE_LUA_FILTER) $$(USER_GUIDE_ADMONITIONS_LUA_FILTER) $$(USER_GUIDE_TEMPLATE_DEPS) | $(NODE_MODULES_PATH) $(DIST_DIR) $(BUILD_DIR)
	@echo -e "$(DARKYELLOW)- Updating version number $(BRIGHTCYAN)v$(VERSION)$(DARKYELLOW) in LaTeX template $$(BRIGHTCYAN)\"$$(notdir $$($1_TEMPLATE))\"$(DARKYELLOW)...$(NC)"
	@sed -e "s/@@VERSION@@/v$(VERSION)/g" $$($1_TEMPLATE).in > $$($1_TEMPLATE)
	@rm -f $$($1_TEMPLATE).bak
	@echo -e "$$(DARKYELLOW)- Building $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(DARKYELLOW) via LaTeX report pipeline...$$(NC)"
	@mkdir -p $$(USER_GUIDE_BUILD_DIR)
	@echo -e "$$(DARKYELLOW)  - Expanding shell command outputs in user-guide markdown sources...$$(NC)"
	@mkdir -p $$($1_EXPANDED_DIR)
	@poetry run python $$(SCRIPTS_DIR)/expand-shell-outputs.py \
		--output-dir $$($1_EXPANDED_DIR) \
		--cwd $$(SCRIPTS_DIR)/.. \
		--format $(2) \
		$$(USER_GUIDE_MD_SOURCES)
	@echo -e "$$(DARKYELLOW)  - Concatenating user-guide markdown sources...$$(NC)"
	@awk 'FNR==1 && NR!=1{print ""; print ""}1' $$(foreach f,$$(USER_GUIDE_MD_SOURCES),$$($1_EXPANDED_DIR)/$$(notdir $$f)) > $$($1_CONCAT_MD)
	@echo -e "$$(DARKYELLOW)  - Converting user-guide markdown to LaTeX body...$$(NC)"
	@mkdir -p $$($1_EXPANDED_DIR)/.mermaid-img
	@PUPPETEER_EXECUTABLE_PATH="$(PUPPETEER_EXECUTABLE_PATH)" \
	MERMAID_FILTER_FORMAT="$(MERMAID_FILTER_FORMAT)" \
	MERMAID_FILTER_WIDTH="$(MERMAID_FILTER_WIDTH)" \
	MERMAID_FILTER_LOC="$$($1_EXPANDED_DIR)/.mermaid-img" \
	pandoc --from=markdown --to=latex --top-level-division=chapter --syntax-highlighting=none --filter "$(MERMAID_FILTER)" $$(USER_GUIDE_LUA_FILTER_FLAGS) --metadata paper_format=$(2) $$($1_CONCAT_MD) -o $$($1_BODY_TEX)
	@sed -i.bak 's/\\def\\LTcaptype{none}/\\def\\LTcaptype{table}/g' $$($1_BODY_TEX)
	@rm -f $$($1_BODY_TEX).bak
	@echo -e "$$(DARKYELLOW)  - Injecting user-guide body into LaTeX template $$(BRIGHTCYAN)\"$$(notdir $$($1_TEMPLATE))\"$(DARKYELLOW) ...$$(NC)"
	@awk -v body="$$($1_BODY_TEX)" '\
		/%%__USER_GUIDE_CONTENT__%%/ { while ((getline line < body) > 0) print line; close(body); inserted=1; next } \
		{ print } \
		END { if (!inserted) { print "Template placeholder %%__USER_GUIDE_CONTENT__%% not found" > "/dev/stderr"; exit 2 } }' \
		$$($1_TEMPLATE) > $$($1_TEX)
	@echo -e "$$(DARKYELLOW)  - Compiling $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(DARKYELLOW) with $$(BRIGHTCYAN)\"$(LATEX_ENGINE)\"$$(DARKYELLOW) (2 passes for references/TOC)...$$(NC)"
	@PATH="$(PATH):$(TEXBIN_FALLBACK)" $(LATEX_ENGINE) -interaction=nonstopmode -halt-on-error -output-directory $$(USER_GUIDE_BUILD_DIR) $$($1_TEX) \
		> $$($1_PDF_BUILT:.pdf=-xelatex-pass1.log) 2>&1 \
		|| { echo -e "$$(RED)✗ xelatex pass 1 failed for $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(RED).$$(NC)" >&2; \
		     echo -e "$$(RED)  Last 30 lines of $$($1_PDF_BUILT:.pdf=-xelatex-pass1.log):$$(NC)" >&2; \
		     tail -30 $$($1_PDF_BUILT:.pdf=-xelatex-pass1.log) >&2; exit 1; }
	@PATH="$(PATH):$(TEXBIN_FALLBACK)" $(LATEX_ENGINE) -interaction=nonstopmode -halt-on-error -output-directory $$(USER_GUIDE_BUILD_DIR) $$($1_TEX) \
		> $$($1_PDF_BUILT:.pdf=-xelatex-pass2.log) 2>&1 \
		|| { echo -e "$$(RED)✗ xelatex pass 2 failed for $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(RED).$$(NC)" >&2; \
		     echo -e "$$(RED)  Last 30 lines of $$($1_PDF_BUILT:.pdf=-xelatex-pass2.log):$$(NC)" >&2; \
		     tail -30 $$($1_PDF_BUILT:.pdf=-xelatex-pass2.log) >&2; exit 1; }
	@cp $$($1_PDF_BUILT) $$($1_PDF)
	@rm -f $$($1_TEMPLATE)
	@echo -e "$$(GREEN)✓ User guide PDF built: $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(GREEN)$$(NC)"
endef

# ============================================================================================
# User Guide PDF targets — A4 light, A4 dark, B5 light, B5 dark
# ============================================================================================
$(eval $(call BUILD_USER_GUIDE_PDF,USER_GUIDE_A4,a4))
$(eval $(call BUILD_USER_GUIDE_PDF,USER_GUIDE_B5,b5))
$(eval $(call BUILD_USER_GUIDE_PDF,USER_GUIDE_DARK_A4,a4))
$(eval $(call BUILD_USER_GUIDE_PDF,USER_GUIDE_DARK_B5,b5))

# ============================================================================================
# User Guide EPUB target
#
# One EPUB3 book, reflowable, from the same USER_GUIDE_MD_SOURCES as the PDF
# variants above. No paper size and no LaTeX: expand-shell-outputs.py runs
# with --format a4 purely for the {{!cmd@A4:...}} truncation rules already in
# the sources (there is no @EPUB spec, so this is equivalent to full output;
# see epub.css.in's header for the figure-sizing knob).
#
# Mermaid diagrams render to SVG here (not PDF, as for the LaTeX builds) so
# they scale losslessly on any reader. The render cache in
# mermaid-filter-cached.js is keyed on diagram text only, so this shares the
# same cache directory as the PDF builds without collision (an svg and a pdf
# render of the same diagram are simply two different cache entries).
#
# --from=markdown-raw_html: several sources use bare angle-bracket
# placeholders in command syntax, e.g. `SYM=<symbol>`. Pandoc's default
# reader treats a bare <word> as a raw HTML tag pass-through; EPUB's strict
# XHTML parser then rejects the resulting document outright (unknown
# element). Disabling raw_html makes Pandoc escape "<" as "&lt;" instead, so
# these render as the literal text they are. See admonitions.lua's
# parse_embedded_markdown_from_codeblock, which mirrors this for embedded
# code inside admonitions.
# --mathml: default EPUB math conversion (texmath) fails silently on some
# of the more complex \text{...}-heavy formulas in this guide, falling back
# to visible raw TeX source. --mathml renders proper <math> markup instead.
# --no-highlight: Pandoc's syntax-highlighted code spans can emit duplicate
# element IDs across chapters, which EPUB (unlike the LaTeX/PDF path) treats
# as a hard validation error. This guide has no use for the highlighting.
# ============================================================================================
$(EPUB_CSS): $(EPUB_CSS_IN)
	@mkdir -p $(USER_GUIDE_BUILD_DIR)
	@sed -e "s/@@EPUB_FIGURE_MAX_WIDTH@@/$(EPUB_FIGURE_MAX_WIDTH)/g" $(EPUB_CSS_IN) > $(EPUB_CSS)

$(USER_GUIDE_EPUB): $(USER_GUIDE_MD_SOURCES) $(EPUB_DEPS) $(EPUB_CSS) | $(NODE_MODULES_PATH) $(DIST_DIR) $(BUILD_DIR)
	@echo -e "$(DARKYELLOW)- Building $(BRIGHTCYAN)\"$(notdir $(USER_GUIDE_EPUB))\"$(DARKYELLOW)...$(NC)"
	@mkdir -p $(USER_GUIDE_BUILD_DIR)
	@echo -e "$(DARKYELLOW)  - Expanding shell command outputs in user-guide markdown sources...$(NC)"
	@mkdir -p $(EPUB_EXPANDED_DIR)
	@poetry run python $(SCRIPTS_DIR)/expand-shell-outputs.py \
		--output-dir $(EPUB_EXPANDED_DIR) \
		--cwd $(SCRIPTS_DIR)/.. \
		--format a4 \
		$(USER_GUIDE_MD_SOURCES)
	@echo -e "$(DARKYELLOW)  - Concatenating user-guide markdown sources...$(NC)"
	@awk 'FNR==1 && NR!=1{print ""; print ""}1' $(foreach f,$(USER_GUIDE_MD_SOURCES),$(EPUB_EXPANDED_DIR)/$(notdir $f)) > $(EPUB_CONCAT_MD)
	@echo -e "$(DARKYELLOW)  - Converting user-guide markdown to EPUB3 via pandoc...$(NC)"
	@mkdir -p $(EPUB_EXPANDED_DIR)/.mermaid-img
	@PUPPETEER_EXECUTABLE_PATH="$(PUPPETEER_EXECUTABLE_PATH)" \
	MERMAID_FILTER_FORMAT="svg" \
	MERMAID_FILTER_WIDTH="$(MERMAID_FILTER_WIDTH)" \
	MERMAID_FILTER_LOC="$(EPUB_EXPANDED_DIR)/.mermaid-img" \
	pandoc --from=markdown-raw_html --to=epub3 \
		--mathml --syntax-highlighting=none \
		--toc --toc-depth=2 \
		--css $(EPUB_CSS) \
		--epub-cover-image=$(EPUB_COVER) \
		--metadata title="EduMatcher User Guide (v$(VERSION))" \
		--metadata author="J. Persson, 2026 v$(VERSION)" \
		--metadata lang=en-US \
		--filter "$(MERMAID_FILTER)" $(USER_GUIDE_LUA_FILTER_FLAGS) \
		$(EPUB_CONCAT_MD) -o $(USER_GUIDE_EPUB)
	@echo -e "$(GREEN)✓ User guide EPUB built: $(BRIGHTCYAN)\"$(notdir $(USER_GUIDE_EPUB))\"$(GREEN)$(NC)"

epub-docs: cover-user-guide $(USER_GUIDE_EPUB) ## Build the User Guide as a single reflowable EPUB3 book

epub-docs-verify: epub-docs ## Build the User Guide EPUB and validate it with epubcheck
	@echo -e "$(DARKYELLOW)- Validating $(BRIGHTCYAN)\"$(notdir $(USER_GUIDE_EPUB))\"$(DARKYELLOW) with epubcheck...$(NC)"
	@if ! command -v epubcheck >/dev/null 2>&1; then \
		echo -e "$(RED)✗ epubcheck not found in PATH.$(NC)" >&2; \
		echo -e "$(RED)  Install with: brew install epubcheck$(NC)" >&2; \
		exit 1; \
	fi
	@epubcheck $(USER_GUIDE_EPUB)
	@echo -e "$(GREEN)✓ EPUB validated: $(BRIGHTCYAN)\"$(notdir $(USER_GUIDE_EPUB))\"$(GREEN)$(NC)"

# ============================================================================================
# Macro: BUILD_TRAINING_GUIDE_PDF
# Shared recipe for every Training Guide PDF variant. Call via $(eval $(call BUILD_TRAINING_GUIDE_PDF,...)).
# ============================================================================================
define BUILD_TRAINING_GUIDE_PDF
$$($1_PDF): $$(TRAINING_GUIDE_MD_SOURCES) $$(TRAINING_GUIDE_TEMPLATE_DEPS) $$(USER_GUIDE_LUA_FILTER) $$(USER_GUIDE_ADMONITIONS_LUA_FILTER) | $(NODE_MODULES_PATH) $(DIST_DIR) $(BUILD_DIR)
	@echo -e "$(DARKYELLOW)- Updating version number $(BRIGHTCYAN)v$(VERSION)$(DARKYELLOW) in LaTeX template $$(BRIGHTCYAN)\"$$(notdir $$($1_TEMPLATE))\"$(DARKYELLOW)...$(NC)"
	@sed -e "s/@@VERSION@@/v$(VERSION)/g" $$($1_TEMPLATE).in > $$($1_TEMPLATE)
	@rm -f $$($1_TEMPLATE).bak
	@echo -e "$$(DARKYELLOW)- Building $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$$(DARKYELLOW) via LaTeX report pipeline...$$(NC)"
	@mkdir -p $$(TRAINING_GUIDE_BUILD_DIR)
	@echo -e "$$(DARKYELLOW)  - Expanding shell command outputs in training markdown sources...$$(NC)"
	@mkdir -p $$($1_EXPANDED_DIR)
	@poetry run python $$(SCRIPTS_DIR)/expand-shell-outputs.py \
		--output-dir $$($1_EXPANDED_DIR) \
		--cwd $$(SCRIPTS_DIR)/.. \
		--format $(2) \
		$$(TRAINING_GUIDE_MD_SOURCES)
	@echo -e "$$(DARKYELLOW)  - Concatenating training markdown sources...$$(NC)"
	@awk 'FNR==1 && NR!=1{print ""; print ""}1' $$(foreach f,$$(TRAINING_GUIDE_MD_SOURCES),$$($1_EXPANDED_DIR)/$$(notdir $$f)) > $$($1_CONCAT_MD)
	@echo -e "$$(DARKYELLOW)  - Converting concatenated training markdown to LaTeX body...$$(NC)"
	@mkdir -p $$($1_EXPANDED_DIR)/.mermaid-img
	@PUPPETEER_EXECUTABLE_PATH="$(PUPPETEER_EXECUTABLE_PATH)" \
	MERMAID_FILTER_FORMAT="$(MERMAID_FILTER_FORMAT)" \
	MERMAID_FILTER_WIDTH="$(MERMAID_FILTER_WIDTH)" \
	MERMAID_FILTER_LOC="$$($1_EXPANDED_DIR)/.mermaid-img" \
	pandoc --from=markdown --to=latex --top-level-division=chapter --syntax-highlighting=none --filter "$(MERMAID_FILTER)" $$(USER_GUIDE_LUA_FILTER_FLAGS) --metadata paper_format=$(2) $$($1_CONCAT_MD) -o $$($1_BODY_TEX)
	@sed -i.bak 's/\\def\\LTcaptype{none}/\\def\\LTcaptype{table}/g' $$($1_BODY_TEX)
	@rm -f $$($1_BODY_TEX).bak
	@echo -e "$$(DARKYELLOW)  - Injecting training body into LaTeX template $$(BRIGHTCYAN)\"$$(notdir $$($1_TEMPLATE))\"$$(DARKYELLOW) ...$$(NC)"
	@awk -v body="$$($1_BODY_TEX)" '\
		/%%__USER_GUIDE_CONTENT__%%/ { while ((getline line < body) > 0) print line; close(body); inserted=1; next } \
		{ print } \
		END { if (!inserted) { print "Template placeholder %%__USER_GUIDE_CONTENT__%% not found" > "/dev/stderr"; exit 2 } }' \
		$$($1_TEMPLATE) > $$($1_TEX)
	@echo -e "$$(DARKYELLOW)  - Compiling $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$$(DARKYELLOW) with $$(BRIGHTCYAN)\"$(LATEX_ENGINE)\"$$(DARKYELLOW) (2 passes for references/TOC)...$$(NC)"
	@PATH="$(PATH):$(TEXBIN_FALLBACK)" $(LATEX_ENGINE) -interaction=nonstopmode -halt-on-error -output-directory $$(TRAINING_GUIDE_BUILD_DIR) $$($1_TEX) \
		> $$($1_PDF_BUILT:.pdf=-xelatex-pass1.log) 2>&1 \
		|| { echo -e "$$(RED)✗ xelatex pass 1 failed for $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$$(RED).$$(NC)" >&2; \
		     echo -e "$$(RED)  Last 30 lines of $$($1_PDF_BUILT:.pdf=-xelatex-pass1.log):$$(NC)" >&2; \
		     tail -30 $$($1_PDF_BUILT:.pdf=-xelatex-pass1.log) >&2; exit 1; }
	@PATH="$(PATH):$(TEXBIN_FALLBACK)" $(LATEX_ENGINE) -interaction=nonstopmode -halt-on-error -output-directory $$(TRAINING_GUIDE_BUILD_DIR) $$($1_TEX) \
		> $$($1_PDF_BUILT:.pdf=-xelatex-pass2.log) 2>&1 \
		|| { echo -e "$$(RED)✗ xelatex pass 2 failed for $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$$(RED).$$(NC)" >&2; \
		     echo -e "$$(RED)  Last 30 lines of $$($1_PDF_BUILT:.pdf=-xelatex-pass2.log):$$(NC)" >&2; \
		     tail -30 $$($1_PDF_BUILT:.pdf=-xelatex-pass2.log) >&2; exit 1; }
	@cp $$($1_PDF_BUILT) $$($1_PDF)
	@rm -f $$($1_TEMPLATE)
	@echo -e "$$(GREEN)✓ Training guide PDF built: $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$$(GREEN)$$(NC)"
endef

$(eval $(call BUILD_TRAINING_GUIDE_PDF,TRAINING_GUIDE_A4,a4))
$(eval $(call BUILD_TRAINING_GUIDE_PDF,TRAINING_GUIDE_B5,b5))
$(eval $(call BUILD_TRAINING_GUIDE_PDF,TRAINING_GUIDE_DARK_A4,a4))
$(eval $(call BUILD_TRAINING_GUIDE_PDF,TRAINING_GUIDE_DARK_B5,b5))

# ============================================================================================
# Per-chapter User Guide PDFs (A4)
# Builds one PDF per markdown source under user-guide/NN-*.md using template_a4.tex.
# Each output carries the same base name as its source (e.g. 01-configuration.pdf).
# Output directory: $(DIST_DIR)/chapters-a4/
# ============================================================================================

CHAPTERS_A4_DIR   := $(DIST_DIR)/chapters-a4
CHAPTERS_A4_BUILD := $(USER_GUIDE_BUILD_DIR)/chapters-a4

# $(info USER_GUIDE_A4_TEMPLATE: $(USER_GUIDE_A4_TEMPLATE))

$(USER_GUIDE_A4_TEMPLATE): $(USER_GUIDE_A4_TEMPLATE).in
	@echo -e "$(DARKYELLOW)- Generating LaTeX template for A4 chapter PDFs from $(BRIGHTCYAN)$(USER_GUIDE_A4_TEMPLATE).in$(DARKYELLOW) ...$(NC)"
	@sed -e "s/@@VERSION@@/v$(VERSION)/g" $(USER_GUIDE_A4_TEMPLATE).in > $(USER_GUIDE_A4_TEMPLATE)

# $(1) = absolute or relative path to a single user-guide .md source file.
define BUILD_CHAPTER_PDF_A4
$$(CHAPTERS_A4_DIR)/$(notdir $(basename $(1))).pdf: \
		$(1) $$(USER_GUIDE_PDF_DEPS) | $$(USER_GUIDE_A4_TEMPLATE) \
		$$(CHAPTERS_A4_DIR) $(NODE_MODULES_PATH)
	@echo -e "$$(DARKYELLOW)- Building chapter PDF: $$(BRIGHTCYAN)$(notdir $(1))$$(DARKYELLOW)...$$(NC)"
	@mkdir -p $$(CHAPTERS_A4_BUILD)/$(notdir $(basename $(1)))/expanded/.mermaid-img
	@poetry run python $$(SCRIPTS_DIR)/expand-shell-outputs.py \
		--output-dir $$(CHAPTERS_A4_BUILD)/$(notdir $(basename $(1)))/expanded \
		--cwd $$(SCRIPTS_DIR)/.. \
		--format a4 \
		$(1)
	@PUPPETEER_EXECUTABLE_PATH="$(PUPPETEER_EXECUTABLE_PATH)" \
	MERMAID_FILTER_FORMAT="$(MERMAID_FILTER_FORMAT)" \
	MERMAID_FILTER_WIDTH="$(MERMAID_FILTER_WIDTH)" \
	MERMAID_FILTER_LOC="$$(CHAPTERS_A4_BUILD)/$(notdir $(basename $(1)))/expanded/.mermaid-img" \
	pandoc --from=markdown --to=latex --top-level-division=chapter \
		--syntax-highlighting=none \
		--filter "$(MERMAID_FILTER)" $$(USER_GUIDE_LUA_FILTER_FLAGS) \
		--metadata paper_format=a4 \
		$$(CHAPTERS_A4_BUILD)/$(notdir $(basename $(1)))/expanded/$(notdir $(1)) \
		-o $$(CHAPTERS_A4_BUILD)/$(notdir $(basename $(1)))/body.tex
	@sed -i.bak 's/\\def\\LTcaptype{none}/\\def\\LTcaptype{table}/g' \
		$$(CHAPTERS_A4_BUILD)/$(notdir $(basename $(1)))/body.tex
	@rm -f $$(CHAPTERS_A4_BUILD)/$(notdir $(basename $(1)))/body.tex.bak
	@awk -v body="$$(CHAPTERS_A4_BUILD)/$(notdir $(basename $(1)))/body.tex" '\
		/%%__USER_GUIDE_CONTENT__%%/ { while ((getline line < body) > 0) print line; close(body); inserted=1; next } \
		{ print } \
		END { if (!inserted) { print "Template placeholder %%__USER_GUIDE_CONTENT__%% not found" > "/dev/stderr"; exit 2 } }' \
		$$(USER_GUIDE_A4_TEMPLATE) > $$(CHAPTERS_A4_BUILD)/$(notdir $(basename $(1)))/report.tex
	@PATH="$(PATH):$(TEXBIN_FALLBACK)" $(LATEX_ENGINE) \
		-interaction=nonstopmode -halt-on-error \
		-output-directory $$(CHAPTERS_A4_BUILD)/$(notdir $(basename $(1))) \
		$$(CHAPTERS_A4_BUILD)/$(notdir $(basename $(1)))/report.tex \
		> $$(CHAPTERS_A4_BUILD)/$(notdir $(basename $(1)))/xelatex-pass1.log 2>&1 \
		|| { echo -e "$$(RED)✗ xelatex pass 1 failed: $(notdir $(basename $(1))).pdf$$(NC)" >&2; \
		     tail -30 $$(CHAPTERS_A4_BUILD)/$(notdir $(basename $(1)))/xelatex-pass1.log >&2; exit 1; }
	@PATH="$(PATH):$(TEXBIN_FALLBACK)" $(LATEX_ENGINE) \
		-interaction=nonstopmode -halt-on-error \
		-output-directory $$(CHAPTERS_A4_BUILD)/$(notdir $(basename $(1))) \
		$$(CHAPTERS_A4_BUILD)/$(notdir $(basename $(1)))/report.tex \
		> $$(CHAPTERS_A4_BUILD)/$(notdir $(basename $(1)))/xelatex-pass2.log 2>&1 \
		|| { echo -e "$$(RED)✗ xelatex pass 2 failed: $(notdir $(basename $(1))).pdf$$(NC)" >&2; \
		     tail -30 $$(CHAPTERS_A4_BUILD)/$(notdir $(basename $(1)))/xelatex-pass2.log >&2; exit 1; }
	@cp $$(CHAPTERS_A4_BUILD)/$(notdir $(basename $(1)))/report.pdf \
		$$(CHAPTERS_A4_DIR)/$(notdir $(basename $(1))).pdf
	@echo -e "$$(GREEN)✓ $(notdir $(basename $(1))).pdf → $$(BRIGHTCYAN)$$(CHAPTERS_A4_DIR)$$(GREEN)$$(NC)"
endef

$(foreach src,$(USER_GUIDE_MD_SOURCES),$(eval $(call BUILD_CHAPTER_PDF_A4,$(src))))

CHAPTERS_A4_PDFS := $(foreach src,$(USER_GUIDE_MD_SOURCES),$(CHAPTERS_A4_DIR)/$(notdir $(basename $(src))).pdf)

$(CHAPTERS_A4_DIR): | $(DIST_DIR)
	@mkdir -p $@

chapters-pdf-a4: check-latex-engine $(CHAPTERS_A4_PDFS) ## Build a separate A4 PDF for each user-guide chapter into $(DIST_DIR)/chapters-a4/
	@rm -f $(USER_GUIDE_A4_TEMPLATE)
	@echo -e "$(GREEN)✓ All $(words $(USER_GUIDE_MD_SOURCES)) chapter PDFs built in $(BRIGHTCYAN)$(CHAPTERS_A4_DIR)$(GREEN)$(NC)"
	
chapters-pdf-a4-bundle: chapters-pdf-a4  ## Build a zip bundle of all A4 chapter PDFs into $(DIST_DIR)	
	@zip -9 -j $(DIST_DIR)/$(PROJECT)_user_guide_as_chapters_a4_bundle-$(VERSION).zip $(CHAPTERS_A4_DIR)/*.pdf
	@echo -e "$(GREEN)✓ PDF bundle built: $(BRIGHTCYAN)\"$(PROJECT)_user_guide_as_chapters_a4_bundle-$(VERSION).zip\"$(GREEN)$(NC)"

chapters-pdf: chapters-pdf-a4-bundle  ## Build a zip bundle of all A4 chapter PDFs into $(DIST_DIR) (alias for chapters-pdf-a4-bundle)
	@:

# Echo all User Guide Variables for debugging Makefile variable generation. 
# $(info USER_GUIDE_PDF_DEPS: $(USER_GUIDE_PDF_DEPS))
# $(info USER_GUIDE_MD_SOURCES: $(USER_GUIDE_MD_SOURCES))
# $(info USER_GUIDE_LUA_FILTER: $(USER_GUIDE_LUA_FILTER))
# $(info USER_GUIDE_BUILD_DIR: $(USER_GUIDE_BUILD_DIR))

# $(info USER_GUIDE_DARK_B5_TEMPLATE: $(USER_GUIDE_DARK_B5_TEMPLATE))
# $(info USER_GUIDE_DARK_B5_PDF: $(USER_GUIDE_DARK_B5_PDF))
# $(info USER_GUIDE_A4_PDF: $(USER_GUIDE_A4_PDF))
# $(info USER_GUIDE_DARK_B5_CONCAT_MD: $(USER_GUIDE_DARK_B5_CONCAT_MD))
# $(info USER_GUIDE_DARK_B5_BODY_TEX: $(USER_GUIDE_DARK_B5_BODY_TEX))
# $(info USER_GUIDE_DARK_B5_TEX: $(USER_GUIDE_DARK_B5_TEX))
# $(info USER_GUIDE_DARK_B5_PDF_BUILT: $(USER_GUIDE_DARK_B5_PDF_BUILT))

$(NODE_MODULES_PATH): ../build-tools/package.json
	@echo -e "$(DARKYELLOW)- Installing shared Node dependencies for Mermaid rendering in $(NODE_TOOLS_DIR)...$(NC)"
	@mkdir -p $(NODE_TOOLS_DIR)
	@PUPPETEER_SKIP_DOWNLOAD=1 npm install --prefix $(NODE_TOOLS_DIR) --save-dev mermaid-filter @mermaid-js/mermaid-cli
	@touch $(NODE_MODULES_PATH)
	@echo -e "$(GREEN)✓ Shared Node dependencies installed$(NC)"

# ============================================================================================
# Documentation Targets
# ============================================================================================
linux-clean-puppeteer-cache:  ## Clean Puppeteer cache on Ubuntu (to free disk space)
	@echo -e "$(DARKYELLOW)- Cleaning Puppeteer cache on...$(NC)"
	@rm -rf ~/.cache/puppeteer
	@rm -rf build-tools/node_modules build-tools/package-lock.json
	@echo -e "$(GREEN)✓ Puppeteer cache cleaned$(NC)"

linux-pdf-docs: check-latex-engine  cover-user-guide  ## Build the user guide in all PDF variants (A4 light/dark, B5 light/dark) in parallel on Ubuntu
	@rm -rf $(USER_GUIDE_BUILD_DIR)  # Clean build dir to ensure no stale files interfere
	@rm -rf $(DIST_DIR)/$(PROJECT)_user-guide-*.pdf 2>/dev/null || true  # Remove old PDFs to prevent confusion
	@PUPPETEER_EXECUTABLE_PATH=/usr/bin/google-chrome $(MAKE) -j4 $(USER_GUIDE_A4_PDF) $(USER_GUIDE_DARK_A4_PDF) $(USER_GUIDE_B5_PDF) $(USER_GUIDE_DARK_B5_PDF)
	@zip -9 -j $(DIST_DIR)/$(PROJECT)_user_guide_bundle-$(VERSION).zip $(DIST_DIR)/$(PROJECT)_*-$(VERSION).pdf
	@echo -e "$(GREEN)✓ PDF bundle built: $(BRIGHTCYAN)\"$(PROJECT)_user_guide_bundle-$(VERSION).zip\"$(GREEN)$(NC)"

linux-docs: $(DOC_STAMP)  ## Build the HTML project documentation with MkDocs on Ubuntu
	@PUPPETEER_EXECUTABLE_PATH=/usr/bin/google-chrome $(MAKE) docs

docs: $(DOC_STAMP) ## Build the HTML project documentation with MkDocs
	@:

check-latex-engine:
	@if ! PATH="$(PATH):$(TEXBIN_FALLBACK)" command -v "$(LATEX_ENGINE)" >/dev/null 2>&1; then \
		echo -e "$(RED)✗ LaTeX engine '$(LATEX_ENGINE)' not found in PATH.$(NC)" >&2; \
		echo -e "$(RED)  Current PATH: $(PATH)$(NC)" >&2; \
		echo -e "$(RED)  Expected fallback path: $(TEXBIN_FALLBACK)$(NC)" >&2; \
		echo -e "$(RED)  Install/update TeX (e.g. MacTeX/BasicTeX) or run after upgrade completes.$(NC)" >&2; \
		exit 1; \
	fi

pdf-docs: check-latex-engine  cover-user-guide ## Build the user guide in all PDF variants (A4 light/dark, B5 light/dark) in parallel
	@rm -rf $(USER_GUIDE_BUILD_DIR)  # Clean build dir to ensure no stale files interfere
	@rm -rf $(DIST_DIR)/$(PROJECT)_user_guide-*.pdf 2>/dev/null || true  # Remove old PDFs to prevent confusion
	@$(MAKE) -j4 $(USER_GUIDE_A4_PDF) $(USER_GUIDE_DARK_A4_PDF) $(USER_GUIDE_B5_PDF) $(USER_GUIDE_DARK_B5_PDF)
	@zip -9 -j $(DIST_DIR)/$(PROJECT)_user_guide_bundle-$(VERSION).zip $(DIST_DIR)/$(PROJECT)_*-$(VERSION).pdf
	@echo -e "$(GREEN)✓ PDF bundle built: $(BRIGHTCYAN)\"$(PROJECT)_user_guide_bundle-$(VERSION).zip\"$(GREEN)$(NC)"

pdf-training: check-latex-engine  cover-training-guide ## Build the training guide in all PDF variants (A4 light/dark, B5 light/dark) in parallel
	@rm -rf $(TRAINING_GUIDE_BUILD_DIR)  # Clean build dir to ensure no stale files interfere
	@rm -rf $(DIST_DIR)/$(PROJECT)_training-guide-*.pdf 2>/dev/null || true  # Remove old PDFs to prevent confusion
	@$(MAKE) -j4 $(TRAINING_GUIDE_A4_PDF) $(TRAINING_GUIDE_DARK_A4_PDF) $(TRAINING_GUIDE_B5_PDF) $(TRAINING_GUIDE_DARK_B5_PDF)
	@echo -e "$(GREEN)✓ Training PDFs built under $(DIST_DIR)$(NC)"
	@zip -9 -j $(DIST_DIR)/$(PROJECT)_training-guide-bundle-$(VERSION).zip $(TRAINING_GUIDE_A4_PDF) $(TRAINING_GUIDE_DARK_A4_PDF) $(TRAINING_GUIDE_B5_PDF) $(TRAINING_GUIDE_DARK_B5_PDF)
	@echo -e "$(GREEN)✓ PDF bundle built: $(BRIGHTCYAN)\"$(PROJECT)_training-guide-bundle-$(VERSION).zip\"$(GREEN)$(NC)"



# If the VERSION have already before been injectyed in the cover-user-guide.html we avoid rebuilding the image
cover-user-guide:  ## Build the cover images for all User Guide PDF variants (A4 light/dark, B5 light/dark)
	@if [ -f "$(ASSETS_DIR)/cover-user-guide.html" ] && grep -q "v$(VERSION)" "$(ASSETS_DIR)/cover-user-guide.html"; then \
		echo -e "$(GREEN)✓ Cover image for user-guide already up-to-date$(NC)"; \
	else \
		echo -e "$(DARKYELLOW)- Building cover images for user-guide PDF variants...$(NC)" && \
		sed "s/@@VERSION@@/v$(VERSION)/g" $(ASSETS_DIR)/cover-user-guide-template.html > $(ASSETS_DIR)/cover-user-guide.html && \
		${SCRIPTS_DIR}/mkfigs.sh -o $(ASSETS_DIR) -s $(ASSETS_DIR) cover-user-guide && \
		echo -e "$(GREEN)✓ Cover image for user-guide built under $(ASSETS_DIR)$(NC)"; \
	fi

cover-training-guide:  ## Build the cover images for all Training Guide PDF variants (A4 light/dark, B5 light/dark)
	@if [ -f "$(ASSETS_DIR)/cover-training-guide.html" ] && grep -q "v$(VERSION)" "$(ASSETS_DIR)/cover-training-guide.html"; then \
		echo -e "$(GREEN)✓ Cover image for training-guide already up-to-date$(NC)"; \
	else \
		echo -e "$(DARKYELLOW)- Building cover images for training-guide PDF variants...$(NC)" && \
		sed "s/@@VERSION@@/v$(VERSION)/g" $(ASSETS_DIR)/cover-training-guide-template.html > $(ASSETS_DIR)/cover-training-guide.html && \
		${SCRIPTS_DIR}/mkfigs.sh -o $(ASSETS_DIR) -s $(ASSETS_DIR) cover-training-guide && \
		echo -e "$(GREEN)✓ Cover image for training-guide built under $(ASSETS_DIR)$(NC)"; \
	fi

_covers: cover-user-guide cover-training-guide  
	@:

covers: _covers  ## Build the cover images in parallel for all User Guide and Training Guide PDF variants
	@${MAKE} -j2 _covers	

$(DIST_DIR) : ## Ensure the dist directory exists
	@mkdir -p $(DIST_DIR)

$(BUILD_DIR) : ## Ensure the build directory exists
	@mkdir -p $(BUILD_DIR)

# ============================================================================================
# Exchange Introduction target
# Assembles docs/how-exchange-works.md from the canonical source files in
# docs-exchange-intro/src (Parts I–IV plus the References backmatter).
#
# Rules:
#   - 00-frontmatter/ is excluded (version header, title page, preface).
#   - 90-backmatter/20-glossary.md is excluded.
#   - 90-backmatter/21-references.md is included.
#   - Heading levels are shifted one step deeper throughout:
#       #   → ##    (part / chapter titles)
#       ##  → ###   (section headings)
#       ### → ####  (sub-sections)
#   - A blank line is inserted between concatenated files so pandoc/MkDocs
#     does not merge the last line of one file with the first of the next.
#
# Prerequisites: sed, awk (both available on macOS and Linux).
# ============================================================================================

# Source directories (in document order)
EXCHANGE_INTRO_SRC := ../docs-exchange-intro/src

# All Part I–IV source files in sorted order, excluding 00-frontmatter entirely
EXCHANGE_INTRO_PART_FILES := \
	$(sort $(wildcard $(EXCHANGE_INTRO_SRC)/01-foundation/[0-9][0-9]-*.md)) \
	$(sort $(wildcard $(EXCHANGE_INTRO_SRC)/02-orders-and-matching/[0-9][0-9]-*.md)) \
	$(sort $(wildcard $(EXCHANGE_INTRO_SRC)/03-risk-and-compliance/[0-9][0-9]-*.md)) \
	$(sort $(wildcard $(EXCHANGE_INTRO_SRC)/04-technology-and-infrastructure/[0-9][0-9]-*.md))

# References backmatter only (glossary intentionally excluded)
EXCHANGE_INTRO_BACKMATTER := $(EXCHANGE_INTRO_SRC)/90-backmatter/21-references.md

# All inputs that should trigger a rebuild of the output file
EXCHANGE_INTRO_SOURCES := $(EXCHANGE_INTRO_PART_FILES) $(EXCHANGE_INTRO_BACKMATTER)

# The generated output file
HOW_EXCHANGE_WORKS := $(DOCS_DIR)/how-exchange-works.md

$(HOW_EXCHANGE_WORKS): $(EXCHANGE_INTRO_SOURCES)
	@echo -e "$(DARKYELLOW)- Assembling $(BRIGHTCYAN)how-exchange-works.md$(DARKYELLOW) from exchange-intro sources...$(NC)"
	@# Write the fixed page header (kept outside the source files so it is never generated)
	@printf '%s\n' \
		'## How a Financial Exchange Works' \
		'' \
		'**A Conceptual Introduction for Software Developers**' \
		'' \
		'> *No code. No fear. Just the concepts you need to understand the system you are building.*' \
		'' \
		'---' \
		'' > $@
	@# Concatenate every source file, separated by a blank line, and shift heading levels:
	@#   #   →  ##    (part and chapter titles)
	@#   ##  →  ###   (sections)
	@#   ### →  ####  (sub-sections)
	@# awk adds the blank separator between files; sed does the heading shift.
	@awk 'FNR==1 && NR!=1 { print "" }; { print }' \
		$(EXCHANGE_INTRO_SOURCES) \
		| sed -E \
			-e 's/^#### /##### /g' \
			-e 's/^### /#### /g' \
			-e 's/^## /### /g' \
			-e 's/^# /## /g' \
		>> $@
	@echo -e "$(GREEN)✓ $(BRIGHTCYAN)how-exchange-works.md$(GREEN) assembled ($(words $(EXCHANGE_INTRO_SOURCES)) source files)$(NC)"

exchange-intro: $(HOW_EXCHANGE_WORKS) ## Regenerate docs/how-exchange-works.md from docs-exchange-intro/src sources

.PHONY: exchange-intro

clean: ## Clean build artifacts (HTML site, PDF build files, logs)
	@echo -e "$(DARKYELLOW)- Cleaning build artifacts...$(NC)"
	@rm -rf  $(BUILD_DIR) $(DIST_DIR) $(STAMP_DIR) $(SITE_DIR)
	@echo -e "$(GREEN)✓ Cleaned build artifacts$(NC)"

really-clean: clean ## Remove all generated files and node_modules (use with caution)
	@rm -rf $(NODE_MODULES_PATH)
	@echo -e "$(GREEN)✓ Removed node_modules as well$(NC)"


# ============================================================================================
# Doc-server
# ============================================================================================
serve: docs ## Serve the project documentation locally with MkDocs
	@echo -e "$(BLUE)Serving documentation on http://localhost:$(DOCS_PORT)$(NC)"
	@poetry run mkdocs serve -f ../mkdocs.yml -a localhost:$(DOCS_PORT)

mp-bump: ## Bump the version for the documented multipass bootstrap sctip to the current project version
	@echo -e "$(DARKYELLOW)- Bumping multipass bootstrap script version to $(BRIGHTCYAN)$(VERSION)$(DARKYELLOW)...$(NC)"
	@sed -E $(SED_INPLACE) "s/(--version[[:space:]]+)[0-9]+\.[0-9]+\.[0-9]+/\1${VERSION}/g" ./**/*.md *.md ../README.md
	@echo -e "$(GREEN)✓ All multipass bootstrap scripts version updated to $(BRIGHTCYAN)$(VERSION)$(GREEN)$(NC)"


# ============================================================================================
# Container handling
# ============================================================================================


# PODMAN := $(shell command -v podman 2>/dev/null)
# PODMAN_COMPOSE := $(shell command -v podman-compose 2>/dev/null)
# DOCKER := $(shell command -v docker 2>/dev/null)
# DOCKER_COMPOSE := $(shell command -v docker-compose 2>/dev/null)

# # If both podman and docker are missing, raise an error
# ifeq ($(PODMAN),)
#     ifeq ($(DOCKER),)
#         $(error Neither podman nor docker found. Please install one of them.)
#     endif
# endif

# ifeq ($(PODMAN_COMPOSE),)
#     ifeq ($(DOCKER_COMPOSE),)
#         $(error Neither podman-compose nor docker-compose found. Please install one of them.)
#     endif
# endif

# Check which container engine is running and set the appropriate tool chain
# PODMAN_RUNNING := $(shell podman info >/dev/null 2>&1 && echo "yes" || echo "no")
# DOCKER_RUNNING := $(shell docker info >/dev/null 2>&1 && echo "yes" || echo "no")
# NO_CONTAINER_ENGINE := $(shell if [ "$(PODMAN_RUNNING)" = "no" ] && [ "$(DOCKER_RUNNING)" = "no" ]; then echo "yes"; else echo "no"; fi)
# 
# ifeq ($(PODMAN_RUNNING),yes)
#     CONTAINER_CMD := ${PODMAN}
#     CONTAINER_COMPOSE_CMD := ${PODMAN_COMPOSE}
#     $(info Using Podman as the container engine)
# else ifeq ($(DOCKER_RUNNING),yes)
#     CONTAINER_CMD := ${DOCKER}
#     CONTAINER_COMPOSE_CMD := ${DOCKER_COMPOSE}
#     $(info Using Docker as the container engine)
# else
#     $(info **WARNING** Neither Podman nor Docker engine is running. Please start one of them to use container-related targets.)
# endif
# 
# 
# container-engine-check:
# 	@if [ "$(NO_CONTAINER_ENGINE)" = "yes" ]; then \
#         echo -e "$(YELLOW)⚠️  Warning: No container engine detected. Skipping container operation. Please start Podman or Docker.$(NC)"; \
#         exit 1; \
#     fi

# docs-container-build: | container-engine-check ## Build the containerized documentation image
# 	@MCPROJSIM_DOCS_PORT=$(DOCS_PORT) $(DOCS_CONTAINER_SCRIPT) build 

# docs-container-start: | container-engine-check ## Start the containerized documentation server
# 	@MCPROJSIM_DOCS_PORT=$(DOCS_PORT) $(DOCS_CONTAINER_SCRIPT) start

# docs-container-stop: | container-engine-check ## Stop the containerized documentation server
# 	@MCPROJSIM_DOCS_PORT=$(DOCS_PORT) $(DOCS_CONTAINER_SCRIPT) stop

# docs-container-restart: | container-engine-check ## Restart the containerized documentation server
# 	@MCPROJSIM_DOCS_PORT=$(DOCS_PORT) $(DOCS_CONTAINER_SCRIPT) restart

# docs-container-status: | container-engine-check ## Show status for the containerized documentation server
# 	@MCPROJSIM_DOCS_PORT=$(DOCS_PORT) $(DOCS_CONTAINER_SCRIPT) status

# docs-container-logs: | container-engine-check ## Show logs for the containerized documentation server
# 	@MCPROJSIM_DOCS_PORT=$(DOCS_PORT) $(DOCS_CONTAINER_SCRIPT) logs --follow

# docs-deploy: ## Build and deploy documentation to GitHub Pages
# 	@echo -e "$(DARKYELLOW)- Deploying documentation to GitHub Pages...$(NC)"
# 	@if poetry run mkdocs gh-deploy --force; then \
# 		echo -e "$(GREEN)✓ Documentation deployed successfully$(NC)"; \
# 	else \
# 		echo -e "$(RED)✗ Error: Documentation deployment failed$(NC)"; \
# 		exit 1; \
# 	fi

# EOF

