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
