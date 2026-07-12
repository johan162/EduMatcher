"""
Regression tests for the HIGH-severity findings (H1-H9) in
docs-design/EduMatcher-Engine-Review.md.

IMPORTANT: These tests encode the *correct* expected behaviour, so they are
EXPECTED TO FAIL until each finding is fixed.  Run them with:

    pytest tests/test_engine_review_highs.py -v

Once a finding is fixed its test(s) must pass and must be kept as permanent
regression coverage.  If the failing tests are disruptive to CI before the
fixes land, add `@pytest.mark.xfail(strict=True, reason="H<n> open")` to the
open ones and remove the marker together with the fix.

Finding → test map
------------------
  H1  client-timestamp queue jumping         TestH1TimePriorityIsEngineAssigned
  H2  amend: no rematch, no collar check     TestH2AmendSemantics
  H3  positions miss quote/OCO fills         TestH3PositionLedgerCompleteness
  H4  drop copy misses quote-flow fills      TestH4DropCopyCompleteness
  H5  duplicate fill messages (quote path)   TestH5NoDuplicateFillMessages
  H6  wrong fill_price on multi-level sweep  TestH6FillPriceAccuracy
  H7  terminal orders never purged           TestH7TerminalOrderPurge
  H8  FOK: hidden liquidity + SMP limbo      TestH8FokCorrectness
  H9  quotes/combos bypass session gating    TestH9SessionGating

The H4/H5 tests exercise the quote path as the representative flow; the same
guarantees must hold for the combo, OCO, and uncross paths once event
publication is consolidated (review recommendation A1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from edumatcher.engine.collar import CollarConfig
from edumatcher.engine.config_loader import (
    EngineConfig,
    FixGatewayConfig,
    SymbolConfig,
)
from edumatcher.engine.main import Engine
from edumatcher.engine.order_book import OrderBook
from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType
from edumatcher.models.message import decode
from edumatcher.models.order import (
    Order,
    OrderStatus,
    OrderType,
    Side,
    SmpAction,
    TIF,
)
from edumatcher.models.participant import ParticipantRole

SYMBOL = "AAPL"  # 2 tick decimals by default → 100.00 == 10000 ticks


# ---------------------------------------------------------------------------
# Shared fixtures (same pattern as test_engine_handlers.py /
# test_engine_review_criticals.py)
# ---------------------------------------------------------------------------


@dataclass
class _FakeSock:
    sent: list[list[bytes]]
    closed: bool = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


@dataclass
class _FakeDropCopy:
    """Records every drop-copy publication for assertion."""

    events: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)

    def publish(self, gateway_id: str, event_type: str, payload: dict) -> None:
        self.events.append((gateway_id, event_type, payload))

    def close(self) -> None:  # pragma: no cover - interface parity
        pass


def _make_engine(
    monkeypatch,
    tmp_path,
    symbols=(SYMBOL,),
    gateways=("GW01", "GW02", "GW03"),
    mm_gateways: tuple[str, ...] = (),
    sessions_enabled: bool = False,
    symbol_configs: dict[str, SymbolConfig] | None = None,
) -> tuple[Engine, _FakeSock]:
    pull_sock = _FakeSock(sent=[])
    pub_sock = _FakeSock(sent=[])

    cfg = EngineConfig(
        symbols=(
            symbol_configs
            if symbol_configs is not None
            else {sym: SymbolConfig(name=sym) for sym in symbols}
        ),
        fix_gateways={
            gw: FixGatewayConfig(
                id=gw,
                description=f"{gw}",
                role=(
                    ParticipantRole.MARKET_MAKER
                    if gw in mm_gateways
                    else ParticipantRole.TRADER
                ),
            )
            for gw in gateways
        },
        sessions_enabled=sessions_enabled,
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
    return engine, pub_sock


def _connect(engine: Engine, *gws: str) -> None:
    for gw in gws or ("GW01", "GW02", "GW03"):
        engine._handle_gateway_connect({"gateway_id": gw})


def _payload(
    side: Side,
    order_type: OrderType,
    qty: int,
    gateway_id: str,
    price: float | None = None,
    tif: TIF = TIF.DAY,
) -> dict[str, Any]:
    o = Order.create(
        symbol=SYMBOL,
        side=side,
        order_type=order_type,
        quantity=qty,
        gateway_id=gateway_id,
        tif=tif,
        price=price,
    )
    return o.to_dict()


def _msgs(pub_sock: _FakeSock, topic: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for frames in pub_sock.sent:
        t, payload = decode(frames)
        if t == topic:
            out.append(payload)
    return out


def _resting_ids(book: OrderBook) -> set[str]:
    return {o.id for o in book.resting_orders()}


def _quote(
    engine: Engine,
    gateway_id: str,
    bid_price: float,
    ask_price: float,
    bid_qty: int = 100,
    ask_qty: int = 100,
    quote_id: str = "Q1",
) -> None:
    engine._handle_quote_new(
        {
            "gateway_id": gateway_id,
            "symbol": SYMBOL,
            "quote_id": quote_id,
            "bid_price": bid_price,
            "ask_price": ask_price,
            "bid_qty": bid_qty,
            "ask_qty": ask_qty,
            "tif": "DAY",
        }
    )


# ---------------------------------------------------------------------------
# H1 — time priority must be assigned by the engine, not the client
#
# The heap key uses Order.timestamp exactly as received in the payload
# (Order.from_dict keeps d["timestamp"]).  A participant that back-dates its
# timestamp jumps the FIFO queue at a price level.
# ---------------------------------------------------------------------------


class TestH1TimePriorityIsEngineAssigned:
    def test_backdated_timestamp_cannot_jump_the_queue(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub = _make_engine(monkeypatch, tmp_path)
        _connect(engine)

        first = _payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.0)
        engine._handle_new_order(first)

        # GW02 arrives strictly later but spoofs an older timestamp.
        spoofer = _payload(Side.BUY, OrderType.LIMIT, 100, "GW02", price=100.0)
        spoofer["timestamp"] = first["timestamp"] - 1_000_000
        engine._handle_new_order(spoofer)

        # One sell for exactly one order's quantity — must hit GW01 (FIFO).
        engine._handle_new_order(
            _payload(Side.SELL, OrderType.LIMIT, 100, "GW03", price=100.0)
        )

        trades = _msgs(pub, "trade.executed")
        assert len(trades) == 1 and trades[0]["quantity"] == 100  # precondition
        assert trades[0]["buy_order_id"] == first["id"], (
            "H1: a back-dated client timestamp jumped the price-time queue — "
            "priority must come from engine arrival order, not payload timestamps"
        )


# ---------------------------------------------------------------------------
# H2 — amend semantics
#
# (a) A price amend that makes the order marketable must trigger matching
#     (or be rejected); it must never leave a crossed book.
# (b) An amended price must be subject to the same collar validation as a
#     new order.
# ---------------------------------------------------------------------------


class TestH2AmendSemantics:
    def test_crossing_amend_does_not_leave_a_crossed_book(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub = _make_engine(monkeypatch, tmp_path)
        _connect(engine)

        bid = _payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=99.0)
        engine._handle_new_order(bid)
        engine._handle_new_order(
            _payload(Side.SELL, OrderType.LIMIT, 100, "GW02", price=101.0)
        )

        # Amend the bid up through the resting ask.
        engine._handle_amend(
            {"order_id": bid["id"], "gateway_id": "GW01", "price": 101.0}
        )

        book = engine.books[SYMBOL]
        best_bid = max(book._bid_qty) if book._bid_qty else None
        best_ask = min(book._ask_qty) if book._ask_qty else None
        assert (
            best_bid is None or best_ask is None or best_bid < best_ask
        ), (
            f"H2: book left crossed after price amend "
            f"(best_bid={best_bid}, best_ask={best_ask}) — a marketable amend "
            f"must match (cancel/replace semantics) or be rejected"
        )

    def test_amend_price_is_collar_validated(self, monkeypatch, tmp_path) -> None:
        engine, pub = _make_engine(
            monkeypatch,
            tmp_path,
            symbol_configs={
                SYMBOL: SymbolConfig(
                    name=SYMBOL,
                    last_buy_price=100.0,  # collar reference → 10000 ticks
                    collar=CollarConfig(
                        symbol=SYMBOL,
                        static_band_pct=0.20,  # allowed: 80.00 .. 120.00
                        dynamic_band_pct=0.50,
                    ),
                )
            },
        )
        engine._load_config()  # wires the collar with reference_price=10000
        _connect(engine)

        order = _payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.0)
        engine._handle_new_order(order)  # passes the collar, rests

        # New order at 150.00 would be rejected (static band breach) —
        # the same price must not be reachable through an amend.
        engine._handle_amend(
            {"order_id": order["id"], "gateway_id": "GW01", "price": 150.0}
        )

        resting = engine.books[SYMBOL].get_order(order["id"])
        assert resting is not None  # precondition: still on the book
        assert resting.price is not None and resting.price <= 12000, (
            f"H2: amend bypassed the price collar — resting price is now "
            f"{resting.price} ticks, outside the ±20% band around 10000"
        )


# ---------------------------------------------------------------------------
# H3 — the position ledger must reflect EVERY fill, whatever flow produced it
#
# _update_position is only called in _handle_new_order and _run_uncross.
# Fills whose aggressing flow entered as a quote or an OCO leg update no
# positions at all — for either counterparty.
# ---------------------------------------------------------------------------


class TestH3PositionLedgerCompleteness:
    def test_quote_flow_fills_update_positions(self, monkeypatch, tmp_path) -> None:
        engine, pub = _make_engine(monkeypatch, tmp_path, mm_gateways=("GW01",))
        _connect(engine)
        engine._handle_new_order(
            _payload(Side.SELL, OrderType.LIMIT, 100, "GW02", price=101.0)
        )

        # MM quote whose bid crosses the resting ask → trade 100 @ 101.00.
        _quote(engine, "GW01", bid_price=101.0, ask_price=102.0)

        trades = _msgs(pub, "trade.executed")
        assert len(trades) == 1 and trades[0]["quantity"] == 100  # precondition

        gw01_pos = engine._gateway_positions.get("GW01", {}).get(SYMBOL, 0)
        gw02_pos = engine._gateway_positions.get("GW02", {}).get(SYMBOL, 0)
        assert gw01_pos == 100, (
            f"H3: quote-flow fill did not update the buyer's position "
            f"(expected +100, ledger shows {gw01_pos})"
        )
        assert gw02_pos == -100, (
            f"H3: quote-flow fill did not update the seller's position "
            f"(expected -100, ledger shows {gw02_pos})"
        )

    def test_oco_flow_fills_update_positions(self, monkeypatch, tmp_path) -> None:
        engine, pub = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_new_order(
            _payload(Side.SELL, OrderType.LIMIT, 100, "GW02", price=100.0)
        )

        engine._handle_oco_order(
            {
                "oco_id": "OCO-POS-1",
                "gateway_id": "GW01",
                "symbol": SYMBOL,
                "quantity": 100,
                "tif": "DAY",
                "leg1": {"side": "BUY", "order_type": "LIMIT", "price": 100.0},
                "leg2": {"side": "SELL", "order_type": "LIMIT", "price": 120.0},
            }
        )

        trades = _msgs(pub, "trade.executed")
        assert len(trades) == 1 and trades[0]["quantity"] == 100  # precondition

        gw01_pos = engine._gateway_positions.get("GW01", {}).get(SYMBOL, 0)
        assert gw01_pos == 100, (
            f"H3: OCO-leg fill did not update the buyer's position "
            f"(expected +100, ledger shows {gw01_pos})"
        )


# ---------------------------------------------------------------------------
# H4 — drop copy must carry fills from every flow
#
# The only _drop_copy.publish call sits in _handle_new_order; fills produced
# by the quote path (and combo / OCO / uncross paths) never reach the
# clearing/risk feed.
# ---------------------------------------------------------------------------


class TestH4DropCopyCompleteness:
    def test_quote_flow_fills_reach_drop_copy(self, monkeypatch, tmp_path) -> None:
        engine, pub = _make_engine(monkeypatch, tmp_path, mm_gateways=("GW01",))
        drop = _FakeDropCopy()
        engine._drop_copy = drop
        _connect(engine)

        engine._handle_new_order(
            _payload(Side.SELL, OrderType.LIMIT, 100, "GW02", price=101.0)
        )
        _quote(engine, "GW01", bid_price=101.0, ask_price=102.0)  # trades 100 @ 101

        trades = _msgs(pub, "trade.executed")
        assert len(trades) == 1  # precondition: the fill really happened

        fill_events = [e for e in drop.events if e[1] == "order.fill"]
        assert fill_events, (
            "H4: a quote-flow fill printed on trade.executed but no order.fill "
            "event was published on the drop-copy feed for either counterparty"
        )


# ---------------------------------------------------------------------------
# H5 — no duplicate fill messages
#
# Only _handle_new_order deduplicates fill events.  In the quote path an
# order that sweeps k price levels appears k times in `events` and k
# identical fill messages (carrying the FINAL cumulative quantities) are
# published — consumers overcount by up to k×.
# ---------------------------------------------------------------------------


class TestH5NoDuplicateFillMessages:
    def test_multi_level_sweep_via_quote_publishes_unique_fill_messages(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub = _make_engine(monkeypatch, tmp_path, mm_gateways=("GW01",))
        _connect(engine)
        engine._handle_new_order(
            _payload(Side.SELL, OrderType.LIMIT, 50, "GW02", price=100.0)
        )
        engine._handle_new_order(
            _payload(Side.SELL, OrderType.LIMIT, 50, "GW02", price=101.0)
        )

        # MM bid at 101.00 sweeps both ask levels (2 fills, 100 total).
        _quote(engine, "GW01", bid_price=101.0, ask_price=102.0, bid_qty=100)

        acks = [m for m in _msgs(pub, "quote.ack.GW01") if m.get("accepted")]
        assert acks, "precondition: quote accepted"
        bid_id = acks[0]["bid_order_id"]

        fills = [m for m in _msgs(pub, "order.fill.GW01") if m["order_id"] == bid_id]
        assert fills, "precondition: at least one fill message for the quote bid"

        signatures = [(m["fill_qty"], m["remaining_qty"]) for m in fills]
        assert len(signatures) == len(set(signatures)), (
            f"H5: duplicate fill messages published for one order "
            f"({len(signatures)} messages, signatures={signatures}) — consumers "
            f"summing fill_qty overcount the execution"
        )


# ---------------------------------------------------------------------------
# H6 — fill messages must report the price the order actually filled at
#
# _handle_new_order computes ONE display price (_fill_px = last trade of the
# whole sweep) and stamps it on every fill message.  A passive order filled
# at a better level is told it filled at the sweep's last price.
# ---------------------------------------------------------------------------


class TestH6FillPriceAccuracy:
    def test_passive_order_fill_price_is_its_own_execution_price(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub = _make_engine(monkeypatch, tmp_path)
        _connect(engine)

        ask_low = _payload(Side.SELL, OrderType.LIMIT, 50, "GW02", price=100.0)
        ask_high = _payload(Side.SELL, OrderType.LIMIT, 50, "GW02", price=101.0)
        engine._handle_new_order(ask_low)
        engine._handle_new_order(ask_high)

        # Aggressor sweeps both levels: 50 @ 100.00, then 50 @ 101.00.
        engine._handle_new_order(
            _payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=101.0)
        )

        trades = _msgs(pub, "trade.executed")
        assert [t["price"] for t in trades] == [100.0, 101.0]  # precondition

        low_fills = [
            m for m in _msgs(pub, "order.fill.GW02") if m["order_id"] == ask_low["id"]
        ]
        assert low_fills, "precondition: passive order received a fill message"
        assert all(m["fill_price"] == 100.0 for m in low_fills), (
            f"H6: passive order resting at 100.00 was told it filled at "
            f"{[m['fill_price'] for m in low_fills]} — fill messages must carry "
            f"the order's own execution price, not the sweep's last price"
        )


# ---------------------------------------------------------------------------
# H7 — orders in a terminal state must be purged from all indexes
#
# Filled orders stay in OrderBook._order_index/_entry_index forever;
# cancelled orders likewise; Engine._order_symbol keeps entries for filled
# orders.  Memory grows without bound and resting_orders() degrades to
# O(all orders ever).
# ---------------------------------------------------------------------------


class TestH7TerminalOrderPurge:
    def test_filled_and_cancelled_orders_leave_the_book_indexes(self) -> None:
        book = OrderBook(SYMBOL)

        filled = Order.create(
            symbol=SYMBOL,
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW01",
            price=10000,
        )
        book.process(filled)
        aggressor = Order.create(
            symbol=SYMBOL,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW02",
            price=10000,
        )
        book.process(aggressor)
        assert filled.status == OrderStatus.FILLED  # precondition

        assert book.get_order(filled.id) is None, (
            "H7: fully FILLED order still retrievable from _order_index"
        )
        assert filled.id not in book._entry_index, (
            "H7: fully FILLED order still present in _entry_index"
        )

        cancelled = Order.create(
            symbol=SYMBOL,
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW01",
            price=10100,
        )
        book.process(cancelled)
        assert book.cancel_order(cancelled.id) is not None  # precondition

        assert book.get_order(cancelled.id) is None, (
            "H7: CANCELLED order still retrievable from _order_index"
        )
        assert cancelled.id not in book._entry_index, (
            "H7: CANCELLED order still present in _entry_index"
        )

    def test_engine_order_symbol_map_is_pruned_on_fill(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub = _make_engine(monkeypatch, tmp_path)
        _connect(engine)

        resting = _payload(Side.SELL, OrderType.LIMIT, 100, "GW02", price=100.0)
        aggressor = _payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.0)
        engine._handle_new_order(resting)
        engine._handle_new_order(aggressor)
        assert len(_msgs(pub, "trade.executed")) == 1  # precondition: both filled

        assert resting["id"] not in engine._order_symbol, (
            "H7: filled resting order never pruned from Engine._order_symbol"
        )
        assert aggressor["id"] not in engine._order_symbol, (
            "H7: filled aggressor never pruned from Engine._order_symbol"
        )


# ---------------------------------------------------------------------------
# H8 — FOK must be exact and atomic
#
# (a) The pre-check reads the VISIBLE level index only, so hidden iceberg
#     quantity that the sweep would happily fill causes a spurious reject.
# (b) The pre-check counts same-gateway quantity that SMP then skips —
#     the sweep runs dry and the FOK ends PARTIALLY filled, in limbo.
# ---------------------------------------------------------------------------


class TestH8FokCorrectness:
    def test_fok_fillable_from_hidden_iceberg_qty_is_filled(self) -> None:
        book = OrderBook(SYMBOL)
        iceberg = Order.create(
            symbol=SYMBOL,
            side=Side.SELL,
            order_type=OrderType.ICEBERG,
            quantity=100,
            gateway_id="GW01",
            price=10000,
            visible_qty=10,
        )
        book.process(iceberg)

        fok = Order.create(
            symbol=SYMBOL,
            side=Side.BUY,
            order_type=OrderType.FOK,
            quantity=100,
            gateway_id="GW02",
            price=10000,
        )
        trades, _events = book.process(fok)

        assert fok.status == OrderStatus.FILLED, (
            f"H8: FOK for 100 rejected/unfilled (status={fok.status.value}) "
            f"although 100 (10 visible + 90 hidden iceberg) was available — "
            f"the pre-check must agree with what the sweep can execute"
        )
        assert sum(t.quantity for t in trades) == 100

    def test_fok_never_ends_partially_filled_under_smp(self) -> None:
        book = OrderBook(SYMBOL)
        # 50 from a genuine counterparty …
        other = Order.create(
            symbol=SYMBOL,
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=50,
            gateway_id="GW02",
            price=10000,
        )
        book.process(other)
        # … and 50 from the aggressor's own gateway (SMP will skip it).
        own = Order.create(
            symbol=SYMBOL,
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=50,
            gateway_id="GW01",
            price=10000,
        )
        book.process(own)

        fok = Order.create(
            symbol=SYMBOL,
            side=Side.BUY,
            order_type=OrderType.FOK,
            quantity=100,
            gateway_id="GW01",
            price=10000,
            smp_action=SmpAction.CANCEL_RESTING,
        )
        book.process(fok)

        assert fok.remaining_qty in (0, fok.quantity), (
            f"H8: FOK ended PARTIALLY filled ({fok.quantity - fok.remaining_qty}"
            f"/{fok.quantity}) — fill-or-kill must be all-or-nothing"
        )
        assert fok.status in (
            OrderStatus.FILLED,
            OrderStatus.REJECTED,
            OrderStatus.CANCELLED,
        ), (
            f"H8: FOK left in non-terminal limbo state {fok.status.value} — "
            f"neither resting, filled, nor cancelled"
        )
        assert fok.id not in _resting_ids(book)


# ---------------------------------------------------------------------------
# H9 — quotes and combo children must respect session gating
#
# _handle_quote_new performs no session-state check at all, and
# _accept_combo posts children with match=True regardless of session state:
# MMs can quote (and trade) while CLOSED, and combos match during auction
# collection phases while ordinary orders queue.
# ---------------------------------------------------------------------------


class TestH9SessionGating:
    def test_quote_rejected_while_market_closed(self, monkeypatch, tmp_path) -> None:
        engine, pub = _make_engine(
            monkeypatch, tmp_path, mm_gateways=("GW01",), sessions_enabled=True
        )
        _connect(engine)  # engine starts in CLOSED when sessions are enabled

        _quote(engine, "GW01", bid_price=99.0, ask_price=101.0)

        acks = _msgs(pub, "quote.ack.GW01")
        assert acks, "precondition: a quote ack must be published"
        assert acks[-1]["accepted"] is False, (
            "H9: quote accepted while the market is CLOSED — quotes must be "
            "subject to the same session gating as orders"
        )

    def test_quote_does_not_match_during_pre_open(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub = _make_engine(
            monkeypatch, tmp_path, mm_gateways=("GW01",), sessions_enabled=True
        )
        _connect(engine)
        engine._handle_session_transition({"to_state": "PRE_OPEN"})

        # Ordinary order: accepted, queued without matching (correct).
        engine._handle_new_order(
            _payload(Side.SELL, OrderType.LIMIT, 100, "GW02", price=100.0)
        )
        # MM quote whose bid crosses the queued ask.
        _quote(engine, "GW01", bid_price=100.0, ask_price=101.0)

        trades = _msgs(pub, "trade.executed")
        assert trades == [], (
            f"H9: {len(trades)} trade(s) executed during PRE_OPEN via the quote "
            f"path — no continuous matching may occur outside CONTINUOUS"
        )

    def test_combo_children_do_not_match_during_pre_open(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub = _make_engine(
            monkeypatch,
            tmp_path,
            symbols=(SYMBOL, "MSFT"),
            sessions_enabled=True,
        )
        _connect(engine)
        engine._handle_session_transition({"to_state": "PRE_OPEN"})

        engine._handle_new_order(
            _payload(Side.SELL, OrderType.LIMIT, 100, "GW02", price=100.0)
        )

        combo = ComboOrder.create(
            combo_id="CMB-H9",
            gateway_id="GW01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol=SYMBOL,
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=10000,  # crosses the queued ask if matching runs
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    price=5000,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())

        trades = _msgs(pub, "trade.executed")
        assert trades == [], (
            f"H9: {len(trades)} trade(s) executed during PRE_OPEN via combo "
            f"children — combo legs must respect the session's matching state"
        )
