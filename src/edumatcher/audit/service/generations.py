"""Read-model generations of a snapshot (workplan AG9, design §7.2).

A generation is a directory the worker builds in scratch and then moves into
``<snapshot>/generations/<n>`` in one rename; ``CURRENT`` names the newest
and is replaced atomically after it. A reader resolves a generation once and
keeps reading it: a rebuild never changes what an open page or cursor sees.
The newest :data:`KEEP` generations are kept; an older one is removed, and a
cursor into it is told so (``GenerationExpired``) rather than moved.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

#: Generations kept: the current one and the one before it.
KEEP = 2
_DIR = "generations"
_CURRENT = "CURRENT"


def current(snapshot_dir: Path) -> int | None:
    """The published generation, or None before the first."""
    try:
        return int((snapshot_dir / _CURRENT).read_text(encoding="utf-8").strip())
    except FileNotFoundError, ValueError:
        return None


def path(snapshot_dir: Path, generation: int) -> Path:
    return snapshot_dir / _DIR / str(generation)


def exists(snapshot_dir: Path, generation: int) -> bool:
    return path(snapshot_dir, generation).is_dir()


def publish(snapshot_dir: Path, built: Path) -> int:
    """Install the complete directory `built` as the next generation and
    make it current; prune all but the newest :data:`KEEP`."""
    generation = (current(snapshot_dir) or 0) + 1
    target = path(snapshot_dir, generation)
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(built, target)
    fd, tmp = tempfile.mkstemp(dir=snapshot_dir, prefix=".current-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(f"{generation}\n")
    os.replace(tmp, snapshot_dir / _CURRENT)
    for old in (snapshot_dir / _DIR).iterdir():
        if old.name.isdigit() and int(old.name) <= generation - KEEP:
            shutil.rmtree(old, ignore_errors=True)
    return generation
