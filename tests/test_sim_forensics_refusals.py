"""tools/sim_forensics check C12 (S30): every refusal is justified on the
state and book it was made on, and no acceptance meets a refusal's reason.

Each test writes an audit trail by hand on the s3-nominal example (sessions
on; AAPL capped at 1 000 shares here): a day whose every answer is right
passes, and each planted wrong answer is named.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from edumatcher.config_deploy import deploy, resolve_example
from edumatcher.engine.config_loader import EngineConfig
from edumatcher.engine.order_limits import OrderLimitsConfig
from tests.sim_forensics_world import OpenDataset, opener
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.checks import refusals  # noqa: E402
from sim_forensics.registry import REGISTRY, Outcome  # noqa: E402


@pytest.fixture
def open_ds(monkeypatch: pytest.MonkeyPatch) -> Iterator[OpenDataset]:
    config = refusals._config

    def capped(files: list[Any]) -> EngineConfig:
        cfg = config(files)
        cfg.symbols["AAPL"].order_limits = OrderLimitsConfig(max_order_qty=1000)
        return cfg

    monkeypatch.setattr(refusals, "_config", capped)
    yield from opener()


class Audit:
    """An audit trail under construction (prices in ticks, 2 decimals)."""

    def __init__(self, tmp: Path) -> None:
        artifact = tmp / "deployed" / "engine_config.json"
        deploy(resolve_example("s3-nominal"), artifact)
        self.lines: list[str] = []
        self.n = 0
        self.chain = ""
        self.put("system.startup", {"run_seq": 1, "config": artifact.read_text()}, True)  # fmt: skip
        self.phase("CLOSED")

    def put(self, topic: str, payload: dict[str, Any], new_chain: bool = False) -> None:  # fmt: skip
        self.n += 1
        msg = f"{self.n:026d}"
        if new_chain:
            self.chain = msg
        self.lines.append(f"[2026-10-24T07:00:00.000+00:00] [{topic}] [seq={self.n} msg={msg} chain={self.chain}] {json.dumps(payload)}\n")  # fmt: skip

    def phase(self, state: str) -> None:
        self.put("session.transition", {"to_state": state}, True)
        self.put("session.state", {"state": state})

    def new(self, oid: str, side: str, qty: int, price: int | None, *, kind: str = "LIMIT", gw: str = "TRADER01", tif: str = "DAY", sym: str = "AAPL", refused: str | None = None) -> None:  # fmt: skip
        self.put("order.new", {"id": oid, "symbol": sym, "side": side, "order_type": kind, "tif": tif, "quantity": qty, "gateway_id": gw, "tick_decimals": 2, "price_ticks": price}, True)  # fmt: skip
        ack: dict[str, Any] = {"order_id": oid, "accepted": refused is None}
        if refused is None:
            ack |= {"symbol": sym, "side": side, "order_type": kind, "qty": qty, "price_ticks": price}  # fmt: skip
        else:
            ack |= {"reason": refused.lower(), "reject_code": refused}
        self.put(f"order.ack.{gw}", ack)

    def cancel(self, oid: str, gw: str, refused: str | None = None) -> None:
        self.put("order.cancel", {"order_id": oid, "gateway_id": gw}, True)
        if refused is None:
            self.put(f"order.cancelled.{gw}", {"order_id": oid, "symbol": "AAPL"})
        else:
            self.put(f"order.ack.{gw}", {"order_id": oid, "accepted": False, "reason": "", "reject_code": refused})  # fmt: skip

    def combo(self, refused: bool) -> None:
        legs = [{"symbol": s, "side": "BUY", "order_type": "LIMIT", "quantity": 10, "price_ticks": 10000} for s in ("AAPL", "MSFT")]  # fmt: skip
        self.put("order.combo", {"combo_id": "C1", "gateway_id": "TRADER01", "combo_type": "AON", "tif": "DAY", "legs": legs}, True)  # fmt: skip
        self.put(
            "combo.ack.TRADER01", {"combo_id": "C1", "accepted": True, "reason": ""}
        )
        if refused:
            self.put("order.ack.TRADER01", {"order_id": "leg-0", "accepted": False, "reason": "", "reject_code": "INSUFFICIENT_LIQUIDITY"})  # fmt: skip
            self.put("combo.status.TRADER01", {"combo_id": "C1", "status": "FAILED", "reason": "Leg 0 (AAPL) REJECTED"})  # fmt: skip
        else:
            for i, s in enumerate(("AAPL", "MSFT")):
                self.put("order.ack.TRADER01", {"order_id": f"leg-{i}", "accepted": True, "symbol": s, "side": "BUY", "order_type": "LIMIT", "qty": 10, "price_ticks": 10000})  # fmt: skip

    def write(self, data: Path) -> Path:
        data.mkdir()
        (data / "audit.log").write_text("".join(self.lines))
        return data


def day(a: Audit) -> None:
    """Every modelled refusal once, each justified, and acceptances beside."""
    a.new("closed", "BUY", 10, 10000, refused="MARKET_CLOSED")
    a.phase("PRE_OPEN")
    a.new("pre-limit", "BUY", 10, 9000)
    a.new("pre-ioc", "BUY", 10, 9000, kind="IOC", refused="SESSION_NOT_PERMITTED")
    a.new("pre-ato", "BUY", 10, 9000, tif="ATO", refused="SESSION_NOT_PERMITTED")
    a.phase("OPENING_AUCTION")
    a.new("ato", "BUY", 10, 9000, tif="ATO")
    a.phase("CONTINUOUS")
    a.new("ask", "SELL", 10, 10000, gw="TRADER02")
    a.new("ask", "SELL", 10, 10000, gw="TRADER02", refused="DUPLICATE_ORDER")
    a.new("big", "BUY", 2000, 9000, refused="MAX_ORDER_QTY")
    a.new("zzz", "BUY", 10, 9000, sym="ZZZ", refused="UNKNOWN_SYMBOL")
    a.new("short-fok", "BUY", 20, 10000, kind="FOK", refused="INSUFFICIENT_LIQUIDITY")  # fmt: skip
    a.cancel("nope", "TRADER01", refused="ORDER_NOT_FOUND")
    a.cancel("ask", "TRADER01", refused="NOT_OWNER")
    a.cancel("ask", "TRADER02")
    a.cancel("ask", "TRADER02", refused="ORDER_NOT_FOUND")
    a.new("ask2", "SELL", 5, 10000, gw="TRADER02")
    a.combo(refused=True)  # AAPL short (5 of 10) and would trade now


def c12(open_ds: OpenDataset, a: Audit, tmp: Path) -> Outcome:
    return REGISTRY["C12"].fn(open_ds(a.write(tmp / "data")))


def test_c12_passes_a_day_of_justified_answers(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    a = Audit(tmp_path)
    day(a)
    out = c12(open_ds, a, tmp_path)
    assert (out.violations, out.samples) == (0, [])
    assert out.note.startswith("order.cancel 4, order.new 10;")
    assert "on the books: 2" in out.note  # the FOK and the combo


def _swap(old: str, new: str) -> Callable[[list[str]], list[str]]:
    def edit(lines: list[str]) -> list[str]:
        i = next(k for k, ln in enumerate(lines) if old in ln)
        lines[i] = lines[i].replace(old, new)
        return lines

    return edit


@pytest.mark.parametrize(
    "plant, error",
    [
        (_swap('"order_id": "pre-limit", "accepted": true', '"order_id": "pre-limit", "accepted": false, "reject_code": "MARKET_CLOSED"'), "order.new refused MARKET_CLOSED, but nothing applies"),  # fmt: skip
        (_swap('"order_id": "closed", "accepted": false', '"order_id": "closed", "accepted": true, "symbol": "AAPL"'), "order.new accepted, but MARKET_CLOSED applies"),  # fmt: skip
        (_swap('"order_id": "big", "accepted": false', '"order_id": "big", "accepted": true, "symbol": "AAPL"'), "order.new accepted, but MAX_ORDER_QTY applies"),  # fmt: skip
        (_swap('"reject_code": "NOT_OWNER"', '"reject_code": "ORDER_NOT_FOUND"'), "order.cancel refused ORDER_NOT_FOUND, but NOT_OWNER applies"),  # fmt: skip
        (_swap('"id": "short-fok", "symbol": "AAPL", "side": "BUY", "order_type": "FOK", "tif": "DAY", "quantity": 20', '"id": "short-fok", "symbol": "AAPL", "side": "BUY", "order_type": "FOK", "tif": "DAY", "quantity": 5'), "FOK refused for liquidity the book held"),  # fmt: skip
        (_swap('"reject_code": "UNKNOWN_SYMBOL"', '"reject_code": "INTERNAL_ERROR"'), "INTERNAL_ERROR"),  # fmt: skip
    ],
)
def test_c12_names_a_wrong_answer(
    tmp_path: Path,
    open_ds: OpenDataset,
    plant: Callable[[list[str]], list[str]],
    error: str,
) -> None:
    a = Audit(tmp_path)
    day(a)
    a.lines = plant(a.lines)
    out = c12(open_ds, a, tmp_path)
    assert error in [s["error"] for s in out.samples]


def test_c12_finds_an_aon_combo_refused_with_nothing_to_trade(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    """X28 refuses an all-or-none combo only when a leg would trade now: on
    empty books nothing would, so the legs must rest."""
    a = Audit(tmp_path)
    a.phase("PRE_OPEN")
    a.phase("CONTINUOUS")
    a.combo(refused=True)
    out = c12(open_ds, a, tmp_path)
    assert [s["error"] for s in out.samples] == ["AON combo refused for liquidity, but the book did not call for it"]  # fmt: skip


def test_c12_follows_an_oco_pair_acked_before_its_legs(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    """oco.ack comes before its legs' acks (2026-11-07 run: 87 741 cancels
    taken for refusals the check owed)."""
    a = Audit(tmp_path)
    a.phase("PRE_OPEN")
    a.phase("CONTINUOUS")
    for k in ("K1", "K2"):
        spec = {"side": "SELL", "order_type": "LIMIT", "price_ticks": 11000}
        a.put("order.oco", {"oco_id": k, "gateway_id": "TRADER01", "symbol": "AAPL", "quantity": 5, "tif": "DAY", "tick_decimals": 2, "leg1": spec, "leg2": spec}, True)  # fmt: skip
        a.put("oco.ack.TRADER01", {"oco_id": k, "accepted": True, "reason": "", "order_id_1": f"{k}-1", "order_id_2": f"{k}-2"})  # fmt: skip
        for leg in ("1", "2"):
            a.put("order.ack.TRADER01", {"order_id": f"{k}-{leg}", "accepted": True, "symbol": "AAPL", "side": "SELL", "order_type": "LIMIT", "qty": 5, "price_ticks": 11000, "oco_group_id": k})  # fmt: skip
    a.put("order.oco_cancel", {"oco_id": "K1", "gateway_id": "TRADER01"}, True)
    a.put("oco.cancel_ack.TRADER01", {"oco_id": "K1", "accepted": True, "reason": "", "cancelled_order_ids": ["K1-1", "K1-2"]})  # fmt: skip
    a.put("order.cancelled.TRADER01", {"order_id": "K1-1", "symbol": "AAPL"})
    a.put("order.cancelled.TRADER01", {"order_id": "K1-2", "symbol": "AAPL"})
    a.put("order.oco_cancel", {"oco_id": "K1", "gateway_id": "TRADER01"}, True)
    a.put("oco.cancel_ack.TRADER01", {"oco_id": "K1", "accepted": False, "reason": "OCO not found", "reject_code": "ORDER_NOT_FOUND"})  # fmt: skip
    out = c12(open_ds, a, tmp_path)
    assert (out.violations, out.samples) == (0, [])
    assert "order.oco_cancel 2" in out.note


def test_c12_lets_a_quote_cancel_clear_a_hit_legs_remainder(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    """A quote inactive after a fill leaves its other leg resting until the
    cancel clears it; with nothing left the cancel is refused."""
    a = Audit(tmp_path)
    a.phase("PRE_OPEN")
    a.phase("CONTINUOUS")
    a.put("quote.new", {"gateway_id": "MM01", "symbol": "AAPL", "quote_id": "Q1", "bid_price_ticks": 9990, "bid_qty": 100, "ask_price_ticks": 10000, "ask_qty": 100}, True)  # fmt: skip
    a.put("quote.ack.MM01", {"quote_id": "Q1", "accepted": True, "symbol": "AAPL", "reason": "", "bid_order_id": "qb", "ask_order_id": "qa"})  # fmt: skip
    a.put("quote.status.MM01", {"quote_id": "Q1", "status": "ACTIVE", "reason": ""})
    a.put("order.cancelled.MM01", {"order_id": "qb", "symbol": "AAPL"}, True)
    a.put("quote.status.MM01", {"quote_id": "Q1", "status": "INACTIVE_BID_FILLED", "reason": ""})  # fmt: skip
    for refused in (False, True):
        a.put("quote.cancel", {"gateway_id": "MM01", "symbol": "AAPL"}, True)
        a.put("quote.cancel_ack.MM01", {"symbol": "AAPL", "quote_id": "Q1", "accepted": not refused, "reason": "", "cancelled_order_ids": [] if refused else ["qa"], **({"reject_code": "ORDER_NOT_FOUND"} if refused else {})})  # fmt: skip
    out = c12(open_ds, a, tmp_path)
    assert (out.violations, out.samples) == (0, [])
    assert "quote.cancel 2" in out.note
