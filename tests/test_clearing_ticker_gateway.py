"""
Tests for clearing, ticker, gateway completer, and remaining coverage gaps.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.models.trade import Trade

# ---------------------------------------------------------------------------
# clearing/main.py — ClearingProcess helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def clearing_proc(tmp_path: Path):
    """ClearingProcess with patched ZMQ; _csv_file closed after each test."""
    from edumatcher.clearing_v1.main import ClearingProcess

    fake_sock = MagicMock()
    with (
        patch("edumatcher.clearing_v1.main.make_subscriber", return_value=fake_sock),
        patch("edumatcher.clearing_v1.main.DATA_DIR", tmp_path),
        patch("edumatcher.clearing_v1.main.CLEARING_REPORT_FILE", tmp_path / "report.csv"),
    ):
        proc = ClearingProcess()
    yield proc
    proc._csv_file.close()


def _make_trade(
    symbol="AAPL",
    buy_gw="GW01",
    sell_gw="GW02",
    price=100.0,
    qty=100,
) -> Trade:
    return Trade.create(
        symbol=symbol,
        buy_order_id="B1",
        sell_order_id="S1",
        buy_gateway_id=buy_gw,
        sell_gateway_id=sell_gw,
        price=price,
        quantity=qty,
        aggressor_side="BUY",
    )


class TestClearingProcess:
    def test_update_ledger_creates_position(self, clearing_proc) -> None:
        proc = clearing_proc
        trade = _make_trade()
        proc._update_ledger(trade)
        assert "GW01" in proc._ledger
        assert "AAPL" in proc._ledger["GW01"]
        assert proc._ledger["GW01"]["AAPL"].position == 100

    def test_update_ledger_both_sides(self, clearing_proc) -> None:
        proc = clearing_proc
        trade = _make_trade()
        proc._update_ledger(trade)
        buy_rec = proc._ledger["GW01"]["AAPL"]
        sell_rec = proc._ledger["GW02"]["AAPL"]
        assert buy_rec.position == 100
        assert sell_rec.position == -100

    def test_record_trade_writes_csv(self, clearing_proc) -> None:
        proc = clearing_proc
        trade = _make_trade()
        proc._record_trade(trade)
        csv_content = proc._csv_path.read_text()
        assert "AAPL" in csv_content

    def test_print_pnl_table_no_error(self, clearing_proc) -> None:
        proc = clearing_proc
        trade = _make_trade(price=100.0, qty=100)
        proc._update_ledger(trade)
        # Set last_price to enable unrealized PnL
        proc._ledger["GW01"]["AAPL"].last_price = 105.0
        # Should not raise
        proc._print_pnl_table()

    def test_print_pnl_table_empty_ledger(self, clearing_proc) -> None:
        proc = clearing_proc
        # Should not raise with empty ledger
        proc._print_pnl_table()

    def test_update_ledger_multiple_trades(self, clearing_proc) -> None:
        proc = clearing_proc
        for i in range(3):
            proc._update_ledger(_make_trade(price=100.0 + i, qty=50))
        assert (
            proc._ledger["GW01"]["AAPL"].volume == pytest.approx(150, abs=1)
            if hasattr(proc._ledger["GW01"]["AAPL"], "volume")
            else True
        )
        # Just check position is correct (3 * 50 = 150)
        assert proc._ledger["GW01"]["AAPL"].position == pytest.approx(150.0)

    def test_init_csv_creates_header(self, clearing_proc) -> None:
        proc = clearing_proc
        proc._csv_file.flush()  # ensure buffered data is written
        csv_content = proc._csv_path.read_text()
        assert "trade_id" in csv_content
        assert "symbol" in csv_content


# ---------------------------------------------------------------------------
# ticker/main.py — TickerProcess helpers
# ---------------------------------------------------------------------------


def _make_ticker(tmp_path: Path):
    from edumatcher.ticker.main import TickerProcess

    fake_sock = MagicMock()
    with patch("edumatcher.ticker.main.make_subscriber", return_value=fake_sock):
        proc = TickerProcess(
            db_path=tmp_path / "stats.db",
            display_interval=30.0,
            db_interval=900.0,
        )
    return proc


class TestTickerProcess:
    def test_refresh_db_nonexistent_file(self, tmp_path: Path) -> None:
        proc = _make_ticker(tmp_path)
        # Should not raise — file doesn't exist
        proc._refresh_db()
        assert proc._daily == {}

    def test_refresh_db_with_data(self, tmp_path: Path) -> None:
        from edumatcher.stats.main import SCHEMA

        db_path = tmp_path / "stats.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(SCHEMA)
        from datetime import date

        today = date.today().isoformat()
        conn.execute(
            "INSERT INTO daily_stats (date, symbol, open_price, close_price, volume, trade_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (today, "AAPL", 100.0, 110.0, 5000, 50),
        )
        conn.commit()
        conn.close()

        fake_sock = MagicMock()
        from edumatcher.ticker.main import TickerProcess

        with patch("edumatcher.ticker.main.make_subscriber", return_value=fake_sock):
            proc = TickerProcess(
                db_path=db_path, display_interval=30.0, db_interval=900.0
            )
        proc._refresh_db()
        assert "AAPL" in proc._daily
        assert "AAPL" in proc._symbols

    def test_refresh_db_broken_db(self, tmp_path: Path) -> None:
        db_path = tmp_path / "broken.db"
        db_path.write_text("not a sqlite db")
        proc = _make_ticker(tmp_path)
        proc._db_path = db_path
        # Should not raise — silently handles error
        proc._refresh_db()

    def test_stop(self, tmp_path: Path) -> None:
        proc = _make_ticker(tmp_path)
        proc._stop()
        assert proc._running is False


# ---------------------------------------------------------------------------
# alf_console/main.py — GatewayCompleter
# ---------------------------------------------------------------------------


class TestGatewayCompleter:
    def _completer(self):
        from edumatcher.alf_console.main import GatewayCompleter

        return GatewayCompleter(known_symbols=["AAPL", "MSFT"])

    def _document(self, text):
        from prompt_toolkit.document import Document

        return Document(text)

    def test_top_level_completions(self) -> None:
        completer = self._completer()
        doc = self._document("N")
        results = list(completer.get_completions(doc, None))
        texts = [c.text for c in results]
        assert "NEW" in texts

    def test_cancel_field_completions(self) -> None:
        completer = self._completer()
        doc = self._document("CANCEL|")
        results = list(completer.get_completions(doc, None))
        texts = [c.text for c in results]
        assert any("ID" in t for t in texts)

    def test_new_limit_field_completions(self) -> None:
        completer = self._completer()
        doc = self._document("NEW|TYPE=LIMIT|")
        results = list(completer.get_completions(doc, None))
        texts = [c.text for c in results]
        assert any("PRICE" in t for t in texts)

    def test_side_value_completions(self) -> None:
        completer = self._completer()
        doc = self._document("NEW|SIDE=")
        results = list(completer.get_completions(doc, None))
        texts = [c.text for c in results]
        assert "BUY" in texts
        assert "SELL" in texts

    def test_sym_value_completions(self) -> None:
        completer = self._completer()
        doc = self._document("NEW|SYM=")
        results = list(completer.get_completions(doc, None))
        texts = [c.text for c in results]
        assert "AAPL" in texts or "MSFT" in texts

    def test_combo_completions(self) -> None:
        completer = self._completer()
        doc = self._document("NEW|TYPE=COMBO|")
        results = list(completer.get_completions(doc, None))
        texts = [c.text for c in results]
        assert any("COMBO_ID" in t or "LEG" in t for t in texts)

    def test_amend_completions(self) -> None:
        completer = self._completer()
        doc = self._document("AMEND|")
        results = list(completer.get_completions(doc, None))
        texts = [c.text for c in results]
        assert any("ID" in t for t in texts)

    def test_combo_completions_static(self) -> None:
        from edumatcher.alf_console.main import GatewayCompleter

        result = GatewayCompleter._combo_completions(
            parts=["NEW", "TYPE=COMBO"],
            already_keys={"TYPE"},
            partial_key="",
        )
        assert any("COMBO_ID" in r for r in result)

    def test_tif_completions(self) -> None:
        completer = self._completer()
        doc = self._document("NEW|TIF=")
        results = list(completer.get_completions(doc, None))
        texts = [c.text for c in results]
        assert "DAY" in texts
        assert "GTC" in texts

    def test_type_completions(self) -> None:
        completer = self._completer()
        doc = self._document("NEW|TYPE=")
        results = list(completer.get_completions(doc, None))
        texts = [c.text for c in results]
        assert "LIMIT" in texts
        assert "MARKET" in texts

    def test_smp_completions(self) -> None:
        completer = self._completer()
        doc = self._document("NEW|SMP=")
        results = list(completer.get_completions(doc, None))
        texts = [c.text for c in results]
        assert "NONE" in texts

    def test_combo_type_completions(self) -> None:
        completer = self._completer()
        doc = self._document("NEW|COMBO_TYPE=")
        results = list(completer.get_completions(doc, None))
        texts = [c.text for c in results]
        assert "AON" in texts

    def test_no_completions_for_unknown_cmd(self) -> None:
        completer = self._completer()
        doc = self._document("UNKNOWN|")
        results = list(completer.get_completions(doc, None))
        # Should not crash, may return empty or unknown completions
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# scheduler/main.py — _time_today edge cases
# ---------------------------------------------------------------------------


class TestSchedulerTimeToday:
    def test_midnight(self) -> None:
        from edumatcher.scheduler.main import _time_today

        dt = _time_today("00:00")
        assert dt.hour == 0
        assert dt.minute == 0

    def test_end_of_day(self) -> None:
        from edumatcher.scheduler.main import _time_today

        dt = _time_today("23:59")
        assert dt.hour == 23
        assert dt.minute == 59


# ---------------------------------------------------------------------------
# engine/persistence.py — load_book_stats and load_gtc_combos
# ---------------------------------------------------------------------------


class TestPersistenceLoaders:
    def test_load_book_stats_nonexistent_file(self, tmp_path: Path) -> None:
        from edumatcher.engine.persistence import load_book_stats

        result = load_book_stats(tmp_path / "nonexistent.json")
        assert result == {}

    def test_load_book_stats_valid_file(self, tmp_path: Path) -> None:
        from edumatcher.engine.persistence import load_book_stats
        import json

        data = {"AAPL": {"last_buy_price": 100.0, "last_sell_price": 99.0}}
        p = tmp_path / "stats.json"
        p.write_text(json.dumps(data))
        result = load_book_stats(p)
        assert result["AAPL"]["last_buy_price"] == 100.0

    def test_load_book_stats_malformed_file(self, tmp_path: Path) -> None:
        from edumatcher.engine.persistence import load_book_stats

        p = tmp_path / "malformed.json"
        p.write_text("not valid json{{{{")
        result = load_book_stats(p)
        assert result == {}

    def test_load_gtc_combos_nonexistent_file(self, tmp_path: Path) -> None:
        from edumatcher.engine.persistence import load_gtc_combos

        result = load_gtc_combos(tmp_path / "nonexistent.json")
        assert result == []

    def test_load_gtc_combos_malformed_file(self, tmp_path: Path) -> None:
        from edumatcher.engine.persistence import load_gtc_combos

        p = tmp_path / "combos.json"
        p.write_text("not json")
        result = load_gtc_combos(p)
        assert result == []


# ---------------------------------------------------------------------------
# models/trade.py — Trade.from_dict
# ---------------------------------------------------------------------------


class TestTradeFromDict:
    def test_from_dict_roundtrip(self) -> None:
        from edumatcher.models.trade import Trade

        trade = Trade.create(
            symbol="AAPL",
            buy_order_id="B1",
            sell_order_id="S1",
            buy_gateway_id="GW01",
            sell_gateway_id="GW02",
            price=150.0,
            quantity=100,
            aggressor_side="BUY",
        )
        d = trade.to_dict()
        restored = Trade.from_dict(d)
        assert restored.id == trade.id
        assert restored.symbol == "AAPL"
        assert restored.price == 150.0


# ---------------------------------------------------------------------------
# models/combo.py — is_fully_filled with leg count mismatch
# ---------------------------------------------------------------------------


class TestComboIsFullyFilled:
    def test_is_fully_filled_leg_count_mismatch(self) -> None:
        from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType
        from edumatcher.models.order import OrderType, Side, TIF

        combo = ComboOrder.create(
            combo_id="C01",
            gateway_id="GW01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol="AAPL",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=150.0,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=100,
                    price=200.0,
                ),
            ],
        )
        # leg_statuses is empty → len(leg_statuses)=0 != len(legs)=2 → returns False
        assert combo.is_fully_filled is False


# ---------------------------------------------------------------------------
# engine/persistence.py — exception path in load_gtc_orders
# ---------------------------------------------------------------------------


class TestPersistenceGTCOrders:
    def test_load_gtc_orders_nonexistent(self, tmp_path: Path) -> None:
        from edumatcher.engine.persistence import load_gtc_orders

        result = load_gtc_orders(tmp_path / "no.json")
        assert result == []

    def test_load_gtc_orders_malformed(self, tmp_path: Path) -> None:
        from edumatcher.engine.persistence import load_gtc_orders

        p = tmp_path / "gtc.json"
        p.write_text("bad json{{")
        result = load_gtc_orders(p)
        assert result == []
