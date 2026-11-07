"""D12 — the circuit breaker, recomputed from the trades (S32).

D11 checks only that nothing trades in CONTINUOUS while a symbol is halted;
E2 and E7 run the engine's own ``CircuitBreakerState``, so they show the
breaker is deterministic, not that it keeps its rule. D12 keeps each
symbol's reference window itself, from the run's config
(``circuit_breaker``: ``reference_window_ns``, the levels, ``reopening``)
and the trades on their own time stamps, as the operator guide describes
it:

- the window holds every print of the last ``reference_window_ns`` (an
  auction's too), the reference is their integer mean; it is seeded at the
  engine's start from the symbol's last buy (else sell) price, while empty;
- a CONTINUOUS print whose distance from the reference is at least a
  level's ``price_shift_pct`` halts the symbol at the deepest such level;
  while halted, prints join no window and halt nothing;
- the halt (``circuit_breaker.halt``, source CB) names that level, the
  print as its trigger, the reference, a call end of the level's duration
  plus at most ``random_end_max_ns``, and the corridor ``reference ± band``;
- each extension (``circuit_breaker.extend``) widens the corridor one rung
  of the ladder and starts a call no shorter than the rung's;
- a timed reopen is not earlier than the call's end and prints inside the
  corridor; the closing backstop prints inside it.

Findings: a halt with no breach, a breach with no halt, a halt whose
numbers differ, a corridor off the ladder, a reopen early or outside its
corridor. Operator halts (source ADMIN) need no breach; they halt the
window all the same. A same-day restart keeps the window (the checkpoint
holds it, X38); a later day's seeds it again.
"""

from __future__ import annotations

import json
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sim_forensics.audit import audit_files, lines, run_config_text
from sim_forensics.dataset import Dataset
from sim_forensics.registry import Outcome, Sample, Skipped, check

from edumatcher.config_artifact import decode as decode_artifact
from edumatcher.engine.circuit_breaker import CircuitBreakerConfig

_KEEP = 50
#: Audit line times have millisecond precision and are written after the
#: engine published.
_SLACK_NS = 2_000_000
#: Commands that end a halt at an administrator's word (no corridor).
_ADMIN_RESUMES = frozenset({"risk.symbol_resume", "risk.circuit_breaker_resume_all"})


@dataclass
class _Breaker:
    config: CircuitBreakerConfig
    window: deque[tuple[int, int]] = field(default_factory=deque)
    total: int = 0
    #: What the engine's breaker calls its reference_price.
    reference: int | None = None
    halted: bool = False
    source: str = ""
    resume_at: int | None = None
    expansion: int = 0
    corridor_ref: int | None = None

    def corridor(self) -> tuple[int, int] | None:
        reopening = self.config.reopening
        if not reopening.enabled or self.corridor_ref is None:
            return None
        ref = self.corridor_ref
        band = ref * reopening.band_pct_at(self.expansion)
        return max(1, int(ref - band)), int(ref + band)

    def seed(self, price: int, now: int) -> None:
        if not self.window:
            self.window.append((now, price))
            self.total = price
            self.reference = price

    def trade(self, price: int, now: int, continuous: bool) -> Any:
        """The level this print fires, if any; it joins the window."""
        cutoff = now - self.config.reference_window_ns
        while self.window and self.window[0][0] < cutoff:
            self.total -= self.window.popleft()[1]
        fired = None
        if self.window and continuous:
            ref = self.total // len(self.window)
            self.reference = ref
            shift = abs(price - ref) / ref if ref > 0 else 0.0
            for level in sorted(self.config.levels, key=lambda lvl: lvl.price_shift_pct):  # fmt: skip
                if shift >= level.price_shift_pct:
                    fired = level
        self.window.append((now, price))
        self.total += price
        return fired


@dataclass
class _Pass:
    td: dict[str, int]
    breakers: dict[str, _Breaker]
    samples: list[Sample] = field(default_factory=list)
    errors: Counter[str] = field(default_factory=Counter)
    seen: Counter[str] = field(default_factory=Counter)
    last_day: Any = None

    def flag(self, error: str, **keys: Any) -> None:
        self.errors[error] += 1
        if len(self.samples) < _KEEP:
            self.samples.append({"error": error, **keys})

    def ticks(self, symbol: str, price: Any) -> int | None:
        return None if price is None else round(float(price) * 10 ** self.td.get(symbol, 2))  # fmt: skip

    def chain(self, msgs: list[tuple[str, dict[str, Any], int]], day: Any, chain: str) -> None:  # fmt: skip
        command = msgs[0][0] if msgs else ""
        for topic, p, ts in msgs:
            if topic == "system.startup":
                self.startup(day)
            elif topic.startswith("system.book_checkpoint.") and p.get("reason") == "STARTUP":  # fmt: skip
                cb = self.breakers.get(p["symbol"])
                price = p.get("last_buy_price_ticks") or p.get("last_sell_price_ticks")
                if cb is not None and price is not None:
                    cb.seed(int(price), ts)
        # A reopen's prints come before its resume, but the engine ended the
        # halt first: they join the window.
        for topic, p, ts in msgs:
            if topic.startswith("circuit_breaker.resume."):
                self.resume(p, msgs, ts, command in _ADMIN_RESUMES, chain)
        expected: dict[str, tuple[Any, dict[str, Any]]] = {}
        for topic, p, ts in msgs:
            if topic == "trade.executed":
                cb = self.breakers.get(p["symbol"])
                if cb is None or cb.halted:
                    continue
                self.seen["prints"] += 1
                level = cb.trade(int(p["price_ticks"]), int(p["ts_ns"]), p.get("match_type") == "CONTINUOUS")  # fmt: skip
                if level is not None:
                    expected[p["symbol"]] = (level, {**p, "reference": cb.reference})
                    cb.halted, cb.source, cb.expansion = True, "CB", 0
                    cb.corridor_ref = cb.reference
                    cb.resume_at = None if level.halt_duration_ns is None else int(p["ts_ns"]) + level.halt_duration_ns  # fmt: skip
            elif topic.startswith("circuit_breaker.halt."):
                self.halt(p, expected, chain)
            elif topic.startswith("circuit_breaker.extend."):
                self.extend(p, ts, chain)
        for symbol, (level, t) in expected.items():
            self.flag("a print breached a level, but no halt followed", symbol=symbol, level=level.name, trade_id=t["id"], price=t["price_ticks"], reference=t["reference"], chain=chain)  # fmt: skip

    def startup(self, day: Any) -> None:
        for cb in self.breakers.values():
            cb.halted, cb.resume_at, cb.expansion, cb.corridor_ref = (
                False,
                None,
                0,
                None,
            )
            if day != self.last_day:
                cb.window.clear()
                cb.total = 0
        self.last_day = day

    def halt(self, p: dict[str, Any], expected: dict[str, tuple[Any, dict[str, Any]]], chain: str) -> None:  # fmt: skip
        sym = p["symbol"]
        cb = self.breakers.get(sym)
        if p.get("halt_source") != "CB":
            self.seen["operator halts"] += 1
            if cb is not None:
                if p.get("level") and p.get("resume_at_ns") is not None:
                    cb.corridor_ref = cb.reference  # a level named: a timed call
                else:
                    cb.reference = None
                    cb.corridor_ref = None
                cb.halted, cb.source, cb.expansion = True, "ADMIN", 0
                cb.resume_at = p.get("resume_at_ns")
            return
        self.seen["breaker halts"] += 1
        if sym not in expected:
            self.flag("halted, but no print breached a level", symbol=sym, level=p.get("level"), chain=chain)  # fmt: skip
            if cb is not None:
                cb.halted, cb.source = True, "CB"
            return
        level, t = expected.pop(sym)
        assert cb is not None
        mine = {
            "level": level.name,
            "trigger_price": int(t["price_ticks"]),
            "reference_price": t["reference"],
            "corridor": cb.corridor(),
        }
        theirs = {
            "level": p.get("level"),
            "trigger_price": self.ticks(sym, p.get("trigger_price")),
            "reference_price": self.ticks(sym, p.get("reference_price")),
            "corridor": None if p.get("corridor_low") is None else (self.ticks(sym, p["corridor_low"]), self.ticks(sym, p["corridor_high"])),  # fmt: skip
        }
        differs = {k: (theirs[k], mine[k]) for k in mine if theirs[k] != mine[k]}
        if differs:
            self.flag("the halt's numbers are not the breach's", symbol=sym, engine_replay=differs, chain=chain)  # fmt: skip
        resume = p.get("resume_at_ns")
        if (resume is None) != (cb.resume_at is None) or (
            resume is not None and cb.resume_at is not None and not cb.resume_at <= resume <= cb.resume_at + cb.config.reopening.random_end_max_ns  # fmt: skip
        ):
            self.flag("the halt's call end is not the level's duration", symbol=sym, resume_at_ns=resume, earliest=cb.resume_at, chain=chain)  # fmt: skip
        cb.resume_at = resume

    def extend(self, p: dict[str, Any], ts: int, chain: str) -> None:
        sym = p["symbol"]
        cb = self.breakers.get(sym)
        if cb is None:
            return
        self.seen["extensions"] += 1
        before = cb.corridor()
        price = self.ticks(sym, p.get("indicative_price"))
        if before is not None and price is not None and before[0] <= price <= before[1]:  # fmt: skip
            self.flag("extended, but the indicative price was inside the corridor", symbol=sym, price=price, corridor=before, chain=chain)  # fmt: skip
        cb.expansion += 1
        mine = cb.corridor()
        theirs = None if p.get("corridor_low") is None else (self.ticks(sym, p["corridor_low"]), self.ticks(sym, p["corridor_high"]))  # fmt: skip
        if theirs != mine or p.get("expansion") != cb.expansion:
            self.flag("the extended corridor is not the ladder's", symbol=sym, engine=(theirs, p.get("expansion")), replay=(mine, cb.expansion), chain=chain)  # fmt: skip
        resume = p.get("resume_at_ns")
        rung = cb.config.reopening.duration_at(cb.expansion)
        if resume is not None and cb.resume_at is not None and resume < cb.resume_at + rung:  # fmt: skip
            self.flag("the extension's call is shorter than its rung", symbol=sym, resume_at_ns=resume, earliest=cb.resume_at + rung, chain=chain)  # fmt: skip
        if resume is not None and resume > ts + rung + cb.config.reopening.random_end_max_ns + _SLACK_NS:  # fmt: skip
            self.flag("the extension's call is longer than its rung and tail", symbol=sym, resume_at_ns=resume, chain=chain)  # fmt: skip
        cb.resume_at = resume

    def resume(self, p: dict[str, Any], msgs: list[tuple[str, dict[str, Any], int]], ts: int, by_admin: bool, chain: str) -> None:  # fmt: skip
        sym = p["symbol"]
        cb = self.breakers.get(sym)
        if cb is None:
            return
        self.seen["reopens"] += 1
        corridor = cb.corridor()
        reason = p.get("reason")
        if reason == "CLOSING_BACKSTOP":
            price = self.ticks(sym, p.get("print_price"))
            if corridor is not None and price is not None and not corridor[0] <= price <= corridor[1]:  # fmt: skip
                self.flag("the closing backstop printed outside the corridor", symbol=sym, price=price, corridor=corridor, chain=chain)  # fmt: skip
        elif not by_admin:
            if cb.resume_at is not None and ts + _SLACK_NS < cb.resume_at:
                self.flag("reopened before the call's end", symbol=sym, at=ts, resume_at_ns=cb.resume_at, chain=chain)  # fmt: skip
            result = next((x for t, x, _ in msgs if t == f"auction.result.{sym}"), None)
            price = self.ticks(sym, result.get("eq_price")) if result else None
            if corridor is not None and price is not None and not corridor[0] <= price <= corridor[1]:  # fmt: skip
                self.flag("reopened outside the corridor", symbol=sym, price=price, corridor=corridor, chain=chain)  # fmt: skip
        cb.halted, cb.resume_at, cb.expansion, cb.corridor_ref = False, None, 0, None


def _ns(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1e9)


@check(
    "D12",
    "book-state",
    "Each circuit-breaker halt, extension and reopen follows from the trades and the config",
    needs=(),
)
def breakers(ds: Dataset) -> Outcome:
    files = audit_files(ds.data_dir)
    if not files:
        raise Skipped("no audit.log in the data dir")
    try:
        config = decode_artifact(run_config_text(files)).engine
    except Exception as exc:  # an audit made before S21 has no config line
        raise Skipped(f"no engine config in the audit: {exc}") from exc
    if not config.enforce_circuit_breakers:
        raise Skipped("circuit breakers are not enforced")
    found = {s: _Breaker(c.circuit_breaker) for s, c in config.symbols.items() if c.circuit_breaker}  # fmt: skip
    if not found:
        raise Skipped("no symbol has a circuit breaker")
    p = _Pass({s: c.tick_decimals for s, c in config.symbols.items()}, found)
    chain = ""
    msgs: list[tuple[str, dict[str, Any], int]] = []
    day = None
    wanted = ("trade.executed", "system.startup", "system.book_checkpoint.", "circuit_breaker.", "auction.result.", "risk.symbol_resume", "risk.circuit_breaker_resume_all")  # fmt: skip
    for ln in lines(files):
        if ln.chain != chain:
            if msgs:
                p.chain(msgs, day, chain)
            chain, msgs = ln.chain, []
        if not ln.topic.startswith(wanted):
            continue
        ts = _ns(ln.ts)
        if ln.topic == "system.startup":
            day = datetime.fromtimestamp(ts / 1e9, ds.session_tz).date()
        msgs.append((ln.topic, json.loads(ln.body), ts))
    if msgs:
        p.chain(msgs, day, chain)
    note = ", ".join(f"{k} {n}" for k, n in sorted(p.seen.items())) or "no print in a symbol with a breaker"  # fmt: skip
    note += "".join(f"; {e}: {n}" for e, n in p.errors.most_common())
    return Outcome(sum(p.errors.values()), p.samples, note)
