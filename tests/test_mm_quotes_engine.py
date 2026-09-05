from __future__ import annotations

from dataclasses import dataclass

import pytest

from edumatcher.engine.config_loader import EngineConfig, FixGatewayConfig, SymbolConfig
from edumatcher.engine.main import Engine
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderType, OrderStatus, Side, SmpAction, TIF
from edumatcher.models.participant import DisconnectBehaviour, ParticipantRole
from edumatcher.models.price import to_ticks
from edumatcher.models.quote import QuoteRefreshPolicy


@dataclass
class _FakeSock:
    sent: list[list[bytes]]
    closed: bool = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


def _make_engine(
    monkeypatch,
    tmp_path,
    *,
    role: ParticipantRole,
    enforce_mm_obligation: bool = False,
    mm_max_spread_ticks: int = 10,
    mm_min_qty: int = 100,
    smp_action: SmpAction = SmpAction.NONE,
    quote_refresh_policy: QuoteRefreshPolicy = QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL,
) -> tuple[Engine, _FakeSock]:
    pull_sock = _FakeSock(sent=[])
    pub_sock = _FakeSock(sent=[])

    cfg = EngineConfig(
        symbols={"AAPL": SymbolConfig(name="AAPL")},
        fix_gateways={
            "GW01": FixGatewayConfig(
                id="GW01",
                description="MM",
                role=role,
                disconnect_behaviour=DisconnectBehaviour.CANCEL_QUOTES_ONLY,
                enforce_mm_obligation=enforce_mm_obligation,
                mm_max_spread_ticks=mm_max_spread_ticks,
                mm_min_qty=mm_min_qty,
                smp_action=smp_action,
                quote_refresh_policy=quote_refresh_policy,
            )
        },
        sessions_enabled=False,
    )

    monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
    monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
    monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
    monkeypatch.setattr("edumatcher.engine.main.load_gtc_orders", lambda _: [])
    monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: {})
    monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)

    cfg_path = tmp_path / "engine_config.yaml"
    cfg_path.write_text("dummy: true\n")
    engine = Engine(config_path=str(cfg_path))
    engine._handle_gateway_connect({"gateway_id": "GW01"})
    pub_sock.sent.clear()
    return engine, pub_sock


def _topics(pub_sock: _FakeSock) -> list[str]:
    return [decode(frames)[0] for frames in pub_sock.sent]


def test_quote_rejected_for_non_market_maker(monkeypatch, tmp_path) -> None:
    engine, pub_sock = _make_engine(monkeypatch, tmp_path, role=ParticipantRole.TRADER)
    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "bid_price": to_ticks(100.0, "AAPL"),
            "bid_qty": 10,
            "ask_price": to_ticks(101.0, "AAPL"),
            "ask_qty": 10,
        }
    )

    topic, payload = decode(pub_sock.sent[-1])
    assert topic == "quote.ack.GW01"
    assert payload["accepted"] is False


def test_quote_accept_and_cancel(monkeypatch, tmp_path) -> None:
    engine, pub_sock = _make_engine(
        monkeypatch, tmp_path, role=ParticipantRole.MARKET_MAKER
    )
    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q1",
            "bid_price": to_ticks(100.0, "AAPL"),
            "bid_qty": 10,
            "ask_price": to_ticks(101.0, "AAPL"),
            "ask_qty": 12,
        }
    )

    assert "quote.ack.GW01" in _topics(pub_sock)
    assert engine._quote_index.get("GW01", "AAPL") is not None

    pub_sock.sent.clear()
    engine._handle_quote_cancel({"gateway_id": "GW01", "symbol": "AAPL"})
    assert engine._quote_index.get("GW01", "AAPL") is None
    assert "quote.status.GW01" in _topics(pub_sock)


def test_kill_switch_cancels_quote_and_orders(monkeypatch, tmp_path) -> None:
    engine, pub_sock = _make_engine(
        monkeypatch, tmp_path, role=ParticipantRole.MARKET_MAKER
    )

    order = Order.create(
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=20,
        gateway_id="GW01",
        tif=TIF.DAY,
        price=9900,
    )
    engine._handle_new_order(order.to_dict())

    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q2",
            "bid_price": to_ticks(99.0, "AAPL"),
            "bid_qty": 5,
            "ask_price": to_ticks(102.0, "AAPL"),
            "ask_qty": 5,
        }
    )

    pub_sock.sent.clear()
    engine._handle_kill_switch({"gateway_id": "GW01"})

    # The ack is no longer necessarily the last message published: an
    # admin.action event (for /admin/monitor) is also emitted alongside it.
    # Find the ack by topic rather than by position.
    acks = [
        decode(frames)
        for frames in pub_sock.sent
        if decode(frames)[0] == "risk.kill_switch_ack.GW01"
    ]
    assert len(acks) == 1
    _, payload = acks[0]
    assert payload["accepted"] is True
    assert payload["cancelled_orders"] >= 1
    assert payload["cancelled_quotes"] >= 1


def test_disconnect_cancels_quotes_only(monkeypatch, tmp_path) -> None:
    engine, _ = _make_engine(monkeypatch, tmp_path, role=ParticipantRole.MARKET_MAKER)

    order = Order.create(
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=20,
        gateway_id="GW01",
        tif=TIF.DAY,
        price=9800,
    )
    engine._handle_new_order(order.to_dict())
    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q3",
            "bid_price": to_ticks(97.0, "AAPL"),
            "bid_qty": 5,
            "ask_price": to_ticks(103.0, "AAPL"),
            "ask_qty": 5,
        }
    )

    engine._handle_gateway_disconnect({"gateway_id": "GW01"})

    assert engine._quote_index.get("GW01", "AAPL") is None
    book = engine._book("AAPL")
    resting_ids = {o.id for o in book.resting_orders() if o.gateway_id == "GW01"}
    assert order.id in resting_ids


def test_quote_obligation_enforced_when_enabled(monkeypatch, tmp_path) -> None:
    engine, pub_sock = _make_engine(
        monkeypatch,
        tmp_path,
        role=ParticipantRole.MARKET_MAKER,
        enforce_mm_obligation=True,
        mm_max_spread_ticks=5,
        mm_min_qty=10,
    )

    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q-OBL-1",
            "bid_price": to_ticks(100.0, "AAPL"),
            "bid_qty": 10,
            "ask_price": to_ticks(100.10, "AAPL"),
            "ask_qty": 10,
        }
    )
    topic, payload = decode(pub_sock.sent[-1])
    assert topic == "quote.ack.GW01"
    assert payload["accepted"] is False
    assert "Spread" in payload["reason"]


def test_quote_obligation_not_enforced_when_disabled(monkeypatch, tmp_path) -> None:
    engine, pub_sock = _make_engine(
        monkeypatch,
        tmp_path,
        role=ParticipantRole.MARKET_MAKER,
        enforce_mm_obligation=False,
        mm_max_spread_ticks=5,
        mm_min_qty=10,
    )

    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q-OBL-2",
            "bid_price": to_ticks(100.0, "AAPL"),
            "bid_qty": 10,
            "ask_price": to_ticks(100.10, "AAPL"),
            "ask_qty": 10,
        }
    )
    topics = _topics(pub_sock)
    assert "quote.ack.GW01" in topics
    ack_payload = decode(
        [f for f in pub_sock.sent if decode(f)[0] == "quote.ack.GW01"][-1]
    )[1]
    assert ack_payload["accepted"] is True


def test_quote_legs_inherit_gateway_smp_action(monkeypatch, tmp_path) -> None:
    """gateways.alf[].smp_action should be attached to both bid and ask legs
    a QUOTE produces, not just left at the SmpAction.NONE default."""
    engine, _ = _make_engine(
        monkeypatch,
        tmp_path,
        role=ParticipantRole.MARKET_MAKER,
        smp_action=SmpAction.CANCEL_RESTING,
    )
    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q-SMP-1",
            "bid_price": to_ticks(100.0, "AAPL"),
            "bid_qty": 10,
            "ask_price": to_ticks(101.0, "AAPL"),
            "ask_qty": 10,
        }
    )
    entry = engine._quote_index.get("GW01", "AAPL")
    assert entry is not None
    book = engine._book("AAPL")
    resting_by_id = {o.id: o for o in book.resting_orders()}
    bid_order = resting_by_id[entry.bid_order_id]
    ask_order = resting_by_id[entry.ask_order_id]
    assert bid_order.smp_action == SmpAction.CANCEL_RESTING
    assert ask_order.smp_action == SmpAction.CANCEL_RESTING


def test_quote_smp_action_defaults_to_none_when_unconfigured(
    monkeypatch, tmp_path
) -> None:
    engine, _ = _make_engine(monkeypatch, tmp_path, role=ParticipantRole.MARKET_MAKER)
    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q-SMP-DEFAULT",
            "bid_price": to_ticks(100.0, "AAPL"),
            "bid_qty": 10,
            "ask_price": to_ticks(101.0, "AAPL"),
            "ask_qty": 10,
        }
    )
    entry = engine._quote_index.get("GW01", "AAPL")
    assert entry is not None
    book = engine._book("AAPL")
    resting_by_id = {o.id: o for o in book.resting_orders()}
    assert resting_by_id[entry.bid_order_id].smp_action == SmpAction.NONE
    assert resting_by_id[entry.ask_order_id].smp_action == SmpAction.NONE


def test_quote_smp_cancel_resting_prevents_self_match(monkeypatch, tmp_path) -> None:
    """With gateways.alf[].smp_action=CANCEL_RESTING, a quote leg that would
    otherwise cross a stale same-gateway resting order cancels that resting
    order instead of self-trading against it."""
    engine, pub_sock = _make_engine(
        monkeypatch,
        tmp_path,
        role=ParticipantRole.MARKET_MAKER,
        smp_action=SmpAction.CANCEL_RESTING,
    )

    # A same-gateway resting SELL at 100.00, left over from e.g. a stale NEW
    # order — not itself a quote leg, so quote-replacement's own cancel path
    # never touches it.
    stale_ask_seed = Order.create(
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        quantity=10,
        gateway_id="GW01",
        tif=TIF.DAY,
        price=10000,  # ticks; 100.00
    )
    stale_ask_id = stale_ask_seed.id
    # _handle_new_order rebuilds its own Order from the payload dict (via
    # Order.from_dict), so it does not mutate stale_ask_seed in place --
    # track the id and re-look-up state from the book itself below.
    engine._handle_new_order(stale_ask_seed.to_dict())
    book = engine._book("AAPL")
    assert stale_ask_id in {o.id for o in book.resting_orders()}

    pub_sock.sent.clear()
    # New quote's bid crosses the stale resting ask.
    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q-SMP-CROSS",
            "bid_price": to_ticks(100.0, "AAPL"),
            "bid_qty": 10,
            "ask_price": to_ticks(101.0, "AAPL"),
            "ask_qty": 10,
        }
    )

    # No trade occurred -- the resting order was SMP-cancelled, not filled.
    assert "trade.executed" not in _topics(pub_sock)
    assert "order.cancelled.GW01" in _topics(pub_sock)
    remaining_ids = {o.id for o in book.resting_orders()}
    assert stale_ask_id not in remaining_ids

    entry = engine._quote_index.get("GW01", "AAPL")
    assert entry is not None
    assert entry.bid_order_id in remaining_ids  # quote's bid still rests


def test_quote_without_smp_action_self_trades_against_stale_resting_order(
    monkeypatch, tmp_path
) -> None:
    """Control case for the previous test: with smp_action left at the
    NONE default, the same crossing scenario DOES self-trade -- proving the
    CANCEL_RESTING behavior above comes from the gateway config wiring and
    not from some other unrelated guard."""
    engine, pub_sock = _make_engine(
        monkeypatch, tmp_path, role=ParticipantRole.MARKET_MAKER
    )

    stale_ask = Order.create(
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        quantity=10,
        gateway_id="GW01",
        tif=TIF.DAY,
        price=10000,
    )
    engine._handle_new_order(stale_ask.to_dict())

    pub_sock.sent.clear()
    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q-NO-SMP-CROSS",
            "bid_price": to_ticks(100.0, "AAPL"),
            "bid_qty": 10,
            "ask_price": to_ticks(101.0, "AAPL"),
            "ask_qty": 10,
        }
    )

    assert "trade.executed" in _topics(pub_sock)


@pytest.mark.parametrize(
    "role",
    [ParticipantRole.TRADER, ParticipantRole.MARKET_MAKER],
)
def test_global_circuit_breaker_halt_all_rejected_for_non_admin(
    monkeypatch, tmp_path, role: ParticipantRole
) -> None:
    engine, pub_sock = _make_engine(monkeypatch, tmp_path, role=role)

    engine._handle_circuit_breaker_halt_all({"gateway_id": "GW01"})

    topic, payload = decode(pub_sock.sent[-1])
    assert topic == "risk.circuit_breaker_halt_all_ack.GW01"
    assert payload["accepted"] is False
    assert "ADMIN" in payload["reason"]


def test_global_circuit_breaker_halt_all_accepts_admin(monkeypatch, tmp_path) -> None:
    pull_sock = _FakeSock(sent=[])
    pub_sock = _FakeSock(sent=[])

    cfg = EngineConfig(
        symbols={
            "AAPL": SymbolConfig(name="AAPL"),
            "MSFT": SymbolConfig(name="MSFT"),
        },
        fix_gateways={
            "GW01": FixGatewayConfig(
                id="GW01",
                description="Admin",
                role=ParticipantRole.ADMIN,
                disconnect_behaviour=DisconnectBehaviour.CANCEL_QUOTES_ONLY,
            )
        },
        sessions_enabled=False,
    )

    monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
    monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
    monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
    monkeypatch.setattr("edumatcher.engine.main.load_gtc_orders", lambda _: [])
    monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: {})
    monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)

    cfg_path = tmp_path / "engine_config.yaml"
    cfg_path.write_text("dummy: true\n")
    engine = Engine(config_path=str(cfg_path))
    engine._handle_gateway_connect({"gateway_id": "GW01"})

    pub_sock.sent.clear()
    engine._handle_circuit_breaker_halt_all({"gateway_id": "GW01"})

    assert engine._halted_symbols.get("AAPL") is True
    assert engine._halted_symbols.get("MSFT") is True

    topic, payload = decode(pub_sock.sent[-1])
    assert topic == "risk.circuit_breaker_halt_all_ack.GW01"
    assert payload["accepted"] is True
    assert payload["halted_symbols"] == 2


@pytest.mark.parametrize(
    "role",
    [ParticipantRole.TRADER, ParticipantRole.MARKET_MAKER],
)
def test_global_circuit_breaker_resume_all_rejected_for_non_admin(
    monkeypatch, tmp_path, role: ParticipantRole
) -> None:
    engine, pub_sock = _make_engine(monkeypatch, tmp_path, role=role)
    # Manually set a halt so there's something to clear
    engine._halted_symbols["AAPL"] = True

    engine._handle_circuit_breaker_resume_all({"gateway_id": "GW01"})

    topic, payload = decode(pub_sock.sent[-1])
    assert topic == "risk.circuit_breaker_resume_all_ack.GW01"
    assert payload["accepted"] is False
    assert "ADMIN" in payload["reason"]
    # Halt state must be unchanged
    assert engine._halted_symbols["AAPL"] is True


def test_global_circuit_breaker_halt_then_resume_all(monkeypatch, tmp_path) -> None:
    pull_sock = _FakeSock(sent=[])
    pub_sock = _FakeSock(sent=[])

    cfg = EngineConfig(
        symbols={
            "AAPL": SymbolConfig(name="AAPL"),
            "MSFT": SymbolConfig(name="MSFT"),
        },
        fix_gateways={
            "GW01": FixGatewayConfig(
                id="GW01",
                description="Admin",
                role=ParticipantRole.ADMIN,
                disconnect_behaviour=DisconnectBehaviour.CANCEL_QUOTES_ONLY,
            )
        },
        sessions_enabled=False,
    )

    monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
    monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
    monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
    monkeypatch.setattr("edumatcher.engine.main.load_gtc_orders", lambda _: [])
    monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: {})
    monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)

    cfg_path = tmp_path / "engine_config.yaml"
    cfg_path.write_text("dummy: true\n")
    engine = Engine(config_path=str(cfg_path))
    engine._handle_gateway_connect({"gateway_id": "GW01"})

    # Halt all
    engine._handle_circuit_breaker_halt_all({"gateway_id": "GW01"})
    assert engine._halted_symbols.get("AAPL") is True
    assert engine._halted_symbols.get("MSFT") is True

    pub_sock.sent.clear()

    # Resume all
    engine._handle_circuit_breaker_resume_all({"gateway_id": "GW01"})

    assert engine._halted_symbols.get("AAPL") is False
    assert engine._halted_symbols.get("MSFT") is False

    topics = _topics(pub_sock)
    assert "circuit_breaker.resume.AAPL" in topics
    assert "circuit_breaker.resume.MSFT" in topics

    topic, payload = decode(pub_sock.sent[-1])
    assert topic == "risk.circuit_breaker_resume_all_ack.GW01"
    assert payload["accepted"] is True
    assert payload["resumed_symbols"] == 2


# ---------------------------------------------------------------------------
# Partial-fill quote-leg semantics (docs-design/EduMatcher-MM-Bot-review.md
# §4 item 3): under INACTIVATE_ON_ANY_FILL, a *partially* filled quote leg
# must (a) stay resting and tradeable after the fill -- it is not cancelled
# by the fill itself, only its sibling is -- and (b) be cancelled once, and
# only once, a replacement quote actually arrives for that (gateway, symbol).
# Before the fix in _handle_quote_new, (a) held but (b) did not: the stale
# remainder was never cancelled and rested alongside the new quote's legs.
# ---------------------------------------------------------------------------


def _resting_ids(book) -> set[str]:
    return {o.id for o in book.resting_orders()}


def test_partial_fill_sibling_cancelled_but_hit_leg_survives(
    monkeypatch, tmp_path
) -> None:
    """INACTIVATE_ON_ANY_FILL on a *partial* fill: sibling is cancelled and
    the quote is inactivated, but the hit leg's own remainder is untouched
    -- still resting, still PARTIAL, not FILLED, not removed from the book.
    This is the documented intent (see the QuoteRefreshPolicy docstring in
    EduMatcher-MM_Quotes_Implementation_Plan.md): only the untouched sibling
    is pulled immediately; the hit leg's remainder stays live until a new
    quote replaces it.
    """
    engine, pub_sock = _make_engine(
        monkeypatch,
        tmp_path,
        role=ParticipantRole.MARKET_MAKER,
        quote_refresh_policy=QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL,
    )
    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q1",
            "bid_price": to_ticks(100.0, "AAPL"),
            "bid_qty": 500,
            "ask_price": to_ticks(101.0, "AAPL"),
            "ask_qty": 500,
        }
    )
    entry = engine._quote_index.get("GW01", "AAPL")
    assert entry is not None
    bid_leg_id = entry.bid_order_id
    ask_leg_id = entry.ask_order_id
    book = engine._book("AAPL")

    pub_sock.sent.clear()
    # Same-gateway counterparty order partially fills the bid leg (100 of
    # 500), mirroring the existing SMP tests' pattern of using GW01 itself
    # as the crossing counterparty rather than standing up a second
    # configured gateway.
    taker = Order.create(
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        quantity=100,
        gateway_id="GW01",
        tif=TIF.DAY,
        price=to_ticks(100.0, "AAPL"),
    )
    engine._handle_new_order(taker.to_dict())

    # Quote is inactivated and the sibling ask leg is gone...
    assert engine._quote_index.get("GW01", "AAPL") is None
    assert "quote.status.GW01" in _topics(pub_sock)
    _, status_payload = next(
        (decode(f) for f in pub_sock.sent if decode(f)[0] == "quote.status.GW01")
    )
    assert status_payload["status"] == "INACTIVE_BID_FILLED"
    assert ask_leg_id not in _resting_ids(book)

    # ...but the HIT bid leg's remainder is still there, still PARTIAL, and
    # still real liquidity: another taker can still trade against it.
    bid_order = book._order_index.get(bid_leg_id)
    assert bid_order is not None
    assert bid_order.status == OrderStatus.PARTIAL
    assert bid_order.remaining_qty == 400
    assert bid_leg_id in _resting_ids(book)

    taker2 = Order.create(
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        quantity=50,
        gateway_id="GW01",
        tif=TIF.DAY,
        price=to_ticks(100.0, "AAPL"),
    )
    engine._handle_new_order(taker2.to_dict())
    bid_order = book._order_index.get(bid_leg_id)
    assert bid_order is not None
    assert bid_order.status == OrderStatus.PARTIAL
    assert bid_order.remaining_qty == 350


def test_reissue_after_partial_fill_cancels_stale_remainder(
    monkeypatch, tmp_path
) -> None:
    """The bug itself, as a regression test: after a partial fill under
    INACTIVATE_ON_ANY_FILL, a fresh two-sided quote for the same
    (gateway, symbol) -- exactly what pm-mm-bot sends on seeing
    quote.status INACTIVE_BID_FILLED -- must cancel the stale partially
    filled leg from the old quote. Before the fix, _handle_quote_new found
    no QuoteIndex entry (already popped by _on_quote_leg_filled) and never
    looked at the book, leaving two live BUY orders resting simultaneously.
    """
    engine, pub_sock = _make_engine(
        monkeypatch,
        tmp_path,
        role=ParticipantRole.MARKET_MAKER,
        quote_refresh_policy=QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL,
    )
    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q1",
            "bid_price": to_ticks(100.0, "AAPL"),
            "bid_qty": 500,
            "ask_price": to_ticks(101.0, "AAPL"),
            "ask_qty": 500,
        }
    )
    entry = engine._quote_index.get("GW01", "AAPL")
    assert entry is not None
    stale_bid_id = entry.bid_order_id
    book = engine._book("AAPL")

    taker = Order.create(
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        quantity=100,
        gateway_id="GW01",
        tif=TIF.DAY,
        price=to_ticks(100.0, "AAPL"),
    )
    engine._handle_new_order(taker.to_dict())
    assert stale_bid_id in _resting_ids(book)  # sanity: still there pre-reissue

    pub_sock.sent.clear()
    # pm-mm-bot's reissue: a fresh two-sided quote for the same slot.
    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q2",
            "bid_price": to_ticks(100.05, "AAPL"),
            "bid_qty": 500,
            "ask_price": to_ticks(101.05, "AAPL"),
            "ask_qty": 500,
        }
    )

    new_entry = engine._quote_index.get("GW01", "AAPL")
    assert new_entry is not None
    assert new_entry.quote_id == "Q2"

    resting = _resting_ids(book)
    # The stale partial remainder from Q1 must be gone...
    assert stale_bid_id not in resting
    # ...an order.cancelled for it must have been published...
    cancelled_ids = {
        decode(f)[1]["order_id"]
        for f in pub_sock.sent
        if decode(f)[0] == "order.cancelled.GW01"
    }
    assert stale_bid_id in cancelled_ids
    # ...and exactly Q2's two fresh legs are resting for GW01 -- not three,
    # not one.
    gw01_resting = {o.id for o in book.resting_orders() if o.gateway_id == "GW01"}
    assert gw01_resting == {new_entry.bid_order_id, new_entry.ask_order_id}


def test_reissue_with_no_prior_quote_is_unaffected(monkeypatch, tmp_path) -> None:
    """The new orphaned-leg fallback must not do anything when there simply
    is no prior quote for this (gateway, symbol) -- the ordinary first-quote
    path is unaffected by the fix."""
    engine, pub_sock = _make_engine(
        monkeypatch, tmp_path, role=ParticipantRole.MARKET_MAKER
    )
    book = engine._book("AAPL")
    assert _resting_ids(book) == set()

    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q1",
            "bid_price": to_ticks(100.0, "AAPL"),
            "bid_qty": 500,
            "ask_price": to_ticks(101.0, "AAPL"),
            "ask_qty": 500,
        }
    )
    entry = engine._quote_index.get("GW01", "AAPL")
    assert entry is not None
    assert _resting_ids(book) == {entry.bid_order_id, entry.ask_order_id}
    assert "order.cancelled.GW01" not in _topics(pub_sock)


def test_reissue_after_full_fill_still_finds_nothing_stray(
    monkeypatch, tmp_path
) -> None:
    """Full-fill case, for contrast with the partial-fill regression test
    above: when the hit leg is fully consumed, the book already purged it
    (OrderBook._apply_fill), so the new orphaned-leg fallback in
    _handle_quote_new finds nothing to cancel -- it is a no-op here, exactly
    as before the fix."""
    engine, pub_sock = _make_engine(
        monkeypatch,
        tmp_path,
        role=ParticipantRole.MARKET_MAKER,
        quote_refresh_policy=QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL,
    )
    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q1",
            "bid_price": to_ticks(100.0, "AAPL"),
            "bid_qty": 500,
            "ask_price": to_ticks(101.0, "AAPL"),
            "ask_qty": 500,
        }
    )
    entry = engine._quote_index.get("GW01", "AAPL")
    assert entry is not None
    full_bid_id = entry.bid_order_id
    book = engine._book("AAPL")

    # Fully consume the bid leg (500 of 500).
    taker = Order.create(
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        quantity=500,
        gateway_id="GW01",
        tif=TIF.DAY,
        price=to_ticks(100.0, "AAPL"),
    )
    engine._handle_new_order(taker.to_dict())
    assert full_bid_id not in _resting_ids(book)  # already purged, full fill

    pub_sock.sent.clear()
    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q2",
            "bid_price": to_ticks(100.05, "AAPL"),
            "bid_qty": 500,
            "ask_price": to_ticks(101.05, "AAPL"),
            "ask_qty": 500,
        }
    )
    # No extra order.cancelled -- there was nothing stray left to cancel.
    assert "order.cancelled.GW01" not in _topics(pub_sock)
    new_entry = engine._quote_index.get("GW01", "AAPL")
    assert new_entry is not None
    gw01_resting = {o.id for o in book.resting_orders() if o.gateway_id == "GW01"}
    assert gw01_resting == {new_entry.bid_order_id, new_entry.ask_order_id}


def test_inactivate_on_full_fill_partial_leg_stays_active_and_unaffected(
    monkeypatch, tmp_path
) -> None:
    """INACTIVATE_ON_FULL_FILL's deliberate 'accumulate partials, stay
    active' behavior (design doc's own Example 2) must be completely
    unaffected by the fix: a partial fill under this policy does not
    inactivate the quote at all, so _handle_quote_new's new fallback path
    is never even reached on the next quote.new for this slot -- the
    QuoteIndex entry is still there, so the ordinary `previous` branch
    handles it exactly as before.
    """
    engine, pub_sock = _make_engine(
        monkeypatch,
        tmp_path,
        role=ParticipantRole.MARKET_MAKER,
        quote_refresh_policy=QuoteRefreshPolicy.INACTIVATE_ON_FULL_FILL,
    )
    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q1",
            "bid_price": to_ticks(100.0, "AAPL"),
            "bid_qty": 500,
            "ask_price": to_ticks(101.0, "AAPL"),
            "ask_qty": 500,
        }
    )
    entry = engine._quote_index.get("GW01", "AAPL")
    assert entry is not None
    bid_leg_id = entry.bid_order_id
    ask_leg_id = entry.ask_order_id
    book = engine._book("AAPL")

    pub_sock.sent.clear()
    taker = Order.create(
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        quantity=100,
        gateway_id="GW01",
        tif=TIF.DAY,
        price=to_ticks(100.0, "AAPL"),
    )
    engine._handle_new_order(taker.to_dict())

    # Quote remains fully active -- no inactivation, sibling untouched, and
    # (unlike INACTIVATE_ON_ANY_FILL) no quote.status is published for a
    # fill that doesn't inactivate anything.
    active_entry = engine._quote_index.get("GW01", "AAPL")
    assert active_entry is not None
    assert active_entry.quote_id == "Q1"
    assert bid_leg_id in _resting_ids(book)
    assert ask_leg_id in _resting_ids(book)
    assert "quote.status.GW01" not in _topics(pub_sock)

    pub_sock.sent.clear()
    # MM explicitly replaces the quote (not a fill-driven reissue, since the
    # policy never inactivated it) -- ordinary replace path, `previous` is
    # found, `_cancel_quote_entry` runs exactly as it always has.
    engine._handle_quote_new(
        {
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "quote_id": "Q2",
            "bid_price": to_ticks(100.05, "AAPL"),
            "bid_qty": 500,
            "ask_price": to_ticks(101.05, "AAPL"),
            "ask_qty": 500,
        }
    )
    new_entry = engine._quote_index.get("GW01", "AAPL")
    assert new_entry is not None
    assert new_entry.quote_id == "Q2"
    gw01_resting = {o.id for o in book.resting_orders() if o.gateway_id == "GW01"}
    assert gw01_resting == {new_entry.bid_order_id, new_entry.ask_order_id}
