"""
Tests for the pm-clearing v2 main process.

ZMQ strategy: real in-process sockets (inproc://) for integration tests.
The test creates a PUB socket, binds it to an inproc address, starts the
clearing process in a thread with a matching SUB socket, then publishes
trade messages and asserts the DB is updated correctly.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any, cast

import pytest
import zmq

from edumatcher.clearing.main import (
    ClearingProcess,
    _to_trade_event_row,
)
from edumatcher.clearing.store import (
    open_writer_connection,
    query_positions,
    query_session_events,
    query_sessions,
    query_trades,
)
from edumatcher.models.trade import Trade

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trade(
    trade_id: str,
    symbol: str = "AAPL",
    price: int = 1000,
    qty: int = 10,
    buy_gw: str = "GW_BUY",
    sell_gw: str = "GW_SELL",
) -> Trade:
    """Create a Trade with a fixed id (bypassing the counter)."""
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
    # Override the auto-generated id so tests can be deterministic.
    object.__setattr__(t, "id", trade_id)
    return t


def _encode_trade(trade: Trade) -> list[bytes]:
    """Encode a trade as a two-frame ZMQ message."""
    topic = b"trade.executed"
    payload = json.dumps(trade.to_dict()).encode()
    return [topic, payload]


class _InprocPublisher:
    """
    Thin wrapper that manages an inproc PUB socket for one test.

    Uses a unique address per test to avoid cross-test interference.
    """

    def __init__(self, addr: str) -> None:
        self._ctx = zmq.Context.instance()
        self._pub: zmq.Socket = self._ctx.socket(zmq.PUB)
        self._pub.bind(addr)

    def publish(self, trade: Trade) -> None:
        self._pub.send_multipart(_encode_trade(trade))

    def close(self) -> None:
        self._pub.close(linger=0)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "clearing_test.db"


@pytest.fixture()
def zmq_addr(request: pytest.FixtureRequest) -> str:
    """Unique inproc address per test to avoid socket reuse."""
    safe = request.node.nodeid.replace("/", "_").replace(":", "_").replace("::", "_")
    return f"inproc://test-{safe}"


# ---------------------------------------------------------------------------
# Unit tests: _to_trade_event_row
# ---------------------------------------------------------------------------


class TestToTradeEventRow:
    def test_fields_populated(self) -> None:
        trade = _make_trade("T1", symbol="AAPL", price=500, qty=20)
        row = _to_trade_event_row(trade, ingest_ts_ns=42)

        assert row.id == "T1"
        assert row.symbol == "AAPL"
        assert row.price == 500
        assert row.quantity == 20
        assert row.ingest_ts_ns == 42
        assert row.buy_gateway_id == "GW_BUY"
        assert row.sell_gateway_id == "GW_SELL"
        assert row.trade_date != ""  # should be a YYYY-MM-DD string

    def test_trade_date_format(self) -> None:
        trade = _make_trade("T2")
        row = _to_trade_event_row(trade, ingest_ts_ns=1)
        import re

        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", row.trade_date)

    def test_empty_order_ids_become_none(self) -> None:
        t = Trade.create(
            symbol="MSFT",
            buy_order_id="",
            sell_order_id="",
            buy_gateway_id="GW_A",
            sell_gateway_id="GW_B",
            price=100,
            quantity=5,
            aggressor_side="SELL",
        )
        row = _to_trade_event_row(t, ingest_ts_ns=1)
        assert row.buy_order_id is None
        assert row.sell_order_id is None


# ---------------------------------------------------------------------------
# Integration tests: ClearingProcess with real inproc ZMQ
# ---------------------------------------------------------------------------


class TestClearingProcessIntegration:
    """
    Integration tests using real inproc:// ZMQ sockets.

    Pattern for each test:
    1. Bind a PUB socket to an inproc address.
    2. Create ClearingProcess (not yet running).
    3. Start process.run() in a daemon thread so the SUB connects.
    4. Sleep briefly to allow the SUB socket to connect to the PUB.
    5. Publish trade messages.
    6. Sleep briefly for receive + flush.
    7. Stop process and join thread.
    8. Assert DB state.
    """

    @staticmethod
    def _start(process: ClearingProcess) -> threading.Thread:
        t = threading.Thread(target=process.run, daemon=True)
        t.start()
        return t

    @staticmethod
    def _stop(process: ClearingProcess, thread: threading.Thread) -> None:
        process.stop()
        thread.join(timeout=3.0)

    def test_single_trade_appears_in_db(self, db_path: Path, zmq_addr: str) -> None:
        pub = _InprocPublisher(zmq_addr)
        process = ClearingProcess(
            pub_addr=zmq_addr,
            db_path=db_path,
            flush_size=1,
            flush_interval_sec=10.0,
            print_every=0,
            retention_days=3650,
        )
        t = self._start(process)
        time.sleep(0.2)  # allow SUB to connect

        pub.publish(_make_trade("T-SINGLE"))
        time.sleep(0.3)

        self._stop(process, t)
        pub.close()

        conn = open_writer_connection(db_path)
        ids = [r["id"] for r in query_trades(conn)]
        conn.close()
        assert "T-SINGLE" in ids

    def test_multiple_trades_flush_on_size(self, db_path: Path, zmq_addr: str) -> None:
        pub = _InprocPublisher(zmq_addr)
        process = ClearingProcess(
            pub_addr=zmq_addr,
            db_path=db_path,
            flush_size=3,
            flush_interval_sec=10.0,
            print_every=0,
            retention_days=3650,
        )
        t = self._start(process)
        time.sleep(0.2)

        for i in range(3):
            pub.publish(_make_trade(f"T-{i}"))
        time.sleep(0.3)

        self._stop(process, t)
        pub.close()

        conn = open_writer_connection(db_path)
        count = conn.execute("SELECT COUNT(*) FROM trade_events").fetchone()[0]
        conn.close()
        assert count == 3

    def test_positions_updated_after_flush(self, db_path: Path, zmq_addr: str) -> None:
        pub = _InprocPublisher(zmq_addr)
        process = ClearingProcess(
            pub_addr=zmq_addr,
            db_path=db_path,
            flush_size=1,
            flush_interval_sec=10.0,
            print_every=0,
            retention_days=3650,
        )
        t = self._start(process)
        time.sleep(0.2)

        pub.publish(_make_trade("T-POS", price=100, qty=50))
        time.sleep(0.3)

        self._stop(process, t)
        pub.close()

        conn = open_writer_connection(db_path)
        rows = query_positions(conn, gateway="GW_BUY")
        conn.close()
        assert len(rows) == 1
        assert rows[0]["net_qty"] == 50

    def test_flush_now_writes_buffer(self, db_path: Path, zmq_addr: str) -> None:
        pub = _InprocPublisher(zmq_addr)
        process = ClearingProcess(
            pub_addr=zmq_addr,
            db_path=db_path,
            flush_size=100,
            flush_interval_sec=60.0,
            print_every=0,
            retention_days=3650,
        )
        t = self._start(process)
        time.sleep(0.2)

        pub.publish(_make_trade("T-MANUAL"))
        time.sleep(0.1)

        # flush_now is thread-safe; the trade may already be in the buffer.
        process.flush_now()

        self._stop(process, t)
        pub.close()

        conn = open_writer_connection(db_path)
        count = conn.execute("SELECT COUNT(*) FROM trade_events").fetchone()[0]
        conn.close()
        assert count >= 1

    def test_malformed_message_does_not_crash(
        self, db_path: Path, zmq_addr: str
    ) -> None:
        """Garbage bytes should be logged and skipped, not crash the process."""
        ctx = zmq.Context.instance()
        pub: zmq.Socket = ctx.socket(zmq.PUB)
        pub.bind(zmq_addr)

        process = ClearingProcess(
            pub_addr=zmq_addr,
            db_path=db_path,
            flush_size=1,
            flush_interval_sec=10.0,
            print_every=0,
            retention_days=3650,
        )
        t = self._start(process)
        time.sleep(0.2)

        pub.send_multipart([b"trade.executed", b"NOT_JSON_{{{"])
        time.sleep(0.2)

        self._stop(process, t)
        pub.close(linger=0)

        assert db_path.exists()

    def test_duplicate_trade_not_inserted_twice(
        self, db_path: Path, zmq_addr: str
    ) -> None:
        pub = _InprocPublisher(zmq_addr)
        process = ClearingProcess(
            pub_addr=zmq_addr,
            db_path=db_path,
            flush_size=1,
            flush_interval_sec=10.0,
            print_every=0,
            retention_days=3650,
        )
        t = self._start(process)
        time.sleep(0.2)

        trade = _make_trade("T-DUPE")
        pub.publish(trade)
        time.sleep(0.15)
        pub.publish(trade)
        time.sleep(0.2)

        self._stop(process, t)
        pub.close()

        conn = open_writer_connection(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM trade_events WHERE id = 'T-DUPE'"
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_db_survives_restart(self, db_path: Path, zmq_addr: str) -> None:
        """Data written in first run should still be present on re-open."""
        pub = _InprocPublisher(zmq_addr)
        process = ClearingProcess(
            pub_addr=zmq_addr,
            db_path=db_path,
            flush_size=1,
            flush_interval_sec=10.0,
            print_every=0,
            retention_days=3650,
        )
        t = self._start(process)
        time.sleep(0.2)

        pub.publish(_make_trade("T-PERSIST", price=200, qty=30))
        time.sleep(0.3)

        self._stop(process, t)
        pub.close()

        conn = open_writer_connection(db_path)
        rows = query_trades(conn)
        conn.close()
        assert any(r["id"] == "T-PERSIST" for r in rows)


class TestClearingMainCli:
    def test_flush_size_validation(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from edumatcher.clearing.main import main

        monkeypatch.setattr(
            "sys.argv",
            ["pm-clearing", "--flush-size", "0"],
        )
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2

    def test_flush_interval_validation(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from edumatcher.clearing.main import main

        monkeypatch.setattr(
            "sys.argv",
            ["pm-clearing", "--flush-interval", "0.0"],
        )
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2

    def test_version_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from edumatcher.clearing.main import main

        monkeypatch.setattr("sys.argv", ["pm-clearing", "--version"])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0


class TestHandleEod:
    """Unit tests for ClearingProcess._handle_eod."""

    @pytest.fixture()
    def process(
        self, db_path: Path, zmq_addr: str
    ) -> Generator[ClearingProcess, None, None]:
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

    def test_eod_writes_session_event(
        self, process: ClearingProcess, db_path: Path
    ) -> None:
        """EOD handler with last_trade_price should write an EOD session_events row."""
        payload = {
            "books": [
                {
                    "symbol": "AAPL",
                    "last_trade_price": 15000,
                    "best_bid": 14900,
                    "best_ask": 15100,
                }
            ]
        }
        process._handle_eod(payload)
        conn = open_writer_connection(db_path)
        rows = query_session_events(conn, event_type="EOD")
        conn.close()
        assert len(rows) == 1
        assert rows[0]["event_type"] == "EOD"

    def test_eod_uses_bid_ask_mid_when_no_last_trade(
        self, process: ClearingProcess, db_path: Path
    ) -> None:
        """When last_trade_price is absent, mid = (bid+ask)//2 is used."""
        import json

        payload = {"books": [{"symbol": "MSFT", "best_bid": 4000, "best_ask": 4100}]}
        process._handle_eod(payload)
        conn = open_writer_connection(db_path)
        rows = query_session_events(conn, event_type="EOD")
        conn.close()
        assert len(rows) == 1
        data = json.loads(rows[0]["payload_json"])
        # mid = (4000+4100)//2 = 4050
        assert data["eod_marks"].get("MSFT") == 4050

    def test_eod_empty_books_still_writes_sentinel(
        self, process: ClearingProcess, db_path: Path
    ) -> None:
        """EOD with no books still writes the sentinel row."""
        process._handle_eod({"books": []})
        conn = open_writer_connection(db_path)
        rows = query_session_events(conn, event_type="EOD")
        conn.close()
        assert len(rows) == 1

    def test_eod_applies_mark_to_existing_position(
        self, process: ClearingProcess, db_path: Path
    ) -> None:
        """EOD should update mark_price in the ledger for open positions."""
        # Manually create a position in the ledger.
        process._ledger.apply_trade(
            symbol="AAPL",
            buy_gateway_id="GW_BUY",
            sell_gateway_id="GW_SELL",
            price=10000,
            tick_decimals=2,
            quantity=10,
            ts_ns=1_000_000,
            ingest_ts_ns=1_000_001,
        )
        process._handle_eod({"books": [{"symbol": "AAPL", "last_trade_price": 12000}]})
        pos = process._ledger.position("GW_BUY", "AAPL")
        assert pos is not None
        assert pos.mark_price == 12000

    def test_eod_does_not_raise_on_bad_payload(self, process: ClearingProcess) -> None:
        """Malformed payload should be silently absorbed, not crash."""
        process._handle_eod(cast(dict[str, Any], None))


class TestHandleGatewayConnect:
    @pytest.fixture()
    def process(
        self, db_path: Path, zmq_addr: str
    ) -> Generator[ClearingProcess, None, None]:
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

    def test_connect_records_row(self, process: ClearingProcess, db_path: Path) -> None:
        process._handle_gateway_connect({"gateway_id": "TRD01"})
        conn = open_writer_connection(db_path)
        rows = query_sessions(conn, gateway="TRD01")
        conn.close()
        assert len(rows) == 1
        assert rows[0]["disconnected_at_ns"] is None

    def test_connect_stores_ts_in_gw_connect_dict(
        self, process: ClearingProcess
    ) -> None:
        process._handle_gateway_connect({"gateway_id": "TRD02"})
        assert "TRD02" in process._gw_connect_ts

    def test_empty_gateway_id_is_ignored(
        self, process: ClearingProcess, db_path: Path
    ) -> None:
        process._handle_gateway_connect({"gateway_id": ""})
        conn = open_writer_connection(db_path)
        count = conn.execute("SELECT COUNT(*) FROM gateway_sessions").fetchone()[0]
        conn.close()
        assert count == 0

    def test_uppercase_normalisation(self, process: ClearingProcess) -> None:
        process._handle_gateway_connect({"gateway_id": "trader01"})  # lowercase
        assert "TRADER01" in process._gw_connect_ts


class TestHandleGatewayDisconnect:
    @pytest.fixture()
    def process(
        self, db_path: Path, zmq_addr: str
    ) -> Generator[ClearingProcess, None, None]:
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

    def test_disconnect_updates_row(
        self, process: ClearingProcess, db_path: Path
    ) -> None:
        process._handle_gateway_connect({"gateway_id": "GW_D"})
        process._handle_gateway_disconnect({"gateway_id": "GW_D", "reason": "Timeout"})
        conn = open_writer_connection(db_path)
        rows = query_sessions(conn, gateway="GW_D")
        conn.close()
        assert len(rows) == 1
        assert rows[0]["disconnected_at_ns"] is not None
        assert rows[0]["disconnect_reason"] == "Timeout"

    def test_disconnect_removes_from_connect_dict(
        self, process: ClearingProcess
    ) -> None:
        process._handle_gateway_connect({"gateway_id": "GW_E"})
        process._handle_gateway_disconnect({"gateway_id": "GW_E"})
        assert "GW_E" not in process._gw_connect_ts

    def test_disconnect_without_prior_connect_is_ignored(
        self, process: ClearingProcess
    ) -> None:
        """Disconnect with no matching connect_ts should not raise."""
        process._handle_gateway_disconnect({"gateway_id": "UNKNOWN"})

    def test_retention_days_prunes_old_rows(self, db_path: Path, zmq_addr: str) -> None:
        """retention_days=1 should prune a row from year 2000."""
        conn = open_writer_connection(db_path)
        conn.execute(
            "INSERT INTO trade_events VALUES ('OLD',1,'2000-01-01','AAPL',1,100,2,null,null,'GW1','GW2',null,2)"
        )
        conn.commit()
        conn.close()

        p = ClearingProcess(
            pub_addr=zmq_addr,
            db_path=db_path,
            flush_size=100,
            flush_interval_sec=60.0,
            print_every=0,
            retention_days=1,
        )
        from edumatcher.clearing.store import prune_old_events

        deleted = prune_old_events(p._conn, retention_days=1)
        p._conn.close()
        assert deleted == 1
