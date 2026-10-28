"""C8, C10 — a quote's lifecycle, from the audit trail.

A quote is live from its accepting ``quote.ack`` until ``quote.status``
says INACTIVE_* or CANCELLED. When a leg's fill inactivates it
(INACTIVE_BID_FILLED / INACTIVE_ASK_FILLED), the refresh policy cancels the
*other* leg in the same dispatch (QUOTE_LEG_FILLED); the filled leg's own
remainder may stay live until a new quote replaces it.

A gateway has one quote per symbol: a new one replaces the old, whose
surviving legs (that remainder included) the engine cancels
(QUOTE_REPLACED) before it acks the new quote (C10).
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
_SIBLING = {"INACTIVE_BID_FILLED": "ask", "INACTIVE_ASK_FILLED": "bid"}


@dataclass
class _Quote:
    gw: str
    legs: dict[str, str] = field(default_factory=dict)  # bid/ask -> order id
    done: str = ""  # the status that ended it
    #: A status that arrived before the quote's ack (engines before X8a's fix).
    early: str = ""


@dataclass
class _Pass:
    samples: list[Sample] = field(default_factory=list)
    errors: Counter[str] = field(default_factory=Counter)
    quotes: dict[tuple[str, str], _Quote] = field(default_factory=dict)
    #: Leg order id -> (gateway, quote id).
    leg_of: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: Legs that are terminal (cancelled or fully filled).
    gone: set[str] = field(default_factory=set)
    #: Sibling legs that must never trade again -> the status that killed them.
    dead: dict[str, str] = field(default_factory=dict)
    #: (gateway, quote id, sibling) the current dispatch must cancel.
    owed: list[tuple[str, str, str]] = field(default_factory=list)
    chain = ""
    inactivated = 0
    #: C10: live legs per (gateway, symbol), the key of each, the legs a
    #: replacement cancelled, and what was found.
    live_legs: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    leg_key: dict[str, tuple[str, str]] = field(default_factory=dict)
    replaced: set[str] = field(default_factory=set)
    c10_samples: list[Sample] = field(default_factory=list)
    c10_errors: Counter[str] = field(default_factory=Counter)

    def flag(self, error: str, **keys: Any) -> None:
        self.errors[error] += 1
        if len(self.samples) < _KEEP:
            self.samples.append({"error": error, "chain": self.chain, **keys})

    def flag10(self, error: str, **keys: Any) -> None:
        self.c10_errors[error] += 1
        if len(self.c10_samples) < _KEEP:
            self.c10_samples.append({"error": error, "chain": self.chain, **keys})

    def legs_live(self, key: tuple[str, str], legs: list[str], qid: str) -> None:
        """A quote's legs go live: no earlier leg of its gateway and symbol
        may still be."""
        stale = self.live_legs.get(key, set()) - set(legs)
        for leg in sorted(stale):
            self.flag10("an earlier leg still live when a new quote was accepted", gateway_id=key[0], symbol=key[1], quote_id=qid, order_id=leg)  # fmt: skip
        self.live_legs[key] = set(legs)
        for leg in legs:
            self.leg_key[leg] = key

    def end_chain(self) -> None:
        for gw, qid, leg in self.owed:
            if leg not in self.gone:
                self.flag("sibling not cancelled in the dispatch that inactivated its quote", gateway_id=gw, quote_id=qid, order_id=leg)  # fmt: skip
        self.owed.clear()

    def ack(self, gw: str, p: dict[str, Any]) -> None:
        # A quote cancel is acked too, with no legs: only a submission's ack
        # creates a quote.
        if not p.get("accepted") or not p.get("bid_order_id"):
            return
        q = self.quotes.setdefault((gw, p["quote_id"]), _Quote(gw))
        q.legs = {"bid": p["bid_order_id"], "ask": p["ask_order_id"]}
        for leg in q.legs.values():
            self.leg_of[leg] = (gw, p["quote_id"])
        if p.get("symbol"):
            self.legs_live((gw, p["symbol"]), list(q.legs.values()), p["quote_id"])
        if q.early:
            self.flag("quote.status before the quote's ack", gateway_id=gw, quote_id=p["quote_id"], status=q.early)  # fmt: skip
            self.inactivate(gw, p["quote_id"], q, q.early)

    def status(self, gw: str, p: dict[str, Any]) -> None:
        qid, st = p["quote_id"], p["status"]
        q = self.quotes.get((gw, qid))
        if q is None:
            # A seeded quote has no quote.ack, only its legs' order.acks and
            # ACTIVE; anything else before the ack is out of order.
            self.quotes[(gw, qid)] = _Quote(gw, early="" if st == "ACTIVE" else st)
            return
        if st == "ACTIVE":
            if q.done:
                self.flag("ACTIVE after the quote ended", gateway_id=gw, quote_id=qid, ended=q.done)  # fmt: skip
            return
        if not q.done:
            self.inactivate(gw, qid, q, st)

    def inactivate(self, gw: str, qid: str, q: _Quote, st: str) -> None:
        q.done = st
        side = _SIBLING.get(st)
        if side and side in q.legs:
            self.inactivated += 1
            sibling = q.legs[side]
            self.dead[sibling] = st
            self.owed.append((gw, qid, sibling))

    def trade(self, p: dict[str, Any]) -> None:
        for key in ("buy_order_id", "sell_order_id"):
            oid = p[key]
            if oid in self.replaced:
                self.flag10("a replaced leg traded", order_id=oid, trade_id=p["id"])  # fmt: skip
            if oid in self.dead:
                gw, qid = self.leg_of[oid]
                self.flag("sibling leg traded after its quote went inactive", gateway_id=gw, quote_id=qid, order_id=oid, trade_id=p["id"])  # fmt: skip

    def seed_leg(self, gw: str, p: dict[str, Any]) -> None:
        q = self.quotes.setdefault((gw, p["quote_id"]), _Quote(gw))
        q.legs["bid" if p["side"] == "BUY" else "ask"] = p["order_id"]
        self.leg_of[p["order_id"]] = (gw, p["quote_id"])
        if p.get("symbol"):
            key = (gw, p["symbol"])
            self.live_legs[key] = self.live_legs.get(key, set()) | {p["order_id"]}
            self.leg_key[p["order_id"]] = key

    def leg_done(self, oid: str, reason: str = "") -> None:
        if oid in self.leg_of:
            self.gone.add(oid)
        key = self.leg_key.pop(oid, None)
        if key is not None:
            self.live_legs[key].discard(oid)
            if reason == "QUOTE_REPLACED":
                self.replaced.add(oid)


def _quote_pass(ds: Dataset) -> _Pass:
    cached = ds.cache.get("quotes")
    if isinstance(cached, _Pass):
        return cached
    files = audit_files(ds.data_dir)
    if not files:
        raise Skipped("no audit.log in the data dir")
    qp = _Pass()
    for ln in lines(files):
        topic = ln.topic
        if ln.chain != qp.chain:
            qp.end_chain()
            qp.chain = ln.chain
        if topic.startswith("quote.ack."):
            qp.ack(topic[10:], json.loads(ln.body))
        elif topic.startswith("quote.status."):
            qp.status(topic[13:], json.loads(ln.body))
        elif topic.startswith("order.ack.") and '"is_seed": true' in ln.body:
            p = json.loads(ln.body)
            if p.get("accepted") and p.get("quote_id"):
                qp.seed_leg(topic[10:], p)
        elif topic == "trade.executed":
            qp.trade(json.loads(ln.body))
        elif topic.startswith("order.cancelled."):
            p = json.loads(ln.body)
            qp.leg_done(p["order_id"], p.get("cancel_reason") or "")
        elif topic.startswith("order.expired."):
            qp.leg_done(json.loads(ln.body)["order_id"])
        elif topic.startswith("order.fill."):
            p = json.loads(ln.body)
            if p["remaining_qty"] == 0:
                qp.leg_done(p["order_id"])
    qp.end_chain()
    ds.cache["quotes"] = qp
    return qp


@check(
    "C8",
    "lifecycle",
    "A quote never turns ACTIVE again once ended; an inactivating fill ends its sibling leg",
    needs=(),
)
def quote_lifecycle(ds: Dataset) -> Outcome:
    """Per quote, in publish order: no ACTIVE after INACTIVE_*/CANCELLED, no
    status before the quote's ack, and after INACTIVE_BID/ASK_FILLED the
    other leg is cancelled (or already done) within that dispatch and never
    trades again."""
    qp = _quote_pass(ds)
    note = f"{len(qp.quotes)} quotes, {qp.inactivated} inactivated by a fill" + "".join(
        f"; {e}: {n}" for e, n in qp.errors.most_common()
    )
    return Outcome(sum(qp.errors.values()), qp.samples, note)


@check(
    "C10",
    "lifecycle",
    "One quote per gateway and symbol: a replacement ends every earlier leg first",
    needs=(),
)
def quote_replacement(ds: Dataset) -> Outcome:
    """When a quote is accepted, no earlier leg of its gateway and symbol is
    live (the old quote's legs and a filled leg's remainder are cancelled
    QUOTE_REPLACED first); a leg cancelled so never trades."""
    qp = _quote_pass(ds)
    note = f"{len(qp.replaced)} legs cancelled QUOTE_REPLACED" + "".join(
        f"; {e}: {n}" for e, n in qp.c10_errors.most_common()
    )
    return Outcome(sum(qp.c10_errors.values()), qp.c10_samples, note)
