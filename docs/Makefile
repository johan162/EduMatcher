# Generic documentation build for the EduMatcher book library.

POETRY := $(shell command -v poetry 2>/dev/null)
ifeq ($(POETRY),)
$(error poetry not found. Install with: pip install poetry)
endif

DOCS_DIR := .
BOOKS_DIR := $(DOCS_DIR)/books
BUILD_ASSETS := $(DOCS_DIR)/build
FILTER_DIR := $(BUILD_ASSETS)/filters
ASSETS_DIR := $(DOCS_DIR)/assets
DIST_DIR := $(DOCS_DIR)/dist
DOWNLOADS_DIR := $(DOCS_DIR)/downloads
BUILD_DIR := $(DOCS_DIR)/.build
STAMP_DIR := $(DOCS_DIR)/.makefile-stamps
SCRIPTS_DIR := ../scripts
MERMAID_FILTER := ../scripts/mermaid-filter-cached.js
PROJECT := edumatcher
VERSION := $(shell grep '^version' ../pyproject.toml | head -1 | cut -d'"' -f2)
PY := poetry run python
LATEX_ENGINE ?= xelatex
TEXBIN_FALLBACK := /Library/TeX/texbin
MERMAID_FILTER_FORMAT ?= pdf
MERMAID_FILTER_WIDTH ?= 600
EPUB_FIGURE_MAX_WIDTH ?= 85%
PUPPETEER_EXECUTABLE_PATH ?= /Applications/Google Chrome.app/Contents/MacOS/Google Chrome
NODE_MODULES_PATH := ../build-tools/node_modules
AWK_JOIN := awk 'FNR==1 && NR!=1{print ""; print ""}1'
LUA_DEPS := $(wildcard $(FILTER_DIR)/*.lua)

BRIGHTCYAN := \033[1;36m
BLUE := \033[0;34m
DARKYELLOW := \033[0;33m
GREEN := \033[0;32m
RED := \033[0;31m
NC := \033[0m

SHELL := $(shell which bash)
.SHELLFLAGS := -euo pipefail -c
.ONESHELL:
.DELETE_ON_ERROR:
.DEFAULT_GOAL := help

BOOKS := quick-start participant-guide operator-guide reference-manual \
		 protocols-and-clients architecture-and-development training-guide

COVER_TITLE_quick-start := QUICK<br><span class="accent">START</span><br>GUIDE
COVER_TITLE_participant-guide := PARTICIPANT<br><span class="accent">GUIDE</span>
COVER_TITLE_operator-guide := OPERATOR'S<br><span class="accent">GUIDE</span>
COVER_TITLE_reference-manual := REFERENCE<br><span class="accent">MANUAL</span>
COVER_TITLE_protocols-and-clients := PROTOCOLS<br><span class="accent">AND CLIENTS</span>
COVER_TITLE_architecture-and-development := ARCHITECTURE<br><span class="accent">AND DEVELOPER</span><br>GUIDE
COVER_TITLE_training-guide := TRAINING<br><span class="accent">GUIDE</span>

include $(BUILD_ASSETS)/book.mk

.PHONY: pdf-docs epub-docs chapters-pdf book-bundles covers book-all docs-all omnibus docs serve docs-check docs-ledger nav \
  pdf-training-guide epub-training-guide chapters-training-guide exchange-intro \
  pdf-exchange-intro epub-exchange-intro epub-downloads clean really-clean help check-latex-engine

pdf-docs: $(addprefix pdf-,$(BOOKS))
epub-docs: $(addprefix epub-,$(BOOKS))
chapters-pdf: $(addprefix chapters-,$(BOOKS))
BOOK_BUNDLE_TARGETS := $(foreach book,$(BOOKS),$($(book)_ALL))
book-bundles: $(BOOK_BUNDLE_TARGETS)

define BOOK_BUNDLE_RULE
$$($(1)_ALL): $$($(1)_PDFS) $$($(1)_EPUB) $$($(1)_CH_ZIP) $$($(1)_COVER_PNG)
	@printf '%b\n' "$(DARKYELLOW)- Building $(BRIGHTCYAN)\"$(PROJECT)_$(subst -,_,$(1))_all-$(VERSION).zip\"$(DARKYELLOW) ...$(NC)"
	@zip -9 -j -q $$@ $$^
	@printf '%b\n' "$(GREEN)OK all-format bundle: $(BRIGHTCYAN)\"$(PROJECT)_$(subst -,_,$(1))_all-$(VERSION).zip\"$(GREEN)$(NC)"
endef

$(foreach book,$(BOOKS),$(eval $(call BOOK_BUNDLE_RULE,$(book))))
covers: $(addprefix cover-,$(BOOKS))
book-all: pdf-docs epub-docs

EPUB_DOWNLOAD_TARGETS := $(foreach book,$(BOOKS),$($(book)_EPUB_DL))
epub-downloads: $(EPUB_DOWNLOAD_TARGETS)

docs: nav epub-downloads
	@printf '%b\n' "$(DARKYELLOW)- Building MkDocs site...$(NC)"
	@cd .. && $(POETRY) run mkdocs build
	@printf '%b\n' "$(GREEN)OK MkDocs site built$(NC)"
serve: nav epub-downloads
	@cd .. && $(POETRY) run mkdocs serve

pdf-exchange-intro:
	@printf '%b\n' "$(DARKYELLOW)- Building Exchange Intro PDFs...$(NC)"
	@$(MAKE) -C ../docs-exchange-intro pdf-docs
	@printf '%b\n' "$(GREEN)OK Exchange Intro PDFs built$(NC)"
# Must run after pdf-exchange-intro, not in parallel with it: pdf-docs does an
# unconditional `rm -rf` of their shared build dir, which races epub-docs's use
# of the same directory.
epub-exchange-intro: pdf-exchange-intro
	@printf '%b\n' "$(DARKYELLOW)- Building Exchange Intro EPUB...$(NC)"
	@$(MAKE) -C ../docs-exchange-intro epub-docs
	@printf '%b\n' "$(GREEN)OK Exchange Intro EPUB built$(NC)"
docs-all: book-all pdf-exchange-intro epub-exchange-intro
omnibus: docs-all chapters-pdf book-bundles
exchange-intro:
	@$(MAKE) -C ../docs-exchange-intro pdf-docs

PRE_SPLIT_TAG := docs-pre-split
PRE_SPLIT_DIR := $(BUILD_DIR)/pre-split

docs-ledger:
	@rm -rf $(PRE_SPLIT_DIR) && mkdir -p $(PRE_SPLIT_DIR)
	@git -C .. archive $(PRE_SPLIT_TAG) docs/user-guide docs/training docs/concepts docs/architecture docs/developer docs/faq.md docs/glossary.md docs/index.md | tar -x -C $(PRE_SPLIT_DIR)
	@$(PY) $(SCRIPTS_DIR)/doc-ledger.py --old $(PRE_SPLIT_DIR)/docs --new $(BOOKS_DIR) docs/shared docs/index.md --map ../docs-design/doc-migration-map.tsv

docs-check: nav
	@(cd .. && $(PY) scripts/checkdocs.py)
	@$(MAKE) --no-print-directory docs-ledger

nav:
	@$(PY) $(BUILD_ASSETS)/gen_nav.py --mkdocs ../mkdocs.yml --docs $(DOCS_DIR) --books $(BOOKS)

check-latex-engine:
	@if ! PATH="$(PATH):$(TEXBIN_FALLBACK)" command -v "$(LATEX_ENGINE)" >/dev/null 2>&1; then echo "LaTeX engine '$(LATEX_ENGINE)' not found" >&2; exit 1; fi

$(DIST_DIR):
	@mkdir -p $@

$(DOWNLOADS_DIR):
	@mkdir -p $@

$(STAMP_DIR)/version-$(VERSION):
	@mkdir -p $(STAMP_DIR)
	@rm -f $(STAMP_DIR)/version-*
	@touch $@

clean:
	@rm -rf $(BUILD_DIR) $(DIST_DIR)/chapters-a4
really-clean: clean
	@rm -rf $(DIST_DIR) $(DOWNLOADS_DIR) $(STAMP_DIR)

help:
	@printf '\n$(DARKYELLOW)EduMatcher documentation targets$(NC)\n'
	@printf '\n$(BRIGHTCYAN)Documentation$(NC)\n'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'docs' 'Build the MkDocs site'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'serve' 'Serve the MkDocs site locally'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'epub-downloads' 'Refresh the EPUB download copies the site links to'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'docs-check' 'Run documentation checks and the migration ledger'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'docs-ledger' 'Check migrated documentation coverage'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'nav' 'Regenerate MkDocs navigation'

	@printf '\n$(BRIGHTCYAN)Book formats$(NC)\n'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'pdf-docs' 'Build all books as four PDF variants'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'epub-docs' 'Build all books as EPUB3'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'chapters-pdf' 'Build per-chapter PDFs for all books'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'book-bundles' 'Create one compressed all-formats bundle per book'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'covers' 'Build all book cover images'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'book-all' 'Build every book as PDF and EPUB'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'omnibus' 'Build the complete documentation library and all book bundles'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'pdf-<book> epub-<book>' 'Build one book in a selected format'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'chapters-<book>' 'Build one book chapter by chapter'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'book-<book>' 'Build one book in all formats'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'cover-<book>' 'Build one book cover image'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'epub-verify-<book>' 'Validate one EPUB with epubcheck'

	@printf '\n$(BRIGHTCYAN)Exchange intro$(NC)\n'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'exchange-intro' 'Build the delegated exchange introduction'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'pdf-exchange-intro' 'Build the exchange introduction PDFs'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'epub-exchange-intro' 'Build the exchange introduction EPUB'

	@printf '\n$(BRIGHTCYAN)Maintenance$(NC)\n'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'clean' 'Remove intermediate build output'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'really-clean' 'Remove all generated documentation output'
	@printf '  $(BLUE)%-30s$(NC) %s\n' 'check-latex-engine' 'Check that the LaTeX engine is available'
	@printf '\n'
