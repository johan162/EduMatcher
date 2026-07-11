# Knowledge Check Materials

This directory contains learner-facing knowledge check material for the exchange concepts content.


**Directories:**

- `quiz-20-questions` Contains quizzes meant to verify that the learner have internalized the concepts and some details in a course setting. Ansewr kesy are *not provided* in plain text but encrypted available to a certified instructor.
- `self-study-30-questions` Contains self-study questions *with answer keys* and some comments on tricky questions 

Answer keys for quizzes are intentionally not stored here in plain text.
They are kept only as encrypted `.gpg` files:

- `instructor-correction-keys.md.gpg`
- `instructor-correction-keys.pdf.gpg`

This will make it possible to use these quizzes in a course setting without learners having access to answers beforehand.


## A note on the scoring system

The scoring model may seem unusual at first, but it is designed to reduce
random guessing in multiple-choice assessments. It does this in two ways:

1. The number of correct options is not disclosed in advance (except that each
	question has at least one correct option).
2. Scoring rewards accurate selections and penalizes incorrect ones:
	+1 point for marking a correct option, and -2 points for marking a wrong
	option.


## CLI encryption workflow

The correction keys are encrypted with `gpg`, which works for both Markdown
and PDF files.

For convenience, this directory also includes a small `Makefile` with helper
targets for encrypting and decrypting the correction keys on both macOS and
Linux.

Common usage:

```bash
make encrypt
make decrypt
make encrypt-md
make encrypt-pdf
make decrypt-md
make decrypt-pdf
```

The `make encrypt` workflow verifies that the encrypted `.gpg` files were
created successfully and then removes the original plaintext correction key
files from the current directory.

### Install gpg

macOS:

```bash
brew install gnupg
```

Linux (Debian/Ubuntu):

```bash
sudo apt install gnupg
```

Linux (Fedora):

```bash
sudo dnf install gnupg2
```

### Encrypt files

From this directory:

```bash
gpg -c instructor-correction-keys.md
gpg -c instructor-correction-keys.pdf
```

This creates:

- `instructor-correction-keys.md.gpg`
- `instructor-correction-keys.pdf.gpg`

### Decrypt files

To restore the plaintext Markdown file:

```bash
gpg -d instructor-correction-keys.md.gpg > instructor-correction-keys.md
```

To restore the plaintext PDF file:

```bash
gpg -d instructor-correction-keys.pdf.gpg > instructor-correction-keys.pdf
```

You will be prompted for the decryption passphrase when opening the encrypted
files.

