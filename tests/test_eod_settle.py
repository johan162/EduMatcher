"""Settlement arithmetic: day P&L from close snapshots, rounding, zero-sum."""

from __future__ import annotations

import random
from decimal import Decimal
from pathlib import Path

import pytest

from edumatcher.clearing.store import (
    PositionRow,
    clearing_instance,
    flush_batch,
    open_writer_connection,
    write_close_snapshot,
)
from edumatcher.eod.settle import (
    EXCHANGE,
    Baseline,
    Settlement,
    SettlementError,
    Snapshot,
    compute_settlement,
    day_pnl,
    equities,
    settle_date,
    to_minor_units,
)


def snap(
    gateway: str,
    symbol: str = "AAPL",
    realized: float = 0.0,
    unrealized: float = 0.0,
    tick_decimals: int = 2,
) -> Snapshot:
    return Snapshot(gateway, symbol, realized, unrealized, tick_decimals)


class TestDayPnl:
    def test_first_day_is_the_whole_equity(self) -> None:
        got = day_pnl([snap("A", realized=100.0, unrealized=5000.0)], {})
        assert got == {"A": {"AAPL": Decimal("51.00")}}

    def test_change_between_two_closes(self) -> None:
        today = [snap("A", unrealized=2000.0)]
        prev = [snap("A", unrealized=5000.0)]
        assert day_pnl(today, equities(prev)) == {"A": {"AAPL": Decimal("-30.00")}}

    def test_a_silent_holder_is_settled_for_the_price_move(self) -> None:
        # A did not trade today: the only change is the mark.
        today = [snap("A", realized=0.0, unrealized=-2000.0)]
        prev = [snap("A", realized=0.0, unrealized=0.0)]
        assert day_pnl(today, equities(prev))["A"]["AAPL"] == Decimal("-20.00")

    def test_each_snapshot_uses_its_own_tick_scale(self) -> None:
        today = [snap("A", unrealized=300.0, tick_decimals=4)]
        prev = [snap("A", unrealized=100.0, tick_decimals=2)]
        assert day_pnl(today, equities(prev))["A"]["AAPL"] == Decimal("0.03") - Decimal(
            "1.00"
        )

    def test_a_gateway_with_no_change_still_appears(self) -> None:
        got = day_pnl(
            [snap("A", unrealized=10.0)], equities([snap("A", unrealized=10.0)])
        )
        assert got == {"A": {"AAPL": Decimal("0.00")}}

    def test_a_key_missing_today_is_ignored(self) -> None:
        assert day_pnl([], equities([snap("A", unrealized=10.0)])) == {}

    def test_symbols_are_kept_apart(self) -> None:
        today = [
            snap("A", "AAPL", unrealized=100.0),
            snap("A", "MSFT", unrealized=-50.0),
        ]
        got = day_pnl(today, {})
        assert got["A"] == {"AAPL": Decimal("1.00"), "MSFT": Decimal("-0.50")}


class TestToMinorUnits:
    def test_largest_remainder_keeps_the_sum(self) -> None:
        amounts = {
            "A": Decimal("0.333"),
            "B": Decimal("0.333"),
            "C": Decimal("-0.666"),
        }
        minor, total = to_minor_units(amounts)
        assert total == 0
        assert sum(minor.values()) == 0
        assert minor == {"A": 33, "B": 33, "C": -66}

    def test_exact_amounts_are_unchanged(self) -> None:
        minor, total = to_minor_units({"A": Decimal("12.34"), "B": Decimal("-12.34")})
        assert minor == {"A": 1234, "B": -1234}
        assert total == 0

    def test_a_nonzero_total_is_returned_not_hidden(self) -> None:
        minor, total = to_minor_units({"A": Decimal("0.03"), "B": Decimal("0.00")})
        assert total == 3
        assert sum(minor.values()) == 3

    def test_ties_break_by_account_id(self) -> None:
        minor, _ = to_minor_units(
            {"B": Decimal("0.005"), "A": Decimal("0.005"), "C": Decimal("-0.010")}
        )
        assert sum(minor.values()) == 0
        assert minor["A"] == 1 and minor["B"] == 0 and minor["C"] == -1

    @pytest.mark.parametrize("seed", range(25))
    def test_random_zero_sum_days_stay_exactly_zero(self, seed: int) -> None:
        rng = random.Random(seed)
        n = rng.randint(2, 40)
        parts = [
            Decimal(rng.randint(-(10**7), 10**7)) / 10 ** rng.randint(0, 6)
            for _ in range(n - 1)
        ]
        parts.append(-sum(parts, Decimal(0)))
        amounts = {f"G{i:02d}": p for i, p in enumerate(parts)}
        minor, total = to_minor_units(amounts)
        assert total == 0
        assert sum(minor.values()) == 0
        for account, exact in amounts.items():
            assert abs(Decimal(minor[account]) - exact * 100) < 1


class TestComputeSettlement:
    def test_three_trader_golden_day(self) -> None:
        # Day 1: A bought 100 @10.00 from B, closing mark 10.50.
        d1 = [
            snap("A", unrealized=5000.0),
            snap("B", unrealized=-5000.0),
        ]
        first = compute_settlement(d1, {})
        assert first.amounts_minor == {"A": 5000, "B": -5000}
        assert first.rounding_minor == 0
        # Day 2: mark 10.20; C bought 50 @10.20 from B.
        d2 = [
            snap("A", unrealized=2000.0),
            snap("B", unrealized=-2000.0),
            snap("C", unrealized=0.0),
        ]
        second = compute_settlement(d2, equities(d1))
        assert second.amounts_minor == {"A": -3000, "B": 3000, "C": 0}
        assert second.detail["A"] == {"AAPL": Decimal("-30.00")}

    def test_tiny_drift_is_booked_to_the_exchange(self) -> None:
        today = [snap("A", unrealized=1000.6), snap("B", unrealized=-1000.0)]
        got = compute_settlement(today, {})
        assert got.amounts_minor == {"A": 1001, "B": -1000}
        assert got.rounding_minor == -1

    def test_a_large_imbalance_is_an_error(self) -> None:
        with pytest.raises(SettlementError, match="sum to zero"):
            compute_settlement([snap("A", unrealized=500_000.0)], {})

    def test_unchanged_positions_do_not_widen_the_tolerance(self) -> None:
        # 2 000 positions that did not move and one gain with no counterparty.
        today = [snap(f"G{i}") for i in range(2000)] + [snap("A", realized=1500.0)]
        with pytest.raises(SettlementError, match="1 changed position"):
            compute_settlement(today, equities(today[:2000]))

    def test_float_noise_on_many_changed_positions_settles(self) -> None:
        today: list[Snapshot] = []
        for i in range(250):
            today += [snap(f"L{i}", unrealized=100.0), snap(f"S{i}", unrealized=-100.0)]
        noisy = [
            Snapshot(s.gateway_id, s.symbol, 1e-7, s.unrealized_pnl, 2) for s in today
        ]
        got = compute_settlement(noisy, {})
        assert got.rounding_minor == 0
        assert got.drift == Decimal("1e-9") * 500

    def test_the_exact_drift_is_kept(self) -> None:
        today = [snap("A", unrealized=1000.6), snap("B", unrealized=-1000.0)]
        assert compute_settlement(today, {}).drift == Decimal("0.006")

    def test_a_gateway_may_not_be_called_exchange(self) -> None:
        with pytest.raises(SettlementError, match=EXCHANGE):
            compute_settlement([snap(EXCHANGE)], {})

    def test_empty_day(self) -> None:
        assert compute_settlement([], {}) == Settlement({}, 0, {})


class TestSettleDate:
    def _seed(self, path: Path) -> None:
        conn = open_writer_connection(path)
        pos = lambda gw, unreal: PositionRow(  # noqa: E731
            gateway_id=gw,
            symbol="AAPL",
            net_qty=100,
            avg_cost=1000.0,
            realized_pnl=0.0,
            unrealized_pnl=unreal,
            mark_price=1050,
            buy_qty=100,
            sell_qty=0,
            buy_notional=100000,
            sell_notional=0,
            last_trade_ts_ns=1,
            updated_ts_ns=1,
        )
        flush_batch(conn, [], [pos("A", 5000.0), pos("B", -5000.0)], [])
        write_close_snapshot(conn, "2026-07-01")
        flush_batch(conn, [], [pos("A", 2000.0), pos("B", -2000.0)], [])
        write_close_snapshot(conn, "2026-07-03")  # weekend gap
        conn.close()

    def test_the_baseline_is_the_previous_settled_date(self, tmp_path: Path) -> None:
        path = tmp_path / "clearing.db"
        self._seed(path)
        conn = open_writer_connection(path)
        try:
            assert settle_date(conn, "2026-07-01", None).amounts_minor == {
                "A": 5000,
                "B": -5000,
            }
            assert settle_date(conn, "2026-07-03", "2026-07-01").amounts_minor == {
                "A": -3000,
                "B": 3000,
            }
        finally:
            conn.close()

    def test_no_baseline_starts_from_zero(self, tmp_path: Path) -> None:
        # Never settled, or the previous settled date has no snapshot any more
        # (clearing.db was reset): the earlier snapshot is not used.
        path = tmp_path / "clearing.db"
        self._seed(path)
        conn = open_writer_connection(path)
        try:
            for previous in (None, "2026-06-30"):
                assert settle_date(conn, "2026-07-03", previous).amounts_minor == {
                    "A": 2000,
                    "B": -2000,
                }
        finally:
            conn.close()

    def test_the_recorded_baseline_wins_over_a_rewritten_snapshot(
        self, tmp_path: Path
    ) -> None:
        # 2026-07-01 was settled at A +10.00; its snapshot now says +50.00.
        path = tmp_path / "clearing.db"
        self._seed(path)
        conn = open_writer_connection(path)
        settled = Baseline(
            {("A", "AAPL"): Decimal("10"), ("B", "AAPL"): Decimal("-10")}, None
        )
        try:
            got = settle_date(conn, "2026-07-03", "2026-07-01", settled)
            assert got.amounts_minor == {"A": 1000, "B": -1000}
            assert got.baseline_changed
            first = settle_date(conn, "2026-07-01", None).equity
            same = settle_date(conn, "2026-07-03", "2026-07-01", Baseline(first, None))
            assert not same.baseline_changed
            assert same.amounts_minor == {"A": -3000, "B": 3000}
        finally:
            conn.close()

    def test_a_reset_ignores_the_recorded_baseline(self, tmp_path: Path) -> None:
        path = tmp_path / "clearing.db"
        self._seed(path)
        conn = open_writer_connection(path)
        settled = Baseline(
            {("A", "AAPL"): Decimal("10"), ("B", "AAPL"): Decimal("-10")}, None
        )
        try:
            got = settle_date(conn, "2026-07-03", "2026-06-30", settled)
            assert got.amounts_minor == {"A": 2000, "B": -2000}
            assert not got.baseline_changed
        finally:
            conn.close()

    def test_another_clearing_db_starts_from_zero(self, tmp_path: Path) -> None:
        path = tmp_path / "clearing.db"
        self._seed(path)
        conn = open_writer_connection(path)
        settled = {("A", "AAPL"): Decimal("10"), ("B", "AAPL"): Decimal("-10")}
        try:
            mine = clearing_instance(conn)
            other = settle_date(
                conn, "2026-07-03", "2026-07-01", Baseline(settled, "elsewhere")
            )
            assert other.amounts_minor == {"A": 2000, "B": -2000}
            assert other.baseline_reset and not other.baseline_changed
            same = settle_date(
                conn, "2026-07-03", "2026-07-01", Baseline(settled, mine)
            )
            assert same.amounts_minor == {"A": 1000, "B": -1000}
            assert same.clearing_instance == mine and not same.baseline_reset
        finally:
            conn.close()

    def test_the_settlement_carries_the_closing_equity(self, tmp_path: Path) -> None:
        path = tmp_path / "clearing.db"
        self._seed(path)
        conn = open_writer_connection(path)
        try:
            got = settle_date(conn, "2026-07-01", None)
            assert got.equity == {
                ("A", "AAPL"): Decimal("50"),
                ("B", "AAPL"): Decimal("-50"),
            }
        finally:
            conn.close()

    def test_no_snapshot_for_the_date_is_an_error(self, tmp_path: Path) -> None:
        path = tmp_path / "clearing.db"
        self._seed(path)
        conn = open_writer_connection(path)
        try:
            with pytest.raises(SettlementError, match="no close snapshot"):
                settle_date(conn, "2026-07-02", "2026-07-01")
        finally:
            conn.close()
