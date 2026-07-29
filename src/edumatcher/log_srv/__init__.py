"""``pm-log-srv`` — the centralized LALF log-collector process.

See docs-design/EduMatcher-log-srv.md for the design; §5/§15 for the LALF
wire protocol this package's :mod:`edumatcher.log_srv.server` speaks, and
§6 for the SQLite schema in :mod:`edumatcher.log_srv.schema`.
"""

from __future__ import annotations
