"""
Negative tests — Group 2: Engine state and startup failures (tests 21-25).

Covers:
  21. Engine shutdown / persistence errors — documents actual behaviour when
      save_gtc_orders raises (OSError propagates — no silent swallow).
      Also verifies DAY orders are expired and GTC orders are NOT expired.
  22. Corrupted GTC orders file — two layers of coverage:
      a) Persistence layer: load_gtc_orders returns [] for file-level errors
         (truncated JSON, wrong root type, binary garbage, empty file).
         Individual corrupt entries are skipped and logged at CRITICAL level;
         remaining valid orders in the same file are still returned.
      b) Engine integration: engine starts cleanly and is fully operational
         when the GTC file on disk is corrupt; valid files are restored
         correctly; orders for unknown symbols are skipped gracefully.
  23. Session state corruption — invalid to_state values are silently ignored
      and internal state is unchanged; duplicate transitions are safe.
  24. Order ID collisions — duplicate order IDs must not crash the engine.
  25. Engine startup without a config file — backward-compat mode (no symbol
      or gateway restrictions) accepts any order and shuts down cleanly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from edumatcher.engine.config_loader import EngineConfig, FixGatewayConfig, SymbolConfig
from edumatcher.engine.main import Engine
from edumatcher.engine.persistence import load_gtc_orders
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderStatus, OrderType, Side, TIF
from edumatcher.models.session import SessionState

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeSock:
    sent: list
    closed: bool = False

    def send_multipart(self, frames: list) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


def _make_engine(
    monkeypatch,
    tmp_path,
    symbols=("AAPL",),
    gateways=("GW01",),
    sessions_enabled: bool = False,
    gtc_orders: list | None = None,
    save_raises: bool = False,
) -> tuple[Engine, _FakeSock]:
    pull_sock = _FakeSock(sent=[])
    pub_sock = _FakeSock(sent=[])

    cfg = EngineConfig(
        symbols={s: SymbolConfig(name=s) for s in symbols},
        fix_gateways={g: FixGatewayConfig(id=g, description=g) for g in gateways},
        sessions_enabled=sessions_enabled,
    )

    monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
    monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
    monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
    monkeypatch.setattr(
        "edumatcher.engine.main.load_gtc_orders",
        lambda _: list(gtc_orders) if gtc_orders else [],
    )
    monkeypatch.setattr("edumatcher.engine.main.load_gtc_combos", lambda _: [])
    monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: {})
    monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)

    if save_raises:
        monkeypatch.setattr(
            "edumatcher.engine.main.save_gtc_orders",
            lambda *_: (_ for _ in ()).throw(OSError("disk full")),
        )
        monkeypatch.setattr(
            "edumatcher.engine.main.save_gtc_combos",
            lambda *_: (_ for _ in ()).throw(OSError("disk full")),
        )
        monkeypatch.setattr(
            "edumatcher.engine.main.save_book_stats",
            lambda *_: (_ for _ in ()).throw(OSError("disk full")),
        )
    else:
        monkeypatch.setattr("edumatcher.engine.main.save_gtc_orders", lambda *_: None)
        monkeypatch.setattr("edumatcher.engine.main.save_gtc_combos", lambda *_: None)
        monkeypatch.setattr("edumatcher.engine.main.save_book_stats", lambda *_: None)

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
) -> dict:
    o = Order.create(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=qty,
        gateway_id=gateway_id,
        tif=tif,
        price=price,
    )
    return o.to_dict()


def _last_ack(pub_sock: _FakeSock) -> dict:
    for frames in reversed(pub_sock.sent):
        topic, payload = decode(frames)
        if "ack" in topic:
            return payload
    return {}


# ===========================================================================
# Test 21 — Engine shutdown / persistence behaviour
# ===========================================================================


class TestShutdownDuringActiveMatching:
    """_shutdown() behaviour with resting orders and persistence errors."""

    def test_shutdown_with_disk_full_raises_os_error(
        self, monkeypatch, tmp_path
    ) -> None:
        """_shutdown() propagates OSError when save_gtc_orders fails.

        The engine currently does NOT swallow persistence errors during
        shutdown — a disk-full condition surfaces as an OSError.  This test
        documents and asserts that actual behaviour.  If the engine is hardened
        to handle it gracefully in the future, update this test accordingly.
        """
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, save_raises=True)
        _connect(engine)
        o = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW01",
            tif=TIF.GTC,
            price=99.0,
        )
        engine._handle_new_order(o.to_dict())
        with pytest.raises(OSError, match="disk full"):
            engine._shutdown()

    def test_shutdown_publishes_expired_for_day_orders(
        self, monkeypatch, tmp_path
    ) -> None:
        """DAY orders must receive an expired event at shutdown."""
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        engine._handle_new_order(_make_order_payload(tif=TIF.DAY))
        pub_sock.sent.clear()
        engine._shutdown()
        expired_topics = [decode(f)[0] for f in pub_sock.sent if b"expired" in f[0]]
        assert len(expired_topics) >= 1

    def test_shutdown_does_not_expire_gtc_orders(self, monkeypatch, tmp_path) -> None:
        """GTC orders must NOT be expired at shutdown — they persist to the
        next session."""
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        o = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            gateway_id="GW01",
            tif=TIF.GTC,
            price=99.0,
        )
        engine._handle_new_order(o.to_dict())
        pub_sock.sent.clear()
        engine._shutdown()
        expired = [decode(f) for f in pub_sock.sent if b"expired" in f[0]]
        for _, msg in expired:
            assert msg.get("tif") != "GTC", "GTC order must not be expired at shutdown"

    def test_shutdown_closes_sockets(self, monkeypatch, tmp_path) -> None:
        """pub_sock must be closed after a normal _shutdown()."""
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        engine._shutdown()
        assert pub_sock.closed is True


# ===========================================================================
# Test 22 — Corrupted GTC persistence file
# ===========================================================================


class TestCorruptedGTCOrdersFile:
    """load_gtc_orders file-level and per-entry error handling."""

    def test_truncated_json_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "gtc.json"
        path.write_text('[{"id": "x", "sym')
        assert load_gtc_orders(path) == []

    def test_wrong_root_type_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "gtc.json"
        path.write_text('{"not": "a list"}')
        assert load_gtc_orders(path) == []

    def test_single_corrupt_enum_entry_returns_empty(self, tmp_path: Path) -> None:
        """A file containing only one corrupt order returns an empty list."""
        o = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW01",
            tif=TIF.GTC,
            price=100.0,
        )
        bad = o.to_dict()
        bad["side"] = "SIDEWAYS"
        path = tmp_path / "gtc.json"
        path.write_text(json.dumps([bad]))
        assert load_gtc_orders(path) == []

    def test_corrupt_entry_logged_at_critical_level(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A corrupt order entry must emit a CRITICAL-level log message."""
        import logging

        o = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW01",
            tif=TIF.GTC,
            price=100.0,
        )
        bad = o.to_dict()
        bad["side"] = "SIDEWAYS"
        path = tmp_path / "gtc.json"
        path.write_text(json.dumps([bad]))
        with caplog.at_level(logging.CRITICAL, logger="edumatcher.engine.persistence"):
            load_gtc_orders(path)
        assert any(
            "CRITICAL" in rec.levelname and "SIDEWAYS" in rec.message
            for rec in caplog.records
        ), "corrupt entry must be logged at CRITICAL with the offending value"

    def test_valid_orders_preserved_when_mixed_with_corrupt(
        self, tmp_path: Path
    ) -> None:
        """Valid entries must be returned even when the file also contains
        corrupt entries.  This is the key behavioural contract introduced
        to prevent a single bad order from blocking engine startup."""
        good1 = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW01",
            tif=TIF.GTC,
            price=100.0,
        )
        bad = good1.to_dict()
        bad["id"] = "corrupt-order"
        bad["side"] = "SIDEWAYS"
        good2 = Order.create(
            symbol="AAPL",
            side=Side.SELL,
            order_type=OrderType.LIMIT,
            quantity=5,
            gateway_id="GW01",
            tif=TIF.GTC,
            price=110.0,
        )
        path = tmp_path / "gtc.json"
        path.write_text(json.dumps([good1.to_dict(), bad, good2.to_dict()]))
        loaded = load_gtc_orders(path)
        loaded_ids = {o.id for o in loaded}
        assert len(loaded) == 2
        assert good1.id in loaded_ids
        assert good2.id in loaded_ids
        assert "corrupt-order" not in loaded_ids

    def test_binary_garbage_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "gtc.json"
        path.write_bytes(b"\x00\xff\xfe\xde\xad\xbe\xef")
        assert load_gtc_orders(path) == []

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "gtc.json"
        path.write_text("")
        assert load_gtc_orders(path) == []

    def test_missing_required_key_returns_empty(self, tmp_path: Path) -> None:
        """A file containing only one order with a missing required key
        returns an empty list (the single entry is skipped)."""
        o = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW01",
            tif=TIF.GTC,
            price=100.0,
        )
        bad = o.to_dict()
        del bad["id"]
        path = tmp_path / "gtc.json"
        path.write_text(json.dumps([bad]))
        assert load_gtc_orders(path) == []

    def test_nonexistent_file_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "does_not_exist.json"
        assert load_gtc_orders(path) == []

    def test_valid_gtc_file_is_loaded_correctly(self, tmp_path: Path) -> None:
        """Sanity-check: a well-formed file must still load properly."""
        o = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW01",
            tif=TIF.GTC,
            price=100.0,
        )
        o.status = OrderStatus.NEW
        path = tmp_path / "gtc.json"
        path.write_text(json.dumps([o.to_dict()]))
        loaded = load_gtc_orders(path)
        assert len(loaded) == 1
        assert loaded[0].symbol == "AAPL"


# ===========================================================================
# Test 22b — Engine startup with corrupt GTC file (integration)
# ===========================================================================


def _make_engine_with_gtc_file(
    monkeypatch,
    tmp_path: Path,
    gtc_path: Path,
    symbols: tuple = ("AAPL",),
    gateways: tuple = ("GW01",),
) -> tuple[Engine, _FakeSock]:
    """Like _make_engine but uses the real load_gtc_orders against *gtc_path*.

    GTC_ORDERS_FILE is patched to *gtc_path*; GTC_COMBOS_FILE is pointed at a
    non-existent temp path so the real load_gtc_combos returns [] without
    touching the live filesystem.  _restore_gtc() is called explicitly after
    construction because the engine only calls it from run().
    """
    pull_sock = _FakeSock(sent=[])
    pub_sock = _FakeSock(sent=[])

    cfg = EngineConfig(
        symbols={s: SymbolConfig(name=s) for s in symbols},
        fix_gateways={g: FixGatewayConfig(id=g, description=g) for g in gateways},
    )
    monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
    monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
    monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
    monkeypatch.setattr("edumatcher.engine.main.GTC_ORDERS_FILE", gtc_path)
    monkeypatch.setattr(
        "edumatcher.engine.main.GTC_COMBOS_FILE", tmp_path / "gtc_combos.json"
    )
    monkeypatch.setattr("edumatcher.engine.main.save_gtc_orders", lambda *_: None)
    monkeypatch.setattr("edumatcher.engine.main.save_gtc_combos", lambda *_: None)
    monkeypatch.setattr("edumatcher.engine.main.save_book_stats", lambda *_: None)
    monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)

    cfg_path = tmp_path / "engine_config.yaml"
    cfg_path.write_text("dummy: true\n")
    engine = Engine(config_path=str(cfg_path))
    # _restore_gtc is normally called from run(); invoke it directly here so
    # tests exercise the full startup GTC-load path without a main loop.
    engine._restore_gtc()
    return engine, pub_sock


class TestEngineStartupWithCorruptGTCFile:
    """Engine must start cleanly and remain fully operational when the GTC
    orders file on disk is corrupt — the real load_gtc_orders is exercised."""

    def test_starts_with_truncated_json(self, monkeypatch, tmp_path: Path) -> None:
        gtc = tmp_path / "gtc.json"
        gtc.write_text('[{"id": "x", "sym')
        engine, _ = _make_engine_with_gtc_file(monkeypatch, tmp_path, gtc)
        assert len(engine._order_symbol) == 0

    def test_starts_with_binary_garbage(self, monkeypatch, tmp_path: Path) -> None:
        gtc = tmp_path / "gtc.json"
        gtc.write_bytes(b"\x00\xff\xfe\xde\xad\xbe\xef")
        engine, _ = _make_engine_with_gtc_file(monkeypatch, tmp_path, gtc)
        assert len(engine._order_symbol) == 0

    def test_starts_with_wrong_root_type(self, monkeypatch, tmp_path: Path) -> None:
        gtc = tmp_path / "gtc.json"
        gtc.write_text('{"not": "a list"}')
        engine, _ = _make_engine_with_gtc_file(monkeypatch, tmp_path, gtc)
        assert len(engine._order_symbol) == 0

    def test_starts_with_empty_file(self, monkeypatch, tmp_path: Path) -> None:
        gtc = tmp_path / "gtc.json"
        gtc.write_text("")
        engine, _ = _make_engine_with_gtc_file(monkeypatch, tmp_path, gtc)
        assert len(engine._order_symbol) == 0

    def test_corrupt_order_skipped_valid_order_restored(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        """A single corrupt order in a file must be skipped; the good order
        that precedes it must still be restored to the engine."""
        good = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW01",
            tif=TIF.GTC,
            price=100.0,
        )
        bad = good.to_dict()
        bad["id"] = "corrupt-order"
        bad["side"] = "SIDEWAYS"
        gtc = tmp_path / "gtc.json"
        gtc.write_text(json.dumps([good.to_dict(), bad]))
        engine, _ = _make_engine_with_gtc_file(monkeypatch, tmp_path, gtc)
        assert good.id in engine._order_symbol, "valid order must be restored"
        assert (
            "corrupt-order" not in engine._order_symbol
        ), "corrupt order must be skipped"
        assert len(engine._order_symbol) == 1

    def test_is_operational_after_corrupt_load(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        """Engine must accept new orders normally after a corrupt GTC load."""
        gtc = tmp_path / "gtc.json"
        gtc.write_text("NOT JSON AT ALL")
        engine, pub_sock = _make_engine_with_gtc_file(monkeypatch, tmp_path, gtc)
        _connect(engine)
        engine._handle_new_order(_make_order_payload())
        ack = _last_ack(pub_sock)
        assert ack.get("accepted") is True

    def test_restores_valid_gtc_orders(self, monkeypatch, tmp_path: Path) -> None:
        """Positive case: a well-formed GTC file populates the order book."""
        o = Order.create(
            symbol="AAPL",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=50,
            gateway_id="GW01",
            tif=TIF.GTC,
            price=99.0,
        )
        o.status = OrderStatus.NEW
        gtc = tmp_path / "gtc.json"
        gtc.write_text(json.dumps([o.to_dict()]))
        engine, _ = _make_engine_with_gtc_file(monkeypatch, tmp_path, gtc)
        assert o.id in engine._order_symbol
        assert engine._order_symbol[o.id] == "AAPL"

    def test_skips_gtc_order_for_symbol_not_in_config(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        """GTC order for a symbol removed from config must be silently skipped."""
        o = Order.create(
            symbol="GONE",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW01",
            tif=TIF.GTC,
            price=50.0,
        )
        o.status = OrderStatus.NEW
        gtc = tmp_path / "gtc.json"
        gtc.write_text(json.dumps([o.to_dict()]))
        engine, _ = _make_engine_with_gtc_file(
            monkeypatch, tmp_path, gtc, symbols=("AAPL",)
        )
        assert o.id not in engine._order_symbol


# ===========================================================================
# Test 23 — Session state corruption / invalid transitions
# ===========================================================================


class TestSessionStateCorruption:
    """Invalid session transitions must be silently ignored."""

    def test_garbage_to_state_is_ignored(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        before = engine._session_state
        engine._handle_session_transition({"to_state": "GARBAGE_STATE"})
        assert engine._session_state == before

    def test_empty_to_state_is_ignored(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        before = engine._session_state
        engine._handle_session_transition({"to_state": ""})
        assert engine._session_state == before

    def test_invalid_transition_continuous_to_pre_open_is_ignored(
        self, monkeypatch, tmp_path
    ) -> None:
        """CONTINUOUS -> PRE_OPEN is not a valid transition."""
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        engine._session_state = SessionState.CONTINUOUS
        engine._handle_session_transition({"to_state": "PRE_OPEN"})
        assert engine._session_state == SessionState.CONTINUOUS

    def test_invalid_transition_closed_to_continuous_is_ignored(
        self, monkeypatch, tmp_path
    ) -> None:
        """CLOSED -> CONTINUOUS is not a valid transition."""
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        assert engine._session_state == SessionState.CLOSED
        engine._handle_session_transition({"to_state": "CONTINUOUS"})
        assert engine._session_state == SessionState.CLOSED

    def test_duplicate_transition_to_same_state_does_not_raise(
        self, monkeypatch, tmp_path
    ) -> None:
        """Transitioning to CLOSING_AUCTION twice must not raise."""
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        engine._session_state = SessionState.CONTINUOUS
        engine._handle_session_transition({"to_state": "CLOSING_AUCTION"})
        assert engine._session_state == SessionState.CLOSING_AUCTION
        # Second identical transition — silently ignored
        engine._handle_session_transition({"to_state": "CLOSING_AUCTION"})
        assert engine._session_state == SessionState.CLOSING_AUCTION

    def test_transitions_disabled_when_sessions_not_enabled(
        self, monkeypatch, tmp_path
    ) -> None:
        """When sessions are disabled all transitions are no-ops."""
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=False)
        engine._session_state = SessionState.CONTINUOUS
        engine._handle_session_transition({"to_state": "CLOSED"})
        assert engine._session_state == SessionState.CONTINUOUS

    def test_missing_to_state_key_does_not_raise(self, monkeypatch, tmp_path) -> None:
        """Payload without 'to_state' must not crash the engine."""
        engine, pub_sock = _make_engine(monkeypatch, tmp_path, sessions_enabled=True)
        before = engine._session_state
        try:
            engine._handle_session_transition({})
        except (KeyError, AttributeError):
            pytest.fail("_handle_session_transition() must not raise on missing key")
        assert engine._session_state == before


# ===========================================================================
# Test 24 — Order ID collisions
# ===========================================================================


class TestOrderIdCollisions:
    """Duplicate order IDs must not crash the engine."""

    def test_duplicate_order_id_does_not_raise(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        payload = _make_order_payload()
        engine._handle_new_order(payload)
        try:
            engine._handle_new_order(payload)
        except Exception as exc:
            pytest.fail(f"Engine raised on duplicate order id: {exc}")

    def test_engine_remains_operational_after_duplicate(
        self, monkeypatch, tmp_path
    ) -> None:
        """After a duplicate submission the engine must still accept fresh orders."""
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        payload = _make_order_payload(price=100.0, qty=50)
        engine._handle_new_order(payload)
        engine._handle_new_order(payload)  # duplicate

        pub_sock.sent.clear()
        engine._handle_new_order(_make_order_payload(price=101.0, qty=10))
        ack = _last_ack(pub_sock)
        assert ack.get("accepted") is True

    def test_order_symbol_map_does_not_grow_on_duplicate(
        self, monkeypatch, tmp_path
    ) -> None:
        """_order_symbol must not grow a second entry for the same order id."""
        engine, pub_sock = _make_engine(monkeypatch, tmp_path)
        _connect(engine)
        payload = _make_order_payload()
        engine._handle_new_order(payload)
        size_after_first = len(engine._order_symbol)
        engine._handle_new_order(payload)
        assert len(engine._order_symbol) == size_after_first


# ===========================================================================
# Test 25 — Engine startup without a config file
# ===========================================================================


class TestEngineStartupWithoutConfig:
    """No-config engine runs in backward-compat mode with no restrictions."""

    def _make_no_config_engine(self, monkeypatch) -> tuple[Engine, _FakeSock]:
        pull_sock = _FakeSock(sent=[])
        pub_sock = _FakeSock(sent=[])
        monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: pull_sock)
        monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
        monkeypatch.setattr("edumatcher.engine.main.save_gtc_orders", lambda *_: None)
        monkeypatch.setattr("edumatcher.engine.main.save_gtc_combos", lambda *_: None)
        monkeypatch.setattr("edumatcher.engine.main.save_book_stats", lambda *_: None)
        monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)
        engine = Engine(config_path="/tmp/_nonexistent_edumatcher_config_.yaml")
        return engine, pub_sock

    def test_starts_without_error(self, monkeypatch) -> None:
        engine, _ = self._make_no_config_engine(monkeypatch)
        assert engine._allowed_symbols is None
        assert engine._allowed_fix_gateways is None

    def test_accepts_any_gateway(self, monkeypatch) -> None:
        engine, _ = self._make_no_config_engine(monkeypatch)
        ok, reason = engine._gateway_status("ANYTHING")
        assert ok is True
        assert reason == ""

    def test_accepts_any_symbol(self, monkeypatch) -> None:
        """No allowlist means any symbol/gateway is accepted."""
        engine, pub_sock = self._make_no_config_engine(monkeypatch)
        o = Order.create(
            symbol="WHATEVER",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="ANY_GW",
            tif=TIF.DAY,
            price=50.0,
        )
        engine._handle_new_order(o.to_dict())
        ack = _last_ack(pub_sock)
        assert ack.get("accepted") is True

    def test_cancel_nonexistent_returns_rejection_not_crash(self, monkeypatch) -> None:
        engine, pub_sock = self._make_no_config_engine(monkeypatch)
        try:
            engine._handle_cancel({"order_id": "FAKE", "gateway_id": "GW01"})
        except Exception as exc:
            pytest.fail(f"_handle_cancel raised unexpectedly: {exc}")
        ack = _last_ack(pub_sock)
        assert ack.get("accepted") is False

    def test_shutdown_does_not_raise(self, monkeypatch) -> None:
        engine, _ = self._make_no_config_engine(monkeypatch)
        try:
            engine._shutdown()
        except Exception as exc:
            pytest.fail(f"_shutdown() raised on no-config engine: {exc}")
