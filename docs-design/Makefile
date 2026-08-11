# Makefile for Design Documentation in EduMatcher project
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


UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
    PUPPETEER_EXECUTABLE_PATH ?= /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
else
    PUPPETEER_EXECUTABLE_PATH ?= /usr/bin/google-chrome
endif

.PHONY: pdfs reqs help clean really-clean dark check-latex-engine

# Makefile itself as a dependency to ensure it is re-evaluated when changed
# NOTE: This requires GNU Make 4.3+ and MacOS ships with vGNU Make 3.81 due to licensing issues
# and then this line will be silently ignored.´unless you have upgrade make via brew or similar.	
.EXTRA_PREREQS := $(firstword $(MAKEFILE_LIST))

# Make behavior
.DEFAULT_GOAL := pdf-docs
MAKEFLAGS += -j16

# Get full path to bash
SHELL := $(shell which bash)

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
RESET := $(NC)

# Formatting
BOLD := \033[1m
UNDERLINE := \033[4m

# Helpers
empty :=
space := $(empty) $(empty)

# ============================================================================================
# Project Wide variable configurations
# ============================================================================================
BUILD_DIR := .build
DIST_DIR := dist
BUILD_DESIGN_DIR := $(BUILD_DIR)
STAMP_DIR := .makefile-stamps
SCRIPTS_DIR := ../scripts
DESIGN_IDEAS_DIR := .

# Theme selection: light (default) or dark.
# Usage:
#   make                 # light mode (default)
#   make dark            # dark mode — PDFs get a -dark suffix
THEME ?= light

ifeq ($(THEME),dark)
DESIGN_LATEX_TEMPLATE := design_template_dark.tex
THEME_SUFFIX := -dark
else
DESIGN_LATEX_TEMPLATE := design_template.tex
THEME_SUFFIX :=
endif

# Derived variable generator for one design document.
# Args:
# 1: variable prefix, e.g. SPRINT_PLANNING
# 2: unique basename, e.g. sprint-based-planning
# 3: pandoc options (optional)
# 4: extra dependencies (optional)
define DEFINE_DESIGN_DOC_VARS
$1_BASENAME := $2
$1_BASENAME_ESC := $(subst $(space),\ ,$2)
$1_MD := $(DESIGN_IDEAS_DIR)/$$($1_BASENAME_ESC).md
$1_PDF := $(DESIGN_IDEAS_DIR)/$$($1_BASENAME_ESC).pdf
$1_STAMP := $(STAMP_DIR)/$$($1_BASENAME_ESC)-pdf$(THEME_SUFFIX).stamp
$1_BUILD_DIR := $(BUILD_DESIGN_DIR)/$$($1_BASENAME_ESC)
$1_MD_CLEAN := $$($1_BUILD_DIR)/$$($1_BASENAME_ESC)_clean.md
$1_BODY_TEX := $$($1_BUILD_DIR)/$$($1_BASENAME_ESC)_body.tex
$1_TEX := $$($1_BUILD_DIR)/$$($1_BASENAME_ESC)_report.tex
$1_PDF_BUILT := $$($1_BUILD_DIR)/$$($1_BASENAME_ESC)_report.pdf
$1_PANDOC_OPTS := $3
$1_EXTRA_DEPS := $4
endef

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

# ============================================================================================
# Makefile Macro for PDF generation from markdown design documents
# This macro defines the rules for generating a PDF from a markdown file using a LaTeX template.
# It takes care of the following steps:
# 1. Convert the markdown file to a LaTeX body using pandoc.
# 2. Inject the generated LaTeX body into the provided LaTeX template at the placeholder.
# 3. Extract the version number and title from the markdown file and replace the corresponding placeholders in the LaTeX template.
# 4. Compile the final LaTeX file to generate the PDF.
# Arguments: 1. A prefix for the variables related to the specific design document (e.g., SPRINT_PLANNING)
#            2. A human-readable name for the design document (used in output messages)
# Note: This macro assumes that the markdown file has a specific format where the version number is on the 
# first line in the format "Version: x.y.z" and the title is the first level 1 heading (e.g., "# Title").
# WARNING: THE TITLE CAN NOT CONTAIN '&' CHARACTER AS THE SUBSTITUTION WILL BE MESSED UP.
# The generated PDF will be placed in the specified distribution directory and named according to the provided variables.
# ============================================================================================
define DESIGN_DOC_PDF_RULE
$$($1_PDF): $$($1_STAMP)
$$($1_STAMP): $$($1_MD) $$(DESIGN_LATEX_TEMPLATE) $$($1_EXTRA_DEPS) | $$(BUILD_DIR) $$(STAMP_DIR) $$(DIST_DIR) $(NODE_MODULES_PATH)
	@echo -e "\n$$(DARKYELLOW)- Building $2 PDF via LaTeX report pipeline...$$(NC)"
	@rm -rf $$($1_BUILD_DIR); 
	@mkdir -p $$($1_BUILD_DIR)
	@sed -E 's/^(#{1,6}[[:space:]]+)[0-9]+([.][0-9]+)*[.]?[[:space:]]+/\1/' $$($1_MD) > $$($1_MD_CLEAN)
	@mkdir -p $$($1_BUILD_DIR)/.mermaid-img
	@PUPPETEER_EXECUTABLE_PATH="$(PUPPETEER_EXECUTABLE_PATH)" \
	MERMAID_FILTER_FORMAT="$(MERMAID_FILTER_FORMAT)" \
	MERMAID_FILTER_WIDTH="$(MERMAID_FILTER_WIDTH)" \
	MERMAID_FILTER_LOC="$$($1_BUILD_DIR)/.mermaid-img" \
	pandoc --from=markdown --to=latex --top-level-division=chapter --syntax-highlighting=none --filter "$(MERMAID_FILTER)" $$(USER_GUIDE_LUA_FILTER_FLAGS) $$($1_PANDOC_OPTS) $$($1_MD_CLEAN) -o $$($1_BODY_TEX)
	@sed -i.bak 's/\\def\\LTcaptype{none}/\\def\\LTcaptype{table}/g' $$($1_BODY_TEX)
	@rm -f $$($1_BODY_TEX).bak
	@awk -v body="$$($1_BODY_TEX)" '\
		/%%__DESIGN_CONTENT__%%/ { while ((getline line < body) > 0) print line; close(body); inserted=1; next } \
		{ print } \
		END { if (!inserted) { print "Template placeholder %%__DESIGN_CONTENT__%% not found" > "/dev/stderr"; exit 2 } }' \
		$$(DESIGN_LATEX_TEMPLATE) > $$($1_TEX)
	@VERSION_FROM_MD=$$$$(head -n 1 $$($1_MD) | sed -E 's/^Version:[[:space:]]*//'); \
	if [ -z "$$$$VERSION_FROM_MD" ]; then \
		echo -e "$$(RED)✗ Error: Could not extract Version from first line of $$($1_MD)$$(NC)"; \
		exit 1; \
	fi; \
	TITLE_FROM_MD=$$$$(grep -m 1 '^# ' $$($1_MD) | sed -E 's/^#[[:space:]]+//'); \
	if [ -z "$$$$TITLE_FROM_MD" ]; then \
		echo -e "$$(RED)✗ Error: Could not extract title from $$($1_MD)$$(NC)"; \
		exit 1; \
	fi; \
	TITLE_FROM_MD_ESCAPED=$$$$(printf '%s' "$$$$TITLE_FROM_MD" | sed -e 's/[\/&\\]/\\&/g'); \
	sed -i.bak -E "s/\{\{VERSION\}\}/Version: $$$$VERSION_FROM_MD/g" $$($1_TEX); \
	sed -i.bak -E "s/\{\{TITLE\}\}/$$$$TITLE_FROM_MD_ESCAPED/g" $$($1_TEX); \
	if ! grep -q "Version: $$$$VERSION_FROM_MD" $$($1_TEX); then \
		echo -e "$$(RED)✗ Error: Failed to update version number in LaTeX template from markdown source$$(NC)"; \
		exit 1; \
	fi; \
	if ! grep -q "$$$$TITLE_FROM_MD" $$($1_TEX); then \
		echo -e "$$(RED)✗ Error: Failed to update title ($$$$TITLE_FROM_MD) in LaTeX template $$($1_TEX) from markdown source$$(NC)"; \
		exit 1; \
	fi; \
	rm -f $$($1_TEX).bak; \
	if ! PATH="$(PATH):$(TEXBIN_FALLBACK)" $(LATEX_ENGINE) -interaction=nonstopmode -halt-on-error -output-directory $$($1_BUILD_DIR) $$($1_TEX) >/dev/null; then \
		echo -e "$$(RED)✗ Error: xelatex pass 1 failed for $$($1_TEX)$$(NC)"; \
		echo -e "$$(YELLOW)  See log: $$($1_BUILD_DIR)/$$($1_BASENAME_ESC)_report.log$$(NC)"; \
		exit 1; \
	fi; \
	if ! PATH="$(PATH):$(TEXBIN_FALLBACK)" $(LATEX_ENGINE) -interaction=nonstopmode -halt-on-error -output-directory $$($1_BUILD_DIR) $$($1_TEX) >/dev/null; then \
		echo -e "$$(RED)✗ Error: xelatex pass 2 failed for $$($1_TEX)$$(NC)"; \
		echo -e "$$(YELLOW)  See log: $$($1_BUILD_DIR)/$$($1_BASENAME_ESC)_report.log$$(NC)"; \
		exit 1; \
	fi; \
	cp $$($1_PDF_BUILT) $$(DIST_DIR)/$$($1_BASENAME_ESC)$$(THEME_SUFFIX)-$$$$VERSION_FROM_MD.pdf; \
	touch $$($1_STAMP); \
	echo -e "$$(GREEN)✓ Version: $$$$VERSION_FROM_MD of \"$2\" PDF built: $$(DARKGRAY)$$(DIST_DIR)/$$($1_BASENAME_ESC)$$(THEME_SUFFIX)-$$$$VERSION_FROM_MD.pdf$$(NC)"
endef

# ============================================================================================
# Design document specific variable definitions
# ============================================================================================
AUTO_DESIGN_MD_FILES := $(sort $(wildcard $(DESIGN_IDEAS_DIR)/EduMatcher-*.md))

# Optional non-prefixed design docs to include in the same pipeline.
EXTRA_DESIGN_DOC_BASENAMES ?= mm-quote-identification
EXTRA_DESIGN_MD_FILES := $(wildcard $(addprefix $(DESIGN_IDEAS_DIR)/,$(addsuffix .md,$(EXTRA_DESIGN_DOC_BASENAMES))))

DESIGN_DOC_MD_FILES := $(sort $(AUTO_DESIGN_MD_FILES) $(EXTRA_DESIGN_MD_FILES))
DESIGN_DOC_BASENAMES := $(basename $(notdir $(DESIGN_DOC_MD_FILES)))

PDF_DESIGN_DOCS := $(addprefix $(STAMP_DIR)/,$(addsuffix -pdf$(THEME_SUFFIX).stamp,$(DESIGN_DOC_BASENAMES)))
REQUIREMENTS_STAMP := $(STAMP_DIR)/EduMatcher-Requirements-pdf$(THEME_SUFFIX).stamp

# ============================================================================================
# Makefile Targets
# ============================================================================================
$(STAMP_DIR)/%-pdf$(THEME_SUFFIX).stamp: $(DESIGN_IDEAS_DIR)/%.md $(DESIGN_LATEX_TEMPLATE) | $(BUILD_DIR) $(STAMP_DIR) $(DIST_DIR) $(NODE_MODULES_PATH)
	@echo -e "\n$(DARKYELLOW)- Building $* PDF via LaTeX report pipeline...$(NC)"
	@DOC_BASENAME="$*"; \
	DOC_BUILD_DIR="$(BUILD_DESIGN_DIR)/$*"; \
	DOC_MD_CLEAN="$$DOC_BUILD_DIR/$*_clean.md"; \
	DOC_BODY_TEX="$$DOC_BUILD_DIR/$*_body.tex"; \
	DOC_TEX="$$DOC_BUILD_DIR/$*_report.tex"; \
	DOC_PDF_BUILT="$$DOC_BUILD_DIR/$*_report.pdf"; \
	rm -rf "$$DOC_BUILD_DIR"; \
	mkdir -p "$$DOC_BUILD_DIR"; \
	sed -E 's/^(#{1,6}[[:space:]]+)[0-9]+([.][0-9]+)*[.]?[[:space:]]+/\1/' "$<" > "$$DOC_MD_CLEAN"; \
	mkdir -p "$$DOC_BUILD_DIR/.mermaid-img"; \
	PUPPETEER_EXECUTABLE_PATH="$(PUPPETEER_EXECUTABLE_PATH)" \
	MERMAID_FILTER_FORMAT="$(MERMAID_FILTER_FORMAT)" \
	MERMAID_FILTER_WIDTH="$(MERMAID_FILTER_WIDTH)" \
	MERMAID_FILTER_LOC="$$DOC_BUILD_DIR/.mermaid-img" \
	pandoc --from=markdown --to=latex --top-level-division=chapter --syntax-highlighting=none --filter "$(MERMAID_FILTER)" $(USER_GUIDE_LUA_FILTER_FLAGS) "$$DOC_MD_CLEAN" -o "$$DOC_BODY_TEX"; \
	sed -i.bak 's/\\def\\LTcaptype{none}/\\def\\LTcaptype{table}/g' "$$DOC_BODY_TEX"; \
	rm -f "$$DOC_BODY_TEX.bak"; \
	awk -v body="$$DOC_BODY_TEX" '\
		/%%__DESIGN_CONTENT__%%/ { while ((getline line < body) > 0) print line; close(body); inserted=1; next } \
		{ print } \
		END { if (!inserted) { print "Template placeholder %%__DESIGN_CONTENT__%% not found" > "/dev/stderr"; exit 2 } }' \
		"$(DESIGN_LATEX_TEMPLATE)" > "$$DOC_TEX"; \
	VERSION_FROM_MD=$$(head -n 1 "$<" | sed -E 's/^Version:[[:space:]]*//'); \
	if [ -z "$$VERSION_FROM_MD" ]; then \
		echo -e "$(RED)✗ Error: Could not extract Version from first line of $<$(NC)"; \
		exit 1; \
	fi; \
	TITLE_FROM_MD=$$(grep -m 1 '^# ' "$<" | sed -E 's/^#[[:space:]]+//'); \
	if [ -z "$$TITLE_FROM_MD" ]; then \
		echo -e "$(RED)✗ Error: Could not extract title from $<$(NC)"; \
		exit 1; \
	fi; \
	TITLE_FROM_MD_ESCAPED=$$(printf '%s' "$$TITLE_FROM_MD" | sed -e 's/[\/&\\]/\\&/g'); \
	sed -i.bak -E "s/\{\{VERSION\}\}/Version: $$VERSION_FROM_MD/g" "$$DOC_TEX"; \
	sed -i.bak -E "s/\{\{TITLE\}\}/$$TITLE_FROM_MD_ESCAPED/g" "$$DOC_TEX"; \
	if ! grep -q "Version: $$VERSION_FROM_MD" "$$DOC_TEX"; then \
		echo -e "$(RED)✗ Error: Failed to update version number in LaTeX template from markdown source$(NC)"; \
		exit 1; \
	fi; \
	if ! grep -q "$$TITLE_FROM_MD" "$$DOC_TEX"; then \
		echo -e "$(RED)✗ Error: Failed to update title ($$TITLE_FROM_MD) in LaTeX template $$DOC_TEX from markdown source$(NC)"; \
		exit 1; \
	fi; \
	rm -f "$$DOC_TEX.bak"; \
	if ! PATH="$(PATH):$(TEXBIN_FALLBACK)" $(LATEX_ENGINE) -interaction=nonstopmode -halt-on-error -output-directory "$$DOC_BUILD_DIR" "$$DOC_TEX" >/dev/null; then \
		echo -e "$(RED)✗ Error: xelatex pass 1 failed for $$DOC_TEX$(NC)"; \
		echo -e "$(YELLOW)  See log: $$DOC_BUILD_DIR/$*_report.log$(NC)"; \
		exit 1; \
	fi; \
	if ! PATH="$(PATH):$(TEXBIN_FALLBACK)" $(LATEX_ENGINE) -interaction=nonstopmode -halt-on-error -output-directory "$$DOC_BUILD_DIR" "$$DOC_TEX" >/dev/null; then \
		echo -e "$(RED)✗ Error: xelatex pass 2 failed for $$DOC_TEX$(NC)"; \
		echo -e "$(YELLOW)  See log: $$DOC_BUILD_DIR/$*_report.log$(NC)"; \
		exit 1; \
	fi; \
	cp "$$DOC_PDF_BUILT" "$(DIST_DIR)/$$DOC_BASENAME$(THEME_SUFFIX)-$$VERSION_FROM_MD.pdf"; \
	touch "$@"; \
	echo -e "$(GREEN)✓ Version: $$VERSION_FROM_MD of \"$*\" PDF built: $(DARKGRAY)$(DIST_DIR)/$$DOC_BASENAME$(THEME_SUFFIX)-$$VERSION_FROM_MD.pdf$(NC)"

help: ## Show this help message
	@echo -e "$(DARKYELLOW)OneSelect - Makefile Targets$(NC)"
	@$(call print_section,Build & Documentation,build|pdf-docs|dark|clean|really-clean)
	@echo ""

$(BUILD_DIR):
	@mkdir -p $(BUILD_DIR)

$(STAMP_DIR):
	@mkdir -p $(STAMP_DIR)

$(DIST_DIR):
	@mkdir -p $(DIST_DIR)

clean: ## Clean all generated intermediate documentation files
	@rm -rf $(BUILD_DIR) $(STAMP_DIR) $(DIST_DIR)
	@echo -e "$(GREEN)✓ Cleaned all generated documentation files$(NC)"

really-clean: clean ## Clean all generated intermediate documentation files and all generated PDFs in the design-ideas directory
	@rm -rf $(NODE_MODULES_PATH)
	@echo -e "$(GREEN)✓ Really cleaned all build and generated files$(NC)"

pdf-docs: $(PDF_DESIGN_DOCS) ## Build all the PDF versions of the design documents (light theme)
	@:

check-latex-engine:
	@if ! PATH="$(PATH):$(TEXBIN_FALLBACK)" command -v "$(LATEX_ENGINE)" >/dev/null 2>&1; then \
		echo -e "$(RED)✗ LaTeX engine '$(LATEX_ENGINE)' not found in PATH.$(NC)" >&2; \
		echo -e "$(RED)  Current PATH: $(PATH)$(NC)" >&2; \
		echo -e "$(RED)  Expected fallback path: $(TEXBIN_FALLBACK)$(NC)" >&2; \
		echo -e "$(RED)  Install/update TeX (e.g. MacTeX/BasicTeX) or run after upgrade completes.$(NC)" >&2; \
		exit 1; \
	fi

pdf-docs: check-latex-engine

dark: ## Build all PDFs in dark theme (adds -dark suffix to filenames)
	@$(MAKE) pdf-docs THEME=dark


reqs: check-latex-engine $(REQUIREMENTS_STAMP) ## Build the MCPProjSim requirements design document PDF
	@:


$(NODE_MODULES_PATH):
	@echo -e "$(DARKYELLOW)- Installing shared Node dependencies for Mermaid rendering in $(NODE_TOOLS_DIR)...$(NC)"
	@mkdir -p $(NODE_TOOLS_DIR)
	@PUPPETEER_SKIP_DOWNLOAD=1 npm install --prefix $(NODE_TOOLS_DIR) --save-dev mermaid-filter @mermaid-js/mermaid-cli
	@echo -e "$(GREEN)✓ Shared Node dependencies installed in $(NODE_TOOLS_DIR)$(NC)"

