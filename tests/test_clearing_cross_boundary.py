"""
Cross-boundary and corner-case tests for the engine → clearing pipeline.

Everything here crosses at least one process boundary using real
engine-built payloads over a real socket (tests/clearing_harness.py), and
asserts SYSTEM-level truths rather than per-module behaviour:

  GREEN GUARDS (must pass today and stay green through all fixes):
    XB1  zero-sum conservation — a closed exchange nets to zero
    XB3  tick-scale round trips — nasty prices survive the display-float wire
    XB4  EOD resilience — empty/duplicate EOD broadcasts are harmless
    XB5  every position tracker in the system must agree
         (red while engine review H3 was open; green since that fix landed —
          kept as the permanent cross-system agreement guard)
    XB6  hostile frames — garbage on the wire never stops ingestion

  EXPECTED FAILURES (each mapped to an open review finding):
    XB2  duplicate delivery must not double positions        (CL-M1)
    XB7  the "day two of class" compound scenario            (CL-C1 x CL-C4)

XB7 deserves a note: it is the literal second morning of a classroom
deployment — engine restarted, clearing restarted, same database — and it
currently gets BOTH the archive and the positions wrong at once.
"""

from __future__ import annotations

import itertools
import random
import sqlite3
from contextlib import contextmanager
from typing import Iterator

import pytest

from edumatcher.engine.config_loader import SymbolConfig
from edumatcher.models.message import encode, make_eod_msg
from edumatcher.models.order import OrderType, Side
from edumatcher.models.price import from_ticks

from tests.clearing_harness import start_clearing
from tests.engine_harness import SYMBOL, connect, make_engine, order_payload


def _new_engine(monkeypatch, tmp_path, run_name: str, **kw):
    run_dir = tmp_path / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    engine, pub = make_engine(monkeypatch, run_dir, **kw)
    connect(engine)
    return engine, pub


def _cross(engine, *, buyer, seller, qty, price, symbol=SYMBOL) -> None:
    engine._handle_new_order(
        order_payload(
            Side.SELL, OrderType.LIMIT, qty, seller, price=price, symbol=symbol
        )
    )
    engine._handle_new_order(
        order_payload(Side.BUY, OrderType.LIMIT, qty, buyer, price=price, symbol=symbol)
    )


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
# XB1 — conservation: an exchange is a closed system (GREEN GUARD)
# ---------------------------------------------------------------------------


class TestXB1ZeroSumConservation:
    @pytest.mark.parametrize("seed", [7, 21, 42])
    def test_positions_and_pnl_net_to_zero_across_all_gateways(
        self, monkeypatch, tmp_path, seed
    ) -> None:
        """For every trade there is a buyer and a seller, so summed over ALL
        gateways per symbol: net quantity is zero, and total P&L — with
        every position marked to ONE common price M — is zero (the stored
        unrealized_pnl uses per-position marks, which legitimately differ,
        so the conservation law must be evaluated at a common mark:
        total_i = realized_i + net_i * (M - avg_cost_i)).  One invariant,
        whole classes of ledger/ingestion bugs."""
        rng = random.Random(seed)
        engine, pub = _new_engine(monkeypatch, tmp_path, f"run{seed}")

        gws = ["GW01", "GW02", "GW03"]
        for _ in range(30):
            buyer, seller = rng.sample(gws, 2)
            _cross(
                engine,
                buyer=buyer,
                seller=seller,
                qty=rng.randint(1, 200),
                price=round(100 + rng.randint(-300, 300) * 0.01, 2),
            )

        cut = start_clearing(tmp_path / f"clearing{seed}.db")
        try:
            cut.publish_engine_output(pub.sent)
            cut.wait_ingested()
            cut.flush()

            conn = cut.db()
            rows = conn.execute(
                "SELECT net_qty, avg_cost, realized_pnl, buy_qty, sell_qty"
                " FROM gateway_symbol_positions WHERE symbol=?",
                (SYMBOL,),
            ).fetchall()

            net_total = sum(r["net_qty"] for r in rows)
            assert net_total == 0, f"XB1: net qty across gateways = {net_total} != 0"
            assert sum(r["buy_qty"] for r in rows) == sum(
                r["sell_qty"] for r in rows
            ), "XB1: total buys != total sells"

            common_mark = 10000.0  # any common M satisfies the identity
            pnl_at_mark = sum(
                r["realized_pnl"] + r["net_qty"] * (common_mark - r["avg_cost"])
                for r in rows
            )
            assert abs(pnl_at_mark) < 1e-3, (
                f"XB1: total P&L at a common mark = {pnl_at_mark} != 0 — "
                f"the exchange is a closed system; someone's gain must be "
                f"someone's loss"
            )
            row = conn.execute(
                "SELECT SUM(buy_qty) AS b FROM gateway_symbol_positions"
                " WHERE symbol=?",
                (SYMBOL,),
            ).fetchone()

            # Archive ↔ ledger identity: each trade contributes its qty to
            # exactly one buyer and one seller.
            traded = conn.execute(
                "SELECT SUM(quantity) AS q FROM trade_events WHERE symbol=?",
                (SYMBOL,),
            ).fetchone()["q"]
            assert row["b"] == traded, (
                f"XB1: ledger buy total {row['b']} != archived trade total " f"{traded}"
            )
        finally:
            cut.stop()


# ---------------------------------------------------------------------------
# XB2 — duplicate delivery must not double-count (EXPECTED FAIL: CL-M1)
# ---------------------------------------------------------------------------


class TestXB2DuplicateDelivery:
    def test_replayed_trade_frames_do_not_double_positions(
        self, monkeypatch, tmp_path
    ) -> None:
        """Deliver the same engine-built trade frames twice (retransmission /
        future replay recovery).  The archive dedups on trade id — but the
        ledger must dedup too, or archive and positions silently diverge."""
        engine, pub = _new_engine(monkeypatch, tmp_path, "run1")
        _cross(engine, buyer="GW01", seller="GW02", qty=100, price=150.0)

        cut = start_clearing(tmp_path / "clearing.db")
        try:
            cut.publish_engine_output(pub.sent)
            cut.publish_engine_output(pub.sent)  # exact replay
            cut.wait_ingested()
            cut.flush()

            conn = cut.db()
            archived = conn.execute(
                "SELECT COUNT(*) AS c FROM trade_events"
            ).fetchone()["c"]
            net = conn.execute(
                "SELECT net_qty FROM gateway_symbol_positions"
                " WHERE gateway_id='GW01' AND symbol=?",
                (SYMBOL,),
            ).fetchone()["net_qty"]

            assert archived == 1  # the archive-side dedup works today
            assert net == 100, (
                f"XB2 (CL-M1): one 100-lot trade delivered twice left GW01 "
                f"with net_qty={net} — idempotency gates the archive but not "
                f"the ledger, so positions and archive now disagree"
            )
        finally:
            cut.stop()


# ---------------------------------------------------------------------------
# XB3 — tick-scale round trips over the display-float wire (GREEN GUARD)
# ---------------------------------------------------------------------------

# (tick_decimals, price_ticks) — chosen to stress binary float representation.
_NASTY_PRICES = [
    (2, 15075),  # 150.75 — plain
    (2, 1),  # 0.01 — smallest tick
    (2, 9999999),  # 99999.99 — large
    (4, 333333),  # 33.3333 — repeating decimal
    (4, 501234),  # 50.1234
    (8, 1),  # 0.00000001 — smallest representable tick
    (8, 12345678901),  # 123.45678901 — many significant digits
]


class TestXB3TickScaleRoundTrips:
    @pytest.mark.parametrize("decimals,ticks", _NASTY_PRICES)
    def test_price_survives_engine_wire_clearing_round_trip(
        self, monkeypatch, tmp_path, decimals, ticks
    ) -> None:
        """The engine stores ticks, publishes display floats, and clearing
        re-derives ticks.  For every representable price this three-hop
        conversion must be EXACT — one off-by-one tick here corrupts every
        notional downstream.  This guard protects the contract if either
        side ever changes its price encoding."""
        sym = f"RT{decimals}"
        engine, pub = _new_engine(
            monkeypatch,
            tmp_path,
            f"run{decimals}_{ticks}",
            symbols=(sym,),
            symbol_configs={sym: SymbolConfig(name=sym, tick_decimals=decimals)},
        )
        engine._load_config()  # registers tick decimals as run() does

        display = from_ticks(ticks, sym)
        _cross(engine, buyer="GW01", seller="GW02", qty=7, price=display, symbol=sym)

        cut = start_clearing(tmp_path / "clearing.db")
        try:
            cut.publish_engine_output(pub.sent)
            cut.wait_ingested()
            cut.flush()

            conn = cut.db()
            row = conn.execute(
                "SELECT price, tick_decimals FROM trade_events WHERE symbol=?",
                (sym,),
            ).fetchone()
            assert row is not None, "precondition: trade archived"
            assert (row["price"], row["tick_decimals"]) == (ticks, decimals), (
                f"XB3: {ticks} ticks @ {decimals}dp went over the wire as "
                f"{display!r} and came back as {row['price']} ticks @ "
                f"{row['tick_decimals']}dp — the display-float round trip "
                f"must be exact for every representable price"
            )
        finally:
            cut.stop()


# ---------------------------------------------------------------------------
# XB4 — EOD resilience: empty and duplicate broadcasts (GREEN GUARD)
# ---------------------------------------------------------------------------


class TestXB4EodResilience:
    def test_empty_and_repeated_eod_broadcasts_are_harmless(
        self, monkeypatch, tmp_path
    ) -> None:
        """An EOD with no books (nothing traded) and a duplicated EOD (engine
        restarted twice in a day) must neither crash clearing nor block
        subsequent ingestion."""
        engine, pub = _new_engine(monkeypatch, tmp_path, "run1")

        cut = start_clearing(tmp_path / "clearing.db")
        try:
            cut.publish_frames([make_eod_msg([])])  # empty day
            cut.publish_frames([make_eod_msg([])])  # duplicate
            cut.publish_frames([encode("system.eod", {})])  # books key absent
            cut.fence()

            # Clearing must still be alive and ingesting.
            _cross(engine, buyer="GW01", seller="GW02", qty=5, price=150.0)
            cut.publish_engine_output(pub.sent)
            cut.wait_ingested(1)
            cut.flush()

            conn = cut.db()
            archived = conn.execute(
                "SELECT COUNT(*) AS c FROM trade_events"
            ).fetchone()["c"]
            sentinels = conn.execute(
                "SELECT COUNT(*) AS c FROM session_events WHERE event_type='EOD'"
            ).fetchone()["c"]
            assert archived == 1, "XB4: ingestion stopped after odd EODs"
            assert sentinels >= 2, "XB4: EOD sentinels not recorded"
        finally:
            cut.stop()


# ---------------------------------------------------------------------------
# XB5 — every position tracker in the system must agree (GREEN GUARD)
# ---------------------------------------------------------------------------


class TestXB5CrossSystemPositionAgreement:
    def test_engine_ledger_agrees_with_clearing_after_quote_flow(
        self, monkeypatch, tmp_path
    ) -> None:
        """One execution, two independent position trackers: the engine's
        in-memory ledger (serves system.position_request to bots) and
        clearing's durable ledger (built from trade.executed).  They watch
        the same exchange, so they must agree — for EVERY flow that can
        trade, including market-maker quotes.

        History: this diverged while engine review H3 was open (quote-flow
        fills skipped the engine's _update_position); it went green when
        that fix consolidated position updates into _publish_trade.  Keep it
        as the permanent cross-system agreement guard — it fails again the
        moment any new flow forgets either tracker."""
        engine, pub = _new_engine(monkeypatch, tmp_path, "run1", mm_gateways=("GW01",))
        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 100, "GW02", price=101.0)
        )
        engine._handle_quote_new(
            {
                "gateway_id": "GW01",
                "symbol": SYMBOL,
                "quote_id": "QXB5",
                "bid_price": 101.0,  # crosses the resting ask → trade
                "ask_price": 102.0,
                "bid_qty": 100,
                "ask_qty": 100,
                "tif": "DAY",
            }
        )

        cut = start_clearing(tmp_path / "clearing.db")
        try:
            cut.publish_engine_output(pub.sent)
            cut.wait_ingested(1)
            cut.flush()

            conn = cut.db()
            clearing_net = conn.execute(
                "SELECT net_qty FROM gateway_symbol_positions"
                " WHERE gateway_id='GW01' AND symbol=?",
                (SYMBOL,),
            ).fetchone()["net_qty"]
            engine_net = engine._gateway_positions.get("GW01", {}).get(SYMBOL, 0)

            assert clearing_net == 100  # clearing sees the public trade — correct
            assert engine_net == clearing_net, (
                f"XB5: the same fill left the engine's position ledger at "
                f"{engine_net} and clearing's at {clearing_net} — two "
                f"trackers of one exchange disagree (engine review H3: "
                f"quote/combo/OCO fills skip _update_position; clearing is "
                f"the correct one)"
            )
        finally:
            cut.stop()


# ---------------------------------------------------------------------------
# XB6 — hostile wire input must never stop ingestion (GREEN GUARD)
# ---------------------------------------------------------------------------


class TestXB6HostileFrames:
    def test_garbage_frames_do_not_interrupt_the_feed(
        self, monkeypatch, tmp_path
    ) -> None:
        engine, pub = _new_engine(monkeypatch, tmp_path, "run1")

        cut = start_clearing(tmp_path / "clearing.db")
        try:
            raw = cut._pub  # deliberate: raw hostile bytes, bypassing helpers
            raw.send_multipart([b"trade.executed"])  # 1 frame only
            raw.send_multipart([b"trade.executed", b"{not json"])  # broken JSON
            raw.send_multipart([b"trade.executed", b"[1, 2, 3]"])  # wrong shape
            raw.send_multipart(
                [b"trade.executed", b'{"price": "NaN", "timestamp": null}']
            )  # missing fields
            raw.send_multipart([b"system.eod", b"null"])  # null payload

            # A valid, engine-built trade must still get through.
            _cross(engine, buyer="GW01", seller="GW02", qty=9, price=150.0)
            cut.publish_engine_output(pub.sent)
            cut.wait_ingested(1)
            cut.flush()

            conn = cut.db()
            row = conn.execute("SELECT quantity FROM trade_events").fetchone()
            assert row is not None and row["quantity"] == 9, (
                "XB6: hostile frames on the feed prevented a subsequent "
                "valid trade from being archived — the receive loop must "
                "absorb garbage and keep going"
            )
        finally:
            cut.stop()


# ---------------------------------------------------------------------------
# XB7 — day two of class (EXPECTED FAIL: CL-C1 x CL-C4 compound)
# ---------------------------------------------------------------------------


class TestXB7DayTwoOfClass:
    def test_second_session_with_restarted_engine_and_clearing(
        self, monkeypatch, tmp_path
    ) -> None:
        """The most realistic failure scenario there is: the course's second
        morning.  Yesterday both processes ran and shut down cleanly; today
        both start fresh on the same database and one more trade prints.

        Ground truth afterwards: GW01 is long 140 (100 + 40) and the archive
        holds two trades.  Today BOTH are wrong at once: the position table
        is overwritten from flat (CL-C4 → 40) and the day-2 trade collides
        with day-1's trade id and vanishes from the archive (CL-C1 → 1 row).
        """
        db_path = tmp_path / "clearing.db"

        # ---- day 1 ----
        monkeypatch.setattr(
            "edumatcher.models.trade._trade_counter", itertools.count(1)
        )
        engine1, pub1 = _new_engine(monkeypatch, tmp_path, "day1")
        _cross(engine1, buyer="GW01", seller="GW02", qty=100, price=150.0)
        cut1 = start_clearing(db_path)
        try:
            cut1.publish_engine_output(pub1.sent)
            cut1.wait_ingested()
            cut1.publish_frames(
                [make_eod_msg([b.snapshot() for b in engine1.books.values()])]
            )
            cut1.fence()
            cut1.flush()
        finally:
            cut1.stop()

        # ---- day 2: both processes restart ----
        monkeypatch.setattr(
            "edumatcher.models.trade._trade_counter", itertools.count(1)
        )
        engine2, pub2 = _new_engine(monkeypatch, tmp_path, "day2")
        _cross(engine2, buyer="GW01", seller="GW02", qty=40, price=152.0)
        cut2 = start_clearing(db_path)
        try:
            cut2.publish_engine_output(pub2.sent)
            cut2.wait_ingested()
            cut2.flush()
        finally:
            cut2.stop()

        with _rw(db_path) as conn:
            archived = conn.execute(
                "SELECT COUNT(*) AS c FROM trade_events"
            ).fetchone()["c"]
            net = conn.execute(
                "SELECT net_qty FROM gateway_symbol_positions"
                " WHERE gateway_id='GW01' AND symbol=?",
                (SYMBOL,),
            ).fetchone()["net_qty"]

        problems = []
        if archived != 2:
            problems.append(
                f"archive holds {archived} trade(s) instead of 2 (CL-C1: "
                f"day-2 trade id collided with day-1 and was dropped)"
            )
        if net != 140:
            problems.append(
                f"GW01 position is {net} instead of 140 (CL-C4: restarted "
                f"clearing overwrote day-1 state from flat)"
            )
        assert not problems, "XB7 day-two-of-class: " + "; ".join(problems)
