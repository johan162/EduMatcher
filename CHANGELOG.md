## [v0.3.2] - 2026-06-14

Release Type: patch

### 📋 Summary
This patch release refreshes the documentation with an updated landing page and updated developer guidance and new design proposals for cross-host process distribution and statistics CLI reporting. No code changes.

### ✨ Additions
- Added cross-host load-balancing design proposal for running EduMatcher processes across multiple machines
- Added statistics CLI command design proposal to replace error-prone direct SQL querying of `stats.db`

### 📚 Documentation
- Improved documentation landing page structure and navigation for faster onboarding
- Updated developer practice and release workflow guidance to match current checklist and script behaviour
- Refreshed experiments proposal


## [v0.3.1] - 2026-06-14

Release Type: patch

### 📋 Summary
This patch release refreshes the FAQ with practical setup and runtime troubleshooting for the new pipx-based installation flow.

### 📚 Documentation
- Expanded FAQ with a new Installation & Setup section covering pipx vs Poetry usage, PATH issues after pipx install, `pm-setup` usage, config/data file lookup rules, and upgrade guidance
- Added FAQ entries for beginner runtime gotchas: pre-seeded MM liquidity matching the first aggressive order, `seed_once` behaviour across days, CLOSED startup state with sessions enabled, and practical state reset instructions
- Updated FAQ launcher references to `./tools/launch_all.sh` and added `tmux`/`screen` alternatives for server environments

### 🛠 Internal
- Updated GitHub Actions artifact upload steps to `actions/upload-artifact@v5` in CI and docs workflows to eliminate Node 20 deprecation warnings


## [v0.3.0] - 2026-06-14

Release Type: minor

### 📋 Summary
This release makes EduMatcher fully installable as a standalone runtime via `pipx install edumatcher`, with no source checkout or Poetry required for end users. A new `pm-setup` bootstrap command, two runtime environment variables (`EDUMATCHER_DATA_DIR`, `EDUMATCHER_CONFIG`), and an updated launch script give instructors and students a clean, repeatable installation path independent of the development environment.

### ✨ Additions
- Added `pm-setup` entry point to bootstrap a session directory: creates the data directory, copies the bundled sample `engine_config.yaml` to the working directory, and prints a shell profile snippet
- Added `EDUMATCHER_DATA_DIR` environment variable to override the data directory at runtime (default: `~/.local/share/edumatcher` when installed, `src/data/` in a source checkout)
- Added `EDUMATCHER_CONFIG` environment variable to override the engine config path at runtime (default: `./engine_config.yaml` in CWD when installed, repo-root file in a source checkout)
- Added `scripts/install-runtime.sh` one-shot installer: checks Python 3.13+, installs pipx if absent, installs `edumatcher` from PyPI, and runs `pm-setup`
- Bundled `engine_config.sample.yaml` as a package resource (extracted by `pm-setup` via `importlib.resources`)

### 🚀 Improvements
- Updated `tools/launch_all.sh` to detect installed vs source mode automatically: runs bare `pm-*` commands when on PATH, falls back to `poetry run` in a source checkout; exports `EDUMATCHER_DATA_DIR`/`EDUMATCHER_CONFIG` to each spawned Terminal window
- Improved `config.py` resolution: source-tree detection (`_IN_SOURCE_TREE`) keeps the existing developer defaults unchanged while enabling XDG-standard paths for installed users

### 📚 Documentation
- Rewrote Getting Started installation section with separate end-user (pipx) and developer (Poetry) tracks, env var reference table, and `pm-setup` walkthrough
- Added developer vs installed mode comparison table to Running the Exchange page
- Stripped `poetry run` prefix from all command examples in Running the Exchange and Processes pages; added installation-mode admonition and env var reference table to Processes page
- Added admonition in Getting Started five-minute walkthrough explaining that an existing MM seed quote may fill the first aggressive order before the second participant types anything

### 🛠 Internal
- Excluded `setup_cmd.py` from coverage reporting (bootstrap CLI not suitable for unit tests)
- Added `tests/test_config_runtime.py` with 5 tests covering `EDUMATCHER_DATA_DIR` and `EDUMATCHER_CONFIG` env var resolution
- Fixed pyright `reportConstantRedefinition` errors in `config.py` by replacing `if/elif/else` assignments with resolver functions
- Fixed mypy `attr-defined` errors in `test_config_runtime.py` by typing the helper return as `types.ModuleType`

## [v0.2.1] - 2026-06-14

Release Type: patch

### 📋 Summary
This patch release fixes a bug where MM seed quotes were re-injected on every engine restart, introduces the `seed_once` configuration field to control that behaviour, and substantially expands the User Guide with three new sections and comprehensive inline documentation for `engine_config.yaml`.

### ✨ Additions
- Added `seed_once` field to `market_maker_quotes` entries in `engine_config.yaml`: `true` (default) injects quotes only on the first startup for a symbol; `false` re-injects on every restart for repeatable demo setups
- Added Getting Started user guide section with architecture overview, minimum session walkthrough, and role-based reading path
- Added Market Making user guide section covering QUOTE command, quote lifecycle, quote refresh policies, MM obligations, MMP sequence, disconnect behaviour, and startup seeding
- Added AI Traders user guide section covering `pm-ai-trader` and `pm-ai-swarm`, personality profiles, decision loop, risk mechanisms, and classroom demo setup
- Added CLI Statistics commands design proposal identifying server-side commands for querying `stats.db` without raw SQL

### 🐛 Bug Fixes
- Fixed GTC quote legs being written to `gtc_orders.json` at shutdown, causing duplicate resting orders in the book on subsequent engine restarts

### 📚 Documentation
- Rewrote `engine_config.yaml` as a fully annotated reference covering all supported fields, precedence rules, and enum values; added examples of all three gateway roles (TRADER, MARKET_MAKER, ADMIN), per-symbol `mm_obligations` overrides, circuit-breaker level merging, and `seed_once` behaviour
- Expanded persistence user guide section with complete schema reference for `audit.log`, `clearing_report.csv`, and `stats.db` (DDL, column descriptions, example SQL queries)
- Added See Also footers to all user guide sections that lacked them
- Converted remaining ASCII diagrams to Mermaid in combo, auction/scheduling, drop-copy, and persistence sections
- Expanded PnL/clearing, gateway, and configuration sections with additional detail and worked examples

### 🛠 Internal
- Fixed black formatting violation in `config_loader.py`
- Made Exchange Intro PDF build optional in `mkbld.sh` behind a new `--intro` flag

## [v0.2.0] - 2026-06-14

Release Type: minor

### 📋 Summary
This release completes the protocol design documentation suite by publishing the BALF design proposal at v1.0.0 and integrating both BALF and CALF protocol appendixes into the User Guide. It marks the first minor version increment, establishing a stable baseline for the full protocol documentation set.

### 📚 Documentation
- Update glossary and sync global and Exchange Intro glossary

### ✨ Additions
- Added BALF protocol design proposal v1.0.0 covering allocation, liquidity, and feed mechanics
- Added BALF protocol description appendix to the User Guide
- Added CALF protocol appendix to the User Guide with harmonized terminology across all protocol appendixes

## [v0.1.9] - 2026-06-13

Release Type: patch

### 📋 Summary
This patch release expands the concept documentation with a new CALF market-data feed page, improves clarity across existing order-book pages, and reorganises the Glossary. GitHub Actions are also updated to be Node 24 compatible.
## [v0.3.0] - 2026-06-14

Release Type: minor

### 📋 Summary
This release makes EduMatcher fully installable as a standalone runtime via `pipx install edumatcher`, with no source checkout or Poetry required for end users. A new `pm-setup` bootstrap command, two runtime environment variables (`EDUMATCHER_DATA_DIR`, `EDUMATCHER_CONFIG`), and an updated launch script give instructors and students a clean, repeatable installation path independent of the development environment.

### ✨ Additions
- Added `pm-setup` entry point to bootstrap a session directory: creates the data directory, copies the bundled sample `engine_config.yaml` to the working directory, and prints a shell profile snippet
- Added `EDUMATCHER_DATA_DIR` environment variable to override the data directory at runtime (default: `~/.local/share/edumatcher` when installed, `src/data/` in a source checkout)
- Added `EDUMATCHER_CONFIG` environment variable to override the engine config path at runtime (default: `./engine_config.yaml` in CWD when installed, repo-root file in a source checkout)
- Added `scripts/install-runtime.sh` one-shot installer: checks Python 3.13+, installs pipx if absent, installs `edumatcher` from PyPI, and runs `pm-setup`
- Bundled `engine_config.sample.yaml` as a package resource (extracted by `pm-setup` via `importlib.resources`)

### 🚀 Improvements
- Updated `tools/launch_all.sh` to detect installed vs source mode automatically: runs bare `pm-*` commands when on PATH, falls back to `poetry run` in a source checkout; exports `EDUMATCHER_DATA_DIR`/`EDUMATCHER_CONFIG` to each spawned Terminal window
- Improved `config.py` resolution: source-tree detection (`_IN_SOURCE_TREE`) keeps the existing developer defaults unchanged while enabling XDG-standard paths for installed users

### 📚 Documentation
- Rewrote Getting Started installation section with separate end-user (pipx) and developer (Poetry) tracks, env var reference table, and `pm-setup` walkthrough
- Added developer vs installed mode comparison table to Running the Exchange page
- Stripped `poetry run` prefix from all command examples in Running the Exchange and Processes pages; added installation-mode admonition and env var reference table to Processes page
- Added admonition in Getting Started five-minute walkthrough explaining that an existing MM seed quote may fill the first aggressive order before the second participant types anything

### 🛠 Internal
- Excluded `setup_cmd.py` from coverage reporting (bootstrap CLI not suitable for unit tests)
- Added `tests/test_config_runtime.py` with 5 tests covering `EDUMATCHER_DATA_DIR` and `EDUMATCHER_CONFIG` env var resolution
- Fixed pyright `reportConstantRedefinition` errors in `config.py` by replacing `if/elif/else` assignments with resolver functions
- Fixed mypy `attr-defined` errors in `test_config_runtime.py` by typing the helper return as `types.ModuleType`

## [v0.2.1] - 2026-06-14

Release Type: patch

### 📋 Summary
This patch release fixes a bug where MM seed quotes were re-injected on every engine restart, introduces the `seed_once` configuration field to control that behaviour, and substantially expands the User Guide with three new sections and comprehensive inline documentation for `engine_config.yaml`.

### ✨ Additions
- Added `seed_once` field to `market_maker_quotes` entries in `engine_config.yaml`: `true` (default) injects quotes only on the first startup for a symbol; `false` re-injects on every restart for repeatable demo setups
- Added Getting Started user guide section with architecture overview, minimum session walkthrough, and role-based reading path
- Added Market Making user guide section covering QUOTE command, quote lifecycle, quote refresh policies, MM obligations, MMP sequence, disconnect behaviour, and startup seeding
- Added AI Traders user guide section covering `pm-ai-trader` and `pm-ai-swarm`, personality profiles, decision loop, risk mechanisms, and classroom demo setup
- Added CLI Statistics commands design proposal identifying server-side commands for querying `stats.db` without raw SQL

### 🐛 Bug Fixes
- Fixed GTC quote legs being written to `gtc_orders.json` at shutdown, causing duplicate resting orders in the book on subsequent engine restarts

### 📚 Documentation
- Rewrote `engine_config.yaml` as a fully annotated reference covering all supported fields, precedence rules, and enum values; added examples of all three gateway roles (TRADER, MARKET_MAKER, ADMIN), per-symbol `mm_obligations` overrides, circuit-breaker level merging, and `seed_once` behaviour
- Expanded persistence user guide section with complete schema reference for `audit.log`, `clearing_report.csv`, and `stats.db` (DDL, column descriptions, example SQL queries)
- Added See Also footers to all user guide sections that lacked them
- Converted remaining ASCII diagrams to Mermaid in combo, auction/scheduling, drop-copy, and persistence sections
- Expanded PnL/clearing, gateway, and configuration sections with additional detail and worked examples

### 🛠 Internal
- Fixed black formatting violation in `config_loader.py`
- Made Exchange Intro PDF build optional in `mkbld.sh` behind a new `--intro` flag

## [v0.2.0] - 2026-06-14

Release Type: minor

### 📋 Summary
This release completes the protocol design documentation suite by publishing the BALF design proposal at v1.0.0 and integrating both BALF and CALF protocol appendixes into the User Guide. It marks the first minor version increment, establishing a stable baseline for the full protocol documentation set.

### 📚 Documentation
- Update glossary and sync global and Exchange Intro glossary

### ✨ Additions
- Added BALF protocol design proposal v1.0.0 covering allocation, liquidity, and feed mechanics
- Added BALF protocol description appendix to the User Guide
- Added CALF protocol appendix to the User Guide with harmonized terminology across all protocol appendixes

## [v0.1.9] - 2026-06-13

Release Type: patch

### 📋 Summary
This patch release expands the concept documentation with a new CALF market-data feed page, improves clarity across existing order-book pages, and reorganises the Glossary. GitHub Actions are also updated to be Node 24 compatible.

### 📚 Documentation
- Added new concept page explaining the CALF market-data protocol: channels, subscription flow, sequence-based gap detection, reconnect behaviour, and index dissemination
- Improved wording and corrected depth examples in the order book introduction
- Moved glossary terms from the order-book deep-dive page into the main Glossary section

### 🛠 Internal
- Updated GitHub Actions workflows and composite action to use Node 24 compatible action versions (`checkout@v5`, `setup-python@v6`, `cache@v5`)


## [v0.1.8] - 2026-06-13

Release Type: patch

### 📋 Summary
This patch release fixes chapter numbering in generated User Guide PDFs and cleans up related documentation build templates and Makefile flow.

### 🐛 Bug Fixes
- Fixed User Guide chapter numbering by switching LaTeX templates from front matter to main matter before chapter content
- Fixed incorrect imprint text in User Guide templates

### 🛠 Internal
- Cleaned up docs Makefile pipeline and template handling for PDF generation


## [v0.1.7] - 2026-06-13

Release Type: patch

### 📋 Summary
This patch release improves documentation usability by adding light and dark viewing modes for the doc-site

### 📚 Documentation
- Updated documentation theming to support both light and dark presentation modes
- Added repo link in doc eadings


## [v0.1.6] - 2026-06-13

Release Type: patch

### 📋 Summary
This patch release cleans up release artifact layout so Python distributions stay at the top level while documentation PDFs remain in their own build directories.

### 🛠 Internal
- Kept Python distribution artifacts in the top-level dist directory for publishing
- Kept documentation PDF builds in the docs dist directories to avoid mixing release assets
- Add PyPi publishing


## [v0.1.5] - 2026-06-13

Release Type: patch

### 📋 Summary
This patch release improves the release automation flow by fixing GitHub release script issues and tightening package validation behavior during publication.

### 🚀 Improvements
- Improved release packaging validation to only verify Python distribution artifacts with Twine

### 🐛 Bug Fixes
- Fixed GitHub release script behavior during release execution


## [v0.1.4] - 2026-06-13

Release Type: patch

### 📋 Summary
This patch release improves the documentation build and release workflow while expanding the market data and index design documentation set. It also streamlines artifact generation to reduce duplicate build work.

### 🚀 Improvements
- Improved build and release scripts to avoid duplicate artifact builds
- Improved documentation PDF pipeline by cleaning Markdown inputs before rendering
- Improved visual documentation by replacing an ASCII graph with a Mermaid diagram

### 📚 Documentation
- Added index calculation design documentation
- Updated CALF design proposal content
- Fixed README documentation site URL

### 🛠 Internal
- Updated User Guide LaTeX templates to include a cover page for book-style output


## [v0.1.3] - 2026-06-11

Release Type: patch

### 📋 Summary
This patch release fixes issues in the GitHub release automation flow and stabilizes post-release branch synchronization after v0.1.2.

### 🐛 Bug Fixes
- Fixed GitHub release script behavior for release creation flow

### 🛠 Internal
- Updated release branch synchronization after v0.1.2


## [v0.1.2] - 2026-06-11

Release Type: patch

### 📋 Summary
This patch release extends the release pipeline to build and bundle the Exchange Introduction document alongside the main package, producing a ZIP archive of all four PDF variants as a release asset.

### 🚀 Improvements
- Improved release build to include Exchange Intro PDF generation in parallel with the main docs build

### 🛠 Internal
- Added ZIP bundling of Exchange Intro PDFs into a single release asset archive
- Updated main build target to invoke the Exchange Intro build step


## [v0.1.1] - 2026-06-11

Release Type: patch

### 📋 Summary
This patch release hardens the first-time release workflow after the initial public launch. It focuses on branch initialization and merge-path clarity so releases from develop to main complete predictably.

### 🛠 Internal
- Improved release script messaging around preconditions for squash merges
- Updated release process checks to surface branch-state issues earlier


## [v0.1.0] - 2026-06-11

Release Type: minor

### 📋 Summary
This is the inaugural public release of EduMatcher, featuring a complete educational matching engine with all essential exchange functionality. Designed for educational purposes, the engine implements realistic order matching, market data, and session management while intentionally omitting authentication and authorization to focus on core exchange principles.

### ✨ Additions
- Added complete order matching engine supporting multiple order types and matching algorithms
- Added market data management and quote generation
- Added session and trading day management
- Added participant and instrument registry
- Added CLI for engine simulation and introspection
- Added MCP (Model Context Protocol) server for AI model integration
- Added comprehensive exchange architecture documentation
- Added Python API for programmatic access to matching engine

### 🚀 Improvements
- Optimized matching performance for high-volume order streams
- Implemented efficient message handling and session state tracking

### 📚 Documentation
- Added complete user guide and architecture documentation
- Added full introduction to principles of an Exchange
- Added glossary and exchange concepts reference
- Added quick-start examples and API reference
- Added integration guide for MCP server usage

### 🛠 Internal
- Established comprehensive test coverage for matching logic and order types
- Configured Poetry-based development environment with dev, docs, and MCP extras
- Set up CI/CD pipeline and automated testing
- Configured code quality checks (type checking, linting, formatting)
- Added build system for PDF documentation generation
