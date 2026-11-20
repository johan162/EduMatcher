"""Where EduMatcher keeps its data by default, with no side effects.

``edumatcher.config`` resolves the data directory once, at import, and warns
when it does not exist. ``pm-setup`` has to ask the same question *before*
the directory exists -- to create it -- so the preference lives here, in a
module whose import does nothing.
"""

from __future__ import annotations

import os
from pathlib import Path

# Detect whether we are running from a source checkout.  data_dir.py lives at
# src/edumatcher/data_dir.py; when installed via pip/pipx it lives somewhere
# inside site-packages and the parent directory is NOT named "src".
_pkg_dir = Path(__file__).parent  # .../edumatcher/
_src_dir = _pkg_dir.parent  # .../src/   (source) or site-packages (installed)
_IN_SOURCE_TREE: bool = _src_dir.name == "src"


def data_dir_preference() -> tuple[Path, str]:
    """Return the data directory implied by tiers 1-3, without checking
    whether it exists.

    This is the single source of truth for "where does EduMatcher put its
    data by default" — shared by the runtime resolver in
    ``edumatcher.config`` (which adds an existence check and a
    host/container fallback on top) and by
    ``pm-setup``, which needs the same preference to decide where to
    *create* the data directory in the first place, before anything exists
    to check.
    """
    _env = os.environ.get("EDUMATCHER_DATA_DIR")
    if _env:
        return Path(_env).expanduser().resolve(), "EDUMATCHER_DATA_DIR"
    if _IN_SOURCE_TREE:
        return _src_dir / "data", "source-tree default"
    return Path("~/.local/share/edumatcher").expanduser(), "installed default"
