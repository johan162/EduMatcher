"""C11 — an order's running totals, from the audit (S22 fields).

Per order, in publish order:

- each ``order.fill``'s ``cum_qty`` and ``cum_notional_ticks`` are the sums
  of its fills so far (``fill_qty``, ``fill_notional_ticks``);
- each fill's ``fill_notional_ticks`` is Σ ``price_ticks`` × ``quantity`` of
  the trades in its ``trade_ids`` -- published after the fills of their
  dispatch, so settled when the dispatch's chain ends;
- an ``order.cancelled`` / ``order.expired`` says, in ``cum_qty``, what had
  filled.

An audit written before these fields existed has none: SKIPPED.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from sim_forensics.audit import audit_files, lines
from sim_forensics.dataset import Dataset
from sim_forensics.registry import Outcome, Sample, Skipped, check

_KEEP = 50


@dataclass
class _Pass:
    samples: list[Sample] = field(default_factory=list)
    errors: Counter[str] = field(default_factory=Counter)
    #: order id -> [filled qty, filled notional] so far.
    totals: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))  # fmt: skip
    #: This chain's fills waiting for their trades, and its trades.
    owed: list[dict[str, Any]] = field(default_factory=list)
    trades: dict[str, int] = field(default_factory=dict)  # id -> price_ticks × qty
    chain = ""
    fills = 0
    ended = 0

    def flag(self, error: str, **keys: Any) -> None:
        self.errors[error] += 1
        if len(self.samples) < _KEEP:
            self.samples.append({"error": error, "chain": self.chain, **keys})

    def fill(self, p: dict[str, Any]) -> None:
        if "cum_qty" not in p:
            return
        self.fills += 1
        t = self.totals[p["order_id"]]
        t[0] += int(p["fill_qty"])
        t[1] += int(p["fill_notional_ticks"])
        if (p["cum_qty"], p["cum_notional_ticks"]) != (t[0], t[1]):
            self.flag("running totals are not the sum of the fills", order_id=p["order_id"], fill=[p["cum_qty"], p["cum_notional_ticks"]], sums=list(t))  # fmt: skip
            t[0], t[1] = int(p["cum_qty"]), int(p["cum_notional_ticks"])
        self.owed.append(p)
        if p["remaining_qty"] == 0:
            del self.totals[p["order_id"]]  # done: keep memory flat

    def trade(self, p: dict[str, Any]) -> None:
        if p.get("price_ticks") is not None:
            self.trades[p["id"]] = int(p["price_ticks"]) * int(p["quantity"])

    def end(self, p: dict[str, Any]) -> None:
        if "cum_qty" not in p:
            return
        self.ended += 1
        filled = self.totals.pop(p["order_id"], [0, 0])[0]
        if p["cum_qty"] != filled:
            self.flag("a cancel or expiry's cum_qty is not what had filled", order_id=p["order_id"], cum_qty=p["cum_qty"], filled=filled)  # fmt: skip

    def end_chain(self) -> None:
        for p in self.owed:
            ids = p.get("trade_ids") or []
            if not ids or any(t not in self.trades for t in ids):
                continue  # a fill without its trades in this chain: not checkable
            notional = sum(self.trades[t] for t in ids)
            if notional != p["fill_notional_ticks"]:
                self.flag("fill notional is not its trades' price × quantity", order_id=p["order_id"], fill=p["fill_notional_ticks"], trades=notional)  # fmt: skip
        self.owed.clear()
        self.trades.clear()


@check(
    "C11",
    "lifecycle",
    "Fills' cumulative qty and notional add up, and match their trades; ends report what filled",
    needs=(),
)
def running_totals(ds: Dataset) -> Outcome:
    files = audit_files(ds.data_dir)
    if not files:
        raise Skipped("no audit.log in the data dir")
    p = _Pass()
    for ln in lines(files):
        if ln.chain != p.chain:
            p.end_chain()
            p.chain = ln.chain
        topic = ln.topic
        if topic.startswith("order.fill."):
            p.fill(json.loads(ln.body))
        elif topic == "trade.executed":
            p.trade(json.loads(ln.body))
        elif topic.startswith(("order.cancelled.", "order.expired.")):
            p.end(json.loads(ln.body))
    p.end_chain()
    if not p.fills and not p.ended:
        raise Skipped("no fill or end carries cum_qty (an audit from before S22)")
    note = f"{p.fills} fills, {p.ended} cancels/expiries" + "".join(
        f"; {e}: {n}" for e, n in p.errors.most_common()
    )
    return Outcome(sum(p.errors.values()), p.samples, note)
