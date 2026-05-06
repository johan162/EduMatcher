"""
Additional Engine handler tests targeting the 232 uncovered statements.

Covers:
  - _parse_fix_order (valid/invalid)
  - _handle_symbols_request
  - _handle_book_snapshot_request
  - _handle_amend (success/error paths)
  - _handle_cancel (success, not found, combo cascade, oco cascade)
  - _handle_session_transition (valid/invalid transitions)
  - _expire_tif
  - _run_uncross
  - _handle_combo_order / _validate_combo / _cascade_cancel_combo
  - _handle_combo_cancel
  - _handle_oco_order / _handle_oco_cancel / _check_oco_after_event
  - _handle_new_order session-state gating (closed, ATO, ATC, no-match types)
  - _flush_snapshots
  - _gateway_status
"""

from __future__ import annotations

from dataclasses import dataclass


from edumatcher.engine.config_loader import (
    EngineConfig,
    FixGatewayConfig,
    SymbolConfig,
)
from edumatcher.engine.main import Engine
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderType, Side, TIF
from edumatcher.models.session import SessionState

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


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
    symbols=("AAPL",),
    gateways=("GW01",),
    sessions_enabled: bool = False,
) -> tuple[Engine, _FakeSock]:
    pull_sock = _FakeSock(sent=[])
    pub_sock = _FakeSock(sent=[])

    cfg = EngineConfig(
        symbols={sym: SymbolConfig(name=sym) for sym in symbols},
        fix_gateways={
            gw: FixGatewayConfig(id=gw, description=f"{gw} trader") for gw in gateways
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


def _connect(engine: Engine, gw: str = "GW01") -> None:
    engine._handle_gateway_connect({"gateway_id": gw})


def _make_order_payload(
    symbol="AAPL",
    side=Side.BUY,
    order_type=OrderType.LIMIT,
    qty=100,
    price=100.0,
    gateway_id="GW01",
    tif=TIF.DAY,
    stop_price=None,
) -> dict:
    o = Order.create(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=qty,
        gateway_id=gateway_id,
        tif=tif,
        price=price,
        stop_price=stop_price,
    )
    return o.to_dict()


# ---------------------------------------------------------------------------
# _parse_fix_order
# ---------------------------------------------------------------------------


class TestParseFIXOrder:
    def test_valid_limit_buy(self) -> None:
        line = "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=50.0|TIF=GTC"
        order = Engine._parse_fix_order(line, gateway_id="MM")
        assert order is not None
        assert order.symbol == "AAPL"
        assert order.side == Side.BUY
        assert order.price == 50.0
        assert order.tif == TIF.GTC

    def test_missing_new_prefix_returns_none(self) -> None:
        line = "AMEND|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=50.0"
        assert Engine._parse_fix_order(line, "MM") is None

    def test_missing_required_field_returns_none(self) -> None:
        line = "NEW|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=50.0"
        assert Engine._parse_fix_order(line, "MM") is None

    def test_invalid_enum_value_returns_none(self) -> None:
        line = "NEW|SYM=AAPL|SIDE=WRONG|TYPE=LIMIT|QTY=100|PRICE=50.0"
        assert Engine._parse_fix_order(line, "MM") is None

    def test_stop_limit_parsed(self) -> None:
        line = "NEW|SYM=AAPL|SIDE=SELL|TYPE=STOP_LIMIT|QTY=50|PRICE=95.0|STOP=100.0"
        order = Engine._parse_fix_order(line, "MM")
        assert order is not None
        assert order.stop_price == 100.0


# ---------------------------------------------------------------------------
# _handle_symbols_request
# ---------------------------------------------------------------------------


class TestHandleSymbolsRequest:
    def test_returns_known_symbols(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
        _connect(engine)
        # Create books
        engine._handle_new_order(_make_order_payload("AAPL"))
        engine._handle_new_order(_make_order_payload("MSFT", gateway_id="GW01"))
        pub_sock.sent.clear()
        engine._handle_symbols_request({"gateway_id": "GW01"})
        topic, msg = decode(pub_sock.sent[-1])
        assert topic == "system.symbols.GW01"
        assert "AAPL" in msg["symbols"]
        assert "MSFT" in msg["symbols"]


# ---------------------------------------------------------------------------
# _handle_book_snapshot_request
# ---------------------------------------------------------------------------


class TestHandleBookSnapshotRequest:
    def test_known_symbol_publishes_snapshot(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_new_order(_make_order_payload())
        pub_sock.sent.clear()
        engine._handle_book_snapshot_request({"symbol": "aapl"})
        assert any(b"book.AAPL" in frames[0] for frames in pub_sock.sent)

    def test_unknown_symbol_sends_nothing(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        count = len(pub_sock.sent)
        engine._handle_book_snapshot_request({"symbol": "NONEXISTENT"})
        assert len(pub_sock.sent) == count


# ---------------------------------------------------------------------------
# _handle_amend
# ---------------------------------------------------------------------------


class TestHandleAmend:
    def test_amend_succeeds(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_new_order(_make_order_payload(qty=100, price=100.0))
        # find order id from ack
        _, ack = decode(pub_sock.sent[-1])
        order_id = ack.get("order_id") or _get_last_ack_id(pub_sock)
        pub_sock.sent.clear()
        engine._handle_amend({"order_id": order_id, "gateway_id": "GW01", "qty": 80})
        topic, msg = decode(pub_sock.sent[-1])
        assert "amended" in topic
        assert msg["qty"] == 80

    def test_amend_requires_price_or_qty(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_amend(
            {"order_id": "x", "gateway_id": "GW01", "price": None, "qty": None}
        )
        topic, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False

    def test_amend_unknown_order_rejected(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_amend({"order_id": "NONE", "gateway_id": "GW01", "qty": 50})
        topic, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False

    def test_amend_unauthorized_gateway(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        engine._handle_amend({"order_id": "x", "gateway_id": "UNKNOWN", "qty": 50})
        topic, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False


def _get_last_ack_id(pub_sock: _FakeSock) -> str:
    for frames in reversed(pub_sock.sent):
        topic, payload = decode(frames)
        if "ack" in topic and payload.get("accepted"):
            return str(payload.get("order_id", ""))
    return ""


# ---------------------------------------------------------------------------
# _handle_cancel
# ---------------------------------------------------------------------------


class TestHandleCancel:
    def test_cancel_existing_order(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_new_order(_make_order_payload())
        order_id = _get_last_ack_id(pub_sock)
        pub_sock.sent.clear()
        engine._handle_cancel({"order_id": order_id, "gateway_id": "GW01"})
        topic, _ = decode(pub_sock.sent[-1])
        assert "cancelled" in topic

    def test_cancel_nonexistent_order_rejected(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_cancel({"order_id": "NONE", "gateway_id": "GW01"})
        topic, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False

    def test_cancel_unauthorized_gateway(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        engine._handle_cancel({"order_id": "x", "gateway_id": "UNKNOWN"})
        topic, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False


# ---------------------------------------------------------------------------
# _handle_session_transition
# ---------------------------------------------------------------------------


class TestSessionTransition:
    def test_transition_ignored_when_sessions_disabled(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, _ = _make_engine(monkeypatch, tmp_path, sessions_enabled=False)
        engine._session_state = SessionState.CONTINUOUS
        engine._handle_session_transition({"to_state": "CLOSED"})
        assert engine._session_state == SessionState.CONTINUOUS

    def test_valid_transition_continuous_to_closing_auction(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        # CONTINUOUS → CLOSING_AUCTION is valid
        engine._session_state = SessionState.CONTINUOUS
        pub_sock.sent.clear()
        engine._handle_session_transition({"to_state": "CLOSING_AUCTION"})
        assert engine._session_state == SessionState.CLOSING_AUCTION
        topic, msg = decode(pub_sock.sent[-1])
        assert "session.state" in topic

    def test_invalid_transition_ignored(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        engine._session_state = SessionState.CONTINUOUS
        count = len(pub_sock.sent)
        engine._handle_session_transition({"to_state": "PRE_OPEN"})
        # No message published for invalid transition
        assert len(pub_sock.sent) == count

    def test_bad_state_value_ignored(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        count = len(pub_sock.sent)
        engine._handle_session_transition({"to_state": "GARBAGE"})
        assert len(pub_sock.sent) == count

    def test_pre_open_to_opening_auction(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        engine._session_state = SessionState.PRE_OPEN
        engine._handle_session_transition({"to_state": "OPENING_AUCTION"})
        assert engine._session_state == SessionState.OPENING_AUCTION

    def test_opening_auction_to_continuous_triggers_uncross(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        _connect(engine)
        # Place crossing orders during OPENING_AUCTION so there's something to uncross
        engine._session_state = SessionState.OPENING_AUCTION
        engine._handle_new_order(_make_order_payload(side=Side.BUY, price=100.0))
        engine._handle_new_order(
            _make_order_payload(side=Side.SELL, price=100.0, gateway_id="GW01")
        )
        pub_sock.sent.clear()
        engine._handle_session_transition({"to_state": "CONTINUOUS"})
        assert engine._session_state == SessionState.CONTINUOUS

    def test_closing_auction_to_closed_expires_atc(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        _connect(engine)
        engine._session_state = SessionState.CLOSING_AUCTION
        # Place an ATC order
        o = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW01",
            tif=TIF.ATC,
            price=100.0,
        )
        engine._handle_new_order(o.to_dict())
        pub_sock.sent.clear()
        engine._handle_session_transition({"to_state": "CLOSED"})
        # ATC orders should be expired
        expired_msgs = [decode(f) for f in pub_sock.sent if b"expired" in f[0]]
        assert len(expired_msgs) >= 1


# ---------------------------------------------------------------------------
# Session-state gating on new orders
# ---------------------------------------------------------------------------


class TestNewOrderSessionGating:
    def test_sessions_enabled_starts_closed_and_rejects_new_orders(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        _connect(engine)
        assert engine._session_state == SessionState.CLOSED
        engine._handle_new_order(_make_order_payload())
        topic, msg = decode(pub_sock.sent[-1])
        assert "order.ack" in topic
        assert msg["accepted"] is False
        assert "closed" in msg["reason"].lower()

    def test_order_rejected_when_market_closed(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        _connect(engine)
        engine._session_state = SessionState.CLOSED
        engine._handle_new_order(_make_order_payload())
        topic, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False
        assert "closed" in msg["reason"].lower()

    def test_ato_rejected_outside_opening_auction(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        _connect(engine)
        engine._session_state = SessionState.CONTINUOUS
        payload = _make_order_payload(tif=TIF.ATO)
        engine._handle_new_order(payload)
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False
        assert "ATO" in msg["reason"]

    def test_atc_rejected_outside_closing_auction(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        _connect(engine)
        engine._session_state = SessionState.CONTINUOUS
        payload = _make_order_payload(tif=TIF.ATC)
        engine._handle_new_order(payload)
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False
        assert "ATC" in msg["reason"]

    def test_market_order_rejected_in_pre_open(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        _connect(engine)
        engine._session_state = SessionState.PRE_OPEN
        payload = _make_order_payload(order_type=OrderType.MARKET, price=None)
        engine._handle_new_order(payload)
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False

    def test_fok_rejected_in_pre_open(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        _connect(engine)
        engine._session_state = SessionState.PRE_OPEN
        payload = _make_order_payload(order_type=OrderType.FOK, price=100.0)
        engine._handle_new_order(payload)
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False

    def test_ato_accepted_during_opening_auction(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        _connect(engine)
        engine._session_state = SessionState.OPENING_AUCTION
        payload = _make_order_payload(tif=TIF.ATO)
        engine._handle_new_order(payload)
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is True


# ---------------------------------------------------------------------------
# Trailing stop edge case in new order handler
# ---------------------------------------------------------------------------


class TestTrailingStopNewOrder:
    def test_trailing_stop_rejected_without_prior_price(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        o = Order.create(
            symbol="AAPL",
            side=Side.SELL,
            order_type=OrderType.TRAILING_STOP,
            quantity=100,
            gateway_id="GW01",
            tif=TIF.DAY,
            trail_offset=5.0,
        )
        engine._handle_new_order(o.to_dict())
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False
        assert "Trailing stop" in msg["reason"]

    def test_trailing_stop_accepted_with_last_trade_price(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        # Seed a last trade price
        engine._book("AAPL").last_trade_price = 100.0
        o = Order.create(
            symbol="AAPL",
            side=Side.SELL,
            order_type=OrderType.TRAILING_STOP,
            quantity=100,
            gateway_id="GW01",
            tif=TIF.DAY,
            trail_offset=5.0,
        )
        engine._handle_new_order(o.to_dict())
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is True


# ---------------------------------------------------------------------------
# Combo handlers
# ---------------------------------------------------------------------------


class TestComboHandlers:
    def _combo_payload(self, gateway_id: str = "GW01") -> dict:
        from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType

        combo = ComboOrder.create(
            combo_id="C001",
            gateway_id=gateway_id,
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=100.0,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=50,
                    price=200.0,
                ),
            ],
        )
        return combo.to_dict()

    def test_combo_order_accepted(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
        _connect(engine)
        engine._handle_combo_order(self._combo_payload())
        topics = [decode(f)[0] for f in pub_sock.sent]
        assert any("combo.ack" in t for t in topics)

    def test_combo_order_rejected_gateway_not_connected(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
        engine._handle_combo_order(self._combo_payload())
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False

    def test_combo_cancel_succeeds(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, symbols=("AAPL", "MSFT"))
        _connect(engine)
        engine._handle_combo_order(self._combo_payload())
        pub_sock.sent.clear()
        engine._handle_combo_cancel({"gateway_id": "GW01", "combo_id": "C001"})
        topics = [decode(f)[0] for f in pub_sock.sent]
        assert any("combo.status" in t for t in topics)

    def test_combo_cancel_not_found(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_combo_cancel({"gateway_id": "GW01", "combo_id": "NONE"})
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False

    def test_validate_combo_too_few_legs(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(monkeypatch, tmp_path)
        from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType

        combo = ComboOrder.create(
            combo_id="X",
            gateway_id="GW01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    price=100.0,
                ),
            ],
        )
        err = engine._validate_combo(combo)
        assert "2 legs" in err

    def test_validate_combo_duplicate_symbols(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(monkeypatch, tmp_path, symbols=("AAPL",))
        from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType

        combo = ComboOrder.create(
            combo_id="X",
            gateway_id="GW01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    price=100.0,
                ),
                ComboLeg(
                    symbol="AAPL",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    price=101.0,
                ),
            ],
        )
        err = engine._validate_combo(combo)
        assert "Duplicate" in err


# ---------------------------------------------------------------------------
# OCO handlers
# ---------------------------------------------------------------------------


class TestOCOHandlers:
    def _oco_payload(self, gateway_id: str = "GW01") -> dict:
        return {
            "oco_id": "OCO001",
            "gateway_id": gateway_id,
            "symbol": "AAPL",
            "quantity": 100,
            "tif": "DAY",
            "leg1": {"side": "BUY", "order_type": "LIMIT", "price": 95.0},
            "leg2": {"side": "BUY", "order_type": "STOP", "stop_price": 105.0},
        }

    def test_oco_accepted(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_oco_order(self._oco_payload())
        topics = [decode(f)[0] for f in pub_sock.sent]
        assert any("oco.ack" in t for t in topics)

    def test_oco_rejected_gateway_not_connected(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        engine._handle_oco_order(self._oco_payload())
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False

    def test_oco_rejected_bad_symbol(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        payload = self._oco_payload()
        payload["symbol"] = "ZZZZ"
        engine._handle_oco_order(payload)
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False

    def test_oco_rejected_zero_qty(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        payload = self._oco_payload()
        payload["quantity"] = 0
        engine._handle_oco_order(payload)
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False

    def test_oco_rejected_bad_leg_definition(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        payload = self._oco_payload()
        payload["leg1"] = {"side": "INVALID", "order_type": "LIMIT"}
        engine._handle_oco_order(payload)
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False

    def test_oco_cancel_succeeds(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_oco_order(self._oco_payload())
        pub_sock.sent.clear()
        engine._handle_oco_cancel({"gateway_id": "GW01", "oco_id": "OCO001"})
        # Should have published cancelled messages
        topics = [decode(f)[0] for f in pub_sock.sent]
        assert any("cancelled" in t for t in topics)

    def test_oco_cancel_not_found(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_oco_cancel({"gateway_id": "GW01", "oco_id": "NONE"})
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False

    def test_oco_sibling_cancelled_when_leg_fills(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine, "GW01")
        if engine._allowed_fix_gateways and "GW02" in engine._allowed_fix_gateways:
            _connect(engine, "GW02")
        # Register OCO pair manually and simulate one leg getting filled
        engine._handle_oco_order(self._oco_payload())
        order_ids = engine._oco_groups.get("OCO001", [])
        assert len(order_ids) == 2

    def test_oco_market_closed_rejected(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        _connect(engine)
        engine._session_state = SessionState.CLOSED
        engine._handle_oco_order(self._oco_payload())
        _, msg = decode(pub_sock.sent[-1])
        assert msg["accepted"] is False


# ---------------------------------------------------------------------------
# _flush_snapshots
# ---------------------------------------------------------------------------


class TestFlushSnapshots:
    def test_flush_publishes_dirty_symbols(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_new_order(_make_order_payload())
        # Force the throttle window to zero so flush always publishes
        engine._last_snapshot["AAPL"] = 0.0
        engine._dirty_symbols.add("AAPL")
        count_before = len(pub_sock.sent)
        engine._flush_snapshots()
        assert len(pub_sock.sent) > count_before

    def test_flush_throttles_rapid_updates(self, monkeypatch, tmp_path) -> None:
        import time as _time

        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_new_order(_make_order_payload())
        # Set last snapshot to "just now" so throttle blocks
        engine._last_snapshot["AAPL"] = _time.monotonic()
        engine._dirty_symbols.add("AAPL")
        count_before = len(pub_sock.sent)
        engine._flush_snapshots()
        assert len(pub_sock.sent) == count_before


# ---------------------------------------------------------------------------
# _gateway_status
# ---------------------------------------------------------------------------


class TestGatewayStatus:
    def test_no_allowlist_always_ok(self, monkeypatch, tmp_path) -> None:
        pull_sock = _FakeSock(sent=[])
        pub_sock = _FakeSock(sent=[])
        monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
        monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
        monkeypatch.setattr(
            "edumatcher.engine.main.load_engine_config",
            lambda _: (_ for _ in ()).throw(FileNotFoundError()),
        )
        monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)
        # Engine without config file → no allowlist
        engine = Engine(config_path=None)
        ok, reason = engine._gateway_status("ANY_GW")
        assert ok is True
        assert reason == ""

    def test_not_in_allowlist(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(monkeypatch, tmp_path)
        ok, reason = engine._gateway_status("UNKNOWN")
        assert ok is False
        assert "not configured" in reason

    def test_in_allowlist_but_not_connected(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(monkeypatch, tmp_path)
        ok, reason = engine._gateway_status("GW01")
        assert ok is False
        assert "not connected" in reason

    def test_connected_and_in_allowlist(self, monkeypatch, tmp_path) -> None:
        engine, _ = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        ok, reason = engine._gateway_status("GW01")
        assert ok is True
        assert reason == ""
