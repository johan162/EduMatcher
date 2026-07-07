# Get full path to bash
SHELL := $(shell which bash)
.SHELLFLAGS := -euo pipefail -c

GPG ?= gpg
UNAME_S := $(shell uname -s)

MD_PLAIN := instructor-correction-keys.md
PDF_PLAIN := instructor-correction-keys.pdf
MD_ENC := $(MD_PLAIN).gpg
PDF_ENC := $(PDF_PLAIN).gpg
QUIZ_PDFS := $(wildcard *-exchange-concepts.pdf)
VERSION_FILE := ../../docs-exchange-intro/version.toml
BOOK_VERSION := $(shell awk -F'"' '/^version[[:space:]]*=/{print $$2; exit}' $(VERSION_FILE))
DIST_DIR := ../../docs-exchange-intro/dist
QUIZZ_BUNDLE := $(DIST_DIR)/exchange-intro-quiz-bundle-$(BOOK_VERSION).zip

.PHONY: check-env encrypt decrypt encrypt-md encrypt-pdf decrypt-md decrypt-pdf bundle-quizz

RED_COLOR := \033[0;31m
GREEN_COLOR := \033[0;32m
NC := \033[0m

check-env:
	@case "$(UNAME_S)" in \
		Darwin|Linux) ;; \
		*) echo -e "$(RED_COLOR)✗ Error: Unsupported OS: $(UNAME_S) $(NC)"; exit 1 ;; \
	esac
	@command -v "$(GPG)" >/dev/null 2>&1 || { echo -e "$(RED_COLOR)✗ Error: gpg not found in PATH. Please install gnupg.$(NC)"; exit 1; }

encrypt: encrypt-md encrypt-pdf

decrypt: decrypt-md decrypt-pdf

encrypt-md: check-env
	@test -f "$(MD_PLAIN)" || { echo -e "$(RED_COLOR)✗ Error: Missing $(MD_PLAIN) $(NC)"; exit 1; }
	"$(GPG)" -c "$(MD_PLAIN)"
	@test -s "$(MD_ENC)" || { echo -e "$(RED_COLOR)✗ Error: Encryption failed: $(MD_ENC) was not created $(NC)"; exit 1; }
	rm -f "$(MD_PLAIN)"
	echo -e "$(GREEN_COLOR)✓ Success: $(MD_ENC) created$(NC)"

encrypt-pdf: check-env
	@test -f "$(PDF_PLAIN)" || { echo -e "$(RED_COLOR)✗ Error: Missing $(PDF_PLAIN) $(NC)"; exit 1; }
	"$(GPG)" -c "$(PDF_PLAIN)"
	@test -s "$(PDF_ENC)" || { echo -e "$(RED_COLOR)✗ Error: Encryption failed: $(PDF_ENC) was not created $(NC)"; exit 1; }
	rm -f "$(PDF_PLAIN)"
	echo -e "$(GREEN_COLOR)✓ Success: $(PDF_ENC) created$(NC)"

decrypt-md: check-env
	@test -f "$(MD_ENC)" || { echo -e "$(RED_COLOR)✗ Error: Missing $(MD_ENC) $(NC)"; exit 1; }
	"$(GPG)" -d "$(MD_ENC)" > "$(MD_PLAIN)"
	@test -s "$(MD_PLAIN)" || { echo -e "$(RED_COLOR)✗ Error: Decryption failed: $(MD_PLAIN) was not created $(NC)"; exit 1; }
	echo -e "$(GREEN_COLOR)✓ Success: $(MD_PLAIN) created$(NC)"

decrypt-pdf: check-env
	@test -f "$(PDF_ENC)" || { echo -e "$(RED_COLOR)✗ Error: Missing $(PDF_ENC) $(NC)"; exit 1; }
	"$(GPG)" -d "$(PDF_ENC)" > "$(PDF_PLAIN)"
	@test -s "$(PDF_PLAIN)" || { echo -e "$(RED_COLOR)✗ Error: Decryption failed: $(PDF_PLAIN) was not created $(NC)"; exit 1; }
	echo -e "$(GREEN_COLOR)✓ Success: $(PDF_PLAIN) created$(NC)"

bundle-quiz: check-env
	@command -v zip >/dev/null 2>&1 || { echo -e "$(RED_COLOR)✗ Error: zip not found in PATH.$(NC)"; exit 1; }
	@test -n "$(BOOK_VERSION)" || { echo -e "$(RED_COLOR)✗ Error: Could not read version from $(VERSION_FILE) $(NC)"; exit 1; }
	@test -n "$(QUIZ_PDFS)" || { echo -e "$(RED_COLOR)✗ Error: No quiz PDFs found matching *-exchange-concepts.pdf $(NC)"; exit 1; }
	@test -f "$(PDF_ENC)" || { echo -e "$(RED_COLOR)✗ Error: Missing $(PDF_ENC) $(NC)"; exit 1; }
	@mkdir -p "$(DIST_DIR)"
	rm -f "$(QUIZZ_BUNDLE)"
	zip -j "$(QUIZZ_BUNDLE)" $(QUIZ_PDFS) "$(PDF_ENC)"
	echo -e "$(GREEN_COLOR)✓ Success: $(QUIZZ_BUNDLE) created$(NC)"