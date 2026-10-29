"""C — order lifecycle: every order's event sequence is one the engine may emit.

One pass over stats.order_events (order by order, in pm-stats's receive
order, which is the engine's publish order: one PUB socket, one SUB socket)
replays each order through a small state machine. C1–C3 report what the
machine rejects; C4 and C5 compare its end states with the engine's persisted
book and with the OCO pairing rule.

Lifecycle per order (events: ACK, REJECT, FILL, AMEND, CANCEL, EXPIRE)::

    (start) --ACK--> LIVE --FILL(remaining>0)/AMEND--> LIVE
    (start) --REJECT--> REJECTED                 rejected on entry
    LIVE --FILL(remaining=0)--> FILLED
    LIVE --CANCEL--> CANCELLED,  LIVE --EXPIRE--> EXPIRED

A REJECT after the order's first event is the rejection of a later command
(a cancel or amend refused, or aimed at an order already done) and leaves the
order as it was: the engine answers an order with one ack, and pm-stats files
a refused request's ``order.ack accepted=false`` under the order's id too,
with nothing to tell the two apart. C9 finds an order rejected after its
accepting ack (X5) in the audit, where the two can be told apart. Quote legs
are acknowledged per quote (QUOTE_ACK), not per order, so on a quoting
gateway an order may start with FILL or CANCEL.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Container
from dataclasses import dataclass, field
from pathlib import Path
from typing import get_args

from sim_forensics.checks.bookkeeping import counter_mismatches
from sim_forensics.dataset import Dataset, iso_ns
from sim_forensics.registry import Outcome, Sample, Skipped, check

from edumatcher.models.generated.order import OrderCancelledCancelReason

_TERMINAL = {"FILLED", "CANCELLED", "EXPIRED", "REJECTED"}
_REJECT_TYPES = ("REJECT", "QUOTE_REJECT", "OCO_REJECT", "COMBO_REJECT")
_CANCEL_REASONS = frozenset(get_args(OrderCancelledCancelReason))
#: The CANCEL rows pm-stats writes for an OCO sibling (X7): each right after
#: the OCO_CANCEL row it comes from, with that row's OCO id. They record the
#: OCO rule ending a leg, and carry oco.cancelled's free-text reason.
_OCO_RULE_CANCELS = (
    "SELECT c.seq FROM stats.order_events c "
    "JOIN stats.order_events o ON o.seq = c.seq - 1 "
    "WHERE c.event_type = 'CANCEL' AND o.event_type = 'OCO_CANCEL' "
    "AND c.oco_group_id = o.order_id"
)


@dataclass
class _Order:
    gw: str
    state: str | None = None
    qty: int | None = None
    remaining: int | None = None
    oco: str | None = None
    combo: str | None = None
    shape: list[str] = field(default_factory=list)
    after_terminal: bool = False  # C2 reported once per order


@dataclass
class _Scan:
    c1: list[Sample] = field(default_factory=list)
    c2: list[Sample] = field(default_factory=list)
    c3: list[Sample] = field(default_factory=list)
    #: Order id → (state, remaining, OCO group) at the end, for orders still
    #: LIVE and for every order the persisted book names.
    final: dict[str, tuple[str | None, int | None, str | None]] = field(
        default_factory=dict
    )
    #: OCO group → order id → its (seq, event_type, state after) events.
    oco: dict[str, dict[str, list[tuple[int, str, str | None]]]] = field(
        default_factory=dict
    )
    #: Combo (engine id) → leg order id → its events, as for OCO groups.
    combo: dict[str, dict[str, list[tuple[int, str, str | None]]]] = field(
        default_factory=dict
    )
    #: OCO groups with an OCO_CANCEL row. The engine reports a sibling's
    #: cancel only as oco.cancelled, and pm-stats keeps that row under the
    #: OCO id without its cancelled_order_id (X7), so the leg it closed is
    #: inferred: the group's leg still live.
    oco_cancelled: set[str] = field(default_factory=set)
    #: Seqs of the _OCO_RULE_CANCELS rows.
    oco_rule: set[int] = field(default_factory=set)
    orders: int = 0
    no_ack_checked: bool = True


def _resting_book(ds: Dataset) -> dict[str, dict[str, object]] | None:
    path = ds.data_dir / "gtc_orders.json"
    if not path.is_file():
        return None
    return {str(o["id"]): o for o in json.loads(Path(path).read_text())}


def _pruning_possible(ds: Dataset) -> bool:
    """True when the span of order events exceeds pm-stats's retention, so an
    order's ACK may have been pruned while later events were kept."""
    keep = ds.conn.execute(
        "SELECT value FROM stats.stats_meta WHERE key = 'keep_order_events_days'"
    ).fetchone()
    first, last = ds.conn.execute(
        "SELECT min(ts), max(ts) FROM stats.order_events"
    ).fetchone()
    if keep is None or first is None:
        return False
    span_days = (iso_ns(last) - iso_ns(first)) / 86_400e9
    return span_days > float(keep[0])


def _shape(events: list[str]) -> str:
    return re.sub(r"(FILL )+", "FILL+ ", " ".join(events) + " ").strip()


def _scan(ds: Dataset) -> _Scan:
    cached = ds.cache.get("lifecycle.scan")
    if isinstance(cached, _Scan):
        return cached
    book = _resting_book(ds) or {}
    quoting = {
        gw
        for (gw,) in ds.conn.execute(
            "SELECT DISTINCT gateway_id FROM stats.order_events "
            "WHERE event_type = 'QUOTE_ACK'"
        )
    }
    scan = _Scan(no_ack_checked=not _pruning_possible(ds))
    scan.oco_cancelled = {
        group
        for (group,) in ds.conn.execute(
            "SELECT DISTINCT order_id FROM stats.order_events "
            "WHERE event_type = 'OCO_CANCEL'"
        )
    }
    scan.oco_rule = {seq for (seq,) in ds.conn.execute(_OCO_RULE_CANCELS)}
    rows = ds.conn.execute(
        "SELECT order_id, seq, event_type, gateway_id, quantity, remaining_qty, "
        "status, fill_qty, oco_group_id, combo_parent_id FROM stats.order_events "
        "WHERE event_type IN ('ACK', 'REJECT', 'FILL', 'AMEND', 'CANCEL', 'EXPIRE') "
        "ORDER BY order_id, seq"
    )
    current: str | None = None
    order = _Order("")
    for oid, seq, et, gw, qty, remaining, status, fill_qty, oco, combo in rows:
        if oid != current:
            if current is not None:
                _finish(scan, current, order, book)
            current, order = oid, _Order(gw)
        order.shape.append(et)
        order.oco = order.oco or oco
        order.combo = order.combo or combo
        _step(scan, oid, order, seq, et, qty, remaining, status, fill_qty, quoting)
    if current is not None:
        _finish(scan, current, order, book)
    ds.cache["lifecycle.scan"] = scan
    return scan


def _step(
    scan: _Scan,
    oid: str,
    o: _Order,
    seq: int,
    et: str,
    qty: int | None,
    remaining: int | None,
    status: str | None,
    fill_qty: int | None,
    quoting: set[str],
) -> None:
    def c1(error: str) -> None:
        scan.c1.append({"order_id": oid, "gateway_id": o.gw, "error": error})

    if o.state in _TERMINAL:
        if et != "REJECT" and not o.after_terminal:
            o.after_terminal = True
            scan.c2.append(
                {"order_id": oid, "gateway_id": o.gw, "error": f"{et} after {o.state}"}
            )
        _record_oco(scan, o, oid, seq, et)
        return
    if o.state is None and et != "ACK" and et != "REJECT":
        if o.gw not in quoting and scan.no_ack_checked:
            c1(f"{et} without an ACK")
        o.state = "LIVE"
    if et == "ACK":
        if o.state is None:
            o.state, o.qty, o.remaining = "LIVE", qty, qty
        else:
            c1("second ACK")
    elif et == "REJECT":
        if o.state is None:
            o.state = "REJECTED"
    elif et == "FILL":
        _fill(scan, oid, o, qty, remaining, status, fill_qty)
    elif et == "AMEND":
        o.qty = qty if qty is not None else o.qty
        o.remaining = remaining if remaining is not None else o.remaining
    elif et == "CANCEL":
        o.state = "CANCELLED"
    elif et == "EXPIRE":
        o.state = "EXPIRED"
    _record_oco(scan, o, oid, seq, et)


def _fill(
    scan: _Scan,
    oid: str,
    o: _Order,
    qty: int | None,
    remaining: int | None,
    status: str | None,
    fill_qty: int | None,
) -> None:
    if o.qty is None:  # a quote leg: its first FILL carries the order qty
        o.qty, o.remaining = qty, qty
    problems: dict[str, object] = {}
    if not fill_qty or fill_qty <= 0:
        problems["fill_qty"] = fill_qty
    elif o.remaining is not None and remaining != o.remaining - fill_qty:
        problems["remaining_qty"] = {
            "stored": remaining,
            "expected": o.remaining - fill_qty,
        }
    if qty is not None and o.qty is not None and qty != o.qty:
        problems["quantity"] = {"stored": qty, "ack": o.qty}
    if (status == "FILLED") != (remaining == 0):
        problems["status"] = {"status": status, "remaining_qty": remaining}
    if problems:
        scan.c3.append({"order_id": oid, "gateway_id": o.gw, "problems": problems})
    o.remaining = remaining
    if remaining == 0 or status == "FILLED":
        o.state = "FILLED"


def _record_oco(scan: _Scan, o: _Order, oid: str, seq: int, et: str) -> None:
    if o.oco is not None:
        scan.oco.setdefault(o.oco, {}).setdefault(oid, []).append((seq, et, o.state))
    if o.combo is not None:
        scan.combo.setdefault(o.combo, {}).setdefault(oid, []).append(
            (seq, et, o.state)
        )


def _finish(scan: _Scan, oid: str, o: _Order, book: Container[str]) -> None:
    scan.orders += 1
    if o.state not in _TERMINAL or oid in book:
        scan.final[oid] = (o.state, o.remaining, o.oco)


def _sample_shapes(ds: Dataset, samples: list[Sample]) -> None:
    """Add each sampled order's event sequence, for the report."""
    for s in samples:
        events = [
            et
            for (et,) in ds.conn.execute(
                "SELECT event_type FROM stats.order_events WHERE order_id = ? "
                "ORDER BY seq",
                (s["order_id"],),
            )
        ]
        s["events"] = _shape(events)


def _with_shapes(ds: Dataset, samples: list[Sample]) -> Outcome:
    _sample_shapes(ds, samples[:20])
    errors = Counter(str(s.get("error", "")) for s in samples)
    note = "; ".join(f"{e}: {n}" for e, n in errors.most_common()) if errors else ""
    return Outcome(len(samples), samples, note)


@check(
    "C1",
    "lifecycle",
    "Each order starts with ACK or REJECT and is accepted at most once",
    needs=("stats",),
)
def legal_starts(ds: Dataset) -> Outcome:
    scan = _scan(ds)
    out = _with_shapes(ds, scan.c1)
    if not scan.no_ack_checked:
        out.note = (out.note + "; " if out.note else "") + (
            "order events span more than their retention: "
            "'without an ACK' not checked"
        )
    return out


@check(
    "C2",
    "lifecycle",
    "Nothing happens to an order after it is filled, cancelled, expired or rejected",
    needs=("stats",),
)
def nothing_after_terminal(ds: Dataset) -> Outcome:
    return _with_shapes(ds, _scan(ds).c2)


@check(
    "C3",
    "lifecycle",
    "Each FILL's remaining_qty = previous remaining − fill_qty; FILLED ⇔ 0 left",
    needs=("stats",),
)
def fill_quantities(ds: Dataset) -> Outcome:
    samples = _scan(ds).c3
    _sample_shapes(ds, samples[:20])
    return Outcome(len(samples), samples)


@check(
    "C4",
    "lifecycle",
    "Orders still live in order_events are exactly the engine's persisted book",
    needs=("stats",),
)
def live_orders_are_the_book(ds: Dataset) -> Outcome:
    """gtc_orders.json is the engine's resting book at shutdown (DAY and GTC,
    orders and quote legs, untriggered stops included)."""
    book = _resting_book(ds)
    if book is None:
        raise Skipped("no gtc_orders.json in the data dir")
    scan = _scan(ds)
    samples: list[Sample] = []
    inferred = 0
    for oid, (state, remaining, oco) in sorted(scan.final.items()):
        resting = book.get(oid)
        if resting is None and oco in scan.oco_cancelled:
            inferred += 1
        elif resting is None:
            samples.append(
                {"order_id": oid, "error": "live in order_events, not in the book"}
            )
        elif state in _TERMINAL:
            samples.append({"order_id": oid, "error": f"in the book but {state}"})
        elif remaining is not None and remaining != resting["remaining_qty"]:
            samples.append(
                {
                    "order_id": oid,
                    "error": "remaining_qty differs",
                    "order_events": remaining,
                    "book": resting["remaining_qty"],
                }
            )
    for oid, resting in sorted(book.items()):
        partial = resting["remaining_qty"] != resting["quantity"]
        if (resting["status"] == "PARTIAL") != partial:
            samples.append(
                {"order_id": oid, "error": "book status disagrees with its quantities"}
            )
        if oid not in scan.final and resting["origin"] == "ORDER":
            if scan.no_ack_checked:
                samples.append(
                    {"order_id": oid, "error": "in the book, no order events"}
                )
    if "clearing" in ds.stores:
        last = ds.conn.execute(
            "SELECT payload_json FROM clearing.session_events "
            "WHERE event_type = 'PHASE' ORDER BY ts_ns DESC, id DESC LIMIT 1"
        ).fetchone()
        if last is not None and json.loads(last[0])["state"] == "CLOSED":
            closed: list[Sample] = [
                {"order_id": oid, "error": "DAY order resting after the close"}
                for oid, o in sorted(book.items())
                if o["tif"] == "DAY"
            ]
            samples += closed
    errors = Counter(str(s["error"]) for s in samples)
    note = f"{len(book)} resting; {inferred} OCO legs closed by OCO_CANCEL; " + (
        "; ".join(f"{e}: {n}" for e, n in errors.most_common())
    )
    return Outcome(len(samples), samples, note)


@check(
    "C5",
    "lifecycle",
    "OCO: two legs; none fills after its sibling ended; a done leg ends its sibling. "
    "Combo: a leg ending unfilled ends the others; none fills after",
    needs=("stats",),
)
def oco_pairs(ds: Dataset) -> Outcome:
    """A leg ends when it fills or is cancelled for a reason of its own; its
    sibling must not fill after that, and after a fill must end by the OCO
    rule, not by its owner's cancel or an expiry. The sibling's cancel by the OCO
    rule may come first in the stream: since X15 the engine pulls it inside
    the dispatch, before it publishes the leg's fill."""
    scan = _scan(ds)
    samples: list[Sample] = []
    both_partial = inferred = 0
    for group, legs in sorted(scan.oco.items()):
        if len(legs) != 2:
            samples.append({"oco_group_id": group, "error": f"{len(legs)} legs"})
            continue
        (a, ea), (b, eb) = legs.items()
        if all(any(et == "FILL" for _s, et, _st in e) for e in (ea, eb)):
            both_partial += 1
        for (leg, events), (sib, sib_events) in (
            ((a, ea), (b, eb)),
            ((b, eb), (a, ea)),
        ):
            ended = next(
                (
                    (s, st)
                    for s, et, st in events
                    if (et, st) == ("FILL", "FILLED")
                    or (et == "CANCEL" and s not in scan.oco_rule)
                ),
                None,
            )
            if ended is not None and any(
                et == "FILL" and s > ended[0] for s, et, _st in sib_events
            ):
                samples.append(
                    {
                        "oco_group_id": group,
                        "order_id": sib,
                        "error": f"fill after sibling {ended[1]}",
                    }
                )
            elif ended is not None and ended[1] == "FILLED":
                # The OCO rule pulls the sibling of a filled leg at once; one
                # its owner cancelled, or that expired, later had outlived it.
                late = next(
                    (
                        et
                        for s, et, _st in sib_events
                        if s > ended[0]
                        and et in ("CANCEL", "EXPIRE")
                        and s not in scan.oco_rule
                    ),
                    None,
                )
                if late is not None:
                    samples.append(
                        {
                            "oco_group_id": group,
                            "order_id": sib,
                            "error": f"{late} after sibling FILLED",
                        }
                    )
            done = events[-1][2] in ("FILLED", "CANCELLED")
            if done and sib_events[-1][2] not in _TERMINAL:
                if group in scan.oco_cancelled:
                    inferred += 1
                    continue
                samples.append(
                    {
                        "oco_group_id": group,
                        "order_id": sib,
                        "error": f"still live after sibling {leg} {events[-1][2]}",
                    }
                )
    samples += _combo_samples(scan)
    note = (
        f"{len(scan.oco)} groups; both legs traded in {both_partial}; "
        f"{inferred} siblings closed only by OCO_CANCEL (X7); {len(scan.combo)} combos"
    )
    return Outcome(len(samples), samples, note)


def _combo_samples(scan: _Scan) -> list[Sample]:
    """A combo fails when a leg is cancelled, rejected or expires before
    every leg filled: the engine then cancels the others, and no leg may
    fill after that (participant guide, combo orders, step 6)."""
    samples: list[Sample] = []
    for combo, legs in sorted(scan.combo.items()):
        ends = [
            (s, oid)
            for oid, events in legs.items()
            for s, et, st in events
            if et in ("CANCEL", "EXPIRE", "REJECT") and st != "FILLED"
        ]
        if not ends:
            continue
        failed_at, failed_leg = min(ends)
        for oid, events in legs.items():
            late = next((s for s, et, _st in events if et == "FILL" and s > failed_at), None)  # fmt: skip
            if late is not None:
                samples.append({"combo_parent_id": combo, "order_id": oid, "error": f"fill after leg {failed_leg[:8]} ended the combo"})  # fmt: skip
            elif events[-1][2] not in _TERMINAL:
                samples.append({"combo_parent_id": combo, "order_id": oid, "error": "leg still live after the combo failed"})  # fmt: skip
    return samples


@check(
    "C6",
    "lifecycle",
    "Cancel reasons are spec codes; recorded rejects match the engine's counter",
    needs=("stats",),
)
def reasons_and_rejects(ds: Dataset) -> Outcome:
    marks = ", ".join("?" * len(_CANCEL_REASONS))
    samples: list[Sample] = [
        {"cancel_reason": reason, "count": n}
        for reason, n in ds.conn.execute(
            "SELECT reason, count(*) FROM stats.order_events "
            "WHERE event_type = 'CANCEL' AND reason IS NOT NULL AND reason <> '' "
            f"AND reason NOT IN ({marks}) AND seq NOT IN ({_OCO_RULE_CANCELS}) "
            "GROUP BY reason",
            tuple(sorted(_CANCEL_REASONS)),
        )
    ]
    (siblings,) = ds.conn.execute(
        f"SELECT count(*) FROM ({_OCO_RULE_CANCELS})"
    ).fetchone()
    note = (
        f"{siblings} OCO sibling cancels carry oco.cancelled's free text, not checked"
    )
    if "metrics" in ds.stores:
        types = ", ".join(f"'{t}'" for t in _REJECT_TYPES)
        rows = (
            (iso_ns(ts), gw)
            for ts, gw in ds.conn.execute(
                "SELECT ts, gateway_id FROM stats.order_events "
                f"WHERE event_type IN ({types})"
            )
        )
        samples += counter_mismatches(ds, "engine.rejects", "pm-engine", rows)
    else:
        note += "; no metrics.db: reject counts not reconciled"
    return Outcome(len(samples), samples, note)
