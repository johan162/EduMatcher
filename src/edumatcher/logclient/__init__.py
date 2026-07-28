"""LALF (Logging ALF) protocol client-side support.

This package holds the pieces phase 1 of the log-server work ships: the
wire-protocol codec (:mod:`edumatcher.logclient.protocol`) used by both
``pm-log-srv`` and any LALF client. ``TcpLogHandler`` (the ``logging.Handler``
that plugs into every other ``pm-*`` process's ``_configure_logging()``) is
phase 2 work — see docs-design/EduMatcher-log-srv.md §8 and §12
(Implementation Plan) for the phased rollout this package is the foundation
for.
"""

from __future__ import annotations
