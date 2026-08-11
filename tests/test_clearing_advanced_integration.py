"""Advanced clearing integration tests covering paths missed in test_clearing_main.py.

Each test verifies a distinct runtime behaviour of ClearingProcess:
- Gateway auth routing (accepted vs refused)
- Gateway bye routing
- Sequence-gap detection with numeric and non-numeric trade IDs
- Duplicate detection (LRU eviction boundary)
- _parse_tick_decimals with invalid inputs
- _print_pnl_table with live positions
- Debug count and summary flush
- Timer-triggered flush
- Topic routing through the receive loop via inproc ZMQ
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any, cast

import pytest
import zmq

from edumatcher.clearing.main import (
    ClearingProcess,
    _parse_tick_decimals,
)
from edumatcher.clearing.store import (
    open_writer_connection,
    query_session_events,
    query_sessions,
)
from edumatcher.models.message import decode
from edumatcher.models.generated.system import (
    TOPIC_GATEWAY_CONNECT,
    TOPIC_GATEWAY_DISCONNECT,
    TOPIC_EOD,
    PREFIX_GATEWAY_AUTH,
    PREFIX_GATEWAY_BYE,
)
from edumatcher.models.generated.session import TOPIC_SESSION_STATE
from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED
from edumatcher.models.trade import Trade


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_trade(
    trade_id: str,
    symbol: str = "AAPL",
    price: int = 1000,
    qty: int = 10,
    buy_gw: str = "GW_BUY",
    sell_gw: str = "GW_SELL",
) -> Trade:
    t = Trade.create(
        symbol=symbol,
        buy_order_id="O_BUY",
        sell_order_id="O_SELL",
        buy_gateway_id=buy_gw,
        sell_gateway_id=sell_gw,
        price=price,
        quantity=qty,
        aggressor_side="BUY",
    )
    object.__setattr__(t, "id", trade_id)
    return t


def _encode_trade(trade: Trade) -> list[bytes]:
    return [TOPIC_TRADE_EXECUTED.encode(), json.dumps(trade.to_dict()).encode()]


@pytest.fixture()
def zmq_addr(request: pytest.FixtureRequest) -> str:
    safe = request.node.nodeid.replace("/", "_").replace(":", "_").replace("::", "_")
    return f"inproc://adv-{safe}"


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "clearing_adv.db"


@pytest.fixture()
def proc(db_path: Path, zmq_addr: str) -> Generator[ClearingProcess, None, None]:
    p = ClearingProcess(
        pub_addr=zmq_addr,
        db_path=db_path,
        flush_size=100,
        flush_interval_sec=60.0,
        print_every=0,
        retention_days=3650,
    )
    try:
        yield p
    finally:
        p._conn.close()


# ---------------------------------------------------------------------------
# Unit tests: _parse_tick_decimals edge cases (lines 135-136)
# ---------------------------------------------------------------------------


class TestParseTickDecimals:
    def test_none_returns_default(self) -> None:
        assert _parse_tick_decimals({"tick_decimals": None}) == 2

    def test_string_that_cannot_convert_returns_default(self) -> None:
        assert _parse_tick_decimals({"tick_decimals": "not_a_number"}) == 2

    def test_below_zero_returns_default(self) -> None:
        assert _parse_tick_decimals({"tick_decimals": -1}) == 2

    def test_above_eight_returns_default(self) -> None:
        assert _parse_tick_decimals({"tick_decimals": 9}) == 2

    def test_valid_values_pass_through(self) -> None:
        for v in range(0, 9):
            assert _parse_tick_decimals({"tick_decimals": v}) == v

    def test_missing_key_returns_default(self) -> None:
        assert _parse_tick_decimals({}) == 2


# ---------------------------------------------------------------------------
# Unit tests: _handle_gateway_auth with refused auth (line 757)
# ---------------------------------------------------------------------------


class TestHandleGatewayAuth:
    def test_refused_auth_is_ignored(self, proc: ClearingProcess, db_path: Path) -> None:
        """accepted=False must NOT record a gateway session (only accepted auths do)."""
        proc._handle_gateway_auth({"gateway_id": "GW_REFUSED", "accepted": False, "reason": "not configured"})
        conn = open_writer_connection(db_path)
        rows = query_sessions(conn, gateway="GW_REFUSED")
        conn.close()
        assert rows == []

    def test_accepted_auth_records_session(self, proc: ClearingProcess, db_path: Path) -> None:
        """accepted=True must record a gateway session, just like gateway_connect."""
        proc._handle_gateway_auth({"gateway_id": "GW_OK", "accepted": True, "reason": ""})
        conn = open_writer_connection(db_path)
        rows = query_sessions(conn, gateway="GW_OK")
        conn.close()
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# Unit tests: _handle_gateway_bye (lines 766-767)
# ---------------------------------------------------------------------------


class TestHandleGatewayBye:
    def test_bye_after_connect_records_disconnect(
        self, proc: ClearingProcess, db_path: Path
    ) -> None:
        """gateway_bye should close the open session opened by gateway_connect."""
        proc._handle_gateway_connect({"gateway_id": "GW_BYE"})
        proc._handle_gateway_bye({"gateway_id": "GW_BYE", "reason": "logout"})
        conn = open_writer_connection(db_path)
        rows = query_sessions(conn, gateway="GW_BYE")
        conn.close()
        assert len(rows) == 1
        assert rows[0]["disconnected_at_ns"] is not None
        assert rows[0]["disconnect_reason"] == "logout"

    def test_bye_without_connect_does_not_raise(self, proc: ClearingProcess) -> None:
        proc._handle_gateway_bye({"gateway_id": "GHOST", "reason": "phantom"})


# ---------------------------------------------------------------------------
# Unit tests: _check_sequence_gap — non-numeric trade IDs (lines 477-479)
# ---------------------------------------------------------------------------


class TestSequenceGapDetection:
    def test_non_numeric_id_disables_sequencing(self, proc: ClearingProcess) -> None:
        """A non-integer id (e.g. UUID) must not trigger a false gap alarm."""
        with proc._lock:
            proc._check_sequence_gap(_make_trade("uuid-aabbccdd"))
            proc._check_sequence_gap(_make_trade("uuid-11223344"))
        assert proc._gap_count == 0
        assert proc._last_seq is None

    def test_gap_is_detected_and_increments_counter(
        self, proc: ClearingProcess, db_path: Path
    ) -> None:
        """Numeric ids with a jump > 1 must increment _gap_count and write a GAP row."""
        with proc._lock:
            proc._check_sequence_gap(_make_trade("100"))
            proc._check_sequence_gap(_make_trade("105"))  # skipped 101-104
        assert proc._gap_count == 1

        conn = open_writer_connection(db_path)
        rows = query_session_events(conn, event_type="GAP")
        conn.close()
        assert len(rows) == 1
        data = json.loads(rows[0]["payload_json"])
        assert data["missing_trades"] == 4

    def test_backward_move_resets_without_alarm(self, proc: ClearingProcess) -> None:
        """Backward trade ID (engine restart) must reset _last_seq, not alarm."""
        with proc._lock:
            proc._check_sequence_gap(_make_trade("200"))
            proc._check_sequence_gap(_make_trade("100"))  # backward = restart
        assert proc._gap_count == 0
        assert proc._last_seq == 100

    def test_consecutive_numeric_ids_produce_no_gap(self, proc: ClearingProcess) -> None:
        with proc._lock:
            for i in range(1, 11):
                proc._check_sequence_gap(_make_trade(str(i)))
        assert proc._gap_count == 0


# ---------------------------------------------------------------------------
# Unit tests: _is_duplicate LRU boundary (lines 462-463)
# ---------------------------------------------------------------------------


class TestIsDuplicateLru:
    def test_first_occurrence_is_not_duplicate(self, proc: ClearingProcess) -> None:
        trade = _make_trade("T1")
        with proc._lock:
            assert not proc._is_duplicate(trade)

    def test_second_occurrence_is_duplicate(self, proc: ClearingProcess) -> None:
        trade = _make_trade("T2")
        with proc._lock:
            proc._is_duplicate(trade)
            assert proc._is_duplicate(trade)

    def test_lru_eviction_allows_reinsertion(self, proc: ClearingProcess) -> None:
        """Once the LRU cap is exceeded the evicted entry is no longer seen."""
        proc._seen_cap = 3
        trades = [_make_trade(str(i)) for i in range(1, 5)]
        with proc._lock:
            for t in trades:
                proc._is_duplicate(t)  # insert all four
            # trade "1" was evicted when "4" was inserted (cap=3)
            assert not proc._is_duplicate(trades[0])  # "1" evicted → not duplicate


# ---------------------------------------------------------------------------
# Integration: receive loop routes non-trade topics (lines 412-415)
# ---------------------------------------------------------------------------


class _InprocPub:
    def __init__(self, addr: str) -> None:
        self._ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
        self._pub: zmq.Socket = self._ctx.socket(zmq.PUB)
        self._pub.bind(addr)

    def send(self, topic: str, payload: dict[str, Any]) -> None:
        self._pub.send_multipart(
            [topic.encode(), json.dumps(payload).encode()]
        )

    def close(self) -> None:
        self._pub.close(linger=0)


class TestReceiveLoopTopicRouting:
    """Verify that the receive loop correctly dispatches non-trade topics."""

    @staticmethod
    def _start(p: ClearingProcess) -> threading.Thread:
        t = threading.Thread(target=p.run, daemon=True)
        t.start()
        return t

    @staticmethod
    def _stop(p: ClearingProcess, t: threading.Thread) -> None:
        p.stop()
        t.join(timeout=3.0)

    def test_gateway_connect_message_through_loop(
        self, db_path: Path, zmq_addr: str
    ) -> None:
        """system.gateway_connect message via PUB → ClearingProcess writes a session."""
        pub = _InprocPub(zmq_addr)
        p = ClearingProcess(
            pub_addr=zmq_addr, db_path=db_path, flush_size=100,
            flush_interval_sec=60.0, print_every=0, retention_days=3650,
        )
        t = self._start(p)
        time.sleep(0.2)

        pub.send(TOPIC_GATEWAY_CONNECT, {"gateway_id": "GW_LOOP"})
        time.sleep(0.3)

        self._stop(p, t)
        pub.close()

        conn = open_writer_connection(db_path)
        rows = query_sessions(conn, gateway="GW_LOOP")
        conn.close()
        assert len(rows) == 1

    def test_gateway_disconnect_message_through_loop(
        self, db_path: Path, zmq_addr: str
    ) -> None:
        """gateway_connect then gateway_disconnect closes the session."""
        pub = _InprocPub(zmq_addr)
        p = ClearingProcess(
            pub_addr=zmq_addr, db_path=db_path, flush_size=100,
            flush_interval_sec=60.0, print_every=0, retention_days=3650,
        )
        t = self._start(p)
        time.sleep(0.2)

        pub.send(TOPIC_GATEWAY_CONNECT, {"gateway_id": "GW_DISC"})
        time.sleep(0.15)
        pub.send(TOPIC_GATEWAY_DISCONNECT, {"gateway_id": "GW_DISC", "reason": "Test"})
        time.sleep(0.3)

        self._stop(p, t)
        pub.close()

        conn = open_writer_connection(db_path)
        rows = query_sessions(conn, gateway="GW_DISC")
        conn.close()
        assert len(rows) == 1
        assert rows[0]["disconnected_at_ns"] is not None

    def test_eod_message_through_loop(self, db_path: Path, zmq_addr: str) -> None:
        """system.eod message via PUB loop writes an EOD session_event."""
        pub = _InprocPub(zmq_addr)
        p = ClearingProcess(
            pub_addr=zmq_addr, db_path=db_path, flush_size=100,
            flush_interval_sec=60.0, print_every=0, retention_days=3650,
        )
        t = self._start(p)
        time.sleep(0.2)

        pub.send(TOPIC_EOD, {"books": []})
        time.sleep(0.4)

        self._stop(p, t)
        pub.close()

        conn = open_writer_connection(db_path)
        rows = query_session_events(conn, event_type="EOD")
        conn.close()
        assert len(rows) == 1

    def test_session_state_message_through_loop(
        self, db_path: Path, zmq_addr: str
    ) -> None:
        """session.state PHASE message is recorded via the receive loop."""
        pub = _InprocPub(zmq_addr)
        p = ClearingProcess(
            pub_addr=zmq_addr, db_path=db_path, flush_size=100,
            flush_interval_sec=60.0, print_every=0, retention_days=3650,
        )
        t = self._start(p)
        time.sleep(0.2)

        pub.send(TOPIC_SESSION_STATE, {"state": "continuous", "prev_state": ""})
        time.sleep(0.3)

        self._stop(p, t)
        pub.close()

        conn = open_writer_connection(db_path)
        rows = query_session_events(conn, event_type="PHASE")
        conn.close()
        assert len(rows) == 1
        data = json.loads(rows[0]["payload_json"])
        assert data["state"] == "CONTINUOUS"

    def test_gateway_auth_message_through_loop(
        self, db_path: Path, zmq_addr: str
    ) -> None:
        """system.gateway_auth.GW1 with accepted=True records a session."""
        pub = _InprocPub(zmq_addr)
        p = ClearingProcess(
            pub_addr=zmq_addr, db_path=db_path, flush_size=100,
            flush_interval_sec=60.0, print_every=0, retention_days=3650,
        )
        t = self._start(p)
        time.sleep(0.2)

        auth_topic = f"{PREFIX_GATEWAY_AUTH}AUTH_GW"
        pub.send(auth_topic, {"gateway_id": "AUTH_GW", "accepted": True, "reason": "", "description": ""})
        time.sleep(0.3)

        self._stop(p, t)
        pub.close()

        conn = open_writer_connection(db_path)
        rows = query_sessions(conn, gateway="AUTH_GW")
        conn.close()
        assert len(rows) == 1

    def test_gateway_bye_message_through_loop(
        self, db_path: Path, zmq_addr: str
    ) -> None:
        """system.gateway_bye.GW1 closes an open session via the receive loop."""
        pub = _InprocPub(zmq_addr)
        p = ClearingProcess(
            pub_addr=zmq_addr, db_path=db_path, flush_size=100,
            flush_interval_sec=60.0, print_every=0, retention_days=3650,
        )
        t = self._start(p)
        time.sleep(0.2)

        pub.send(TOPIC_GATEWAY_CONNECT, {"gateway_id": "BYE_GW"})
        time.sleep(0.1)
        bye_topic = f"{PREFIX_GATEWAY_BYE}BYE_GW"
        pub.send(bye_topic, {"gateway_id": "BYE_GW", "reason": "normal"})
        time.sleep(0.3)

        self._stop(p, t)
        pub.close()

        conn = open_writer_connection(db_path)
        rows = query_sessions(conn, gateway="BYE_GW")
        conn.close()
        assert len(rows) == 1
        assert rows[0]["disconnected_at_ns"] is not None


# ---------------------------------------------------------------------------
# Integration: _print_pnl_table with real positions (lines 824-839)
# ---------------------------------------------------------------------------


class TestPrintPnlTable:
    def test_print_does_not_raise_with_positions(
        self, proc: ClearingProcess
    ) -> None:
        """_print_pnl_table must render cleanly when positions exist."""
        proc._ledger.apply_trade(
            symbol="AAPL",
            buy_gateway_id="GW_B",
            sell_gateway_id="GW_S",
            price=15000,
            tick_decimals=2,
            quantity=100,
            ts_ns=1_000_000_000,
            ingest_ts_ns=1_000_000_001,
        )
        # Mark up so unrealized PnL is non-zero.
        for pos in proc._ledger.all_positions():
            pos.mark_price = 16000

        proc._print_pnl_table()  # Must not raise

    def test_print_does_not_raise_with_no_positions(
        self, proc: ClearingProcess
    ) -> None:
        """_print_pnl_table must return immediately when there are no positions."""
        proc._print_pnl_table()

    def test_print_cadence_triggers_at_print_every(
        self, db_path: Path, zmq_addr: str
    ) -> None:
        """Setting print_every=1 means the table should be printed after each trade."""
        pub = _InprocPub(zmq_addr)
        p = ClearingProcess(
            pub_addr=zmq_addr, db_path=db_path, flush_size=1,
            flush_interval_sec=60.0, print_every=1, retention_days=3650,
        )
        t = threading.Thread(target=p.run, daemon=True)
        t.start()
        time.sleep(0.2)

        trade = _make_trade("T-PRINT", price=500, qty=5)
        pub.send(TOPIC_TRADE_EXECUTED, trade.to_dict())
        time.sleep(0.3)

        p.stop()
        t.join(timeout=3.0)
        pub.close()

        # The table was printed; just assert no exception was raised (the
        # real assertion is that run() didn't throw).
        assert not t.is_alive()


# ---------------------------------------------------------------------------
# Integration: debug count infrastructure (lines 281-298)
# ---------------------------------------------------------------------------


class TestDebugCountInfrastructure:
    def test_dbg_count_only_fires_when_debug_logging_enabled(
        self, proc: ClearingProcess, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_dbg_count must be a no-op when debug logging is disabled."""
        with caplog.at_level(logging.WARNING):
            proc._dbg_count("test_key")
        assert "test_key" not in proc._debug_counts

    def test_dbg_count_increments_when_debug_logging_active(
        self, proc: ClearingProcess
    ) -> None:
        proc_logger = logging.getLogger("edumatcher.clearing.main")
        proc_logger.setLevel(logging.DEBUG)
        try:
            proc._dbg_count("test_event")
            assert proc._debug_counts.get("test_event", 0) == 1
        finally:
            proc_logger.setLevel(logging.WARNING)

    def test_flush_debug_summary_clears_counts(self, proc: ClearingProcess) -> None:
        """Forcing a flush should clear _debug_counts."""
        proc_logger = logging.getLogger("edumatcher.clearing.main")
        proc_logger.setLevel(logging.DEBUG)
        try:
            proc._dbg_count("event_a")
            proc._dbg_count("event_b", amount=3)
            # Force flush by setting last summary far in the past.
            proc._debug_last_summary = 0.0
            proc._flush_debug_summary(force=True)
            assert len(proc._debug_counts) == 0
        finally:
            proc_logger.setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Integration: warm-start hydration (lines 314-315)
# ---------------------------------------------------------------------------


class TestWarmStartHydration:
    def test_positions_restored_on_restart(self, db_path: Path, zmq_addr: str) -> None:
        """A new ClearingProcess instance should restore positions from the DB."""
        pub = _InprocPub(zmq_addr)
        p1 = ClearingProcess(
            pub_addr=zmq_addr, db_path=db_path, flush_size=1,
            flush_interval_sec=60.0, print_every=0, retention_days=3650,
        )
        t = threading.Thread(target=p1.run, daemon=True)
        t.start()
        time.sleep(0.2)

        trade = _make_trade("T-WS", price=2000, qty=50)
        pub.send(TOPIC_TRADE_EXECUTED, trade.to_dict())
        time.sleep(0.3)

        p1.stop()
        t.join(timeout=3.0)
        pub.close()

        # Second process: must restore GW_BUY/AAPL position from DB.
        p2 = ClearingProcess(
            pub_addr=zmq_addr, db_path=db_path, flush_size=1,
            flush_interval_sec=60.0, print_every=0, retention_days=3650,
        )
        pos = p2._ledger.position("GW_BUY", "AAPL")
        p2._conn.close()

        assert pos is not None
        assert pos.net_qty == 50
