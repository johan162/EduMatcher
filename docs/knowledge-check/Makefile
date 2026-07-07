# Get full path to bash
SHELL := $(shell which bash)
.SHELLFLAGS := -euo pipefail -c

GPG ?= gpg
UNAME_S := $(shell uname -s)

MD_PLAIN := instructor-correction-keys.md
PDF_PLAIN := instructor-correction-keys.pdf
MD_ENC := $(MD_PLAIN).gpg
PDF_ENC := $(PDF_PLAIN).gpg

.PHONY: check-env encrypt decrypt encrypt-md encrypt-pdf decrypt-md decrypt-pdf

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