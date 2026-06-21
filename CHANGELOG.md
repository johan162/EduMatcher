## [v0.9.1] - 2026-06-21

Release Type: patch

### 📋 Summary
This patch release improves configuration-generation workflows and refreshes the ref-data example set so generated files better expose available defaults to end users. It also includes targeted documentation and training refinements for CALF, RALF, and VM onboarding.

### ✨ Additions
- Added `pm-config-gen` support for emitting comment blocks that list defaultable `engine_config.yaml` fields when values are omitted
- Added expanded ref-data example profiles covering one, three, ten, and thirty-book setups across basic, nominal, and complex variants

### 🚀 Improvements
- Improved market-maker seed generation so configs can emit deterministic midpoint-based startup quotes instead of manual post-processing
- Improved `pm-config-gen` coverage for CALF-oriented configuration generation paths used by example datasets
- Improved generated example configs by regenerating all ref-data outputs with default-field comment visibility enabled

### 📚 Documentation
- Updated User Guide and training material for CALF and RALF workflows with additional operational guidance
- Updated VM installation guidance for a clearer setup path in training flows

### 🛠 Internal
- Updated release assets and example snapshots to align with regenerated config outputs


## [v0.9.0] - 2026-06-21

Release Type: minor

### 📋 Summary
This release fully implements the CALF protocol for market-data dissemination and extends the user-guide with practical examples and operator guidance. It also improves training coverage for CALF and RALF workflows.

### ✨ Additions
- Added CALF protocol implementation with companion documentation and third-party connection examples

### 🚀 Improvements
- Improved gateway operator readiness with a dedicated CALF and RALF runbook

### 📚 Documentation
- Added a new examples section in the User Guide for protocol-oriented workflows
- Updated training and User Guide content with expanded CALF and RALF coverage

### 🛠 Internal
- Improved user-guide structure by renaming appendixes to make room for additional chapters


## [v0.8.0] - 2026-06-20

Release Type: minor

### 📋 Summary
This release adds a turnkey Multipass VM runtime flow so users can bootstrap EduMatcher with a single curl command and run the EuMatcher platform directly in a fresh VM. It also improves onboarding documentation with VM-specific setup and launch guidance.

### ✨ Additions
- Added a Multipass VM provisioning pipeline in `vm/` with automated runtime installation and setup
- Added a curl bootstrap script to download and run the VM build and provisioning scripts without cloning the full repository

### 📚 Documentation
- Updated the docs landing page quick-start section with curl-based VM setup and links to detailed setup guides
- Illustration of Exchange and Order books created and added



## [v0.7.1] - 2026-06-20

Release Type: patch

### 📋 Summary
This patch release hardens cross-platform reliability for the RALF example integration tests, especially on Linux CI runners. It also improves protocol discoverability in the User Guide by adding a dedicated overview page that maps ALF, BALF, CALF, and RALF usage and references.


### 🐛 Bug Fixes
- Fixed Linux PTY read handling in RALF C example tests where EOF can surface as `EIO`
- Fixed Linux portability issues in RALF C example sources and build flags to avoid platform-specific crashes

### 📚 Documentation
- Added an External Protocols Overview chapter describing ALF, BALF, CALF, and RALF purpose, status, and where to find detailed protocol references
- Updated User Guide cross-links so protocol selection and process-level protocol context are easier to discover

### 🛠 Internal
- Cleaned up and refactored RALF example test code to reduce duplication while preserving behavior


## [v0.7.0] - 2026-06-20

Release Type: minor

### 📋 Summary
This release introduces the new RALF post-trade dissemination flow with the `pm-ralf-gwy` gateway, protocol appendix, and external client examples for clearing, drop-copy, and audit consumers. It also extends configuration generation and training content so operators and students can provision and run RALF workflows end to end.

### ✨ Additions
- Added `pm-ralf-gwy` post-trade dissemination gateway with RALF1 session handling, subscriptions, heartbeats, and replay support
- Added RALF protocol and user-guide material including the dedicated post-trade chapter and protocol appendix
- Added Python and C RALF parser and subscriber example libraries in `docs-design/examples/ralf`
- Added a dedicated training chapter for RALF protocol operations covering handshake, subscriptions, replay, and error-handling drills

### 🚀 Improvements
- Improved `pm-config-gen` to optionally emit a top-level `post_trade_gateway` section with configurable RALF listener options
- Improved release packaging to include training bundle artifacts


### 📚 Documentation
- Updated the RALF protocol appendix to explicitly state protocol support is provided through TCP connection to `pm-ralf-gwy`
- Expanded training and user-guide cross-references for new RALF and post-trade workflows


## [v0.6.1] - 2026-06-19

Release Type: patch

### 📋 Summary
This patch release adds a dedicated PDF pipeline for the Training Guide and aligns the training LaTeX templates with a single chapter-level TOC and training-specific cover output. It also updates release packaging to include training PDF artifacts.

### ✨ Additions
- Added a dedicated `training-pdf` Make target that builds all four Training Guide PDF variants into `docs/dist`
- Added release packaging updates so the Training Guide PDF bundle is included in GitHub release artifacts

### 📚 Documentation
- Updated and refined training chapters with improved user-guide cross-links and consistency updates

### 🛠 Internal
- Added a dedicated performance test Make target for easier benchmarking workflows
- Updated CI workflows to remain Node 24 compatible for artifact handling


## [v0.6.0] - 2026-06-19

Release Type: minor

### 📋 Summary
This release adds the new `pm-mm-bot` autonomous market-maker process and expands gateway support for market-maker startup and quote-leg inspection workflows (exposed through the new QBOOT and QLEGS commands). It also adds a self-paced training section which teaches the running and operation of the exchange. The user-guide material was significantly updated and expanded to match the latest release.

### ✨ Additions
- Added `pm-mm-bot` autonomous market-maker process for maintaining two-sided liquidity with session-aware startup, quote refresh, and repricing logic
- Added `QBOOT` command and wire message support for discovering existing active quote bootstrap state during market-maker startup and reconnect flows
- Added `QLEGS` operator command in `pm-gateway` for inspecting active and recently completed quote legs with fill-state visibility
- Added symbol metadata to `system.symbols.{GW}` replies and extended the gateway `SYMBOLS` command to display tick size and MM obligation metadata
- Added new training chapters covering advanced admin operations, drop-copy replay/recovery, and automation with `ExchangeCommandClient` and `pm-mm-bot`

### 🐛 Bug Fixes
- Fixed Mermaid rendering failures in MM design documentation caused by unescaped pipe characters in graph labels

### 📚 Documentation
- Added a full user-guide page for `pm-mm-bot` including CLI usage, bootstrap behavior, session handling, and troubleshooting guidance
- Updated gateway and message documentation to describe `QBOOT`, `QLEGS`, enriched `SYMBOLS` metadata, and MM-oriented operator workflows
- Added self-paced training material across installation, startup, market making, trade lifecycle, observer processes, and advanced operational topics

### 🛠 Internal
- Added latency performance test coverage 


## [v0.5.0] - 2026-06-17

Release Type: minor

### 📋 Summary
This release adds a new `pm-stats-cli` command for querying simulation statistics, refactors the exchange introduction documentation for easier maintenance, and optimizes the PDF build pipeline. It also improves process documentation and updates dependencies.

### ✨ Additions
- Added `pm-stats-cli` command for querying and reporting on simulation statistics stored in `stats.db`, replacing the need for direct SQL access

### 🚀 Improvements
- Improved documentation of all `pm-` CLI commands and processes
- Improved PDF build pipeline to run all builds in full parallel mode for faster build time
- Refactored Exchange Intro documentation into separate chapter files with a Manifest configuration for easier maintenance

### 📚 Documentation
- Added comprehensive statistics and reporting chapter to the User Guide documenting `pm-stats-cli` usage and capabilities
- Fixed broken documentation links in user-guide and related docs

### 🛠 Internal
- Bumped project dependencies to latest versions
- Bumped build-tools to latest version
- Updated default Make target


## [v0.4.0] - 2026-06-16

Release Type: minor

### 📋 Summary
This release focus on improving config documentation and generation. It adds a new `pm-config-gen` CLI for generating 
egine config `engine_config.yaml` file from concise command-line inputs. It also expands the
configuration documentation and design material so users can bootstrap configs
faster with fewer manual YAML errors.

### ✨ Additions
- Added `pm-config-gen` CLI tool for generating `engine_config.yaml` from high-level flags to make it less error prone to correctly write the engine configuration.

### 📚 Documentation
- Expanded the configuration guide with a full `pm-config-gen` reference, option tables, formats, and practical recipes
- Updated Getting Started, Running the Engine, docs landing page, and README quick-start paths to include `pm-config-gen`
- Refreshed configuration examples and design references to match current parser behaviour and defaults
- Improved FAQ
- Updated admonition rendering in Exchange Intro
- Updated various Mermaid graphs in docs

### 🛠 Internal
- Added design proposal for config-generator behaviour, option surface, and implementation plan


## [v0.3.3] - 2026-06-15

Release Type: patch

### 📋 Summary
This patch release hardens the documentation PDF toolchain and refreshes user-guide and architecture documentation. It focuses on reliable Mermaid and admonition rendering in generated PDFs while cleaning up docs build flow and fixing documentation issues.

### ✨ Additions
- Added Mermaid rendering support for User Guide and Design Docs PDF generation

### 🚀 Improvements
- Improved docs build flow by moving PDF bundle orchestration into Makefiles instead of `mkbld.sh`
- Improved docs Makefile consistency by reusing the same `node_modules` build-tools directory across docs pipelines

### 🐛 Bug Fixes
- Fixed PDF rendering of `note` admonitions and Lua-filtered admonition boxes which was missing

### 📚 Documentation
- Updated User Guide content and corrected broken-link references
- Updated architecture descriptions to match the current implementation
- Fixed multiple broken documentation links in the User Guide and related docs


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
