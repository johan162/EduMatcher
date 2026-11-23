"""Exchange state that must be absent before a symbol is listed."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from edumatcher.config import (
    BOOK_STATS_FILE,
    ENGINE_PUB_ADDR,
    GTC_COMBOS_FILE,
    GTC_ORDERS_FILE,
)
from edumatcher.emo.cli import pm_processes
from edumatcher.engine.persistence import atomic_write_text


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
    # By the program, not by text anywhere on a command line: a wrapper shell,
    # a tmux or watch command naming .../pm-engine is not an engine. An
    # engine of another user still holds the port probed above.
    pids = [str(proc.pid) for proc, program in pm_processes() if program == "pm-engine"]
    return f"pm-engine is running (pid {', '.join(pids)})" if pids else None


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
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


def _has_leg(combo: Any, symbol: str) -> bool:
    return isinstance(combo, dict) and any(
        isinstance(leg, dict) and leg.get("symbol") == symbol
        for leg in combo.get("legs") or []
    )


def discard_saved_state(symbol: str) -> list[str]:
    """Remove *symbol*'s saved state, and nothing else; say what went.

    Its book statistics, its resting orders, and every combo with a leg in
    it, together with that combo's leg orders in other symbols: a combo is
    one order, and its legs would be restored pointing at a combo that is
    gone. Everything else is written back exactly as it was read. Only with
    the engine stopped: it rewrites these files at its next checkpoint.
    """
    removed: list[str] = []
    stats = _load_json(BOOK_STATS_FILE)
    if isinstance(stats, dict) and symbol in stats:
        del stats[symbol]
        atomic_write_text(BOOK_STATS_FILE, json.dumps(stats, indent=2))
        removed.append(f"{BOOK_STATS_FILE}: last prices")
    leg_ids: set[str] = set()
    combos = _load_json(GTC_COMBOS_FILE)
    if isinstance(combos, list):
        gone = [c for c in combos if _has_leg(c, symbol)]
        if gone:
            for combo in gone:
                leg_ids.update(str(i) for i in combo.get("child_order_ids") or [])
            kept = [c for c in combos if not _has_leg(c, symbol)]
            atomic_write_text(GTC_COMBOS_FILE, json.dumps(kept, indent=2))
            removed.append(f"{GTC_COMBOS_FILE}: {len(gone)} resting combo(s)")
    orders = _load_json(GTC_ORDERS_FILE)
    if isinstance(orders, list):
        kept_orders = [
            o
            for o in orders
            if not (
                isinstance(o, dict)
                and (o.get("symbol") == symbol or str(o.get("id")) in leg_ids)
            )
        ]
        if len(kept_orders) != len(orders):
            atomic_write_text(GTC_ORDERS_FILE, json.dumps(kept_orders, indent=2))
            removed.append(
                f"{GTC_ORDERS_FILE}: {len(orders) - len(kept_orders)} resting "
                "order(s), combo legs included"
            )
    return removed


def other_processes() -> list[str]:
    """The pm-* programs of this user still running, other than the engine
    (refused outright): each read the configuration when it started, so it
    keeps the old symbol list until it is restarted."""
    return [
        f"{program} (pid {proc.pid})"
        for proc, program in pm_processes()
        if program != "pm-engine"
    ]
