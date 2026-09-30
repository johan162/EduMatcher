"""Exchange state that must be absent before a symbol is listed."""

from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from edumatcher.config import (
    BOOK_STATS_FILE,
    ENGINE_PUB_ADDR,
    GTC_COMBOS_FILE,
    GTC_ORDERS_FILE,
)


def engine_running() -> str | None:
    """Why the engine may be running, or None when it is not."""
    address = urlsplit(ENGINE_PUB_ADDR)
    try:
        with socket.create_connection(
            (address.hostname or "127.0.0.1", address.port or 5556), timeout=0.3
        ):
            return f"something is listening on {ENGINE_PUB_ADDR}"
    except OSError:
        pass
    try:
        result = subprocess.run(
            # Anchored so a log file such as emo/pm-engine.log does not match.
            ["pgrep", "-f", r"(^|/)pm-engine( |$)"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "pgrep is unavailable, so a running pm-engine cannot be ruled out"
    pids = [pid for pid in result.stdout.split() if pid.isdigit()]
    return f"pm-engine is running (pid {', '.join(pids)})" if pids else None


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # the engine treats an unreadable file as empty too


def saved_state(symbol: str) -> list[str]:
    """Saved engine state for *symbol*, which would override the listing."""
    found: list[str] = []
    stats = _load_json(BOOK_STATS_FILE)
    if isinstance(stats, dict) and symbol in stats:
        found.append(f"{BOOK_STATS_FILE}: last prices")
    orders = _load_json(GTC_ORDERS_FILE)
    if isinstance(orders, list):
        count = sum(
            1 for o in orders if isinstance(o, dict) and o.get("symbol") == symbol
        )
        if count:
            found.append(f"{GTC_ORDERS_FILE}: {count} resting order(s)")
    combos = _load_json(GTC_COMBOS_FILE)
    if isinstance(combos, list):
        count = sum(
            1
            for c in combos
            if isinstance(c, dict)
            and any(
                isinstance(leg, dict) and leg.get("symbol") == symbol
                for leg in c.get("legs") or []
            )
        )
        if count:
            found.append(f"{GTC_COMBOS_FILE}: {count} resting combo(s)")
    return found
