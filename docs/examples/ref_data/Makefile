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

.PHONY: help configs $(SUBDIRS)

SHELL := $(shell which bash)

# Every direct subdirectory that contains a mkrefdata.sh is a target.
SUBDIRS := $(patsubst %/mkrefdata.sh,%,$(wildcard */mkrefdata.sh))

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
	@echo -e "  $(BLUE)make$(NC)         regenerate configs in all $(words $(SUBDIRS)) subdirectories"
	@echo -e "  $(BLUE)make configs$(NC) same as above"
	@echo -e ""
	@echo -e "Subdirectories found:"
	@for d in $(SUBDIRS); do echo -e "  $(BLUE)$$d$(NC)"; done

configs: $(SUBDIRS) ## Regenerate configs in every subdirectory

$(SUBDIRS):
	@echo -e "$(YELLOW)- Regenerating configs: $@$(NC)"
	@bash $@/mkrefdata.sh
	@echo -e "$(GREEN)✓ $@ done$(NC)"
