# Makefile for EduMatcher project
# Structure: timestamp-file dependencies for smart re-runs; each command target
# may depend on one or more stamp files that track when a task last succeeded.

.PHONY: help install reinstall clean-venv test test-short test-html verify \
check _check lint format typecheck pre-commit \
build clean maintainer-clean docs docs-serve run pull-all \
black flake8 mypy

# Makefile itself as a dependency to ensure re-evaluation when changed.
# NOTE: Requires GNU Make 4.3+. macOS ships with 3.81 (brew install make to upgrade).
.EXTRA_PREREQS := $(firstword $(MAKEFILE_LIST))

.DEFAULT_GOAL := help

SHELL := $(shell which bash)

.DELETE_ON_ERROR:
.ONESHELL:

# ============================================================================================
# Colors & formatting
# ============================================================================================
BLACK_COLOR  := \033[0;30m
RED          := \033[0;31m
GREEN        := \033[0;32m
DARKYELLOW   := \033[0;33m
BLUE         := \033[0;34m
YELLOW       := \033[1;33m
BRIGHTCYAN   := \033[1;36m
NC           := \033[0m

# ============================================================================================
# Tool availability
# ============================================================================================
POETRY := $(shell command -v poetry 2>/dev/null)
ifeq ($(POETRY),)
    $(error poetry not found. Install with: pip install poetry)
endif

# ============================================================================================
# Variables
# ============================================================================================
SRC_DIR   := src
TEST_DIR  := tests
DOCS_DIR  := docs
DIST_DIR  := dist
BUILD_DIR := .build

PROJECT   := edumatcher
APP_NAME  := EduMatcher
VERSION   := $(shell grep '^version' pyproject.toml | head -1 | cut -d'"' -f2)
PYPI_NAME := $(PROJECT)

COVERAGE := 85

SRC_FILES  := $(shell find $(SRC_DIR) -name '*.py')
TEST_FILES := $(shell find $(TEST_DIR) -name '*.py')
MISC_FILES := pyproject.toml README.md
LOCK_FILE  := poetry.lock

# Stamp files — touch these to record a successful run
STAMP_DIR         := .makefile-stamps
$(shell mkdir -p $(STAMP_DIR))

INSTALL_STAMP   := $(STAMP_DIR)/install-stamp
FORMAT_STAMP    := $(STAMP_DIR)/format-stamp
LINT_STAMP      := $(STAMP_DIR)/lint-stamp
PYRIGHT_STAMP   := $(STAMP_DIR)/pyright-stamp
TYPECHECK_STAMP := $(STAMP_DIR)/typecheck-stamp
TEST_STAMP      := $(STAMP_DIR)/test-stamp

PYPI_VERSION := $(shell echo $(VERSION) | tr -d '-')
BUILD_WHEEL  := $(DIST_DIR)/$(PYPI_NAME)-$(PYPI_VERSION)-py3-none-any.whl
BUILD_SDIST  := $(DIST_DIR)/$(PYPI_NAME)-$(PYPI_VERSION).tar.gz

# ============================================================================================
# Timestamp dependencies
# ============================================================================================
$(INSTALL_STAMP): pyproject.toml $(LOCK_FILE)
	@echo -e "$(DARKYELLOW)- Installing dependencies...$(NC)"
	@poetry config virtualenvs.in-project true
	@poetry install
	@sleep 1
	@touch $(INSTALL_STAMP)
	@echo -e "$(GREEN)✓ Project dependencies installed$(NC)"

$(LOCK_FILE): pyproject.toml
	@echo -e "$(DARKYELLOW)- Regenerating lock file...$(NC)"
	@poetry lock
	@touch $(LOCK_FILE)

$(FORMAT_STAMP): $(SRC_FILES) $(TEST_FILES)
	@echo -e "$(DARKYELLOW)- Running code formatter (black --check)...$(NC)"
	@if poetry run black --check $(SRC_DIR) $(TEST_DIR) -q; then \
		touch $(FORMAT_STAMP); \
		echo -e "$(GREEN)✓ Formatting check passed$(NC)"; \
	else \
		rm -f $(FORMAT_STAMP); \
		echo -e "$(RED)✗ Black formatting check failed. Run 'poetry run black $(SRC_DIR) $(TEST_DIR)' to fix.$(NC)"; \
		exit 1; \
	fi

$(LINT_STAMP): $(SRC_FILES) $(TEST_FILES)
	@echo -e "$(DARKYELLOW)- Running linter (flake8)...$(NC)"
	@if poetry run flake8 $(SRC_DIR) $(TEST_DIR); then \
		touch $(LINT_STAMP); \
		echo -e "$(GREEN)✓ Flake8 linting passed$(NC)"; \
	else \
		echo -e "$(RED)✗ Flake8 linting failed$(NC)"; \
		exit 1; \
	fi

$(PYRIGHT_STAMP): $(SRC_FILES) $(TEST_FILES)
	@if poetry run pyright --version >/dev/null 2>&1; then \
		echo -e "$(DARKYELLOW)- Running pyright...$(NC)"; \
		if poetry run pyright --level error $(SRC_DIR) $(TEST_DIR); then \
			echo -e "$(GREEN)✓ Pyright passed$(NC)"; \
		else \
			echo -e "$(RED)✗ Pyright failed$(NC)"; \
			exit 1; \
		fi; \
	else \
		echo -e "$(YELLOW)⚠  pyright not found, skipping (install with: poetry add --group dev pyright)$(NC)"; \
	fi
	@touch $(PYRIGHT_STAMP)

$(TYPECHECK_STAMP): $(SRC_FILES) $(TEST_FILES)
	@echo -e "$(DARKYELLOW)- Running type checker (mypy)...$(NC)"
	@if poetry run mypy $(SRC_DIR) $(TEST_DIR); then \
		touch $(TYPECHECK_STAMP); \
		echo -e "$(GREEN)✓ Mypy type checking passed$(NC)"; \
	else \
		echo -e "$(RED)✗ Mypy type checking failed$(NC)"; \
		exit 1; \
	fi

$(TEST_STAMP): $(SRC_FILES) $(TEST_FILES)
	@echo -e "$(DARKYELLOW)- Running tests with coverage check (≥$(COVERAGE)%)...$(NC)"
	@if poetry run pytest tests/ -m "not perf" \
		--cov=$(SRC_DIR)/$(PROJECT) \
		--cov-report=term-missing \
		--cov-report=xml \
		--cov-fail-under=$(COVERAGE) \
		-q; then \
		touch $(TEST_STAMP); \
		echo -e "$(GREEN)✓ All tests passed with required coverage$(NC)"; \
	else \
		echo -e "$(RED)✗ Tests failed or coverage below $(COVERAGE)%$(NC)"; \
		exit 1; \
	fi

$(BUILD_WHEEL) $(BUILD_SDIST): $(SRC_FILES) $(MISC_FILES)
	@echo -e "$(DARKYELLOW)- Building packages...$(NC)"
	@if poetry build; then \
		echo -e "$(GREEN)✓ Packages built$(NC)"; \
	else \
		echo -e "$(RED)✗ Package build failed$(NC)"; \
		exit 1; \
	fi
	@echo -e "$(DARKYELLOW)- Verifying packages with twine...$(NC)"
	@if poetry run twine check dist/*.whl dist/*.tar.gz; then \
		echo -e "$(GREEN)✓ 📦 Package verification passed$(NC)"; \
	else \
		echo -e "$(RED)✗ Package verification failed$(NC)"; \
		exit 1; \
	fi

# ============================================================================================
# Help
# ============================================================================================
define print_section
	@echo ""
	@echo -e "$(BRIGHTCYAN)$1:$(NC)"
	@grep -E '^($(2)):.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(BLUE)%-22s$(NC) %s\n", $$1, $$2}' | sort
endef

help: ## Show this help message
	@echo -e "$(DARKYELLOW)EduMatcher — Makefile targets$(NC)"
	$(call print_section,Project Setup,install|reinstall|run)
	$(call print_section,Code Quality,check|lint|format|typecheck|pre-commit)
	$(call print_section,Testing,test|test-short|test-html|verify)
	$(call print_section,Build & Documentation,build|docs|docs-serve)
	$(call print_section,Cleanup,clean|clean-venv|maintainer-clean)
	$(call print_section,Git Operations,pull-all)
	@echo ""

# ============================================================================================
# Development environment
# ============================================================================================
install: $(INSTALL_STAMP) ## Install project dependencies into .venv
	@:

reinstall: clean-venv install ## Remove .venv and reinstall from scratch
	@echo -e "$(GREEN)✓ Project reinstalled$(NC)"

run: ## Launch the full system (engine + all processes) via launch_all.sh
	@bash launch_all.sh

# ============================================================================================
# Testing
# ============================================================================================
test: $(TEST_STAMP) ## Run test suite (excl. perf), terminal coverage report [stamp-cached]
	@:

test-perf: ## Run performance tests (marked with @pytest.mark.perf)
	@echo -e "$(DARKYELLOW)- Running performance tests...$(NC)"
	@poetry run pytest -o addopts='' tests -v -s -m perf -p no:cov

test-short: ## Run tests quickly with no coverage output
	@echo -e "$(DARKYELLOW)- Running short test run (no coverage)...$(NC)"
	@poetry run pytest tests/ -m "not perf" -q --no-cov

test-html: ## Run tests, generate HTML + XML coverage reports
	@echo -e "$(DARKYELLOW)- Running tests with HTML coverage...$(NC)"
	@poetry run pytest tests/ -m "not perf" \
		--cov=$(SRC_DIR)/$(PROJECT) \
		--cov-report=html \
		--cov-report=xml \
		--cov-fail-under=$(COVERAGE) \
		-q
	@echo -e "$(GREEN)✓ Reports: htmlcov/index.html and coverage.xml$(NC)"

verify: ## Run end-to-end deterministic matching verification suite
	@if [ ! -f tools/verify_matching.sh ]; then \
		echo -e "$(RED)✗ tools/verify_matching.sh not found$(NC)"; exit 1; \
	fi
	@bash tools/verify_matching.sh

# ============================================================================================
# Code quality
# ============================================================================================
check: ## Run all code quality checks in parallel (format + lint + typecheck)
	$(MAKE) -j 3 _check

_check: format lint typecheck
	@:

lint flake8: $(LINT_STAMP) ## Run flake8 linting [stamp-cached]
	@:

format black: $(FORMAT_STAMP) ## Check formatting with black [stamp-cached]
	@:

typecheck mypy: $(TYPECHECK_STAMP) ## Run mypy type checking [stamp-cached]
	@:

pre-commit: $(INSTALL_STAMP) ## Run all quality checks + short test (pre-commit gate)
	@echo -e "$(DARKYELLOW)Running pre-commit checks...$(NC)"
	@$(MAKE) -j 3 _check
	@$(MAKE) test-short
	@echo -e "$(GREEN)✓ All pre-commit checks passed$(NC)"

# ============================================================================================
# Build
# ============================================================================================
build: $(INSTALL_STAMP) check test docs $(BUILD_WHEEL) $(BUILD_SDIST) ## Build sdist + wheel (runs check, test, docs first)
	@:

# ============================================================================================
# Documentation
# ============================================================================================
docs: ## Build the MkDocs documentation site into site/
	@echo -e "$(DARKYELLOW)- Building documentation...$(NC)"
	@poetry run mkdocs build
	@echo -e "$(GREEN)✓ Documentation built in site/$(NC)"

docs-serve: ## Serve the documentation site locally with live reload
	@poetry run mkdocs serve

# ============================================================================================
# Cleanup
# ============================================================================================
clean-venv: ## Remove the virtual environment
	@echo -e "$(DARKYELLOW)- Removing .venv...$(NC)"
	@rm -rf .venv $(INSTALL_STAMP)
	@echo -e "$(GREEN)✓ Virtual environment removed$(NC)"

clean: ## Remove build artefacts, caches, stamp files (keeps .venv intact)
	@echo -e "$(DARKYELLOW)- Cleaning build artefacts and caches...$(NC)"
	@rm -rf .pytest_cache $(DIST_DIR) $(BUILD_DIR)
	@rm -rf .coverage coverage.xml htmlcov site
	@rm -rf .mypy_cache $(STAMP_DIR)
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@echo -e "$(GREEN)✓ Clean completed$(NC)"

maintainer-clean: clean-venv clean ## Full clean including .venv (use before a fresh reinstall)
	@echo -e "$(GREEN)✓ Maintainer clean completed$(NC)"

# ============================================================================================
# Git
# ============================================================================================
pull-all: ## Pull all local branches that exist on origin
	@if [ -n "$$(git status --porcelain)" ]; then \
		echo -e "$(RED)✗ Working directory not clean. Commit or stash first.$(NC)"; \
		exit 1; \
	fi
	@echo -e "$(DARKYELLOW)- Fetching from origin...$(NC)"
	@git fetch --prune origin
	@current_branch=$$(git rev-parse --abbrev-ref HEAD); \
	for branch in $$(git branch --format='%(refname:short)'); do \
		if git show-ref --verify --quiet refs/remotes/origin/$$branch; then \
			echo -e "$(BLUE)  Pulling $$branch...$(NC)"; \
			git checkout $$branch && git pull origin $$branch || \
				echo -e "$(RED)  ✗ Failed to pull $$branch$(NC)"; \
		else \
			echo -e "$(YELLOW)  ⚠ Skipping $$branch (not on origin)$(NC)"; \
		fi; \
	done; \
	git checkout $$current_branch
	@echo -e "$(GREEN)✓ All branches pulled$(NC)"

### End of Makefile
