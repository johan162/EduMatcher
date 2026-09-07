"""The REST + WebSocket transport Driver, against ``pm-api-gwy``.

Implements the ``Driver`` protocol over the REST API, treating the
WebSocket stream as the authoritative acknowledgement source for order
entry, cancel, and amend calls, with per-Actor sequence-gap detection and
acknowledgement-timeout handling.

See design.md Components §6 (REST Driver).
"""
