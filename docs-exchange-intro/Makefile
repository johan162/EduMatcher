# Makefile for building Exchange Intro Documentation 
# For mermaid rendering we use a mermaid Node filter, installed once in a
# shared top-level tools directory used by all doc builds.
# npm install --prefix ../build-tools --save-dev mermaid-filter @mermaid-js/mermaid-cli

NODE_TOOLS_DIR := ../build-tools
NODE_MODULES_PATH := $(NODE_TOOLS_DIR)/node_modules
MERMAID_FILTER := $(NODE_MODULES_PATH)/.bin/mermaid-filter
MERMAID_FILTER_FORMAT ?= pdf
MERMAID_FILTER_WIDTH ?= 600


UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
    PUPPETEER_EXECUTABLE_PATH ?= /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
else
    PUPPETEER_EXECUTABLE_PATH ?= /usr/bin/google-chrome
endif

.PHONY: pdf-docs pdf-parts-a4 help clean really-clean check-latex-engine cover bundle-quiz


# Makefile itself as a dependency to ensure it is re-evaluated when changed
# NOTE: This requires GNU Make 4.3+ and MacOS ships with vGNU Make 3.81 due to licensing issues
# and then this line will be silently ignored unless you have upgraded make via brew or similar.	
.EXTRA_PREREQS := $(firstword $(MAKEFILE_LIST))

# Make behavior
.DEFAULT_GOAL := pdf-docs
# .SILENT: # Comment out to show command lines during execution for debugging

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
DIST_DIR := $(DOCS_DIR)/dist
BUILD_DIR := $(DOCS_DIR)/.build
SCRIPTS_DIR := $(DOCS_DIR)/../scripts
LOCAL_SCRIPTS_DIR := $(DOCS_DIR)/scripts
SITE_DIR := $(DOCS_DIR)/site
ASSETS_DIR := $(DOCS_DIR)/assets

# Cover data
NUM_CHAPTERS := 42
NUM_GLOSSARY := $(shell bash $(LOCAL_SCRIPTS_DIR)/count_gloss.sh)

# Project settings
PROJECT := exchange-intro
VERSION := $(shell grep '^version' version.toml | head -1 | cut -d'"' -f2)

# Temporary build directory for exchange intro PDF generation
EXCHANGE_INTRO_BUILD_DIR := $(BUILD_DIR)

# Manifest-driven source ordering for the split chapter tree.
BOOK_MANIFEST := $(DOCS_DIR)/book.toml
BOOK_SOURCES_SCRIPT := $(DOCS_DIR)/scripts/book_sources.py

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
EXCHANGE_INTRO_MD_SOURCES := $(shell poetry run python $(BOOK_SOURCES_SCRIPT) --manifest $(BOOK_MANIFEST))

# Per-part markdown source lists (frontmatter + part N + backmatter).
# Computed at parse time so Make tracks individual file dependencies.
PART_1_MD_SOURCES := $(shell poetry run python $(BOOK_SOURCES_SCRIPT) --manifest $(BOOK_MANIFEST) --part 1)
PART_2_MD_SOURCES := $(shell poetry run python $(BOOK_SOURCES_SCRIPT) --manifest $(BOOK_MANIFEST) --part 2)
PART_3_MD_SOURCES := $(shell poetry run python $(BOOK_SOURCES_SCRIPT) --manifest $(BOOK_MANIFEST) --part 3)
PART_4_MD_SOURCES := $(shell poetry run python $(BOOK_SOURCES_SCRIPT) --manifest $(BOOK_MANIFEST) --part 4)

# Non-markdown assets that should still trigger a rebuild when changed.
EXCHANGE_INTRO_PDF_DEPS := \
	$(BOOK_MANIFEST) \
	$(BOOK_SOURCES_SCRIPT) \
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


# ============================================================================================
# Per-part A4 PDF path variables
# Each part gets its own build dir so parallel builds never share intermediate files.
# Cover images are the only difference from the full-book template_a4.tex build.
# ============================================================================================

PARTS_A4_DIST_DIR := $(DIST_DIR)/parts-a4-pdf

PART_1_PDF   := $(PARTS_A4_DIST_DIR)/exchange-intro-part-I-$(VERSION).pdf
PART_1_BUILD := $(BUILD_DIR)/part-1
PART_1_COVER := assets/cover-exchange-intro-part-I.png

PART_2_PDF   := $(PARTS_A4_DIST_DIR)/exchange-intro-part-II-$(VERSION).pdf
PART_2_BUILD := $(BUILD_DIR)/part-2
PART_2_COVER := assets/cover-exchange-intro-part-II.png

PART_3_PDF   := $(PARTS_A4_DIST_DIR)/exchange-intro-part-III-$(VERSION).pdf
PART_3_BUILD := $(BUILD_DIR)/part-3
PART_3_COVER := assets/cover-exchange-intro-part-III.png

PART_4_PDF   := $(PARTS_A4_DIST_DIR)/exchange-intro-part-IV-$(VERSION).pdf
PART_4_BUILD := $(BUILD_DIR)/part-4
PART_4_COVER := assets/cover-exchange-intro-part-IV.png
# $(info EXCHANGE_INTRO_A4_PDF_BUILT: $(EXCHANGE_INTRO_A4_PDF_BUILT))

# Source and Test Files
DOC_FILES := $(shell find $(DOCS_DIR) -type f \( -name '*.md' -o -name '*.yml' -o -name '*.yaml' -o -name '*.lua' -o -name '*.tex' -o -name 'book.toml' \))

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
	@$(call print_section,Documentation,docs|pdfs|pdf-docs|pdf-parts-a4)
	@echo ""

$(DIST_DIR):
	@mkdir -p $(DIST_DIR)

$(PARTS_A4_DIST_DIR):
	@mkdir -p $(PARTS_A4_DIST_DIR)

check-latex-engine:
	@if ! PATH="$(PATH):$(TEXBIN_FALLBACK)" command -v "$(LATEX_ENGINE)" >/dev/null 2>&1; then \
		echo -e "$(RED)✗ LaTeX engine '$(LATEX_ENGINE)' not found in PATH.$(NC)" >&2; \
		echo -e "$(RED)  Current PATH: $(PATH)$(NC)" >&2; \
		echo -e "$(RED)  Expected fallback path: $(TEXBIN_FALLBACK)$(NC)" >&2; \
		echo -e "$(RED)  Install/update TeX (e.g. MacTeX/BasicTeX) or run after upgrade completes.$(NC)" >&2; \
		exit 1; \
	fi

pdf-docs: check-latex-engine cover ## Build all PDF documentation variants in parallel
	@rm -rf $(EXCHANGE_INTRO_BUILD_DIR)  # Clean build dir to ensure no stale files interfere
	@rm $(DIST_DIR)/$(PROJECT)-*.pdf 2>/dev/null || true  # Remove old PDFs to prevent confusion
	@$(MAKE) -j4 $(EXCHANGE_INTRO_A4_PDF) $(EXCHANGE_INTRO_DARK_A4_PDF) $(EXCHANGE_INTRO_B5_PDF) $(EXCHANGE_INTRO_DARK_B5_PDF)
	@zip -9 -j $(DIST_DIR)/$(PROJECT)-bundle-$(VERSION).zip $(DIST_DIR)/$(PROJECT)-*-$(VERSION).pdf
	@echo -e "$(GREEN)✓ PDF bundle built: $(BRIGHTCYAN)\"$(PROJECT)-bundle-$(VERSION).zip\"$(GREEN)$(NC)"

pdf-parts-a4: check-latex-engine ## Build each book part as a separate A4 PDF booklet
	@rm -f $(PARTS_A4_DIST_DIR)/exchange-intro-part-*-$(VERSION).pdf 2>/dev/null || true
	@$(MAKE) -j4 $(PART_1_PDF) $(PART_2_PDF) $(PART_3_PDF) $(PART_4_PDF)
	@zip -9 -j $(DIST_DIR)/exchange-intro-parts-a4-bundle-$(VERSION).zip $(PARTS_A4_DIST_DIR)/exchange-intro-part-*-$(VERSION).pdf
	@echo -e "$(GREEN)✓ Parts A4 bundle built: $(BRIGHTCYAN)\"exchange-intro-parts-a4-bundle-$(VERSION).zip\"$(GREEN)$(NC)"

clean: ## Remove all generated files (PDFs, build artifacts, stamps)
	@rm -rf $(EXCHANGE_INTRO_BUILD_DIR) $(DIST_DIR) $(STAMP_DIR) $(SITE_DIR) mermaid-filter.err
	@echo -e "$(GREEN)✓ Cleaned all generated files$(NC)"

really-clean: clean ## Remove all generated files and node_modules (use with caution)
	@rm -rf $(NODE_MODULES_PATH)
	@echo -e "$(GREEN)✓ Removed node_modules as well$(NC)"

bundle-quiz:  ## Build the quiz bundle zip file
	$(MAKE) -C knowledge-check/quiz-20-questions bundle-quiz

cover:  ## Build the cover images for the book with version number injected
	@echo -e "$(DARKYELLOW)- Building cover image ...$(NC)"
	@sed -e "s/@@VERSION@@/v$(VERSION)/g" \
	-e  's/@@CHAPTERS@@/${NUM_CHAPTERS}/g' \
	-e 's/@@GLOSSARY@@/${NUM_GLOSSARY}/g' \
	$(ASSETS_DIR)/cover-exchange-intro-template.html > $(ASSETS_DIR)/cover-exchange-intro.html
	@${SCRIPTS_DIR}/mkfigs.sh -q -o $(ASSETS_DIR) -s $(ASSETS_DIR) cover-exchange-intro
	@rm -f $(ASSETS_DIR)/cover-exchange-intro.html
	@echo -e "$(GREEN)✓ Cover image for exchange-intro built under $(ASSETS_DIR)$(NC)"

cover-parts: ## Build cover for the split by PART of the book
	@echo -e "$(DARKYELLOW)- Building cover images for each PART ...$(NC)"
	@TITLE_I="Foundation \& History" 
	@TITLE_II="Orders \& Matching"
	@TITLE_III="Risk \& Compliance" 
	@TITLE_IV="Technology \& Infra" 
	@for part in I II III IV; do \
	    _title="TITLE_$${part}" && \
		echo -e "${BLUE}  PART $${part} - $${!_title} ...${NC}" && \
		sed -e "s/@@VERSION@@/v$(VERSION)/g" \
		-e "s/@@TITLE@@/PART $$part - $${!_title}/" \
		-e 's/@@CHAPTERS@@/${NUM_CHAPTERS}/g' \
		-e 's/@@GLOSSARY@@/${NUM_GLOSSARY}/g' \
		$(ASSETS_DIR)/cover-exchange-intro-part-template.html > $(ASSETS_DIR)/cover-exchange-intro-part-$$part.html; \
		${SCRIPTS_DIR}/mkfigs.sh -q -o $(ASSETS_DIR) -s $(ASSETS_DIR) cover-exchange-intro-part-$$part; \
		rm -f $(ASSETS_DIR)/cover-exchange-intro-part-$$part.html; \
	done
	@echo -e "$(GREEN)✓ Cover images for each PART built under $(ASSETS_DIR)$(NC)"


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
	@printf '%s\0' $(EXCHANGE_INTRO_MD_SOURCES) \
		| xargs -0 poetry run python $$(SCRIPTS_DIR)/expand-shell-outputs.py \
			--output-dir $$($1_EXPANDED_DIR) \
			--cwd $$(SCRIPTS_DIR)/.. \
			--preserve-paths \
			--format $(2)
	@echo -e "$$(DARKYELLOW)  - Concatenating markdown sources...$$(NC)"
	@find $$($1_EXPANDED_DIR) -type f -name '*.md' -print0 \
		| sort -z \
		| xargs -0 awk 'FNR==1 && NR!=1{print ""; print ""}1' > $$($1_CONCAT_MD)
	@echo -e "$$(DARKYELLOW)  - Converting concatenated markdown to LaTeX body...$$(NC)"
	@mkdir -p $$($1_EXPANDED_DIR)/.mermaid-img
	@PUPPETEER_EXECUTABLE_PATH="$(PUPPETEER_EXECUTABLE_PATH)" \
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
	@echo -e "$$(DARKYELLOW)  - Compiling $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(DARKYELLOW) with $$(BRIGHTCYAN)\"$(LATEX_ENGINE)\"$$(DARKYELLOW) (3 passes for references/TOC with shorttoc)...$$(NC)"
	@PATH="$(PATH):$(TEXBIN_FALLBACK)" $(LATEX_ENGINE) -interaction=nonstopmode -halt-on-error -output-directory $$(EXCHANGE_INTRO_BUILD_DIR) $$($1_TEX) \
		> $$($1_PDF_BUILT:.pdf=-xelatex-pass1.log) 2>&1 \
		|| { echo -e "$$(RED)✗ xelatex pass 1 failed for $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(RED).$$(NC)" >&2; \
		     echo -e "$$(RED)  Last 30 lines of $$($1_PDF_BUILT:.pdf=-xelatex-pass1.log):$$(NC)" >&2; \
		     tail -30 $$($1_PDF_BUILT:.pdf=-xelatex-pass1.log) >&2; exit 1; }
	@PATH="$(PATH):$(TEXBIN_FALLBACK)" $(LATEX_ENGINE) -interaction=nonstopmode -halt-on-error -output-directory $$(EXCHANGE_INTRO_BUILD_DIR) $$($1_TEX) \
		> $$($1_PDF_BUILT:.pdf=-xelatex-pass2.log) 2>&1 \
		|| { echo -e "$$(RED)✗ xelatex pass 2 failed for $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(RED).$$(NC)" >&2; \
		     echo -e "$$(RED)  Last 30 lines of $$($1_PDF_BUILT:.pdf=-xelatex-pass2.log):$$(NC)" >&2; \
		     tail -30 $$($1_PDF_BUILT:.pdf=-xelatex-pass2.log) >&2; exit 1; }
	@PATH="$(PATH):$(TEXBIN_FALLBACK)" $(LATEX_ENGINE) -interaction=nonstopmode -halt-on-error -output-directory $$(EXCHANGE_INTRO_BUILD_DIR) $$($1_TEX) \
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


# ============================================================================================
# Macro: BUILD_PART_PDF
# Builds one per-part A4 booklet from frontmatter + part-N content + backmatter.
# The cover image is the only difference from the full-book template_a4.tex: it is
# patched into a per-part copy of the template with sed so the original is untouched.
#
# $(1) = variable prefix: PART_1 | PART_2 | PART_3 | PART_4
# $(2) = paper format: a4
# $(3) = part number: 1..4   (selects PART_$(3)_MD_SOURCES)
# $(4) = roman numeral: I..IV (used in log messages)
# ============================================================================================
define BUILD_PART_PDF
$$($1_PDF): $$(PART_$(3)_MD_SOURCES) $$(EXCHANGE_INTRO_PDF_DEPS) $$($1_COVER) | $$(PARTS_A4_DIST_DIR) $(NODE_MODULES_PATH)
	@echo -e "$$(DARKYELLOW)- Building Part $(4) booklet: $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$$(DARKYELLOW)...$$(NC)"
	@rm -rf $$($1_BUILD)
	@mkdir -p $$($1_BUILD)/expanded
	@echo -e "$$(DARKYELLOW)  - Patching cover image in template for Part $(4)...$$(NC)"
	@sed 's|assets/cover-exchange-intro\.png|$$($1_COVER)|g' $$(DOCS_DIR)/template_a4.tex > $$($1_BUILD)/template_a4.tex
	@echo -e "$$(DARKYELLOW)  - Expanding shell command outputs in markdown sources...$$(NC)"
	@printf '%s\0' $$(PART_$(3)_MD_SOURCES) \
		| xargs -0 poetry run python $$(SCRIPTS_DIR)/expand-shell-outputs.py \
			--output-dir $$($1_BUILD)/expanded \
			--cwd $$(SCRIPTS_DIR)/.. \
			--preserve-paths \
			--format $(2)
	@echo -e "$$(DARKYELLOW)  - Concatenating markdown sources...$$(NC)"
	@find $$($1_BUILD)/expanded -type f -name '*.md' -print0 \
		| sort -z \
		| xargs -0 awk 'FNR==1 && NR!=1{print ""; print ""}1' > $$($1_BUILD)/concat.md
	@echo -e "$$(DARKYELLOW)  - Converting concatenated markdown to LaTeX body...$$(NC)"
	@mkdir -p $$($1_BUILD)/expanded/.mermaid-img
	@PUPPETEER_EXECUTABLE_PATH="$(PUPPETEER_EXECUTABLE_PATH)" \
	MERMAID_FILTER_FORMAT="$(MERMAID_FILTER_FORMAT)" \
	MERMAID_FILTER_WIDTH="$(MERMAID_FILTER_WIDTH)" \
	MERMAID_FILTER_LOC="$$($1_BUILD)/expanded/.mermaid-img" \
	pandoc --from=markdown --to=latex --top-level-division=chapter --syntax-highlighting=none --filter "$(MERMAID_FILTER)" $$(EXCHANGE_INTRO_LUA_FILTER_FLAGS) --metadata paper_format=$(2) $$($1_BUILD)/concat.md -o $$($1_BUILD)/body.tex
	@sed -i.bak 's/\\def\\LTcaptype{none}/\\def\\LTcaptype{table}/g' $$($1_BUILD)/body.tex
	@rm -f $$($1_BUILD)/body.tex.bak
	@echo -e "$$(DARKYELLOW)  - Injecting body into patched LaTeX template for Part $(4)...$$(NC)"
	@awk -v body="$$($1_BUILD)/body.tex" '\
		/%%__EXCHANGE_INTRO_CONTENT__%%/ { while ((getline line < body) > 0) print line; close(body); inserted=1; next } \
		{ print } \
		END { if (!inserted) { print "Template placeholder %%__EXCHANGE_INTRO_CONTENT__%% not found" > "/dev/stderr"; exit 2 } }' \
		$$($1_BUILD)/template_a4.tex > $$($1_BUILD)/report.tex
	@echo -e "$$(DARKYELLOW)  - Compiling $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$$(DARKYELLOW) with $$(BRIGHTCYAN)\"$(LATEX_ENGINE)\"$$(DARKYELLOW) (3 passes for references/TOC with shorttoc)...$$(NC)"
	@PATH="$(PATH):$(TEXBIN_FALLBACK)" $(LATEX_ENGINE) -interaction=nonstopmode -halt-on-error -output-directory $$($1_BUILD) $$($1_BUILD)/report.tex \
		> $$($1_BUILD)/xelatex-pass1.log 2>&1 \
		|| { echo -e "$$(RED)✗ xelatex pass 1 failed for Part $(4).$$(NC)" >&2; \
		     echo -e "$$(RED)  Last 30 lines of $$($1_BUILD)/xelatex-pass1.log:$$(NC)" >&2; \
		     tail -30 $$($1_BUILD)/xelatex-pass1.log >&2; exit 1; }
	@PATH="$(PATH):$(TEXBIN_FALLBACK)" $(LATEX_ENGINE) -interaction=nonstopmode -halt-on-error -output-directory $$($1_BUILD) $$($1_BUILD)/report.tex \
		> $$($1_BUILD)/xelatex-pass2.log 2>&1 \
		|| { echo -e "$$(RED)✗ xelatex pass 2 failed for Part $(4).$$(NC)" >&2; \
		     echo -e "$$(RED)  Last 30 lines of $$($1_BUILD)/xelatex-pass2.log:$$(NC)" >&2; \
		     tail -30 $$($1_BUILD)/xelatex-pass2.log >&2; exit 1; }
	@PATH="$(PATH):$(TEXBIN_FALLBACK)" $(LATEX_ENGINE) -interaction=nonstopmode -halt-on-error -output-directory $$($1_BUILD) $$($1_BUILD)/report.tex \
		> $$($1_BUILD)/xelatex-pass3.log 2>&1 \
		|| { echo -e "$$(RED)✗ xelatex pass 3 failed for Part $(4).$$(NC)" >&2; \
		     echo -e "$$(RED)  Last 30 lines of $$($1_BUILD)/xelatex-pass3.log:$$(NC)" >&2; \
		     tail -30 $$($1_BUILD)/xelatex-pass3.log >&2; exit 1; }
	@cp $$($1_BUILD)/report.pdf $$($1_PDF)
	@echo -e "$$(GREEN)✓ Part $(4) booklet built: $$(BRIGHTCYAN)\"$$(notdir $$($1_PDF))\"$(GREEN)$$(NC)"
endef


# ============================================================================================
# Per-part A4 booklet targets — Part I, II, III, IV
# ============================================================================================
$(eval $(call BUILD_PART_PDF,PART_1,a4,1,I))
$(eval $(call BUILD_PART_PDF,PART_2,a4,2,II))
$(eval $(call BUILD_PART_PDF,PART_3,a4,3,III))
$(eval $(call BUILD_PART_PDF,PART_4,a4,4,IV))


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

