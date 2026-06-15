# Makefile for building Exchange Intro Documentation 
# For mermaid rendering we use a mermaid Node filter, installed once in a
# shared top-level tools directory used by all doc builds.
# npm install --prefix ../build-tools --save-dev mermaid-filter @mermaid-js/mermaid-cli

NODE_TOOLS_DIR := ../build-tools
NODE_MODULES_PATH := $(NODE_TOOLS_DIR)/node_modules
MERMAID_FILTER := $(NODE_MODULES_PATH)/.bin/mermaid-filter
PUPPETER_EXECUTABLE_PATH ?= /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
MERMAID_FILTER_FORMAT ?= pdf
MERMAID_FILTER_WIDTH ?= 600

.PHONY: pdf-docs help clean really-clean


# Makefile itself as a dependency to ensure it is re-evaluated when changed
# NOTE: This requires GNU Make 4.3+ and MacOS ships with vGNU Make 3.81 due to licensing issues
# and then this line will be silently ignored unless you have upgraded make via brew or similar.	
.EXTRA_PREREQS := $(firstword $(MAKEFILE_LIST))

# Make behavior
.DEFAULT_GOAL := pdfs

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
DIST_DIR := dist
BUILD_DIR := .build
SCRIPTS_DIR := ../scripts
SITE_DIR := ./site

# Project settings
PROJECT := exchange-intro
VERSION := $(shell grep '^version' version.toml | head -1 | cut -d'"' -f2)

# Temporary build directory for exchange intro PDF generation
EXCHANGE_INTRO_BUILD_DIR := $(BUILD_DIR)

# Exchange Intro Book PDF output paths and templates
# Variant-specific paths are derived by DEFINE_EXCHANGE_INTRO_VARS below.
# EXCHANGE_INTRO_LUA_FILTER is shared across all variants.
EXCHANGE_INTRO_LUA_FILTER := $(DOCS_DIR)/pagebreaks.lua
ADMONITIONS_LUA_FILTER := $(DOCS_DIR)/admonitions.lua
BOOK_STRUCTURE_LUA_FILTER := $(DOCS_DIR)/book_structure.lua
EXCHANGE_INTRO_LUA_FILTER_FLAGS := --lua-filter $(BOOK_STRUCTURE_LUA_FILTER) --lua-filter $(EXCHANGE_INTRO_LUA_FILTER) --lua-filter $(ADMONITIONS_LUA_FILTER)

# Markdown sources that are concatenated into the User Guide PDF body.
# Keep this list markdown-only; non-markdown assets are tracked separately
# via EXCHANGE_INTRO_PDF_DEPS so they trigger rebuilds without polluting content.
# NOTE: wildcard/sort split on spaces; use find + escaped spaces so filenames
# like "00-Preface & Intro.md" remain a single list item in make.
EXCHANGE_INTRO_MD_SOURCES := \
	$(shell find $(DOCS_DIR)/src -maxdepth 1 -type f -name '[0-9][0-9]-*.md' -print | sed 's/ /\\ /g' | sort)

# $(info EXCHANGE_INTRO_MD_SOURCES: $(EXCHANGE_INTRO_MD_SOURCES))

# Non-markdown assets that should still trigger a rebuild when changed.
EXCHANGE_INTRO_PDF_DEPS := \
	$(DOCS_DIR)/book_structure.lua \
	$(DOCS_DIR)/pagebreaks.lua \
	$(DOCS_DIR)/admonitions.lua \
	$(DOCS_DIR)/template_a4.tex \
	$(DOCS_DIR)/template_dark_a4.tex \
	$(DOCS_DIR)/template_b5.tex \
	$(DOCS_DIR)/template_dark_b5.tex 


# ============================================================================================
# Macro: DEFINE_EXCHANGE_INTRO_VARS
# Derives all variant-specific file-path variables from the base name alone.
# $(1) = EXCHANGE_INTRO | EXCHANGE_INTRO_B5 | EXCHANGE_INTRO_DARK | EXCHANGE_INTRO_DARK_B5
#
# The suffix is extracted by stripping the EXCHANGE_INTRO prefix from $(1):
#   tex_sfx  — lowercase with underscores (_b5, _dark, _dark_b5)  for LaTeX template names
#   file_sfx — lowercase with hyphens    (-b5, -dark, -dark-b5)   for all other file names
# ============================================================================================
define DEFINE_EXCHANGE_INTRO_VARS
$(1)_TEMPLATE     := $$(DOCS_DIR)/template$(shell printf '%s' '$(patsubst EXCHANGE_INTRO%,%,$(1))' | tr '[:upper:]' '[:lower:]').tex
$(1)_PDF          := $$(DIST_DIR)/$$(PROJECT)$(shell printf '%s' '$(patsubst EXCHANGE_INTRO%,%,$(1))' | tr '[:upper:]_' '[:lower:]-')-$$(VERSION).pdf
$(1)_CONCAT_MD    := $$(EXCHANGE_INTRO_BUILD_DIR)/exchange_intro_concat$(shell printf '%s' '$(patsubst EXCHANGE_INTRO%,%,$(1))' | tr '[:upper:]_' '[:lower:]-').md
$(1)_BODY_TEX     := $$(EXCHANGE_INTRO_BUILD_DIR)/exchange_intro_body$(shell printf '%s' '$(patsubst EXCHANGE_INTRO%,%,$(1))' | tr '[:upper:]_' '[:lower:]-').tex
$(1)_TEX          := $$(EXCHANGE_INTRO_BUILD_DIR)/exchange_intro_report$(shell printf '%s' '$(patsubst EXCHANGE_INTRO%,%,$(1))' | tr '[:upper:]_' '[:lower:]-').tex
$(1)_PDF_BUILT    := $$(EXCHANGE_INTRO_BUILD_DIR)/exchange_intro_report$(shell printf '%s' '$(patsubst EXCHANGE_INTRO%,%,$(1))' | tr '[:upper:]_' '[:lower:]-').pdf
$(1)_EXPANDED_DIR := $$(EXCHANGE_INTRO_BUILD_DIR)/exchange_intro_expanded$(shell printf '%s' '$(patsubst EXCHANGE_INTRO%,%,$(1))' | tr '[:upper:]_' '[:lower:]-')
endef

$(eval $(call DEFINE_EXCHANGE_INTRO_VARS,EXCHANGE_INTRO_A4))
$(eval $(call DEFINE_EXCHANGE_INTRO_VARS,EXCHANGE_INTRO_B5))
$(eval $(call DEFINE_EXCHANGE_INTRO_VARS,EXCHANGE_INTRO_DARK_A4))
$(eval $(call DEFINE_EXCHANGE_INTRO_VARS,EXCHANGE_INTRO_DARK_B5))


# $(info EXCHANGE_INTRO_A4_PDF: $(EXCHANGE_INTRO_A4_PDF))
# $(info EXCHANGE_INTRO_A4_PDF_BUILT: $(EXCHANGE_INTRO_A4_PDF_BUILT))

# Source and Test Files
DOC_FILES :=  $(shell find $(DOCS_DIR) -name 'src/*.md' -o -name '*.yml' -o -name '*.yaml' -o -name '*.lua' -o -name '*.tex') 

# Timestamp files
STAMP_DIR := .makefile-stamps
$(shell mkdir -p $(STAMP_DIR))

DOC_STAMP := $(STAMP_DIR)/docs-stamp

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
	@$(call print_section,Documentation,docs|pdfs|pdf-docs)
	@echo ""

$(DIST_DIR):
	@mkdir -p $(DIST_DIR)

pdf-docs: ## Build all PDF documentation variants in parallel
	@rm -rf $(EXCHANGE_INTRO_BUILD_DIR)  # Clean build dir to ensure no stale files interfere
	@rm $(DIST_DIR)/$(PROJECT)-*.pdf 2>/dev/null || true  # Remove old PDFs to prevent confusion
	@$(MAKE) -j4 $(EXCHANGE_INTRO_A4_PDF) $(EXCHANGE_INTRO_DARK_A4_PDF) $(EXCHANGE_INTRO_B5_PDF) $(EXCHANGE_INTRO_DARK_B5_PDF)
	@zip -9 -j $(DIST_DIR)/$(PROJECT)-bundle-$(VERSION).zip $(DIST_DIR)/$(PROJECT)-*-$(VERSION).pdf
	@echo -e "$(GREEN)✓ PDF bundle built: $(BRIGHTCYAN)\"$(PROJECT)-bundle-$(VERSION).zip\"$(GREEN)$(NC)"

clean: ## Remove all generated files (PDFs, build artifacts, stamps)
	@rm -rf $(EXCHANGE_INTRO_BUILD_DIR) $(DIST_DIR) $(STAMP_DIR) $(SITE_DIR) mermaid-filter.err
	@echo -e "$(GREEN)✓ Cleaned all generated files$(NC)"

really-clean: clean ## Remove all generated files and node_modules (use with caution)
	@rm -rf $(NODE_MODULES_PATH)
	@echo -e "$(GREEN)✓ Removed node_modules as well$(NC)"


# ============================================================================================
# Macro: BUILD_EXCHANGE_INTRO_PDF
# Shared recipe for every Exchange Intro PDF variant. Call via $(eval $(call BUILD_EXCHANGE_INTRO_PDF,...)).
# $(1) = variable name prefix (e.g. EXCHANGE_INTRO, EXCHANGE_INTRO_B5)
# $(2) = paper format: a4 or b5  (passed to the pandoc Lua filter)
# Note: Make variables used inside recipe lines are escaped as $$(VAR) so they survive
# $(call) expansion and are resolved at recipe-execution time.
# ============================================================================================
define BUILD_EXCHANGE_INTRO_PDF
$$($1_PDF): $$(EXCHANGE_INTRO_MD_SOURCES) $$(EXCHANGE_INTRO_PDF_DEPS) $$($1_TEMPLATE) $$(EXCHANGE_INTRO_LUA_FILTER) | $(DIST_DIR) $(NODE_MODULES_PATH)
	@echo -e "$(DARKYELLOW)- Updating version number $(BRIGHTCYAN)v$(VERSION)$(DARKYELLOW) in LaTeX template $$(BRIGHTCYAN)\"$$(notdir $$($1_TEMPLATE))\"$(DARKYELLOW)...$(NC)"
	@sed -i.bak -E 's/Version: [0-9]+(\.[0-9]+)*(rc[0-9]{1,2})?/Version: $(VERSION)/g' $$($1_TEMPLATE)
	@rm -f $$($1_TEMPLATE).bak
	@echo -e "$$(DARKYELLOW)- Building $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(DARKYELLOW) via LaTeX pipeline...$$(NC)"
	@mkdir -p $$(EXCHANGE_INTRO_BUILD_DIR)
	@echo -e "$$(DARKYELLOW)  - Expanding shell command outputs in markdown sources...$$(NC)"
	@mkdir -p $$($1_EXPANDED_DIR)
	@find $(DOCS_DIR)/src -maxdepth 1 -type f -name '[0-9][0-9]-*.md' -print0 \
		| sort -z \
		| xargs -0 poetry run python $$(SCRIPTS_DIR)/expand-shell-outputs.py \
			--output-dir $$($1_EXPANDED_DIR) \
			--cwd $$(SCRIPTS_DIR)/.. \
			--format $(2)
	@echo -e "$$(DARKYELLOW)  - Concatenating markdown sources...$$(NC)"
	@find $$($1_EXPANDED_DIR) -maxdepth 1 -type f -name '[0-9][0-9]-*.md' -print0 \
		| sort -z \
		| xargs -0 awk 'FNR==1 && NR!=1{print ""; print ""}1' > $$($1_CONCAT_MD)
	@echo -e "$$(DARKYELLOW)  - Converting concatenated markdown to LaTeX body...$$(NC)"
	@mkdir -p $$($1_EXPANDED_DIR)/.mermaid-img
	@PUPPETEER_EXECUTABLE_PATH="$(PUPPETER_EXECUTABLE_PATH)" \
	MERMAID_FILTER_FORMAT="$(MERMAID_FILTER_FORMAT)" \
	MERMAID_FILTER_WIDTH="$(MERMAID_FILTER_WIDTH)" \
	MERMAID_FILTER_LOC="$$($1_EXPANDED_DIR)/.mermaid-img" \
	pandoc --from=markdown --to=latex --top-level-division=chapter --syntax-highlighting=none --filter "$(MERMAID_FILTER)"  $$(EXCHANGE_INTRO_LUA_FILTER_FLAGS) --metadata paper_format=$(2) $$($1_CONCAT_MD) -o $$($1_BODY_TEX)
	@sed -i.bak 's/\\def\\LTcaptype{none}/\\def\\LTcaptype{table}/g' $$($1_BODY_TEX)
	@rm -f $$($1_BODY_TEX).bak
	@echo -e "$$(DARKYELLOW)  - Injecting body into handcrafted LaTeX template $$(BRIGHTCYAN)\"$$(notdir $$($1_TEMPLATE))\"$(DARKYELLOW) ...$$(NC)"
	@awk -v body="$$($1_BODY_TEX)" '\
		/%%__EXCHANGE_INTRO_CONTENT__%%/ { while ((getline line < body) > 0) print line; close(body); inserted=1; next } \
		{ print } \
		END { if (!inserted) { print "Template placeholder %%__EXCHANGE_INTRO_CONTENT__%% not found" > "/dev/stderr"; exit 2 } }' \
		$$($1_TEMPLATE) > $$($1_TEX)
	@echo -e "$$(DARKYELLOW)  - Compiling $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(DARKYELLOW) with xelatex (3 passes for references/TOC with shorttoc)...$$(NC)"
	@xelatex -interaction=nonstopmode -halt-on-error -output-directory $$(EXCHANGE_INTRO_BUILD_DIR) $$($1_TEX) \
		> $$($1_PDF_BUILT:.pdf=-xelatex-pass1.log) 2>&1 \
		|| { echo -e "$$(RED)✗ xelatex pass 1 failed for $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(RED).$$(NC)" >&2; \
		     echo -e "$$(RED)  Last 30 lines of $$($1_PDF_BUILT:.pdf=-xelatex-pass1.log):$$(NC)" >&2; \
		     tail -30 $$($1_PDF_BUILT:.pdf=-xelatex-pass1.log) >&2; exit 1; }
	@xelatex -interaction=nonstopmode -halt-on-error -output-directory $$(EXCHANGE_INTRO_BUILD_DIR) $$($1_TEX) \
		> $$($1_PDF_BUILT:.pdf=-xelatex-pass2.log) 2>&1 \
		|| { echo -e "$$(RED)✗ xelatex pass 2 failed for $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(RED).$$(NC)" >&2; \
		     echo -e "$$(RED)  Last 30 lines of $$($1_PDF_BUILT:.pdf=-xelatex-pass2.log):$$(NC)" >&2; \
		     tail -30 $$($1_PDF_BUILT:.pdf=-xelatex-pass2.log) >&2; exit 1; }
	@xelatex -interaction=nonstopmode -halt-on-error -output-directory $$(EXCHANGE_INTRO_BUILD_DIR) $$($1_TEX) \
		> $$($1_PDF_BUILT:.pdf=-xelatex-pass3.log) 2>&1 \
		|| { echo -e "$$(RED)✗ xelatex pass 3 failed for $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(RED).$$(NC)" >&2; \
		     echo -e "$$(RED)  Last 30 lines of $$($1_PDF_BUILT:.pdf=-xelatex-pass3.log):$$(NC)" >&2; \
		     tail -30 $$($1_PDF_BUILT:.pdf=-xelatex-pass3.log) >&2; exit 1; }
	cp $$($1_PDF_BUILT) $$($1_PDF)
	@echo -e "$$(GREEN)✓ Document PDF built: $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(GREEN)$$(NC)"
endef


# ============================================================================================
# Exchange Intro PDF targets — A4 light, A4 dark, B5 light, B5 dark
# ============================================================================================
$(eval $(call BUILD_EXCHANGE_INTRO_PDF,EXCHANGE_INTRO_A4,a4))
$(eval $(call BUILD_EXCHANGE_INTRO_PDF,EXCHANGE_INTRO_B5,b5))
$(eval $(call BUILD_EXCHANGE_INTRO_PDF,EXCHANGE_INTRO_DARK_A4,a4))
$(eval $(call BUILD_EXCHANGE_INTRO_PDF,EXCHANGE_INTRO_DARK_B5,b5))


# Echo all Exchange Intro Variables for debugging Makefile variable generation. 
# $(info EXCHANGE_INTRO_PDF_DEPS: $(EXCHANGE_INTRO_PDF_DEPS))
# $(info EXCHANGE_INTRO_MD_SOURCES: $(EXCHANGE_INTRO_MD_SOURCES))
# $(info EXCHANGE_INTRO_LUA_FILTER: $(EXCHANGE_INTRO_LUA_FILTER))
# $(info EXCHANGE_INTRO_BUILD_DIR: $(EXCHANGE_INTRO_BUILD_DIR))

# $(info EXCHANGE_INTRO_DARK_B5_TEMPLATE: $(EXCHANGE_INTRO_DARK_B5_TEMPLATE))
# $(info EXCHANGE_INTRO_DARK_B5_PDF: $(EXCHANGE_INTRO_DARK_B5_PDF))
# $(info EXCHANGE_INTRO_A4_PDF: $(EXCHANGE_INTRO_A4_PDF))
# $(info EXCHANGE_INTRO_DARK_B5_CONCAT_MD: $(EXCHANGE_INTRO_DARK_B5_CONCAT_MD))
# $(info EXCHANGE_INTRO_DARK_B5_BODY_TEX: $(EXCHANGE_INTRO_DARK_B5_BODY_TEX))
# $(info EXCHANGE_INTRO_DARK_B5_TEX: $(EXCHANGE_INTRO_DARK_B5_TEX))
# $(info EXCHANGE_INTRO_DARK_B5_PDF_BUILT: $(EXCHANGE_INTRO_DARK_B5_PDF_BUILT))


$(NODE_MODULES_PATH):
	@echo -e "$(DARKYELLOW)- Installing shared Node dependencies for Mermaid rendering in $(NODE_TOOLS_DIR)...$(NC)"
	@mkdir -p $(NODE_TOOLS_DIR)
	@npm install --prefix $(NODE_TOOLS_DIR) --save-dev mermaid-filter @mermaid-js/mermaid-cli
	@echo -e "$(GREEN)✓ Shared Node dependencies installed$(NC)"

# EOF

