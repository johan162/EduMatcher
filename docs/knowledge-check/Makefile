SHELL := /bin/sh

GPG ?= gpg
UNAME_S := $(shell uname -s)

MD_PLAIN := instructor-correction-keys.md
PDF_PLAIN := instructor-correction-keys.pdf
MD_ENC := $(MD_PLAIN).gpg
PDF_ENC := $(PDF_PLAIN).gpg

.PHONY: check-env encrypt decrypt encrypt-md encrypt-pdf decrypt-md decrypt-pdf

check-env:
	@case "$(UNAME_S)" in \
		Darwin|Linux) ;; \
		*) echo "Unsupported OS: $(UNAME_S)"; exit 1 ;; \
	esac
	@command -v "$(GPG)" >/dev/null 2>&1 || { echo "gpg not found in PATH"; exit 1; }

encrypt: encrypt-md encrypt-pdf

decrypt: decrypt-md decrypt-pdf

encrypt-md: check-env
	@test -f "$(MD_PLAIN)" || { echo "Missing $(MD_PLAIN)"; exit 1; }
	"$(GPG)" -c "$(MD_PLAIN)"
	@test -s "$(MD_ENC)" || { echo "Encryption failed: $(MD_ENC) was not created"; exit 1; }
	rm -f "$(MD_PLAIN)"

encrypt-pdf: check-env
	@test -f "$(PDF_PLAIN)" || { echo "Missing $(PDF_PLAIN)"; exit 1; }
	"$(GPG)" -c "$(PDF_PLAIN)"
	@test -s "$(PDF_ENC)" || { echo "Encryption failed: $(PDF_ENC) was not created"; exit 1; }
	rm -f "$(PDF_PLAIN)"

decrypt-md: check-env
	@test -f "$(MD_ENC)" || { echo "Missing $(MD_ENC)"; exit 1; }
	"$(GPG)" -d "$(MD_ENC)" > "$(MD_PLAIN)"

decrypt-pdf: check-env
	@test -f "$(PDF_ENC)" || { echo "Missing $(PDF_ENC)"; exit 1; }
	"$(GPG)" -d "$(PDF_ENC)" > "$(PDF_PLAIN)"