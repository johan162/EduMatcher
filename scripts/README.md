# Build Scripts

This directory contains the maintenance scripts for `edumatcher`.
They support local development, CI validation, release preparation,
documentation workflows, setup verification, and containerized docs serving.

# Table of Contents

- [Build Scripts](#build-scripts)
- [Table of Contents](#table-of-contents)
  - [Script Conventions](#script-conventions)
  - [Scripts Overview](#scripts-overview)
    - [`mkbld.sh` - Main Build Script](#mkbldsh---main-build-script)
    - [`mkcovupd.sh` - Coverage Badge Updater](#mkcovupdsh---coverage-badge-updater)
    - [`mkrelease.sh` - Release Automation Script](#mkreleasesh---release-automation-script)
    - [`mkghrelease.sh` - GitHub Release Creator](#mkghreleasesh---github-release-creator)
    - [`mkdocs.sh` - Documentation Automation Script](#mkdocssh---documentation-automation-script)
    - [`expand-shell-outputs.py` - Markdown Command Output Expander](#expand-shell-outputspy---markdown-command-output-expander)
    - [`install-runtime.sh` - End-user Runtime Installer](#install-runtimesh---end-user-runtime-installer)
    - [`verify_setup.sh` - Local Setup Verification](#verify_setupsh---local-setup-verification)
    - [`docs-contctl.sh` - Containerized Docs Server Manager](#docs-contctlsh---containerized-docs-server-manager)
  - [Deprecated Scripts](#deprecated-scripts)
    - [`mkchlogentry.sh` - CHANGELOG Entry Script](#mkchlogentrysh---changelog-entry-script)
    - [`mkcover.sh` - PDF Cover Inserter](#mkcoversh---pdf-cover-inserter)
  - [Typical Workflows](#typical-workflows)
    - [Daily Development Check](#daily-development-check)
    - [Fresh Local Setup Verification](#fresh-local-setup-verification)
    - [Documentation Workflows](#documentation-workflows)
    - [Release Workflow](#release-workflow)
  - [Troubleshooting](#troubleshooting)


## Script Conventions

- Most scripts support `--help`.
- Several scripts support `--dry-run`, but not all do.
- The project is Poetry-based, so the scripts generally assume `poetry` is installed.
- Scripts that are meant for guarded automation typically exit on the first error.
- Run scripts from the project root unless a script explicitly says otherwise.

## Scripts Overview

### `mkbld.sh` - Main Build Script

Runs the main quality and packaging pipeline and is the primary script used by CI. This script **must** be run as a step in the release process.

```bash
./scripts/mkbld.sh [OPTIONS]
```

**What it does:**
1. Verifies the Poetry environment and required dev tools
2. Runs `flake8`, `mypy`, and `black --check`
3. Runs the test suite with coverage enforcement
4. Updates the README coverage badge locally when `coverage.xml` changes
5. Builds wheel and source distribution artifacts
6. Validates the built artifacts with `twine check`

**Options:**
- `--dry-run` - Show commands without executing them
- `--help` - Display help message
- `--intro` - Build the Exchange Intro PDF bundle (needed for a release)

**Requirements:**
- Poetry installed and available on `PATH`
- Development dependencies installed: `poetry install --with dev`
- Run from the project root

**Outputs:**
- `coverage.xml`
- `htmlcov/`
- `dist/`
- `docs-exchange-intro/dist/`

### `mkcovupd.sh` - Coverage Badge Updater

Updates the coverage badge in the top-level `README.md` from the current `coverage.xml` report.

```bash
./scripts/mkcovupd.sh [OPTIONS]
```

**What it does:**
1. Extracts line coverage from `coverage.xml`
2. Converts it to a rounded percentage
3. Chooses the Shields badge color from the current coverage result
4. Updates the coverage badge URL in `README.md`
5. Asserts that the exact expected badge URL is present afterward
6. Skips rewriting `README.md` when the badge is already up to date

**Options:**
- `--dry-run` - Show commands without executing them
- `--help` - Display help message

**Badge color mapping:**
- `>= 90%` → `darkgreen`
- `>= 80%` → `brightgreen`
- `>= 70%` → `yellowgreen`
- `>= 60%` → `yellow`
- `>= 50%` → `orange`
- `< 50%` → `red`

**Requirements:**
- `coverage.xml` must exist
- `README.md` must already contain a coverage badge

### `mkrelease.sh` - Release Automation Script

Automates the local release workflow, including version bumping, quality gates, changelog validation, and git operations.

```bash
./scripts/mkrelease.sh <version> [major|minor|patch] [OPTIONS]
```

**Examples:**
```bash
./scripts/mkrelease.sh 0.2.0rc5 minor --dry-run
./scripts/mkrelease.sh 0.2.0 patch
```

**What it does:**
1. Validates the requested version and release prerequisites
2. Runs the project quality gates
3. Updates the Poetry version in `pyproject.toml`
4. Verifies that `CHANGELOG.md` already contains an entry for the requested version
5. Performs the configured branch / tag workflow. This means tagging `develop` and squash merge `develop` to `main` and also back-sync `main` to `develop` 

**Options:**
- `--dry-run` - Preview release actions
- `--help`, `-h` - Display help message

**Notes:**
- Versioning is Poetry-driven; package version data is not edited manually in `__init__.py`
- Pre-release versions should use the current Poetry / PEP 440 style, for example `0.2.0rc5`
- Run `mkchlogentry.sh` first to create the new `CHANGELOG.md` entry before starting the release


### `mkghrelease.sh` - GitHub Release Creator

Creates a GitHub release with the `gh` CLI after the local release work and CI/artifact generation are complete.'
It will base the GitHub release on the latest tag on `main`

```bash
./scripts/mkghrelease.sh [OPTIONS]
```

**What it does:**
1. Validates that `gh` is installed and authenticated
2. Finds the release tag to publish
3. Collects artifacts from `dist/`
4. Prepares release notes
5. Creates the GitHub release and uploads the artifacts

**Options:**
- `--help` - Display help message
- `--pre-release` - Force pre-release mode (same as ticking the pre-release box in the GitHub UI)
- `--dry-run` - Preview without creating the release

**Requirements:**
- GitHub CLI installed and authenticated
- Release artifacts already built in `dist/`
- Typically run after `mkrelease.sh` and after CI completes successfully

### `mkdocs.sh` - Documentation Automation Script

Builds, serves, deploys, or cleans the MkDocs documentation site.

```bash
./scripts/mkdocs.sh {serve|build|deploy|clean}
```

**Commands:**
- `serve` - Start the local MkDocs development server
- `build` - Build the static site into `site/`
- `deploy` - Deploy docs with `mkdocs gh-deploy`
- `clean` - Remove built docs artifacts

**Behavior:**
- Works from the project root automatically
- Ensures docs dependencies are available before running
- Creates the `docs/CHANGELOG.md` symlink when needed

**Requirements:**
- Poetry docs dependencies preferred: `poetry install --with docs`

### `expand-shell-outputs.py` - Markdown Command Output Expander

Expands `{{!command}}` placeholders inside markdown files into fenced code blocks containing the command output.
The docs PDF pipeline uses this to materialize command examples before concatenating markdown sources.

```bash
./scripts/expand-shell-outputs.py --output-dir DIR [--cwd DIR] [--format FORMAT] FILE [FILE ...]
```

**Examples:**
```bash
./scripts/expand-shell-outputs.py --output-dir /tmp/expanded docs/user-guide/00-getting-started.md
./scripts/expand-shell-outputs.py --output-dir .build/expanded --cwd . --format a4 docs/user-guide/*.md
```

**Placeholder examples:**
- `{{!cmd}}` - Insert full command output in one code block
- `{{!cmd:10}}` - Insert the first 10 lines
- `{{!cmd:10:20}}` - Insert first 10 lines and last 20 lines in separate code blocks
- `{{!cmd@A4:25:25,B5:20:20}}` - Use format-specific truncation
- `{{!cmd@L}}` - Add line numbers to emitted output

**Options:**
- `--output-dir DIR` - Directory where expanded markdown copies are written
- `--cwd DIR` - Working directory for placeholder commands
- `--format FORMAT` - Format selector used by format-specific truncation specs, for example `a4` or `b5`

**Behavior:**
- Preserves the basename of each input file in the output directory
- Processes files in parallel
- Exits non-zero if any placeholder command fails

### `install-runtime.sh` - End-user Runtime Installer

Installs EduMatcher for students and instructors using `pipx`, without requiring a source checkout or Poetry environment.

```bash
./scripts/install-runtime.sh [OPTIONS]
```

**What it does:**
1. Checks for Python 3.13 or later
2. Ensures `pipx` is installed, installing it when possible
3. Installs or upgrades `edumatcher` from PyPI via `pipx`
4. Runs `pm-setup` to initialize the runtime data/config environment
5. Prints next steps for starting an exchange session

**Options:**
- `--upgrade` - Force reinstall / upgrade of the existing `pipx` installation
- `--help` - Display help message

**Environment variables:**
- `EDUMATCHER_DATA_DIR` - Override the data directory initialized by `pm-setup`
- `EDUMATCHER_CONFIG` - Override where EduMatcher expects `engine_config.yaml`

**Requirements:**
- Python 3.13 or later
- Network access to install from PyPI
- `pipx`, or a platform where the script can install `pipx`

### `verify_setup.sh` - Local Setup Verification

Verifies that a local Poetry-based installation is working end to end.

```bash
./scripts/verify_setup.sh
```

**What it does:**
1. Verifies Poetry is installed
2. Installs dependencies with `poetry install --with dev`
3. Verifies the configuration command works

**Best used for:**
- Initial local setup verification
- Smoke testing a fresh development environment

### `docs-contctl.sh` - Containerized Docs Server Manager

Manages the containerized documentation server built from `Dockerfile.docs`.

```bash
./scripts/docs-contctl.sh [command] [options]
```

**Commands:**
- `start` - Start the docs server container (default)
- `stop` - Stop and remove the docs server container
- `restart` - Restart the docs server container
- `status` - Show current status and URL
- `logs` - Show container logs
- `build` - Build or rebuild the docs image

**Options:**
- `-p`, `--port PORT` - Published host port
- `-n`, `--name NAME` - Container name override
- `-d`, `--detach` - Run in the background
- `-f`, `--foreground` - Run in the foreground
- `-h`, `--help` - Display help message

**Environment variables:**
- `EDUMATCHER_DOCS_IMAGE` - Override image name
- `EDUMATCHER_DOCS_PORT` - Override default port
- `EDUMATCHER_USE_PROXY_CA=true` - Build with proxy CA support

**When to use it:**
- Use this script when you want the docs served from the same containerized environment used for docs image validation
- Prefer `make docs-serve` or `poetry run mkdocs serve` for the fastest local editing feedback


## Deprecated scripts

Documented for historical reasons.

### `mkchlogentry.sh` - CHANGELOG Entry Script

**THIS IS NOW A DEPRECATED SCRIPT. USE THE CoPilot SKILL `/changelog-entry` INSTEAD**

Creates and prepends a new release-entry template in the top-level `CHANGELOG.md`.
Run this before `mkrelease.sh`.

```bash
./scripts/mkchlogentry.sh <version> [major|minor|patch] [OPTIONS]
```

**Examples:**
```bash
./scripts/mkchlogentry.sh 0.7.2 patch
./scripts/mkchlogentry.sh 0.8.0 minor --dry-run
```

**What it does:**
1. Validates the requested version format
2. Refuses to create duplicate entries for an existing version
3. Prepends a new entry using the established release layout
4. Leaves `CHANGELOG.md` ready for the developer to replace placeholders with final release notes

**Options:**
- `--dry-run` - Preview the entry without modifying files
- `--help`, `-h` - Display help message

**Requirements:**
- Run from the project root
- Update the generated placeholder bullets before running `mkrelease.sh`


### `mkcover.sh` - PDF Cover Inserter

**THIS IS DEPRECATED THE COVER FOR THE PDF BOOKS ARE INSERTED AS PART OF THE LATEX-TEMPLATE**

Inserts an image as the first page of an existing PDF, replacing the PDF's current first page.
This is used by documentation PDF workflows that generate a placeholder cover page first and then replace it with a rendered image.

```bash
./scripts/mkcover.sh [OPTIONS] <image> <pdf>
```

**Examples:**
```bash
./scripts/mkcover.sh assets/cover.png docs/dist/book.pdf
./scripts/mkcover.sh --dpi 300 -o docs/dist/book-with-cover.pdf assets/cover.png docs/dist/book.pdf
```

**What it does:**
1. Reads the page size from the target PDF
2. Converts the image into a single-page PDF at the target page size
3. Replaces the target PDF's first page with the generated cover page
4. Writes either in place or to a separate output file

**Options:**
- `-q`, `--quiet` - Suppress normal output
- `--dpi N` - Set image conversion DPI, default `72`
- `-o`, `--output FILE` - Write to a separate output PDF instead of overwriting the input
- `-h`, `--help` - Display help message

**Requirements:**
- ImageMagick (`magick` or `convert`) for image-to-PDF conversion
- One PDF merge/page tool: `pdftk`, Ghostscript (`gs`), or Poppler (`pdfseparate` and `pdfunite`)
- `pdfinfo` from Poppler or Ghostscript for page-size detection



## Typical Workflows

### Daily Development Check

```bash
./scripts/mkbld.sh
open htmlcov/index.html
```

### Fresh Local Setup Verification

```bash
./scripts/verify_setup.sh
```

### Documentation Workflows

```bash
# Local fast feedback
poetry install --with docs
make docs-serve

# Containerized docs environment
make docs-container-start
./scripts/docs-contctl.sh status
./scripts/docs-contctl.sh logs --follow
```

### Runtime Installation

```bash
# Install EduMatcher as an end-user runtime
./scripts/install-runtime.sh

# Upgrade an existing pipx installation
./scripts/install-runtime.sh --upgrade
```

### PDF Cover Replacement

```bash
./scripts/mkcover.sh --dpi 300 assets/cover.png docs/dist/book.pdf
```

### Release Workflow

```bash
# Create the changelog entry first
./scripts/mkchlogentry.sh 0.2.0rc5 minor

# Edit CHANGELOG.md and replace the placeholder bullets

# Preview the release steps first
./scripts/mkrelease.sh 0.2.0rc5 minor --dry-run

# Perform the release workflow
./scripts/mkrelease.sh 0.2.0rc5 minor

# After CI and artifacts are ready, create the GitHub release
./scripts/mkghrelease.sh
```

## Troubleshooting

**Problem: `coverage.xml` not found**

```bash
poetry run pytest --cov=src/edumatcher --cov-report=xml
./scripts/mkcovupd.sh
```

**Problem: docs dependencies missing**

```bash
poetry install --with docs
```

**Problem: dev tools missing for build scripts**

```bash
poetry install --with dev
```

**Problem: Podman not available for containerized docs**

- Install Podman and ensure the engine is running before using `docs-contctl.sh`

**Problem: PDF cover insertion fails**

- Install ImageMagick and one supported PDF tool: `pdftk`, Ghostscript, or Poppler

**Problem: `expand-shell-outputs.py` fails during docs PDF build**

- Run the failing placeholder command manually from the configured `--cwd` directory and fix its exit status or output assumptions


