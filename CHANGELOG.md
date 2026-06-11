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
