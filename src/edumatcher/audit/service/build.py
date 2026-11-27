"""Build one read-model generation of a snapshot (workplan AG9).

The only place the Audit GUI reconstructs a session, and it runs in the
worker process, never in the API (design §7.3). It reads the snapshot's
pinned records through the replay library (``normalise``, ``ordered``, the
reconstruction, detectors and episode assembler: no business rule here) and
writes, into a directory that is published only when complete:

``events.db``
    the canonical event rows of ``/events`` (zlib-compressed JSON: book
    records carry their recent trades, and rows are only read by position)
    with the columns its filters use;
``replay.db``
    pm-audit-replay's episode index (stories, findings);
``market.db``
    the market model (heatmap, lifelines);
``meta.json``
    what was built, from how many records, by which version and settings.
"""

from __future__ import annotations

import json
import sqlite3
import zlib
from collections.abc import Callable
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from edumatcher.audit.replay import index as episode_index
from edumatcher.audit.replay.detect import (
    DEFAULT_CLOCK_SKEW_WARN,
    Detector,
    detected,
    observed,
)
from edumatcher.audit.replay.episodes import assemble
from edumatcher.audit.replay.facts import Fact, normalise
from edumatcher.audit.replay.ordering import ordered
from edumatcher.audit.replay.pipeline import Reconstruction
from edumatcher.audit.service.market import MarketModel
from edumatcher.audit.service.rows import event_row
from edumatcher.audit.service.snapshot import Snapshot
from edumatcher.cli_version import package_version
from edumatcher.models.generated.order import TOPIC_ORDER_NEW

#: The detection settings the index is built with: pm-audit-replay's
#: defaults, spelled as its ``detection_key`` spells them.
DETECTION = f"strict=0 clock_skew={DEFAULT_CLOCK_SKEW_WARN:g}"
EVENTS = "events.db"
INDEX = "replay.db"
MARKET = "market.db"
META = "meta.json"

#: Records between two progress reports (each may stop the build).
_STEP = 2000

#: ``report(stage, done, total)``: progress, and the build's chance to stop
#: (it raises to cancel or time out).
Report = Callable[[str, int | None, int | None], None]


def build_generation(snapshot: Snapshot, out: Path, report: Report) -> dict[str, Any]:
    """Build every read model of `snapshot` into the new directory `out`."""
    out.mkdir(parents=True)
    total = snapshot.descriptor.entries
    facts: list[Fact] = []
    report("reading", 0, total)
    for fact in ordered(normalise(snapshot.entries())):
        facts.append(fact)
        if len(facts) % _STEP == 0:
            report("reading", len(facts), total)
    report("reading", len(facts), total)

    _write_events(out / EVENTS, facts, report)

    report("indexing", None, None)
    run = Reconstruction()
    detector = Detector(run.state)
    episodes = detected(
        assemble(observed(run.run(facts), detector), run.state, run.links),
        detector,
    )
    episode_index.build(out / INDEX, episodes, run.state, snapshot.paths(), detection=DETECTION)  # fmt: skip

    report("market", None, None)
    MarketModel(facts).dump(out / MARKET)

    meta = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "records": len(facts),
        "detection": DETECTION,
        "version": package_version(),
    }
    (out / META).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def _write_events(path: Path, facts: list[Fact], report: Report) -> None:
    """The canonical rows, with the columns ``EventFilter`` queries."""
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript("""
            CREATE TABLE events (
                pos INTEGER PRIMARY KEY, topic TEXT NOT NULL, symbol TEXT,
                actor TEXT, gateway TEXT, row BLOB NOT NULL);
            CREATE TABLE event_orders (order_id TEXT NOT NULL, pos INTEGER NOT NULL);
            """)
        for pos, f in enumerate(facts):
            p = f.payload
            gateway = p.get("gateway_id")
            conn.execute(
                "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
                (
                    pos,
                    f.topic,
                    f.symbol,
                    f.actor,
                    gateway if isinstance(gateway, str) else None,
                    zlib.compress(json.dumps(event_row(f)).encode(), 1),
                ),
            )
            ids = {p.get("order_id"), p.get("buy_order_id"), p.get("sell_order_id")}
            if f.kind == TOPIC_ORDER_NEW:
                ids.add(p.get("id"))
            conn.executemany(
                "INSERT INTO event_orders VALUES (?, ?)",
                [(i, pos) for i in ids if isinstance(i, str)],
            )
            if (pos + 1) % _STEP == 0:
                report("events", pos + 1, len(facts))
        conn.executescript("""
            CREATE INDEX events_symbol ON events (symbol, pos);
            CREATE INDEX events_actor ON events (actor, pos);
            CREATE INDEX events_gateway ON events (gateway, pos);
            CREATE INDEX event_orders_id ON event_orders (order_id, pos);
            """)
        conn.commit()
    report("events", len(facts), len(facts))


__all__ = [
    "DETECTION",
    "EVENTS",
    "INDEX",
    "MARKET",
    "META",
    "Report",
    "build_generation",
]
