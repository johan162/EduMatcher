"""H5 — what the run exercised.

A check over a feature the run never used passes vacuously. H5 counts, from
the audit, every order the engine took in -- by how it entered (a plain
order, a quote leg, an OCO leg, a combo leg, a seed), order type, TIF,
resolved SMP action, session phase on entry -- and how each one ended; and
how often each engine feature's message appears. Samples are the values of
each dimension that never occurred, then the rarest combinations.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from sim_forensics.audit import audit_files, lines
from sim_forensics.dataset import Dataset
from sim_forensics.registry import Outcome, Sample, Skipped, check

from edumatcher.models.order import TIF, OrderType, SmpAction
from edumatcher.models.session import SessionState

#: Feature messages, by exact topic or by prefix up to the last dot.
FEATURES = (
    "order.cancel",
    "order.amend",
    "order.amended.",
    "order.oco",
    "order.oco_cancel",
    "oco.cancelled.",
    "order.combo",
    "order.combo_cancel",
    "combo.ack.",
    "combo.status.",
    "quote.new",
    "quote.cancel",
    "auction.result.",
    "circuit_breaker.halt.",
    "circuit_breaker.extend.",
    "circuit_breaker.resume.",
    "risk.symbol_halt",
    "risk.symbol_resume",
    "risk.cancel_symbol",
    "risk.force_uncross",
    "risk.kill_switch",
    "risk.kill_switch_gateway",
    "risk.kill_switch_global",
    "risk.circuit_breaker_halt_all",
    "risk.circuit_breaker_resume_all",
    "system.reference_reload",
    "system.startup_recovery",
)
_EXACT = frozenset(f for f in FEATURES if not f.endswith("."))
_PREFIXES = tuple(f for f in FEATURES if f.endswith("."))
ENTRIES = ("ORDER", "QUOTE", "OCO", "COMBO", "SEED")
OUTCOMES = ("FILLED", "PARTIAL+CANCELLED", "CANCELLED", "PARTIAL+EXPIRED", "EXPIRED", "REJECTED", "LIVE")  # fmt: skip

Key = tuple[str, str, str, str, str]  # entry, order type, TIF, SMP, phase


@dataclass
class _Order:
    key: Key
    traded: bool = False


@dataclass
class _Pass:
    matrix: dict[Key, Counter[str]] = field(default_factory=lambda: defaultdict(Counter))  # fmt: skip
    features: Counter[str] = field(default_factory=Counter)
    #: Explicit `smp_action` on `order.new` (None = the gateway default).
    asked_smp: Counter[str] = field(default_factory=Counter)
    reject_codes: Counter[str] = field(default_factory=Counter)
    #: Orders seen but not yet ended, by id.
    live: dict[str, _Order] = field(default_factory=dict)
    #: `order.new` not yet answered: id -> (entry, type, TIF).
    asked: dict[str, tuple[str, str, str]] = field(default_factory=dict)
    #: `quote.new` not yet answered: quote id -> TIF.
    quote_tif: dict[str, str] = field(default_factory=dict)
    #: Refused cancels and amends, by code.
    refused: Counter[str] = field(default_factory=Counter)
    phase = "-"

    def new(self, p: dict[str, Any]) -> None:
        entry = "COMBO" if p.get("combo_parent_id") else "OCO" if p.get("oco_group_id") else "ORDER"  # fmt: skip
        self.asked[p["id"]] = (entry, p.get("order_type") or "?", p.get("tif") or "?")
        if p.get("smp_action"):
            self.asked_smp[p["smp_action"]] += 1

    def ack(self, p: dict[str, Any]) -> None:
        oid = p.get("order_id")
        if not oid:
            return
        asked = self.asked.pop(oid, None)
        if not p.get("accepted"):
            if asked is None:  # refuses a cancel or amend, not an order
                self.refused[p.get("reject_code") or "?"] += 1
            else:
                self.matrix[(*asked, "?", self.phase)]["REJECTED"] += 1
                self.reject_codes[p.get("reject_code") or "?"] += 1
            return
        if asked is None and oid in self.live:
            return  # accepts an amend
        if p.get("is_seed"):
            entry = "SEED"
        elif p.get("quote_id"):
            entry = "QUOTE"
        elif p.get("combo_parent_id"):
            entry = "COMBO"
        elif p.get("oco_group_id"):
            entry = "OCO"
        else:
            entry = asked[0] if asked else "ORDER"
        otype = p.get("order_type") or (asked[1] if asked else "?")
        tif = p.get("tif") or (asked[2] if asked else "?")
        smp = p.get("smp_action") or "?"
        self.live[oid] = _Order((entry, otype, tif, smp, self.phase))

    def quote_new(self, p: dict[str, Any]) -> None:
        self.quote_tif[p["quote_id"]] = p.get("tif") or "?"

    def quote_ack(self, p: dict[str, Any]) -> None:
        """A quote's legs get no ``order.ack``: its ``quote.ack`` names them.
        An ack with no ``quote.new`` waiting answers a quote cancel."""
        tif = self.quote_tif.pop(p.get("quote_id") or "", None)
        if tif is None:
            return
        key: Key = ("QUOTE", "LIMIT", tif, "?", self.phase)
        if not p.get("accepted"):
            self.matrix[key]["REJECTED"] += 1
            self.reject_codes[p.get("reject_code") or "?"] += 1
            return
        for leg in (p.get("bid_order_id"), p.get("ask_order_id")):
            if leg:
                self.live[leg] = _Order(key)

    def end(self, oid: str, how: str) -> None:
        o = self.live.pop(oid, None)
        if o is None:
            return
        if o.traded and how in ("CANCELLED", "EXPIRED"):
            how = f"PARTIAL+{how}"
        self.matrix[o.key][how] += 1

    def fill(self, p: dict[str, Any]) -> None:
        if p.get("remaining_qty") == 0:
            self.end(p["order_id"], "FILLED")
        elif (o := self.live.get(p["order_id"])) is not None:
            o.traded = True

    def finish(self) -> None:
        for o in self.live.values():
            self.matrix[o.key]["LIVE"] += 1
        self.live.clear()

    def feature(self, topic: str) -> None:
        if topic in _EXACT:
            self.features[topic] += 1
        elif topic.startswith(_PREFIXES):
            self.features[topic[: topic.rfind(".") + 1]] += 1


def _coverage_pass(ds: Dataset) -> _Pass:
    files = audit_files(ds.data_dir)
    if not files:
        raise Skipped("no audit.log in the data dir")
    cp = _Pass()
    for ln in lines(files):
        topic = ln.topic
        if topic.startswith(("book.", "depth.")):
            continue
        if topic == "order.new":
            cp.new(json.loads(ln.body))
        elif topic.startswith("order.ack."):
            cp.ack(json.loads(ln.body))
        elif topic.startswith("quote.ack."):
            cp.quote_ack(json.loads(ln.body))
        elif topic.startswith("order.fill."):
            cp.fill(json.loads(ln.body))
        elif topic.startswith("order.cancelled."):
            cp.end(json.loads(ln.body)["order_id"], "CANCELLED")
        elif topic.startswith("order.expired."):
            cp.end(json.loads(ln.body)["order_id"], "EXPIRED")
        elif topic == "session.state":
            cp.phase = json.loads(ln.body)["state"]
        else:
            if topic == "quote.new":
                cp.quote_new(json.loads(ln.body))
            cp.feature(topic)
    cp.finish()
    return cp


def _never(cp: _Pass) -> list[tuple[str, list[str]]]:
    """Per dimension, the values the run never produced."""
    seen: list[set[str]] = [set(), set(), set(), set(), set()]
    outcomes: set[str] = set()
    for key, counts in cp.matrix.items():
        for i, value in enumerate(key):
            seen[i].add(value)
        outcomes.update(counts)
    dims: list[tuple[str, list[str]]] = [
        ("entry", [e for e in ENTRIES if e not in seen[0]]),
        ("order_type", [t.value for t in OrderType if t.value not in seen[1]]),
        ("tif", [t.value for t in TIF if t.value not in seen[2]]),
        ("smp_action (resolved)", [s.value for s in SmpAction if s.value not in seen[3]]),  # fmt: skip
        ("smp_action (asked in order.new)", [s.value for s in SmpAction if not cp.asked_smp[s.value]]),  # fmt: skip
        ("phase on entry", [s.value for s in SessionState if s.value not in seen[4]]),
        ("outcome", [o for o in OUTCOMES if o not in outcomes]),
        ("feature message", [f for f in FEATURES if not cp.features[f]]),
    ]
    return [(d, v) for d, v in dims if v]


@check(
    "H5",
    "statistical",
    "Coverage: orders by entry, type, TIF, SMP, phase and outcome; feature messages",
    needs=(),
)
def coverage(ds: Dataset) -> Outcome:
    """INFO: one violation per value of a dimension the run never produced,
    so a zero is visible; then the rarest (entry, type, TIF, SMP, phase)
    combinations with their outcomes."""
    cp = _coverage_pass(ds)
    never = _never(cp)
    rare = sorted(cp.matrix.items(), key=lambda kv: (sum(kv[1].values()), kv[0]))
    samples: list[Sample] = [{"dimension": d, "never": v} for d, v in never]
    for k, c in rare:
        samples.append({"entry": k[0], "order_type": k[1], "tif": k[2], "smp_action": k[3], "phase": k[4], "outcomes": dict(c)})  # fmt: skip
    orders = sum(sum(c.values()) for c in cp.matrix.values())
    note = (
        f"{orders} orders in {len(cp.matrix)} combinations; features: "
        + ", ".join(f"{f} {n}" for f, n in sorted(cp.features.items()))
        + "; explicit SMP asked: "
        + (", ".join(f"{s} {n}" for s, n in sorted(cp.asked_smp.items())) or "none")
        + "; reject codes: "
        + (", ".join(f"{c} {n}" for c, n in cp.reject_codes.most_common()) or "none")
        + "; refused cancels/amends: "
        + (", ".join(f"{c} {n}" for c, n in cp.refused.most_common()) or "none")
    )
    return Outcome(sum(len(v) for _, v in never), samples, note)
