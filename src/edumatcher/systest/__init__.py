"""``pm-systest``: the system-level trading verification framework.

This package starts a real multi-process EduMatcher deployment, drives it
through the ALF and REST order-entry transports using a declarative Scenario
DSL, and asserts that the resulting matching outcome, order lifecycle, book
state, and dissemination fan-out (CALF, RALF, drop copy, WebSocket, audit
journal, stats, clearing) are identical across transports and stable across
runs.

See ``docs-design/EduMatcher-System-Trading-Verification.md`` and the
``system-trading-verification`` spec for the framework's architecture,
Scenario DSL, driver protocol, canonicalisation rules, and invariant set.
"""
