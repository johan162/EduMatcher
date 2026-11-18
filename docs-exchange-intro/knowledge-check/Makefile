# Get full path to bash
SHELL := $(shell which bash)
.SHELLFLAGS := -euo pipefail -c

.DEFAULT_GOAL := help

GPG ?= gpg
UNAME_S := $(shell uname -s)

QUIZ_DIR := quiz-20-questions
MD_PLAIN := $(QUIZ_DIR)/exchange-quiz-answer-keys.md
PDF_PLAIN := $(QUIZ_DIR)/exchange-quiz-answer-keys.pdf
MD_ENC := $(MD_PLAIN).gpg
ANSWERS_PLAIN := question-bank/answers.json
ANSWERS_ENC := $(ANSWERS_PLAIN).gpg
PDF_ENC := $(PDF_PLAIN).gpg
QUIZ_PDFS := $(wildcard $(QUIZ_DIR)/*-exchange-quiz.pdf)
VERSION_FILE := ../version.toml
BOOK_VERSION := $(shell awk -F'"' '/^version[[:space:]]*=/{print $$2; exit}' $(VERSION_FILE))
DIST_DIR := ../dist
QUIZ_BUNDLE := $(DIST_DIR)/exchange_intro_quiz_bundle-$(BOOK_VERSION).zip

# Markdown -> A4 PDF: pandoc renders GitHub-flavoured HTML (task-list checkboxes,
# tables and the inline page-break <div>s survive), headless Chrome prints it.
# --section-divs wraps each "### N." question in a <section> that print-a4.css
# keeps on one page, so no hand-placed page breaks are needed between questions.
CHROME ?= $(shell command -v google-chrome || command -v chromium || command -v chromium-browser || echo "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
PRINT_CSS := print-a4.css
SELF_STUDY_DIR := self-study-30-questions
QUIZ_MD_PDFS := $(patsubst %.md,%.pdf,$(wildcard $(QUIZ_DIR)/*.md))
SELF_STUDY_PDFS := $(patsubst %.md,%.pdf,$(wildcard $(SELF_STUDY_DIR)/*.md))

.PHONY: help check-env check-pdf-env pdf pdf-quiz pdf-self-study clean-pdf encrypt decrypt encrypt-md encrypt-pdf encrypt-answers decrypt-md decrypt-pdf decrypt-answers bundle-quiz

RED_COLOR := \033[0;31m
GREEN_COLOR := \033[0;32m
NC := \033[0m

help: ## Show this help message
	@echo "Quiz answer-key and bundle targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN_COLOR)%-16s$(NC) %s\n", $$1, $$2}'

check-env: ## Check that the OS is supported and gpg is installed
	@case "$(UNAME_S)" in \
		Darwin|Linux) ;; \
		*) echo -e "$(RED_COLOR)✗ Error: Unsupported OS: $(UNAME_S) $(NC)"; exit 1 ;; \
	esac
	@command -v "$(GPG)" >/dev/null 2>&1 || { echo -e "$(RED_COLOR)✗ Error: gpg not found in PATH. Please install gnupg.$(NC)"; exit 1; }

encrypt: encrypt-md encrypt-pdf encrypt-answers ## Encrypt both answer keys and the question-bank answers, and remove the plaintext files

decrypt: decrypt-md decrypt-pdf decrypt-answers ## Decrypt both answer keys and the question-bank answers

encrypt-md: check-env ## Encrypt the Markdown answer key and remove the plaintext
	@test -f "$(MD_PLAIN)" || { echo -e "$(RED_COLOR)✗ Error: Missing $(MD_PLAIN) $(NC)"; exit 1; }
	@"$(GPG)" -c "$(MD_PLAIN)"
	@test -s "$(MD_ENC)" || { echo -e "$(RED_COLOR)✗ Error: Encryption failed: $(MD_ENC) was not created $(NC)"; exit 1; }
	@rm -f "$(MD_PLAIN)"
	@echo -e "$(GREEN_COLOR)✓ Success: $(MD_ENC) created$(NC)"

encrypt-pdf: check-env ## Encrypt the PDF answer key and remove the plaintext
	@test -f "$(PDF_PLAIN)" || { echo -e "$(RED_COLOR)✗ Error: Missing $(PDF_PLAIN) $(NC)"; exit 1; }
	@"$(GPG)" -c "$(PDF_PLAIN)"
	@test -s "$(PDF_ENC)" || { echo -e "$(RED_COLOR)✗ Error: Encryption failed: $(PDF_ENC) was not created $(NC)"; exit 1; }
	@rm -f "$(PDF_PLAIN)"
	@echo -e "$(GREEN_COLOR)✓ Success: $(PDF_ENC) created$(NC)"

encrypt-answers: check-env ## Encrypt the question-bank answers JSON and remove the plaintext
	@test -f "$(ANSWERS_PLAIN)" || { echo -e "$(RED_COLOR)✗ Error: Missing $(ANSWERS_PLAIN) $(NC)"; exit 1; }
	@"$(GPG)" -c "$(ANSWERS_PLAIN)"
	@test -s "$(ANSWERS_ENC)" || { echo -e "$(RED_COLOR)✗ Error: Encryption failed: $(ANSWERS_ENC) was not created $(NC)"; exit 1; }
	@rm -f "$(ANSWERS_PLAIN)"
	@echo -e "$(GREEN_COLOR)✓ Success: $(ANSWERS_ENC) created$(NC)"

decrypt-md: check-env ## Decrypt the Markdown answer key
	@test -f "$(MD_ENC)" || { echo -e "$(RED_COLOR)✗ Error: Missing $(MD_ENC) $(NC)"; exit 1; }
	@"$(GPG)" -d "$(MD_ENC)" > "$(MD_PLAIN)"
	@test -s "$(MD_PLAIN)" || { echo -e "$(RED_COLOR)✗ Error: Decryption failed: $(MD_PLAIN) was not created $(NC)"; exit 1; }
	@echo -e "$(GREEN_COLOR)✓ Success: $(MD_PLAIN) created$(NC)"

decrypt-pdf: check-env ## Decrypt the PDF answer key
	@test -f "$(PDF_ENC)" || { echo -e "$(RED_COLOR)✗ Error: Missing $(PDF_ENC) $(NC)"; exit 1; }
	@$(GPG) -d "$(PDF_ENC)" > "$(PDF_PLAIN)"
	@test -s "$(PDF_PLAIN)" || { echo -e "$(RED_COLOR)✗ Error: Decryption failed: $(PDF_PLAIN) was not created $(NC)"; exit 1; }
	@echo -e "$(GREEN_COLOR)✓ Success: $(PDF_PLAIN) created$(NC)"

decrypt-answers: check-env ## Decrypt the question-bank answers JSON
	@test -f "$(ANSWERS_ENC)" || { echo -e "$(RED_COLOR)✗ Error: Missing $(ANSWERS_ENC) $(NC)"; exit 1; }
	@"$(GPG)" -d "$(ANSWERS_ENC)" > "$(ANSWERS_PLAIN)"
	@test -s "$(ANSWERS_PLAIN)" || { echo -e "$(RED_COLOR)✗ Error: Decryption failed: $(ANSWERS_PLAIN) was not created $(NC)"; exit 1; }
	@echo -e "$(GREEN_COLOR)✓ Success: $(ANSWERS_PLAIN) created$(NC)"

bundle-quiz: check-env ## Zip the quiz PDFs and encrypted PDF key into dist/
	@command -v zip >/dev/null 2>&1 || { echo -e "$(RED_COLOR)✗ Error: zip not found in PATH.$(NC)"; exit 1; }
	@test -n "$(BOOK_VERSION)" || { echo -e "$(RED_COLOR)✗ Error: Could not read version from $(VERSION_FILE) $(NC)"; exit 1; }
	@test -n "$(QUIZ_PDFS)" || { echo -e "$(RED_COLOR)✗ Error: No quiz PDFs found matching $(QUIZ_DIR)/*-exchange-quiz.pdf $(NC)"; exit 1; }
	@test -f "$(PDF_ENC)" || { echo -e "$(RED_COLOR)✗ Error: Missing $(PDF_ENC) $(NC)"; exit 1; }
	@mkdir -p "$(DIST_DIR)"
	@rm -f "$(QUIZ_BUNDLE)"
	@zip -j -q "$(QUIZ_BUNDLE)" $(QUIZ_PDFS) "$(PDF_ENC)"
	@echo -e "$(GREEN_COLOR)✓ Success: $(QUIZ_BUNDLE) created$(NC)"

check-pdf-env: ## Check that pandoc and Chrome/Chromium are available
	@command -v pandoc >/dev/null 2>&1 || { echo -e "$(RED_COLOR)✗ Error: pandoc not found in PATH.$(NC)"; exit 1; }
	@test -x "$(CHROME)" || { echo -e "$(RED_COLOR)✗ Error: Chrome/Chromium not found; set CHROME=/path/to/chrome $(NC)"; exit 1; }

pdf: pdf-quiz pdf-self-study ## Convert all quiz and self-study Markdown files to A4 PDFs

pdf-quiz: check-pdf-env $(QUIZ_MD_PDFS) ## Convert quiz-20-questions/*.md to A4 PDFs

pdf-self-study: check-pdf-env $(SELF_STUDY_PDFS) ## Convert self-study-30-questions/*.md to A4 PDFs

clean-pdf: ## Remove the PDFs generated by the pdf targets
	@rm -f $(QUIZ_MD_PDFS) $(SELF_STUDY_PDFS)

%.pdf: %.md $(PRINT_CSS)
	@tmp="$$(mktemp -d)"; trap 'rm -rf "$$tmp"' EXIT; \
	pandoc -f gfm -t html5 -s --section-divs --embed-resources --css "$(PRINT_CSS)" \
		--metadata pagetitle="$(basename $(notdir $<))" -o "$$tmp/page.html" "$<"; \
	"$(CHROME)" --headless --disable-gpu --no-pdf-header-footer --user-data-dir="$$tmp/profile" \
		--print-to-pdf="$(abspath $@)" "file://$$tmp/page.html" >/dev/null 2>&1
	@test -s "$@" || { echo -e "$(RED_COLOR)✗ Error: PDF conversion failed for $< $(NC)"; exit 1; }
	@echo -e "$(GREEN_COLOR)✓ Success: $@ created$(NC)"
