"""LALF (Logging ALF) protocol client-side support.

- :mod:`edumatcher.logclient.protocol`: the wire-protocol codec, shared by
  ``pm-log-srv`` and every LALF client.
- :mod:`edumatcher.logclient.handler`: ``TcpLogHandler``, the
  ``logging.Handler`` that ships a process's records to ``pm-log-srv`` and
  falls back to a local file when it stays unreachable.
- :mod:`edumatcher.logclient.discovery`: ``resolve_handler``, the start-up
  probe every ``pm-*`` entry point's ``_configure_logging()`` calls to pick
  that handler or the console.

Design: docs-design/EduMatcher-log-srv.md §8.
"""

from __future__ import annotations
