"""C9 — IOC, FOK and MARKET orders end in the dispatch that brought them.

These orders never rest: the engine matches what it can and ends the order
before it handles the next command, so everything about one happens in its
``order.new``'s chain -- rejected, filled, or the rest cancelled. A FOK in
addition trades all or nothing: filled in full, rejected (a single
rejecting ack, finding X5), or -- the one cancel the operator guide allows
(risk controls, "FOK — self-match liquidity is excluded before the
pre-check") -- acked and cancelled ``SELF_MATCH_PREVENTED`` without a fill
when its owner's own resting orders are what it would need.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sim_forensics.audit import audit_files, lines
from sim_forensics.dataset import Dataset
from sim_forensics.registry import Outcome, Sample, Skipped, check

_KEEP = 50
_TYPES = frozenset({"IOC", "FOK", "MARKET"})
_ID = '{"order_id": "'


@dataclass
class _Order:
    kind: str
    chain: str
    gw: str
    acked: bool = False
    filled: int = 0
    end: str = ""  # FILLED, REJECTED, CANCELLED:<reason>, EXPIRED


@dataclass
class _Pass:
    samples: list[Sample] = field(default_factory=list)
    errors: Counter[str] = field(default_factory=Counter)
    ends: Counter[str] = field(default_factory=Counter)
    #: The current chain's orders.
    orders: dict[str, _Order] = field(default_factory=dict)
    chain = ""

    def flag(self, error: str, oid: str, o: _Order, **keys: Any) -> None:
        self.errors[error] += 1
        if len(self.samples) < _KEEP:
            self.samples.append({"error": error, "order_id": oid, "order_type": o.kind, "gateway_id": o.gw, "chain": o.chain, **keys})  # fmt: skip

    def new(self, p: dict[str, Any]) -> None:
        if p.get("order_type") in _TYPES:
            self.orders[p["id"]] = _Order(p["order_type"], self.chain, p["gateway_id"])

    def event(self, oid: str, what: str, p: dict[str, Any]) -> None:
        o = self.orders.get(oid)
        if o is None:
            return
        if what == "ack":
            if p.get("accepted"):
                o.acked = True
            else:
                if o.acked and o.kind == "FOK":
                    self.flag("FOK acked, then rejected", oid, o, code=p.get("reject_code"))  # fmt: skip
                o.end = "REJECTED"
        elif what == "fill":
            o.filled += int(p.get("fill_qty") or 0)
            if p.get("remaining_qty") == 0:
                o.end = "FILLED"
        elif what == "cancelled":
            o.end = f"CANCELLED:{p.get('cancel_reason') or ''}"
        elif what == "expired":
            o.end = "EXPIRED"

    def end_chain(self) -> None:
        for oid, o in self.orders.items():
            if not o.end:
                self.flag("still live after its dispatch", oid, o, filled=o.filled)
                continue
            self.ends[f"{o.kind} {o.end.split(':')[0]}"] += 1
            if o.kind != "FOK":
                continue
            if o.end.startswith("CANCELLED"):
                if o.filled:
                    self.flag("FOK traded part, then cancelled", oid, o, filled=o.filled, end=o.end)  # fmt: skip
                elif o.end != "CANCELLED:SELF_MATCH_PREVENTED":
                    self.flag("FOK cancelled for a reason other than SMP", oid, o, end=o.end)  # fmt: skip
            elif o.end == "EXPIRED":
                self.flag("FOK expired", oid, o, filled=o.filled)
        self.orders.clear()


@check(
    "C9",
    "lifecycle",
    "IOC, FOK and MARKET end in their own dispatch; a FOK fills all or nothing",
    needs=(),
)
def immediate_orders(ds: Dataset) -> Outcome:
    files = audit_files(ds.data_dir)
    if not files:
        raise Skipped("no audit.log in the data dir")
    p = _Pass()
    for ln in lines(files):
        if ln.chain != p.chain:
            p.end_chain()
            p.chain = ln.chain
        topic = ln.topic
        if topic == "order.new":
            p.new(json.loads(ln.body))
        elif topic.startswith(("order.ack.", "order.fill.", "order.cancelled.", "order.expired.")):  # fmt: skip
            # Most of these are other orders': skip them unparsed.
            if ln.body.startswith(_ID) and ln.body[len(_ID) : ln.body.find('"', len(_ID))] not in p.orders:  # fmt: skip
                continue
            body = json.loads(ln.body)
            p.event(body.get("order_id") or "", topic.split(".")[1], body)
    p.end_chain()
    note = ", ".join(f"{k} {n}" for k, n in sorted(p.ends.items())) or "none"
    note += "".join(f"; {e}: {n}" for e, n in p.errors.most_common())
    return Outcome(sum(p.errors.values()), p.samples, note)
