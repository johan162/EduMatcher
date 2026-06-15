# Makefile for Design Documentation in MCProjSim project
# For mermaid rendering we use a mermaid Node filter, installed once in a
# shared top-level tools directory used by all doc builds.
# npm install --prefix ../build-tools --save-dev mermaid-filter @mermaid-js/mermaid-cli

NODE_TOOLS_DIR := ../build-tools
NODE_MODULES_PATH := $(NODE_TOOLS_DIR)/node_modules
MERMAID_FILTER := $(NODE_MODULES_PATH)/.bin/mermaid-filter
PUPPETER_EXECUTABLE_PATH ?= /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
MERMAID_FILTER_FORMAT ?= pdf
MERMAID_FILTER_WIDTH ?= 600


.PHONY: pdfs reqs help clean really-clean dark 

# Makefile itself as a dependency to ensure it is re-evaluated when changed
# NOTE: This requires GNU Make 4.3+ and MacOS ships with vGNU Make 3.81 due to licensing issues
# and then this line will be silently ignored.´unless you have upgrade make via brew or similar.	
.EXTRA_PREREQS := $(firstword $(MAKEFILE_LIST))

# Make behavior
.DEFAULT_GOAL := pdf-design-docs
MAKEFLAGS += -j12

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
	@PUPPETEER_EXECUTABLE_PATH="$(PUPPETER_EXECUTABLE_PATH)" \
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
	sed -i.bak -E "s/\{\{VERSION\}\}/Version: $$$$VERSION_FROM_MD/g" $$($1_TEX); \
	sed -i.bak -E "s/\{\{TITLE\}\}/$$$$TITLE_FROM_MD/g" $$($1_TEX); \
	if ! grep -q "Version: $$$$VERSION_FROM_MD" $$($1_TEX); then \
		echo -e "$$(RED)✗ Error: Failed to update version number in LaTeX template from markdown source$$(NC)"; \
		exit 1; \
	fi; \
	if ! grep -q "$$$$TITLE_FROM_MD" $$($1_TEX); then \
		echo -e "$$(RED)✗ Error: Failed to update title ($$$$TITLE_FROM_MD) in LaTeX template $$($1_TEX) from markdown source$$(NC)"; \
		exit 1; \
	fi; \
	rm -f $$($1_TEX).bak; \
	if ! xelatex -interaction=nonstopmode -halt-on-error -output-directory $$($1_BUILD_DIR) $$($1_TEX) >/dev/null; then \
		echo -e "$$(RED)✗ Error: xelatex pass 1 failed for $$($1_TEX)$$(NC)"; \
		echo -e "$$(YELLOW)  See log: $$($1_BUILD_DIR)/$$($1_BASENAME_ESC)_report.log$$(NC)"; \
		exit 1; \
	fi; \
	if ! xelatex -interaction=nonstopmode -halt-on-error -output-directory $$($1_BUILD_DIR) $$($1_TEX) >/dev/null; then \
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
SPRINT_PLANNING_PANDOC_FILTER := $(SCRIPTS_DIR)/pandoc_sprint_planning_table_widths.lua

$(eval $(call DEFINE_DESIGN_DOC_VARS,BALF_PROPOSAL,EduMatcher-BALF_Proposal,,))
$(eval $(call DEFINE_DESIGN_DOC_VARS,FEATURE_IMPLEMENTATION,EduMatcher-Feature_Implementation_Plan,,))
$(eval $(call DEFINE_DESIGN_DOC_VARS,MM_QUOTES_IMPLEMENTATION,EduMatcher-MM_Quotes_Implementation_Plan,,))
$(eval $(call DEFINE_DESIGN_DOC_VARS,TICK_MIGRATION_PLAN,EduMatcher-Tick_Migration_Plan,,))
$(eval $(call DEFINE_DESIGN_DOC_VARS,MARKET_DATA_PROTOCOL,EduMatcher-Market_Data_Protocol,,))
$(eval $(call DEFINE_DESIGN_DOC_VARS,SESSION_GWY_COMMAND,EduMatcher-Session-gwy-command,,))
$(eval $(call DEFINE_DESIGN_DOC_VARS,INDEX_DESIGN,EduMatcher-Index,,))
$(eval $(call DEFINE_DESIGN_DOC_VARS,CROSS_HOST_CONNECTION,EduMatcher-Cross-host-connection,,))

$(eval $(call DEFINE_DESIGN_DOC_VARS,REQUIREMENTS,EduMatcher-Requirements,,))


# ============================================================================================
# Makefile Targets
# ============================================================================================

$(eval $(call DESIGN_DOC_PDF_RULE,BALF_PROPOSAL,"EduMatcher-BALF_Proposal"))
$(eval $(call DESIGN_DOC_PDF_RULE,FEATURE_IMPLEMENTATION,"EduMatcher-Feature_Implementation_Plan"))
$(eval $(call DESIGN_DOC_PDF_RULE,MM_QUOTES_IMPLEMENTATION,"EduMatcher-MM_Quotes_Implementation_Plan"))
$(eval $(call DESIGN_DOC_PDF_RULE,TICK_MIGRATION_PLAN,"EduMatcher-Tick_Migration_Plan"))	
$(eval $(call DESIGN_DOC_PDF_RULE,MARKET_DATA_PROTOCOL,"EduMatcher-Market_Data_Protocol"))
$(eval $(call DESIGN_DOC_PDF_RULE,SESSION_GWY_COMMAND,"EduMatcher-Session-gwy-command"))
$(eval $(call DESIGN_DOC_PDF_RULE,INDEX_DESIGN,"EduMatcher-Index"))
$(eval $(call DESIGN_DOC_PDF_RULE,CROSS_HOST_CONNECTION,"EduMatcher-Cross-host-connection"))

$(eval $(call DESIGN_DOC_PDF_RULE,REQUIREMENTS,"EduMatcher-Requirements"))


PDF_DESIGN_DOCS := $(BALF_PROPOSAL_PDF) $(FEATURE_IMPLEMENTATION_PDF) $(MM_QUOTES_IMPLEMENTATION_PDF) \
$(TICK_MIGRATION_PLAN_PDF) $(MARKET_DATA_PROTOCOL_PDF) $(SESSION_GWY_COMMAND_PDF) $(INDEX_DESIGN_PDF) \
$(CROSS_HOST_CONNECTION_PDF)

help: ## Show this help message
	@echo -e "$(DARKYELLOW)OneSelect - Makefile Targets$(NC)"
	@$(call print_section,Build & Documentation,build|pdf-design-docs|dark|clean|really-clean)
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

dark: ## Build all PDFs in dark theme (adds -dark suffix to filenames)
	@$(MAKE) pdf-design-docs THEME=dark


reqs: $(REQUIREMENTS_PDF) ## Build the MCPProjSim requirements design document PDF
	@:


$(NODE_MODULES_PATH):
	@echo -e "$(DARKYELLOW)- Installing shared Node dependencies for Mermaid rendering in $(NODE_TOOLS_DIR)...$(NC)"
	@mkdir -p $(NODE_TOOLS_DIR)
	@npm install --prefix $(NODE_TOOLS_DIR) --save-dev mermaid-filter @mermaid-js/mermaid-cli
	@echo -e "$(GREEN)✓ Shared Node dependencies installed in $(NODE_TOOLS_DIR)$(NC)"

