"""G — what the engine persists for its next start."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sim_forensics.audit import audit_files, lines
from sim_forensics.checks.derived import market_pass
from sim_forensics.dataset import Dataset
from sim_forensics.registry import Outcome, Sample, Skipped, check

#: Order types that rest with a limit price, and those armed by a stop price.
_PRICED = ("LIMIT", "ICEBERG", "STOP_LIMIT")
_STOPPED = ("STOP", "STOP_LIMIT", "TRAILING_STOP")
_LIVE_COMBO = ("PENDING", "PARTIALLY_MATCHED")


def _load(ds: Dataset, name: str) -> list[dict[str, Any]] | None:
    path = ds.data_dir / name
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    assert isinstance(data, list)
    return data


@check(
    "G1",
    "lifecycle",
    "gtc_orders.json and gtc_combos.json hold only live, well-formed entries",
    needs=(),
)
def persisted_orders_are_live(ds: Dataset) -> Outcome:
    """Each persisted order on its own: live status, 0 < remaining <= quantity,
    the status its quantities imply, the prices its type needs, and the
    tick_decimals pm-stats knows for the symbol. Whether the file is the
    book order_events leave live is C4; the re-run's book is E4."""
    orders = _load(ds, "gtc_orders.json")
    if orders is None:
        raise Skipped("no gtc_orders.json in the data dir")
    combos = _load(ds, "gtc_combos.json") or []
    decimals: dict[str, int] = {}
    if "stats" in ds.stores:
        decimals = dict(
            ds.conn.execute("SELECT symbol, tick_decimals FROM stats.instruments")
        )
    samples: list[Sample] = []
    for o in orders:
        errors = []
        if o["status"] not in ("NEW", "PARTIAL"):
            errors.append(f"status {o['status']}")
        if not 0 < o["remaining_qty"] <= o["quantity"]:
            errors.append("remaining_qty outside (0, quantity]")
        elif (o["status"] == "PARTIAL") != (o["remaining_qty"] < o["quantity"]):
            errors.append("status disagrees with its quantities")
        kind = o["order_type"]
        if kind in _PRICED and not isinstance(o["price_ticks"], int):
            errors.append("no integer price_ticks")
        if kind in _STOPPED and not isinstance(o["stop_price_ticks"], int):
            errors.append("no integer stop_price_ticks")
        expected = decimals.get(o["symbol"])
        if expected is not None and o["tick_decimals"] != expected:
            errors.append(f"tick_decimals {o['tick_decimals']} != {expected}")
        if errors:
            samples.append({"order_id": o["id"], "errors": errors})
    for c in combos:
        if c["status"] not in _LIVE_COMBO or c["tif"] != "GTC":
            samples.append(
                {
                    "combo_id": c["id"],
                    "errors": [f"status {c['status']}, tif {c['tif']}"],
                }
            )
    note = f"{len(orders)} orders, {len(combos)} combos persisted"
    return Outcome(len(samples), samples, note)


@check(
    "G2",
    "lifecycle",
    "Trade ids carry the run_seq of the engine start that made them",
    needs=("stats",),
)
def trade_ids_follow_run_seq(ds: Dataset) -> Outcome:
    """engine_run_seq.json holds the last start's run_seq: no trade id may
    carry a higher one, run_seq never falls in trade-time order (a reused
    run_seq would restart the counter under old ids), and every trade after
    the audit's last engine start carries the file's run_seq."""
    path = ds.data_dir / "engine_run_seq.json"
    if not path.is_file():
        raise Skipped("no engine_run_seq.json in the data dir")
    run_seq = int(json.loads(path.read_text())["run_seq"])
    last_start = ""
    if audit_files(ds.data_dir):
        starts_seen = market_pass(ds).starts
        last_start = starts_seen[-1] if starts_seen else ""
    samples: list[Sample] = []
    high = 0
    starts = 0
    for ts, trade_id in ds.conn.execute(
        "SELECT ts, trade_id FROM stats.trade_log ORDER BY ts, trade_id"
    ):
        seq = int(trade_id.split("-")[0])
        if seq > high:
            starts += 1
        if seq > run_seq:
            samples.append({"trade_id": trade_id, "error": f"run_seq above {run_seq}"})
        elif seq < high:
            samples.append(
                {"trade_id": trade_id, "error": f"run_seq {seq} after run_seq {high}"}
            )
        elif last_start and ts > last_start and seq != run_seq:
            samples.append(
                {
                    "trade_id": trade_id,
                    "error": f"after the last engine start, not run_seq {run_seq}",
                }
            )
        high = max(high, seq)
    note = f"run_seq {run_seq}; {starts} run_seq(s) in trade_log; " + (
        f"last engine start in the audit {last_start}"
        if last_start
        else "no engine start in the audit"
    )
    return Outcome(len(samples), samples, note)


#: The order lists of a book checkpoint.
_CHECKPOINT_LISTS = ("bids", "asks", "buy_stops", "sell_stops", "trailing_stops")


def _rounds(ds: Dataset) -> list[tuple[str, str, str, dict[str, int]]]:
    """The audit's checkpoint rounds: (session date, reason, phase, order id
    -> remaining) -- one round is the engine's consecutive checkpoints."""
    rounds: list[tuple[str, str, str, dict[str, int]]] = []
    current: tuple[str, str] | None = None
    for ln in lines(audit_files(ds.data_dir)):
        if not ln.topic.startswith("system.book_checkpoint."):
            current = None
            continue
        p = json.loads(ln.body)
        key = (p["reason"], p["phase"])
        if key != current:
            rounds.append((_session_date(ds, ln.ts), *key, {}))
            current = key
        orders = rounds[-1][3]
        for name in _CHECKPOINT_LISTS:
            for r in p.get(name) or []:
                orders[r["order_id"]] = r["remaining_qty"]
    return rounds


def _session_date(ds: Dataset, ts: str) -> str:
    return datetime.fromisoformat(ts).astimezone(ds.session_tz).date().isoformat()


@check(
    "G3",
    "lifecycle",
    "Each day's archived closing book is the close's checkpoint and the next day's start",
    needs=(),
)
def eod_archive_continues(ds: Dataset) -> Outcome:
    """For each ``eod/<date>/gtc_orders.json``: its orders (id, remaining)
    are the book of that day's CLOSED checkpoint, and of the next start's
    round (the next PRE_OPEN, or a restart's STARTUP) -- nothing appears or
    vanishes overnight. The shutdown's EOD round is no start and is passed
    over: the audit recorder may catch only part of it (X34). Seeded quote
    legs (a restart seeds again, by design) are not counted against it."""
    root = ds.data_dir / "eod"
    days = sorted(p.name for p in root.iterdir() if (p / "gtc_orders.json").is_file()) if root.is_dir() else []  # fmt: skip
    if not days:
        raise Skipped("no eod/<date>/gtc_orders.json in the data dir")
    if not audit_files(ds.data_dir):
        raise Skipped("no audit.log in the data dir")
    rounds = _rounds(ds)
    seeds = _seed_ids(ds)
    samples: list[Sample] = []
    checked = 0
    for day in days:
        archived = {
            str(o["id"]): int(o["remaining_qty"])
            for o in json.loads((root / day / "gtc_orders.json").read_text())
        }
        # The close is the transition to CLOSED, not an engine start that
        # found the market closed (a STARTUP round before the open).
        close = next((i for i, r in enumerate(rounds) if r[0] == day and r[1:3] == ("PHASE", "CLOSED")), None)  # fmt: skip
        if close is None:
            continue  # the audit does not hold that close
        checked += 1
        start = next(
            (
                i
                for i in range(close + 1, len(rounds))
                if rounds[i][1] == "STARTUP" or rounds[i][1:3] == ("PHASE", "PRE_OPEN")
            ),
            None,
        )
        for label, i in (("the close", close), ("the next start", start)):
            if i is None:
                continue
            book = {k: v for k, v in rounds[i][3].items() if k not in seeds}
            if book != archived:
                lost = sorted(archived.keys() - book.keys())
                new = sorted(book.keys() - archived.keys())
                changed = sorted(k for k in archived.keys() & book.keys() if archived[k] != book[k])  # fmt: skip
                samples.append({"day": day, "against": label, "reason": rounds[i][1], "missing": lost[:5], "extra": new[:5], "changed": changed[:5]})  # fmt: skip
    note = f"{len(days)} archived days, {checked} with their close in the audit"
    return Outcome(len(samples), samples, note)


def _seed_ids(ds: Dataset) -> set[str]:
    """Order ids of seeded quote legs (their acks say is_seed)."""
    out: set[str] = set()
    for ln in lines(audit_files(ds.data_dir)):
        if ln.topic.startswith("order.ack.") and '"is_seed": true' in ln.body:
            out.add(str(json.loads(ln.body)["order_id"]))
    return out
