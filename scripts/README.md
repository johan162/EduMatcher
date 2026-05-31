# Build Scripts

This directory contains the maintenance scripts for `mcprojsim`.
They support local development, CI validation, release preparation,
documentation workflows, setup verification, and containerized docs serving.

# Table of Contents

- [Build Scripts](#build-scripts)
- [Table of Contents](#table-of-contents)
  - [Script Conventions](#script-conventions)
  - [Scripts Overview](#scripts-overview)
    - [`mkchlogentry.sh` - CHANGELOG Entry Script](#mkchlogentrysh---changelog-entry-script)
    - [`mkbld.sh` - Main Build Script](#mkbldsh---main-build-script)
    - [`mkcovupd.sh` - Coverage Badge Updater](#mkcovupdsh---coverage-badge-updater)
    - [`mkrelease.sh` - Release Automation Script](#mkreleasesh---release-automation-script)
    - [`mkrelease2.sh` - CI-Delegating Release Script](#mkrelease2sh---ci-delegating-release-script)
    - [`mkghrelease.sh` - GitHub Release Creator](#mkghreleasesh---github-release-creator)
    - [`mkmcpbundle.sh` - MCP Bundle Builder](#mkmcpbundlesh---mcp-bundle-builder)
    - [`mkdocs.sh` - Documentation Automation Script](#mkdocssh---documentation-automation-script)
    - [`gen-examples.sh` - Examples Page Generator](#gen-examplessh---examples-page-generator)
    - [`gen_nb_sickness_example.py` - NB Sickness Example Generator](#gen_nb_sickness_examplepy---nb-sickness-example-generator)
    - [`verify_setup.sh` - Local Setup Verification](#verify_setupsh---local-setup-verification)
    - [`docs-contctl.sh` - Containerized Docs Server Manager](#docs-contctlsh---containerized-docs-server-manager)
    - [`pandoc_sprint_planning_table_widths.lua` - Pandoc Lua Filter](#pandoc_sprint_planning_table_widthslua---pandoc-lua-filter)
  - [Typical Workflows](#typical-workflows)
    - [Daily Development Check](#daily-development-check)
    - [Fresh Local Setup Verification](#fresh-local-setup-verification)
    - [Documentation Workflows](#documentation-workflows)
    - [Release Workflow](#release-workflow)
  - [Troubleshooting](#troubleshooting)
  - [Related Files](#related-files)


## Script Conventions

- Most scripts support `--help`.
- Several scripts support `--dry-run`, but not all do.
- The project is Poetry-based, so the scripts generally assume `poetry` is installed.
- Scripts that are meant for guarded automation typically exit on the first error.

## Scripts Overview

### `mkbld.sh` - Main Build Script

Runs the main quality and packaging pipeline and is the primary script used by CI.

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

**Requirements:**
- Poetry installed and available on `PATH`
- Development dependencies installed: `poetry install --with dev`
- Run from the project root

**Outputs:**
- `coverage.xml`
- `htmlcov/`
- `dist/`

### `mkchlogentry.sh` - CHANGELOG Entry Script

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


### `mkrelease2.sh` - CI-Delegating Release Script

Alternative release script that merges to `main` and pushes, then delegates all quality gates, tagging, GitHub Release creation, and PyPI publishing to CI.

```bash
./scripts/mkrelease2.sh <version> [major|minor|patch] [OPTIONS]
```

**What it does:**
1. Validates the repo state
2. Bumps the version and updates `CHANGELOG.md` on `develop`
3. Commits and pushes `develop`
4. Squash-merges `develop` → `main` and pushes
5. Merges `main` → `develop` (back-merge) and pushes

CI then automatically runs lint, type-checking, and tests; builds and verifies artifacts; creates the git tag and GitHub Release; and publishes to PyPI.

**Options:**
- `--dry-run` - Preview without making changes
- `--help`, `-h` - Display help message

**When to prefer this over `mkrelease.sh`:**
- Use `mkrelease2.sh` when your CI pipeline is configured to handle tagging and publishing automatically on merge to `main`.
- Use `mkrelease.sh` for a fully local release pipeline where you run quality gates before pushing.


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


### `mkmcpbundle.sh` - MCP Bundle Builder

Creates a versioned MCP server bundle zip file containing a manifest, a bootstrap script, and the project wheel.
Useful for distributing the MCP server independently of PyPI.

```bash
./scripts/mkmcpbundle.sh [OPTIONS]
```

**What it does:**
1. Reads the version from `pyproject.toml`
2. Ensures a wheel exists in `dist/` (builds one if missing)
3. Creates a bundle payload containing `manifest.json`, `bootstrap.sh`, and `README.md`
4. Produces a versioned zip archive in `dist/`

**Options:**
- `--help` - Display help message

**Requirements:**
- `mkbld.sh` should be run first to ensure the wheel is up to date
- Run from the project root


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

### `verify_setup.sh` - Local Setup Verification

Verifies that a local Poetry-based installation is working end to end.

```bash
./scripts/verify_setup.sh
```

**What it does:**
1. Verifies Poetry is installed
2. Installs dependencies with `poetry install --with dev`
3. Checks that the `mcprojsim` CLI is available
4. Validates the sample project file
5. Runs a short simulation
6. Confirms expected output files are created
7. Verifies the configuration command works

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
- `MCPROJSIM_DOCS_IMAGE` - Override image name
- `MCPROJSIM_DOCS_PORT` - Override default port
- `MCPROJSIM_USE_PROXY_CA=true` - Build with proxy CA support

**When to use it:**
- Use this script when you want the docs served from the same containerized environment used for docs image validation
- Prefer `make docs-serve` or `poetry run mkdocs serve` for the fastest local editing feedback

### `gen-examples.sh` - Examples Page Generator

Generates `docs/examples.md` from the template `docs/examples_template.md` by expanding two placeholder types.

```bash
./scripts/gen-examples.sh [--jobs N] [template] [output]
# or
make gen-examples
```

**Placeholder types:**
- `{{file:path}}` — inserts file contents in a fenced code block (language auto-detected from extension)
- `{{run:command}}` — emits the user-facing command in a `bash` block, then inserts captured output in a `text` block

**What it does:**
1. **Pass 1** — scans the template for `{{run:...}}` commands, executes each unique command in parallel, and caches outputs under `.build/gen-examples/runs/`
2. **Pass 2** — renders the final markdown by expanding all `{{file:...}}` and `{{run:...}}` placeholders using the cached outputs

**Options:**
- `--jobs N` — max number of parallel Pass 1 commands (`0` = no limit; default)
- `--help` — display help message

**Requirements:**
- Run from the project root
- `mcprojsim` must be installed and on `PATH` (or via `poetry run`) for `{{run:...}}` commands to produce output

### `gen_nb_sickness_example.py` - NB Sickness Example Generator

One-shot Python script that (re)generates `examples/sprint_nb_sickness_large.yaml` — a 60-task sprint planning example with a Negative Binomial velocity model and sickness modelling enabled.

```bash
poetry run python scripts/gen_nb_sickness_example.py
```

**What it does:**
- Generates 60 tasks with lognormal estimates (story point sizes 3, 5, 8, 12) using a fixed random seed
- First 30 tasks are independent; the remaining 30 each have 1–3 dependencies
- Writes the YAML file directly to `examples/sprint_nb_sickness_large.yaml`

**Requirements:**
- `pyyaml` available (included in the `dev` and `mcp` dependency groups)
- Run from the project root

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
poetry run pytest --cov=src/mcprojsim --cov-report=xml
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

**Problem: `pandoc_sprint_planning_table_widths.lua` not applied**

- Ensure Pandoc is installed and that you pass `--lua-filter scripts/pandoc_sprint_planning_table_widths.lua` explicitly on the command line

## Related Files

## Support Files

### `pandoc_sprint_planning_table_widths.lua` - Pandoc Lua Filter

A Pandoc Lua filter that overrides column widths for 3-column tables when converting sprint planning documentation to LaTeX/PDF output.
It is not a standalone script — it is passed to `pandoc` via `--lua-filter`.

```bash
pandoc docs/user_guide/sprint_planning.md \
  --lua-filter scripts/pandoc_sprint_planning_table_widths.lua \
  -o sprint_planning.pdf
```

**Behavior:**
- Only activates for LaTeX/PDF output (`FORMAT == "latex"`)
- Only applies to tables with exactly 3 columns
- Sets proportional column widths appropriate for the sprint planning reference table layout

**Requirements:**
- Pandoc installed (`brew install pandoc` or equivalent)
- A LaTeX distribution for PDF output (e.g. MacTeX / TeX Live)

- [Makefile](../Makefile) - Thin wrappers for common development and docs commands
- [README.md](../README.md) - Main project usage and installation guide
- [QUICKSTART.md](../QUICKSTART.md) - End-user quick start guide
- [GitHub workflows](../.github/workflows/) - CI/CD automation
