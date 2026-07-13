"""
Regression tests for the CRITICAL and HIGH findings (CL-C1..C4, CL-H1..H4)
in docs-design/EduMatcher-Review-Clearing.md.

IMPORTANT: These tests encode the *correct* expected behaviour, so they are
EXPECTED TO FAIL until each finding is fixed.  Run them with:

    pytest tests/test_clearing_review_criticals_highs.py -v

Design principles (review §8, via tests/clearing_harness.py):
  * every payload is produced by the ENGINE'S OWN code (real Engine
    handlers, real make_*_msg builders, real book.snapshot()),
  * delivery goes through a real ZMQ PUB socket into a real running
    ClearingProcess — its own subscriptions, decode, dispatch, and flush
    pipeline are all in the loop,
  * assertions are about observable outcomes (what is durably in the DB /
    what the operator sees), never about which topic or code path carries
    the information — so any reasonable fix goes green without test edits.

Finding → test map
------------------
  CL-C1  trade-id collision across engine   TestCLC1EngineRestartArchive
         restarts silently drops trades
  CL-C2  EOD mark-to-market dead on arrival TestCLC2EodMarksApplied
  CL-C3  gateway sessions never recorded    TestCLC3GatewaySessionTracking
  CL-C4  clearing restart corrupts          TestCLC4ClearingRestartWarmStart
         positions (no warm start)
  CL-H1  feed gaps invisible                TestCLH1GapDetection
  CL-H2  cross-scale P&L totals             TestCLH2CrossScaleTotals
  CL-H3  avg_cost rendered in raw ticks     TestCLH3AvgCostDisplayConsistency
  CL-H4  reconcile blind to total raw loss  TestCLH4ReconcileCompleteness
"""

from __future__ import annotations

import itertools
import json
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from edumatcher.clearing.cli import _normalize_rows
from edumatcher.clearing.store import (
    query_gateways,
    query_positions,
    query_reconcile,
    query_sessions,
)
from edumatcher.engine.config_loader import SymbolConfig
from edumatcher.models.message import make_eod_msg
from edumatcher.models.order import OrderType, Side

from tests.clearing_harness import PROBE_GW, start_clearing
from tests.engine_harness import SYMBOL, connect, make_engine, order_payload


# ---------------------------------------------------------------------------
# Engine-flow helpers — all market activity goes through real Engine handlers.
# ---------------------------------------------------------------------------


def _cross(
    engine,
    *,
    buyer: str = "GW01",
    seller: str = "GW02",
    qty: int = 100,
    price: float = 150.0,
    symbol: str = SYMBOL,
) -> None:
    """One guaranteed trade: seller rests, buyer lifts."""
    engine._handle_new_order(
        order_payload(Side.SELL, OrderType.LIMIT, qty, seller, price=price, symbol=symbol)
    )
    engine._handle_new_order(
        order_payload(Side.BUY, OrderType.LIMIT, qty, buyer, price=price, symbol=symbol)
    )


def _new_engine(monkeypatch, tmp_path, run_name: str, **kw):
    run_dir = tmp_path / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    engine, pub = make_engine(monkeypatch, run_dir, **kw)
    connect(engine)
    return engine, pub


@contextmanager
def _rw(db_path) -> Iterator[sqlite3.Connection]:
    """Read/write connection that is actually CLOSED on exit.

    NB: ``with sqlite3.connect(...)`` alone only manages the transaction —
    it never closes the connection, which leaks a handle per call and
    triggers Python 3.13+ ``ResourceWarning: unclosed database``.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CL-C1 — no executed trade may ever vanish from the archive, engine
#          restarts included
# ---------------------------------------------------------------------------


class TestCLC1EngineRestartArchive:
    def test_trades_from_a_restarted_engine_are_all_archived(
        self, monkeypatch, tmp_path
    ) -> None:
        """Engine run 1 prints a trade; the engine restarts (its trade-id
        counter restarts with it — models/trade.py PERF #2); run 2 prints a
        DIFFERENT trade.  Clearing stayed up throughout.  Both executions
        must exist in trade_events and the archive must agree with the
        ledger — regardless of what the engine uses for trade ids."""
        cut = start_clearing(tmp_path / "clearing.db")
        try:
            # --- engine run 1 ---
            monkeypatch.setattr(
                "edumatcher.models.trade._trade_counter", itertools.count(1)
            )
            engine1, pub1 = _new_engine(monkeypatch, tmp_path, "run1")
            _cross(engine1, qty=50, price=150.0)
            cut.publish_engine_output(pub1.sent)

            # --- engine restart: fresh process, counter starts over ---
            monkeypatch.setattr(
                "edumatcher.models.trade._trade_counter", itertools.count(1)
            )
            engine2, pub2 = _new_engine(monkeypatch, tmp_path, "run2")
            _cross(engine2, qty=70, price=151.0)
            cut.publish_engine_output(pub2.sent)

            cut.wait_ingested()
            cut.flush()

            conn = cut.db()
            rows = conn.execute(
                "SELECT quantity, price FROM trade_events ORDER BY ingest_ts_ns"
            ).fetchall()
            quantities = sorted(r["quantity"] for r in rows)
            assert quantities == [50, 70], (
                f"CL-C1: archive holds {quantities} — a trade from the "
                f"restarted engine silently vanished (id collision + "
                f"INSERT OR IGNORE); every execution must be archived"
            )

            # Archive and ledger must tell the same story.
            archived_qty = sum(r["quantity"] for r in rows)
            buyer_buys = conn.execute(
                "SELECT buy_qty FROM gateway_symbol_positions"
                " WHERE gateway_id='GW01' AND symbol=?",
                (SYMBOL,),
            ).fetchone()["buy_qty"]
            assert archived_qty == buyer_buys == 120, (
                f"CL-C1: archive total {archived_qty} != ledger buy total "
                f"{buyer_buys} — the two records of the same session diverge"
            )
        finally:
            cut.stop()


# ---------------------------------------------------------------------------
# CL-C2 — the EOD broadcast must produce closing marks for traded symbols
# ---------------------------------------------------------------------------


class TestCLC2EodMarksApplied:
    def test_eod_broadcast_yields_marks_for_every_traded_symbol(
        self, monkeypatch, tmp_path
    ) -> None:
        """Build the system.eod message exactly as Engine._shutdown does
        (make_eod_msg over real book.snapshot() dicts) after a trade at
        150.75.  Clearing's EOD pass must extract a closing mark for the
        symbol — today the field names don't match and it extracts none."""
        engine, pub = _new_engine(monkeypatch, tmp_path, "run1")
        _cross(engine, qty=10, price=150.75)
        eod_frames = make_eod_msg(
            [book.snapshot() for book in engine.books.values()]
        )  # identical construction to engine/main.py _shutdown

        cut = start_clearing(tmp_path / "clearing.db")
        try:
            cut.publish_engine_output(pub.sent)
            cut.wait_ingested()
            cut.publish_frames([eod_frames])
            cut.fence()

            conn = cut.db()
            row = conn.execute(
                "SELECT payload_json FROM session_events"
                " WHERE event_type='EOD' ORDER BY ts_ns DESC LIMIT 1"
            ).fetchone()
            assert row is not None, "precondition: EOD sentinel row written"
            payload = json.loads(row["payload_json"])

            marks = payload.get("eod_marks") or {}
            assert SYMBOL in marks, (
                f"CL-C2: EOD broadcast for a symbol that traded produced NO "
                f"closing mark (eod_marks={marks}) — the handler's field "
                f"names have drifted from book.snapshot()"
            )
            # The mark_price column is INTEGER ticks (store.py schema):
            # 150.75 at 2 tick decimals must arrive as 15075 ticks.
            assert marks[SYMBOL] == 15075, (
                f"CL-C2: closing mark for {SYMBOL} is {marks[SYMBOL]} — "
                f"expected 15075 ticks (150.75); display-float truncation "
                f"or a unit mix-up corrupted the mark"
            )
        finally:
            cut.stop()


# ---------------------------------------------------------------------------
# CL-C3 — gateway connect/disconnect must reach the session history
# ---------------------------------------------------------------------------


class TestCLC3GatewaySessionTracking:
    def test_engine_side_gateway_connect_is_recorded(
        self, monkeypatch, tmp_path
    ) -> None:
        """A gateway performs the real connect handshake with the engine.
        Whatever the engine broadcasts as a consequence, clearing's
        gateway_sessions history must end up with a row for that gateway.
        Today the engine broadcasts system.gateway_auth.{id} while clearing
        listens for system.gateway_connect — so nothing is ever recorded."""
        engine, pub = _new_engine(monkeypatch, tmp_path, "run1", gateways=("GW77",))
        # connect() above already ran the real handshake for GW77 and the
        # engine published its broadcast(s) into pub.sent.

        cut = start_clearing(tmp_path / "clearing.db")
        try:
            cut.publish_engine_output(pub.sent)
            cut.fence()
            cut.flush()

            conn = cut.db()
            sessions = [
                s
                for s in query_sessions(conn)
                if not s["gateway_id"].startswith(PROBE_GW)
            ]
            assert any(s["gateway_id"] == "GW77" for s in sessions), (
                f"CL-C3: gateway GW77 completed the engine connect handshake "
                f"but clearing recorded no session (rows={sessions}) — the "
                f"lifecycle information never reaches the PUB topics clearing "
                f"consumes"
            )
        finally:
            cut.stop()


# ---------------------------------------------------------------------------
# CL-C4 — clearing must survive its own restart with positions intact
# ---------------------------------------------------------------------------


class TestCLC4ClearingRestartWarmStart:
    def test_positions_accumulate_across_a_clearing_restart(
        self, monkeypatch, tmp_path
    ) -> None:
        db_path = tmp_path / "clearing.db"
        engine, pub = _new_engine(monkeypatch, tmp_path, "run1")

        # --- clearing session 1: GW01 buys 100 @ 150.00 ---
        _cross(engine, qty=100, price=150.0)
        frames_day1 = list(pub.sent)
        cut1 = start_clearing(db_path)
        try:
            cut1.publish_engine_output(frames_day1)
            cut1.wait_ingested()
            cut1.flush()
        finally:
            cut1.stop()

        with _rw(db_path) as conn:
            net1 = conn.execute(
                "SELECT net_qty FROM gateway_symbol_positions"
                " WHERE gateway_id='GW01' AND symbol=?",
                (SYMBOL,),
            ).fetchone()["net_qty"]
        assert net1 == 100  # precondition: session 1 persisted correctly

        # --- clearing restarts; engine keeps running: GW01 buys 50 more ---
        _cross(engine, qty=50, price=151.0)
        frames_after = pub.sent[len(frames_day1):]
        cut2 = start_clearing(db_path)
        try:
            cut2.publish_engine_output(frames_after)
            cut2.wait_ingested()
            cut2.flush()
        finally:
            cut2.stop()

        with _rw(db_path) as conn:
            row = conn.execute(
                "SELECT net_qty, buy_qty, realized_pnl FROM"
                " gateway_symbol_positions WHERE gateway_id='GW01' AND symbol=?",
                (SYMBOL,),
            ).fetchone()
        assert row["net_qty"] == 150, (
            f"CL-C4: after a clearing restart, GW01's position is "
            f"{row['net_qty']} instead of 150 — the restarted process began "
            f"from flat and OVERWROTE the durable position state it was "
            f"supposed to protect (no warm start)"
        )
        assert row["buy_qty"] == 150, (
            f"CL-C4: cumulative buy_qty {row['buy_qty']} lost pre-restart "
            f"history"
        )


# ---------------------------------------------------------------------------
# CL-H1 — a feed gap must be delivered or detected, never silent
# ---------------------------------------------------------------------------


class TestCLH1GapDetection:
    def test_dropped_trade_is_recovered_or_flagged(
        self, monkeypatch, tmp_path
    ) -> None:
        """The engine prints three trades; the transport drops the middle
        one (exactly what ZMQ PUB/SUB does during a subscriber hiccup).
        A correct clearing process either ends up with all three trades
        (reliable/replayed transport) or leaves a durable gap alarm.
        Today it ends with two trades and no alarm — permanently wrong
        positions with zero operator signal."""
        engine, pub = _new_engine(monkeypatch, tmp_path, "run1")
        per_trade_frames: list[list[list[bytes]]] = []
        for qty in (10, 20, 30):
            before = len(pub.sent)
            _cross(engine, qty=qty, price=150.0)
            per_trade_frames.append(pub.sent[before:])

        cut = start_clearing(tmp_path / "clearing.db")
        try:
            cut.publish_engine_output(per_trade_frames[0])
            # per_trade_frames[1] is lost in transit
            cut.publish_engine_output(per_trade_frames[2])
            cut.wait_ingested()
            cut.fence()
            cut.flush()

            conn = cut.db()
            archived = conn.execute(
                "SELECT COUNT(*) AS c FROM trade_events"
            ).fetchone()["c"]
            gap_alarms = conn.execute(
                "SELECT COUNT(*) AS c FROM session_events"
                " WHERE event_type LIKE '%GAP%'"
            ).fetchone()["c"]
            assert archived == 3 or gap_alarms > 0, (
                f"CL-H1: transport dropped 1 of 3 trades; clearing archived "
                f"{archived} and raised {gap_alarms} gap alarms — a missed "
                f"trade must be recovered or loudly detected (sequence "
                f"numbers / replay), never silently absorbed"
            )
        finally:
            cut.stop()


# ---------------------------------------------------------------------------
# CL-H2 — P&L totals across symbols with different tick scales must be
#          expressed in currency, not raw ticks
# ---------------------------------------------------------------------------


class TestCLH2CrossScaleTotals:
    def test_gateway_pnl_total_is_currency_across_tick_scales(
        self, monkeypatch, tmp_path
    ) -> None:
        """GW01 makes exactly +1.00 on a 2-decimal symbol (100 ticks) and
        +0.0001 on a 4-decimal symbol (1 tick).  The operator-facing
        gateway total must be 1.0001 in currency.  Summing raw ticks gives
        the meaningless 101."""
        engine, pub = _new_engine(
            monkeypatch,
            tmp_path,
            "run1",
            symbols=(SYMBOL, "GLD4"),
            symbol_configs={
                SYMBOL: SymbolConfig(name=SYMBOL),
                "GLD4": SymbolConfig(name="GLD4", tick_decimals=4),
            },
        )
        engine._load_config()  # registers tick decimals, as run() does

        # AAPL: buy 1 @ 100.00, sell 1 @ 101.00 → realized +1.00
        _cross(engine, qty=1, price=100.0)
        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 1, "GW02", price=101.0)
        )
        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 1, "GW01", price=101.0)
        )
        # GLD4: buy 1 @ 50.0000, sell 1 @ 50.0001 → realized +0.0001
        _cross(engine, qty=1, price=50.0, symbol="GLD4")
        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 1, "GW02", price=50.0001, symbol="GLD4")
        )
        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 1, "GW01", price=50.0001, symbol="GLD4")
        )

        cut = start_clearing(tmp_path / "clearing.db")
        try:
            cut.publish_engine_output(pub.sent)
            cut.wait_ingested()
            cut.flush()

            conn = cut.db()
            gw01 = next(
                r for r in query_gateways(conn) if r["gateway_id"] == "GW01"
            )
            total = gw01["realized_pnl_total"]
            assert abs(total - 1.0001) < 1e-9, (
                f"CL-H2: GW01 realized total reported as {total} — expected "
                f"1.0001 currency (made +1.00 on a 2dp symbol and +0.0001 on "
                f"a 4dp symbol); raw tick units from different scales were "
                f"summed together"
            )
        finally:
            cut.stop()


# ---------------------------------------------------------------------------
# CL-H3 — every price-like field on one CLI row must be in the same unit
# ---------------------------------------------------------------------------


class TestCLH3AvgCostDisplayConsistency:
    def test_positions_row_avg_cost_matches_mark_after_single_fill(
        self, monkeypatch, tmp_path
    ) -> None:
        """After exactly one fill at 150.00, avg_cost and mark_price are the
        same number by definition.  The CLI positions view (query +
        _normalize_rows, the real pm-clearing-cli pipeline) must therefore
        render them identically — today avg_cost comes out 100x off."""
        engine, pub = _new_engine(monkeypatch, tmp_path, "run1")
        _cross(engine, qty=100, price=150.0)

        cut = start_clearing(tmp_path / "clearing.db")
        try:
            cut.publish_engine_output(pub.sent)
            cut.wait_ingested()
            cut.flush()

            conn = cut.db()
            rows = _normalize_rows("positions", query_positions(conn, gateway="GW01"))
            row = rows[0]
            assert row["avg_cost"] == row["mark_price"] == 150.0, (
                f"CL-H3: one fill at 150.00 renders as avg_cost="
                f"{row['avg_cost']} vs mark_price={row['mark_price']} — the "
                f"same execution price must display as the same number"
            )
        finally:
            cut.stop()


# ---------------------------------------------------------------------------
# CL-H4 — reconcile must detect total raw-side loss
# ---------------------------------------------------------------------------


class TestCLH4ReconcileCompleteness:
    def test_reconcile_reports_key_missing_entirely_from_raw_archive(
        self, monkeypatch, tmp_path
    ) -> None:
        """Summaries say GW01 traded; every raw row for the key is gone
        (the exact shape CL-C1 produces for a whole day).  The reconcile
        verb exists to catch divergence — it must report this one."""
        db_path = tmp_path / "clearing.db"
        engine, pub = _new_engine(monkeypatch, tmp_path, "run1")
        _cross(engine, qty=100, price=150.0)

        cut = start_clearing(db_path)
        try:
            cut.publish_engine_output(pub.sent)
            cut.wait_ingested()
            cut.flush()
        finally:
            cut.stop()

        with _rw(db_path) as conn:
            conn.execute("DELETE FROM trade_events")  # total raw loss
            conn.commit()
            discrepancies = query_reconcile(conn)

        assert discrepancies, (
            "CL-H4: gateway_daily_summary reports traded volume for a key "
            "with ZERO surviving trade_events rows, and reconcile returned "
            "no discrepancies — the raw-driven LEFT JOIN cannot see "
            "summary-only keys, i.e. it is blind to exactly the total-loss "
            "case it exists to catch"
        )
