from __future__ import annotations

from edumatcher.engine.config_loader import EngineConfig, FixGatewayConfig, SymbolConfig
from edumatcher.engine.main import Engine
from edumatcher.models.order import Order, OrderType, Side, TIF
from edumatcher.models.participant import DisconnectBehaviour, ParticipantRole
from edumatcher.models.price import to_ticks
from edumatcher.models.quote import QuoteRefreshPolicy

from tests.test_mm_quotes_engine import _FakeSock

# NOTE: _allowed_fix_gateways is a frozenset snapshot taken once at Engine
# construction, so every gateway used below must be present in the config
# passed to Engine() and then connected via _handle_gateway_connect.


def test_repro_stale_ask_leg_crosses_new_bid(monkeypatch, tmp_path) -> None:
    pull_sock = _FakeSock(sent=[])
    pub_sock = _FakeSock(sent=[])
    cfg = EngineConfig(
        symbols={"AAPL": SymbolConfig(name="AAPL")},
        fix_gateways={
            "MM01": FixGatewayConfig(
                id="MM01",
                role=ParticipantRole.MARKET_MAKER,
                disconnect_behaviour=DisconnectBehaviour.CANCEL_QUOTES_ONLY,
                quote_refresh_policy=QuoteRefreshPolicy.INACTIVATE_ON_ANY_FILL,
            ),
            "TRADER01": FixGatewayConfig(
                id="TRADER01",
                role=ParticipantRole.TRADER,
            ),
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
    engine._handle_gateway_connect({"gateway_id": "MM01"})
    engine._handle_gateway_connect({"gateway_id": "TRADER01"})
    pub_sock.sent.clear()

    book = engine._book("AAPL")

    # Step 1: bootstrapped quote SEED-MM01-AAPL-1
    engine._handle_quote_new(
        {
            "gateway_id": "MM01",
            "symbol": "AAPL",
            "quote_id": "SEED-MM01-AAPL-1",
            "bid_price": to_ticks(95.83, "AAPL"),
            "bid_qty": 1000,
            "ask_price": to_ticks(95.85, "AAPL"),
            "ask_qty": 1000,
        }
    )
    entry = engine._quote_index.get("MM01", "AAPL")
    assert entry is not None
    stale_ask_id = entry.ask_order_id

    # Step 2: TRADER01 hits the ASK leg partially (qty 50 @ 100 limit)
    taker = Order.create(
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=50,
        gateway_id="TRADER01",
        tif=TIF.DAY,
        price=to_ticks(100.0, "AAPL"),
    )
    engine._handle_new_order(taker.to_dict())

    # Quote inactivated, stale ask leg still resting partially filled.
    assert engine._quote_index.get("MM01", "AAPL") is None
    remaining = book.quote_orders_for_gateway("MM01")
    assert [o.id for o in remaining] == [stale_ask_id]
    assert remaining[0].remaining_qty == 950

    # Step 3: MM01 manually reissues quote MM01-AAPL-2, bid=99.50 ask=99.80
    # -- bid_price (99.50) > stale ask price (95.85): if the stale leg isn't
    # cancelled first, the new bid leg will immediately cross it.
    engine._handle_quote_new(
        {
            "gateway_id": "MM01",
            "symbol": "AAPL",
            "quote_id": "MM01-AAPL-2",
            "bid_price": to_ticks(99.50, "AAPL"),
            "bid_qty": 1000,
            "ask_price": to_ticks(99.80, "AAPL"),
            "ask_qty": 1000,
        }
    )

    new_entry = engine._quote_index.get("MM01", "AAPL")
    assert new_entry is not None
    new_bid = book.get_order(new_entry.bid_order_id)
    assert new_bid is not None
    print("new_bid remaining_qty:", new_bid.remaining_qty, "status:", new_bid.status)
    assert new_bid.remaining_qty == 1000, (
        "BUG: new bid leg crossed the stale (uncancelled) ask leg from the "
        "replaced quote"
    )
