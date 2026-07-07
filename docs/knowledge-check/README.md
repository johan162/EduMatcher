# Knowledge Check Materials

This directory contains learner-facing knowledge check material for the
exchange concepts content.

The numbered `*-exchange-concepts.md` files are the question-set variants used
for training, review, or assessment.

Instructor correction keys are intentionally not stored here in plaintext.
They are kept only as encrypted `.gpg` files:

- `instructor-correction-keys.md.gpg`
- `instructor-correction-keys.pdf.gpg`

This is done so answer keys can be versioned with the course material while
remaining accessible only to instructors who have the decryption passphrase.

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

