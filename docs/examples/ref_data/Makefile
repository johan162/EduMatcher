# Makefile — regenerate all example reference-data configs.
#
# Each subdirectory contains a mkrefdata.sh that accepts a `configs` target
# (the default). Run:
#
#   make           # regenerate all
#   make configs   # same
#
# The subdirectories are discovered automatically via wildcard expansion; no
# manual list is needed when new setups are added.

.PHONY: help force configs

# Makefile itself as a dependency to ensure it is re-evaluated when changed
# NOTE: This requires GNU Make 4.3+ and MacOS ships with vGNU Make 3.81 due to licensing issues
# and then this line will be silently ignored.´unless you have upgrade make via brew or similar.	
.EXTRA_PREREQS := $(firstword $(MAKEFILE_LIST))

SHELL := $(shell which bash)

# Every direct subdirectory that contains a mkrefdata.sh is a target.
SUBDIRS := $(patsubst %/mkrefdata.sh,%,$(wildcard */mkrefdata.sh))
CONFIGS := $(SUBDIRS:%=%/engine_config.yaml)

.DEFAULT_GOAL := configs

# ============================================================================================
# Colors
# ============================================================================================
GREEN  := \033[0;32m
YELLOW := \033[1;33m
BLUE   := \033[0;34m
NC     := \033[0m

# ============================================================================================
# Targets
# ============================================================================================

help: ## Show this help message
	@echo -e "$(YELLOW)EduMatcher — reference data config generator$(NC)"
	@echo -e ""
	@echo -e "  $(BLUE)make$(NC)         generate missing or outdated configs in all $(words $(SUBDIRS)) subdirectories"
	@echo -e "  $(BLUE)make configs$(NC) same as above"
	@echo -e "  $(BLUE)make force$(NC)   force regeneration of all configs"
	@echo -e ""
	@echo -e "Subdirectories found:"
	@for d in $(SUBDIRS); do echo -e "  $(BLUE)$$d$(NC)"; done

force: ## Force regeneration of configs in every subdirectory
	$(MAKE) --always-make configs

configs: $(CONFIGS) ## Generate missing or outdated configs in every subdirectory

$(CONFIGS): %/engine_config.yaml: %/mkrefdata.sh
	@echo -e "$(YELLOW)- Generating config: $@$(NC)"
	@$*/mkrefdata.sh
	@pm-config-deploy --check $*/engine_config.yaml
	@echo -e "$(GREEN)✓ $@ done$(NC)"
