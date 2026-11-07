"""C12 — every refusal is justified, and every acceptance too (S30); C13 —
a kill switch or a disconnect cancels exactly what it names (S31); C14 —
orders expire as their time in force ends, and nothing outlives it (S33).

D8 checks the collar both ways; C12 does it for the refusals the engine
decides from state the audit shows, each command judged on the state
before its dispatch:

- ``order.new``, the gates of ``Engine._handle_new_order`` in their order:
  the gateway configured, the symbol configured, the fields (a duplicate
  live id, a quantity or price not positive, an iceberg's slice), the
  symbol's order limits, the session (closed; ATO / ATC outside their
  auction), a halt (MARKET / FOK / IOC refused, CIRCUIT_BREAKER_ACTIVE for
  a breaker's halt, INSTRUMENT_HALTED for an operator's), and MARKET / FOK
  / IOC outside continuous trading;
- ``order.cancel`` and ``order.amend``: the order live (ORDER_NOT_FOUND;
  an amend may say ORDER_ALREADY_TERMINAL) and the gateway's own
  (NOT_OWNER);
- ``order.oco_cancel``: the pair still registered (both legs live);
- ``quote.new``: the market maker's spread and size obligation;
  ``quote.cancel``: an active quote on the symbol.

A refusal for one of these reasons that does not hold is a finding, and so
is an acceptance that meets one. Refusals the state here cannot judge are
counted, not checked: the collar (D8), a FOK's or an all-or-none combo's
liquidity (the replay's books, ``matching.py``, under C12 too), a gateway
not connected, the per-type field rules. ``INTERNAL_ERROR`` is always a
finding. The set of live orders is reset from every book checkpoint.

C13, on the same state: a kill switch -- a gateway's own (``risk.kill_switch``,
one symbol or all), an administrator's on one gateway
(``risk.kill_switch_gateway``: one symbol or all, its quotes only or
everything) or on the market (``risk.kill_switch_global``) -- and a
disconnect or a missed-heartbeat timeout (``system.gateway_bye``: the
gateway's ``disconnect_behaviour``, LEAVE_ALL, CANCEL_QUOTES_ONLY or
CANCEL_ALL) cancel every live order in their scope, quote legs included
(also a hit quote's remainder), and nothing beyond it, each with its
reason (KILL_SWITCH, GATEWAY_DISCONNECT); a cascade it sets off (an OCO
sibling, a combo's other legs) is part of it. An accepted switch's ack lists
exactly what it cancelled, quote legs apart, and counts its lists; a
refused one cancels nothing; the administrator's two need an ADMIN caller.
A kill switch is a mass cancel: nothing keeps the gateway from trading
again (KILL_SWITCH_ACTIVE is in the spec's enum but no gate uses it).

C14, on the same state, each order's TIF from its ack (a quote's legs from
their ``quote.new``, the books from their checkpoints): an
``order.expired`` only as its window ends -- DAY at the transition to
CLOSED, ATO as the opening auction ends, ATC as the closing auction ends --
and never for a GTC order; after that transition no order of the TIF is
live; and a quote whose legs expired at the close ends with them (a
``quote.status`` that is not ACTIVE).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sim_forensics.audit import audit_files, lines, run_config_text
from sim_forensics.dataset import Dataset
from sim_forensics.registry import Sample, Skipped

from edumatcher.config_artifact import decode as decode_artifact
from edumatcher.engine.config_loader import EngineConfig

_KEEP = 50
_COMMANDS = frozenset({"order.new", "order.cancel", "order.amend", "order.oco_cancel", "quote.new", "quote.cancel", "risk.kill_switch", "risk.kill_switch_gateway", "risk.kill_switch_global", "system.gateway_disconnect"})  # fmt: skip
#: order.new codes this check derives; any other refusal is counted only.
_NEW_CODES = frozenset({"GATEWAY_NOT_CONFIGURED", "UNKNOWN_SYMBOL", "DUPLICATE_ORDER", "QTY_OUT_OF_RANGE", "PRICE_OUT_OF_RANGE", "MAX_ORDER_QTY", "MAX_ORDER_VALUE", "MARKET_CLOSED", "SESSION_NOT_PERMITTED", "INSTRUMENT_HALTED", "CIRCUIT_BREAKER_ACTIVE"})  # fmt: skip
_CANNOT_REST = frozenset({"MARKET", "FOK", "IOC"})
_STAMPED_SIDES = ("bids", "asks", "buy_stops", "sell_stops", "trailing_stops")
#: Kill-switch commands and the prefix of each's ack.
_KILL_SWITCHES = {
    "risk.kill_switch": "risk.kill_switch_ack.",
    "risk.kill_switch_gateway": "risk.kill_switch_gateway_ack.",
    "risk.kill_switch_global": "risk.kill_switch_global_ack.",
}
#: Messages that create the orders and pairs a dispatch's ends then name.
_CREATING = ("order.ack.", "quote.ack.", "oco.ack.")


@dataclass
class _Live:
    gw: str
    symbol: str
    oco: str | None = None
    quote: bool = False  # a market maker's quote leg
    tif: str | None = None


@dataclass
class _Pass:
    config: EngineConfig
    samples: list[Sample] = field(default_factory=list)
    errors: Counter[str] = field(default_factory=Counter)
    judged: Counter[str] = field(default_factory=Counter)
    unjudged: Counter[str] = field(default_factory=Counter)
    #: C13's own: kill switches and disconnects.
    sweep_samples: list[Sample] = field(default_factory=list)
    sweep_errors: Counter[str] = field(default_factory=Counter)
    sweeps: Counter[str] = field(default_factory=Counter)
    #: C14's own: expiries.
    expiry_samples: list[Sample] = field(default_factory=list)
    expiry_errors: Counter[str] = field(default_factory=Counter)
    expiries: Counter[str] = field(default_factory=Counter)
    #: The TIF of the quote.new this dispatch answers (its legs carry none).
    quote_tif: str | None = None
    #: Quote id → its two legs.
    _legs_of: dict[str, tuple[str, ...]] = field(default_factory=dict)
    phase: str | None = None
    #: Symbol → halt source (CB, ADMIN).
    halted: dict[str, str] = field(default_factory=dict)
    live: dict[str, _Live] = field(default_factory=dict)
    #: (gateway, oco id) → its two legs, while both are live.
    oco: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    #: (gateway, symbol) → the active quote's id.
    quotes: dict[tuple[str, str], str] = field(default_factory=dict)
    #: Quote id → (gateway, symbol): quote.status names only the quote.
    quote_of: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: (gateway, symbol) → its live quote legs, active quote or not: a
    #: quote cancel also clears a hit leg's remainder.
    quote_legs: dict[tuple[str, str], set[str]] = field(default_factory=dict)

    def flag(self, error: str, **keys: Any) -> None:
        self.errors[error] += 1
        if len(self.samples) < _KEEP:
            self.samples.append({"error": error, **keys})

    # --- judging ---------------------------------------------------------

    def judge(self, topic: str, p: dict[str, Any], out: list[tuple[str, dict[str, Any]]], chain: str) -> None:  # fmt: skip
        for t, x in out:
            if x.get("reject_code") == "INTERNAL_ERROR":
                self.flag("INTERNAL_ERROR", topic=t, reason=x.get("reason"), chain=chain)  # fmt: skip
        if topic == "order.new":
            self._new(p, out, chain)
        elif topic in ("order.cancel", "order.amend"):
            self._cancel_or_amend(topic, p, out, chain)
        elif topic == "order.oco_cancel":
            self._oco_cancel(p, out, chain)
        elif topic == "quote.new":
            self._quote(p, out, chain)
        elif topic == "quote.cancel":
            self._quote_cancel(p, out, chain)

    # --- C13: kill switches and disconnects -----------------------------

    def sweep_flag(self, error: str, **keys: Any) -> None:
        self.sweep_errors[error] += 1
        if len(self.sweep_samples) < _KEEP:
            self.sweep_samples.append({"error": error, **keys})

    def sweep(self, topic: str, p: dict[str, Any], out: list[tuple[str, dict[str, Any]]], chain: str) -> None:  # fmt: skip
        """C13: a kill switch or a disconnect cancels exactly the live
        orders it names, for its reason, and its ack lists them."""
        # A cascade cancels with it: an OCO sibling, a combo's other legs
        # (no reason).
        cancels: dict[str, str | None] = {}
        for t, x in out:
            if t.startswith("order.cancelled."):
                cancels[x["order_id"]] = x.get("cancel_reason")
            elif t.startswith("oco.cancelled."):
                cancels[x["cancelled_order_id"]] = "OCO_SIBLING"
        if topic in _KILL_SWITCHES:
            ack = next((x for t, x in out if t.startswith(_KILL_SWITCHES[topic])), None)  # fmt: skip
            if ack is None:
                self.unjudged[f"{topic} without an ack"] += 1
                return
            what = topic.removeprefix("risk.")
            caller = str(p.get("gateway_id") or "").upper()
            if not ack.get("accepted"):
                if any(r == "KILL_SWITCH" for r in cancels.values()):
                    self.sweep_flag(f"{what} refused, but it cancelled", chain=chain)
                self.sweeps[f"{what} refused"] += 1
                return
            if topic != "risk.kill_switch" and self._role(caller) != "ADMIN":
                self.sweep_flag(f"{what} accepted from {caller}, not an ADMIN", chain=chain)  # fmt: skip
            target = None if topic == "risk.kill_switch_global" else caller if topic == "risk.kill_switch" else str(p.get("target_gateway_id") or "").upper()  # fmt: skip
            symbol = None if topic == "risk.kill_switch_global" else p.get("symbol") or None  # fmt: skip
            quotes_only = topic == "risk.kill_switch_gateway" and bool(p.get("quotes_only"))  # fmt: skip
            self._swept(what, self._scope(target, symbol, quotes_only), cancels, "KILL_SWITCH", ack, chain)  # fmt: skip
            return
        bye = next((t.rsplit(".", 1)[1] for t, _ in out if t.startswith("system.gateway_bye.")), None)  # fmt: skip
        if bye is not None:
            cfg = self.config.participants.get(bye)
            behaviour = cfg.disconnect_behaviour.value if cfg is not None else "CANCEL_QUOTES_ONLY"  # fmt: skip
            scope = set() if behaviour == "LEAVE_ALL" else self._scope(bye, None, behaviour == "CANCEL_QUOTES_ONLY")  # fmt: skip
            self._swept(f"disconnect {behaviour}", scope, cancels, "GATEWAY_DISCONNECT", None, chain)  # fmt: skip

    def _role(self, gw: str) -> str:
        cfg = self.config.participants.get(gw)
        return cfg.role.value if cfg is not None else ""

    def _scope(self, gw: str | None, symbol: str | None, quotes_only: bool) -> set[str]:  # fmt: skip
        return {
            oid
            for oid, o in self.live.items()
            if (gw is None or o.gw == gw) and (symbol is None or o.symbol == symbol) and (o.quote or not quotes_only)  # fmt: skip
        }

    def _swept(self, what: str, scope: set[str], cancels: dict[str, str | None], reason: str, ack: dict[str, Any] | None, chain: str) -> None:  # fmt: skip
        self.sweeps[what] += 1
        left = sorted(scope - cancels.keys())
        if left:
            self.sweep_flag(f"{what} left orders live", chain=chain, count=len(left), example=left[:3])  # fmt: skip
        beyond = sorted(oid for oid, r in cancels.items() if oid not in scope and r == reason)  # fmt: skip
        if beyond:
            self.sweep_flag(f"{what} cancelled beyond its scope", chain=chain, count=len(beyond), example=beyond[:3])  # fmt: skip
        wrong = sorted(oid for oid, r in cancels.items() if oid in scope and r not in (reason, None, "OCO_SIBLING"))  # fmt: skip
        if wrong:
            self.sweep_flag(f"{what} cancelled for another reason", chain=chain, count=len(wrong), reasons=sorted({str(cancels[o]) for o in wrong}))  # fmt: skip
        if ack is None:
            return
        orders, quotes = ack.get("cancelled_order_ids") or [], ack.get("cancelled_quote_order_ids") or []  # fmt: skip
        if (ack.get("cancelled_orders"), ack.get("cancelled_quotes")) != (len(orders), len(quotes)):  # fmt: skip
            self.sweep_flag(f"{what} ack's counts are not its lists", chain=chain, counts=(ack.get("cancelled_orders"), ack.get("cancelled_quotes")), lists=(len(orders), len(quotes)))  # fmt: skip
        listed = set(orders) | set(quotes)
        own = {oid for oid, r in cancels.items() if r == reason}
        if listed != own:
            self.sweep_flag(f"{what} ack's lists are not what it cancelled", chain=chain, unlisted=sorted(own - listed)[:3], not_cancelled=sorted(listed - own)[:3])  # fmt: skip
        misfiled = [o for o in orders if o in self.live and self.live[o].quote]
        misfiled += [o for o in quotes if o in self.live and not self.live[o].quote]
        if misfiled:
            self.sweep_flag(f"{what} ack files a quote leg as an order or the reverse", chain=chain, example=misfiled[:3])  # fmt: skip

    def _verdict(self, what: str, refused: str | None, expected: str | None, modelled: frozenset[str], chain: str, **keys: Any) -> None:  # fmt: skip
        """Compare the engine's answer (*refused*: its code, None when it
        accepted) with the one the state calls for."""
        if refused is not None and refused not in modelled:
            if refused != "INSUFFICIENT_LIQUIDITY":  # the book part's (matching.py)
                self.unjudged[f"{what} {refused}"] += 1
            return
        self.judged[what] += 1
        if refused == expected:
            return
        if refused is None:
            self.flag(f"{what} accepted, but {expected} applies", chain=chain, **keys)  # fmt: skip
        else:
            self.flag(f"{what} refused {refused}, but {expected or 'nothing'} applies", chain=chain, **keys)  # fmt: skip

    def _new_expected(self, p: dict[str, Any]) -> str | None:
        """The first gate of ``Engine._handle_new_order`` that refuses *p*."""
        cfg = self.config
        gw, sym, kind = str(p["gateway_id"]).upper(), p["symbol"], p["order_type"]
        if cfg.participants and gw not in cfg.participants:
            return "GATEWAY_NOT_CONFIGURED"
        if cfg.symbols and sym not in cfg.symbols:
            return "UNKNOWN_SYMBOL"
        if p["id"] in self.live:
            return "DUPLICATE_ORDER"
        qty = int(p["quantity"])
        if qty <= 0:
            return "QTY_OUT_OF_RANGE"
        price = p.get("price_ticks")
        if price is not None and price <= 0:
            return "PRICE_OUT_OF_RANGE"
        visible = p.get("visible_qty")
        if kind == "ICEBERG" and visible is not None and visible > qty:
            return "QTY_OUT_OF_RANGE"
        limits = cfg.symbols[sym].order_limits if sym in cfg.symbols else None
        if limits is not None:
            if limits.max_order_qty is not None and qty > limits.max_order_qty:
                return "MAX_ORDER_QTY"
            td = cfg.symbols[sym].tick_decimals
            if limits.max_order_value is not None and price is not None and qty * price / 10**td > limits.max_order_value:  # fmt: skip
                return "MAX_ORDER_VALUE"
        if cfg.sessions_enabled:
            if self.phase == "CLOSED":
                return "MARKET_CLOSED"
            if p.get("tif") == "ATO" and self.phase != "OPENING_AUCTION":
                return "SESSION_NOT_PERMITTED"
            if p.get("tif") == "ATC" and self.phase != "CLOSING_AUCTION":
                return "SESSION_NOT_PERMITTED"
        if sym in self.halted and kind in _CANNOT_REST:
            return "CIRCUIT_BREAKER_ACTIVE" if self.halted[sym] == "CB" else "INSTRUMENT_HALTED"  # fmt: skip
        continuous = self.phase == "CONTINUOUS" or not cfg.sessions_enabled
        if not continuous and kind in _CANNOT_REST:
            return "SESSION_NOT_PERMITTED"
        return None

    def _new(self, p: dict[str, Any], out: list[tuple[str, dict[str, Any]]], chain: str) -> None:  # fmt: skip
        if self.phase is None and self.config.sessions_enabled:
            self.unjudged["order.new before the phase is known"] += 1
            return
        acks = [x for t, x in out if t.startswith("order.ack.") and x.get("order_id") == p["id"]]  # fmt: skip
        if not acks:
            self.unjudged["order.new without an ack"] += 1
            return
        # An accepted FOK may be refused after the book decided (X5): the
        # first answer is the gates'.
        first = acks[0]
        refused = None if first.get("accepted") else first.get("reject_code")
        self._verdict("order.new", refused, self._new_expected(p), _NEW_CODES, chain, order_id=p["id"], symbol=p["symbol"], order_type=p["order_type"], phase=self.phase)  # fmt: skip

    def _cancel_or_amend(self, topic: str, p: dict[str, Any], out: list[tuple[str, dict[str, Any]]], chain: str) -> None:  # fmt: skip
        oid, gw = p["order_id"], str(p["gateway_id"]).upper()
        done = "order.cancelled." if topic == "order.cancel" else "order.amended."
        refused: str | None = "?"
        for t, x in out:
            if x.get("order_id") != oid:
                continue
            if t.startswith("order.ack.") and not x.get("accepted"):
                refused = x.get("reject_code")
                break
            if t.startswith(done):
                refused = None
                break
        if refused == "?":
            self.unjudged[f"{topic} without an answer"] += 1
            return
        o = self.live.get(oid)
        expected = (
            "ORDER_NOT_FOUND" if o is None else "NOT_OWNER" if o.gw != gw else None
        )
        if topic == "order.amend" and expected == "ORDER_NOT_FOUND" and refused == "ORDER_ALREADY_TERMINAL":  # fmt: skip
            expected = refused
        modelled = frozenset({"ORDER_NOT_FOUND", "NOT_OWNER", "ORDER_ALREADY_TERMINAL"})
        if refused is not None and refused not in modelled and expected is None:
            self.unjudged[f"{topic} {refused}"] += 1
            return
        self._verdict(topic, refused, expected, modelled | ({refused} if refused else frozenset()), chain, order_id=oid, gateway_id=gw)  # fmt: skip

    def _oco_cancel(self, p: dict[str, Any], out: list[tuple[str, dict[str, Any]]], chain: str) -> None:  # fmt: skip
        ack = next((x for t, x in out if t.startswith("oco.cancel_ack.")), None)
        if ack is None:
            self.unjudged["order.oco_cancel without an answer"] += 1
            return
        key = (str(p["gateway_id"]).upper(), str(p["oco_id"]))
        refused = None if ack.get("accepted") else ack.get("reject_code")
        expected = None if key in self.oco else "ORDER_NOT_FOUND"
        self._verdict("order.oco_cancel", refused, expected, frozenset({"ORDER_NOT_FOUND"}), chain, oco_id=key[1], gateway_id=key[0])  # fmt: skip

    def _quote(self, p: dict[str, Any], out: list[tuple[str, dict[str, Any]]], chain: str) -> None:  # fmt: skip
        ack = next((x for t, x in out if t.startswith("quote.ack.")), None)
        if ack is None:
            self.unjudged["quote.new without an answer"] += 1
            return
        gw, sym = str(p["gateway_id"]).upper(), p["symbol"]
        reason = str(ack.get("reason") or "")
        refused = None if ack.get("accepted") else "MM_SPREAD" if reason.startswith("Spread ") else "MM_SIZE" if reason.startswith("Quote size must be") else reason  # fmt: skip
        expected = None
        policy = self._mm_policy(gw, sym)
        if policy is not None:
            spread_max, min_qty = policy
            if int(p["ask_price_ticks"]) - int(p["bid_price_ticks"]) > spread_max:
                expected = "MM_SPREAD"
            elif int(p["bid_qty"]) < min_qty or int(p["ask_qty"]) < min_qty:
                expected = "MM_SIZE"
        self._verdict("quote.new", refused, expected, frozenset({"MM_SPREAD", "MM_SIZE"}), chain, quote_id=p.get("quote_id"), symbol=sym, gateway_id=gw)  # fmt: skip

    def _mm_policy(self, gw: str, sym: str) -> tuple[int, int] | None:
        """(max spread in ticks, min size) a quote must meet, or None: the
        gateway and symbol's policy, the symbol's, the gateway's."""
        cfg = self.config.participants.get(gw)
        if cfg is None:
            return None
        policy: Any = cfg
        symbol_policy = self.config.global_symbol_mm_obligation_policies.get(sym)
        if symbol_policy is not None:
            policy = symbol_policy
        if sym in cfg.mm_obligation_policies:
            policy = cfg.mm_obligation_policies[sym]
        if not policy.enforce_mm_obligation:
            return None
        return int(policy.mm_max_spread_ticks), int(policy.mm_min_qty)

    def _quote_cancel(self, p: dict[str, Any], out: list[tuple[str, dict[str, Any]]], chain: str) -> None:  # fmt: skip
        ack = next((x for t, x in out if t.startswith("quote.cancel_ack.")), None)
        if ack is None:
            self.unjudged["quote.cancel without an answer"] += 1
            return
        key = (str(p["gateway_id"]).upper(), p["symbol"])
        refused = None if ack.get("accepted") else ack.get("reject_code")
        expected = None if key in self.quotes or self.quote_legs.get(key) else "ORDER_NOT_FOUND"  # fmt: skip
        self._verdict("quote.cancel", refused, expected, frozenset({"ORDER_NOT_FOUND"}), chain, symbol=key[1], gateway_id=key[0])  # fmt: skip

    # --- state -----------------------------------------------------------

    def add(self, oid: str, o: _Live) -> None:
        self.live[oid] = o
        if o.quote:
            self.quote_legs.setdefault((o.gw, o.symbol), set()).add(oid)

    def end(self, oid: str) -> None:
        o = self.live.pop(oid, None)
        if o is None:
            return
        if o.oco is not None:
            self.oco.pop((o.gw, o.oco), None)
        if o.quote:
            self.quote_legs.get((o.gw, o.symbol), set()).discard(oid)

    def dispatch(self, command: str, body: dict[str, Any], out: list[tuple[str, dict[str, Any]]], chain: str) -> None:  # fmt: skip
        """One dispatch: judged (C12, C13, C14) on the state before it,
        then applied."""
        if command:
            self.judge(command, body, out, chain)
        self.sweep(command, body, out, chain)
        prev = self.phase
        state = next((x["state"] for t, x in out if t == "session.state"), None)
        self.expired(out, prev, state, chain)
        self.quote_tif = body.get("tif") if command == "quote.new" else None
        quotes = dict(self.quotes)
        # The messages' account first, then the books' own (the checkpoints
        # a transition publishes): each must show the window closed.
        books = [(t, x) for t, x in out if t.startswith("system.book_checkpoint.")]
        self.apply_all([(t, x) for t, x in out if not t.startswith("system.book_checkpoint.")])  # fmt: skip
        self.outlived(out, prev, state, quotes, chain)
        self.apply_all(books)

    # --- C14: expiries ----------------------------------------------------

    def expiry_flag(self, error: str, **keys: Any) -> None:
        self.expiry_errors[error] += 1
        if len(self.expiry_samples) < _KEEP:
            self.expiry_samples.append({"error": error, **keys})

    @staticmethod
    def _window(tif: str | None, prev: str | None, state: str | None) -> bool:
        """Whether this dispatch ends *tif*'s window: DAY at the close, ATO
        and ATC as their auction ends."""
        if tif == "DAY":
            return state == "CLOSED" and prev != "CLOSED"
        auction = {"ATO": "OPENING_AUCTION", "ATC": "CLOSING_AUCTION"}.get(tif or "")
        return auction is not None and prev == auction and state not in (None, auction)  # fmt: skip

    def expired(self, out: list[tuple[str, dict[str, Any]]], prev: str | None, state: str | None, chain: str) -> None:  # fmt: skip
        """C14: an order expires only as its window ends, and a GTC never."""
        for t, x in out:
            if not t.startswith("order.expired."):
                continue
            o = self.live.get(x["order_id"])
            if o is None:
                self.expiry_flag("expired an order not live", order_id=x["order_id"], chain=chain)  # fmt: skip
                continue
            self.expiries[f"{o.tif} expired"] += 1
            if not self._window(o.tif, prev, state):
                self.expiry_flag(f"a {o.tif} order expired outside its window", order_id=x["order_id"], phase=(prev, state), chain=chain)  # fmt: skip

    def outlived(self, out: list[tuple[str, dict[str, Any]]], prev: str | None, state: str | None, quotes: dict[tuple[str, str], str], chain: str) -> None:  # fmt: skip
        """C14: no order outlives its window, and a quote whose legs expired
        at the close ends with them."""
        if state is None or state == prev:
            return
        for tif in ("DAY", "ATO", "ATC"):
            if not self._window(tif, prev, state):
                continue
            left = sorted(oid for oid, o in self.live.items() if o.tif == tif)
            self.expiries[f"{tif} windows closed"] += 1
            if left:
                self.expiry_flag(f"{tif} orders outlived their window", count=len(left), example=left[:3], chain=chain)  # fmt: skip
            kept = sorted(o["order_id"] for t, x in out if t.startswith("system.book_checkpoint.") for side in _STAMPED_SIDES for o in x.get(side) or [] if o.get("tif") == tif)  # fmt: skip
            if kept:
                self.expiry_flag(f"{tif} orders outlived their window in the book", count=len(kept), example=kept[:3], chain=chain)  # fmt: skip
        if state != "CLOSED":
            return
        expired = {x["order_id"] for t, x in out if t.startswith("order.expired.")}
        ended = {x["quote_id"] for t, x in out if t.startswith("quote.status.") and x.get("status") != "ACTIVE"}  # fmt: skip
        for key, qid in quotes.items():
            legs_gone = not self.quote_legs.get(key)
            if legs_gone and qid not in ended and self.quotes.get(key) == qid and any(o in expired for o in self._legs_of.get(qid, ())):  # fmt: skip
                self.expiry_flag("a quote's legs expired at the close, but the quote did not end", quote_id=qid, gateway_id=key[0], symbol=key[1], chain=chain)  # fmt: skip

    def apply_all(self, out: list[tuple[str, dict[str, Any]]]) -> None:
        """A dispatch's messages: what it created first, then the rest in
        order -- an order may be acked after it already traded (an OCO's
        legs after its oco.ack, a quote's fills beside its ack)."""
        for t, x in out:
            if t.startswith(_CREATING):
                self.apply(t, x)
        for t, x in out:
            if not t.startswith(_CREATING):
                self.apply(t, x)

    def apply(self, topic: str, p: dict[str, Any]) -> None:
        """What one engine message changes."""
        if topic.startswith("order.ack."):
            if p.get("accepted") and p.get("order_id") and p.get("symbol"):
                self.add(p["order_id"], _Live(topic.rsplit(".", 1)[1], p["symbol"], p.get("oco_group_id"), bool(p.get("quote_id") or p.get("is_seed")), p.get("tif")))  # fmt: skip
                if p.get("quote_id"):
                    self._legs_of[p["quote_id"]] = (*self._legs_of.get(p["quote_id"], ()), p["order_id"])  # fmt: skip
                    self.quote_of.setdefault(p["quote_id"], (topic.rsplit(".", 1)[1], p["symbol"]))  # fmt: skip
            elif not p.get("accepted") and p.get("order_id") in self.live and p.get("reject_code") == "INSUFFICIENT_LIQUIDITY":  # fmt: skip
                self.end(p["order_id"])  # acked, then refused by the book (X5)
        elif topic.startswith("order.fill."):
            if p.get("remaining_qty") == 0:
                self.end(p["order_id"])
        elif topic.startswith(("order.cancelled.", "order.expired.")):
            self.end(p["order_id"])
        elif topic.startswith("oco.cancelled."):
            self.end(p["cancelled_order_id"])
        elif topic.startswith("oco.ack."):
            if p.get("accepted"):
                # A leg's own ack names the pair; one that ends on entry
                # unregisters it (end).
                gw = topic.rsplit(".", 1)[1]
                self.oco[(gw, p["oco_id"])] = (p["order_id_1"], p["order_id_2"])
        elif topic.startswith("quote.status."):
            key = self.quote_of.get(p["quote_id"])
            if key is not None:
                if p.get("status") == "ACTIVE":
                    self.quotes[key] = p["quote_id"]
                elif self.quotes.get(key) == p["quote_id"]:
                    del self.quotes[key]
        elif topic.startswith("quote.ack."):
            if p.get("accepted"):
                key = (topic.rsplit(".", 1)[1], p["symbol"])
                self.quote_of[p["quote_id"]] = key
                self.quotes[key] = p["quote_id"]
                self._legs_of[p["quote_id"]] = tuple(p[side] for side in ("bid_order_id", "ask_order_id") if p.get(side))  # fmt: skip
                for oid in self._legs_of[p["quote_id"]]:
                    self.add(oid, _Live(key[0], key[1], quote=True, tif=self.quote_tif))
        elif topic.startswith("quote.cancel_ack."):
            if p.get("accepted"):
                self.quotes.pop((topic.rsplit(".", 1)[1], p["symbol"]), None)
                for oid in p.get("cancelled_order_ids") or []:
                    self.end(oid)
        elif topic.startswith("circuit_breaker.halt."):
            self.halted[p["symbol"]] = p.get("halt_source") or "CB"
        elif topic.startswith("circuit_breaker.resume."):
            self.halted.pop(p["symbol"], None)
        elif topic == "session.state":
            self.phase = p["state"]
        elif topic == "system.startup":
            self.live.clear()
            self.oco.clear()
            self.quotes.clear()
            self.quote_legs.clear()
            self.halted.clear()
            self.phase = None
        elif topic.startswith("system.book_checkpoint."):
            self.checkpoint(p)

    def checkpoint(self, p: dict[str, Any]) -> None:
        """The engine's own account of a book: its live orders, as they are."""
        sym = p["symbol"]
        self.phase = p.get("phase") or self.phase
        for oid in [oid for oid, o in self.live.items() if o.symbol == sym]:
            self.end(oid)
        groups: dict[tuple[str, str], list[str]] = {}
        quotes: dict[tuple[str, str], set[str]] = {}
        for side in _STAMPED_SIDES:
            for o in p.get(side) or []:
                gw = o["gateway_id"]
                self.add(o["order_id"], _Live(gw, sym, o.get("oco_group_id"), bool(o.get("quote_id")), o.get("tif")))  # fmt: skip
                if o.get("oco_group_id"):
                    groups.setdefault((gw, o["oco_group_id"]), []).append(o["order_id"])  # fmt: skip
                if o.get("quote_id"):
                    quotes.setdefault((gw, o["quote_id"]), set()).add(o["order_id"])
                    self.quote_of[o["quote_id"]] = (gw, sym)
                    self._legs_of[o["quote_id"]] = tuple(
                        sorted(quotes[(gw, o["quote_id"])])
                    )
        for key, legs in groups.items():
            if len(legs) == 2:
                self.oco[key] = (legs[0], legs[1])
        if p.get("reason") == "STARTUP":
            for (gw, qid), ids in quotes.items():
                if len(ids) == 2:
                    self.quotes[(gw, sym)] = qid


def _config(files: list[Any]) -> EngineConfig:
    return decode_artifact(run_config_text(files)).engine


def state_pass(ds: Dataset) -> _Pass:
    """The pass over the audit (once per dataset); ``matching.py`` registers
    C12 and C13 with it."""
    cached = ds.cache.get("refusals")
    if isinstance(cached, _Pass):
        return cached
    p = _state_pass(ds)
    ds.cache["refusals"] = p
    return p


def _state_pass(ds: Dataset) -> _Pass:
    files = audit_files(ds.data_dir)
    if not files:
        raise Skipped("no audit.log in the data dir")
    try:
        config = _config(files)
    except Exception as exc:  # an audit made before S21 has no config line
        raise Skipped(f"no engine config in the audit: {exc}") from exc
    p = _Pass(config)
    chain, command = "", ""
    body: dict[str, Any] = {}
    out: list[tuple[str, dict[str, Any]]] = []
    for ln in lines(files):
        if ln.chain != chain:
            p.dispatch(command, body, out, chain)
            chain, command, body, out = ln.chain, "", {}, []
        if ln.topic in _COMMANDS and not command and not out:
            command, body = ln.topic, json.loads(ln.body)
            continue
        if ln.topic.startswith(("book.", "depth.", "auction.indicative.")):
            continue
        out.append((ln.topic, json.loads(ln.body)))
    p.dispatch(command, body, out, chain)
    return p
