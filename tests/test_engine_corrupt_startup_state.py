"""The engine never starts on state it could not read without saying so loudly.

F1 (docs-design/EduMatcher-Log-Ledger.md §6.2): an unreadable GTC orders or
combos file, or an unreadable entry in one, is copied aside before the engine's
first checkpoint overwrites it, and the CRITICAL message names the copy.
WP-ENG04 (C7): ``book_stats.json`` likewise — a corrupt entry or breaker
window is skipped, the file kept, and the engine still starts.
F2: a compiled configuration that exists but cannot be read is fatal, like an
invalid one, instead of running on built-in defaults.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from edumatcher.engine.persistence import (
    load_book_stats,
    load_gtc_combos,
    load_gtc_orders,
    save_gtc_orders,
)
from edumatcher.models.order import Order, OrderType, Side, TIF


def _order() -> Order:
    return Order.create(
        symbol="AAPL",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        gateway_id="GW01",
        tif=TIF.GTC,
        price_ticks=10000,
    )


def _copies(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.corrupt-*"))


@pytest.mark.parametrize("text", ["{ not json", '{"an": "object"}'])
@pytest.mark.parametrize("loader", [load_gtc_orders, load_gtc_combos])
def test_an_unreadable_file_is_kept_before_anything_overwrites_it(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, loader: Any, text: str
) -> None:
    path = tmp_path / "gtc.json"
    path.write_text(text)

    with caplog.at_level(logging.CRITICAL, logger="edumatcher.engine.persistence"):
        assert loader(path) == []

    (copy,) = _copies(path)
    assert copy.read_text() == text
    (record,) = caplog.records
    assert record.levelno == logging.CRITICAL
    assert str(copy) in record.getMessage()
    assert "none restored" in record.getMessage()


def test_corrupt_entries_are_skipped_and_the_file_is_kept_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "gtc_orders.json"
    save_gtc_orders([_order()], path)
    good = json.loads(path.read_text())
    original = json.dumps([{"id": "bad-1"}, *good, {"id": "bad-2"}])
    path.write_text(original)

    with caplog.at_level(logging.CRITICAL, logger="edumatcher.engine.persistence"):
        orders = load_gtc_orders(path)

    assert len(orders) == 1
    (copy,) = _copies(path)
    assert copy.read_text() == original
    assert [r.getMessage().split(" (id=")[1].split(")")[0] for r in caplog.records] == [
        "'bad-1'",
        "'bad-2'",
    ]
    assert all(str(copy) in r.getMessage() for r in caplog.records)


def test_corrupt_combos_are_skipped_and_the_file_is_kept_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "gtc_combos.json"
    original = json.dumps([{"id": "bad-1"}, "not a combo"])
    path.write_text(original)

    with caplog.at_level(logging.CRITICAL, logger="edumatcher.engine.persistence"):
        assert load_gtc_combos(path) == []

    (copy,) = _copies(path)
    assert copy.read_text() == original
    assert len(caplog.records) == 2
    assert all(str(copy) in r.getMessage() for r in caplog.records)


def test_a_readable_file_is_not_copied(tmp_path: Path) -> None:
    path = tmp_path / "gtc_orders.json"
    save_gtc_orders([_order()], path)
    assert len(load_gtc_orders(path)) == 1
    assert _copies(path) == []


def test_a_copy_that_cannot_be_made_stops_the_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Better not to start than to start and overwrite the only copy."""
    path = tmp_path / "gtc.json"
    path.write_text("{ not json")

    def refuse(*_: object) -> None:
        raise OSError("read-only file system")

    monkeypatch.setattr("edumatcher.engine.persistence.shutil.copy2", refuse)
    with pytest.raises(OSError, match="read-only"):
        load_gtc_orders(path)


@pytest.mark.parametrize("error", [PermissionError, FileNotFoundError])
def test_an_unreadable_config_is_fatal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: type[OSError],
) -> None:
    from edumatcher.engine.main import Engine

    config = tmp_path / "engine_config.yaml"
    config.write_text("symbols: {}\n")

    def unreadable(_: object) -> None:
        raise error("denied")

    monkeypatch.setattr("edumatcher.engine.main.load_engine_config", unreadable)
    monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: None)
    monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: None)

    with caplog.at_level(logging.CRITICAL), pytest.raises(SystemExit) as excinfo:
        Engine(config_path=str(config))

    assert excinfo.value.code == 1
    assert f"FATAL: Config file {config} could not be read" in caplog.text


# --- book_stats.json (WP-ENG04, C7) -------------------------------------------

_GOOD_STATS = {"last_buy_price": 101.0, "last_sell_price": 100.5, "prev_close": 101.0}


@pytest.mark.parametrize(
    "bad",
    [
        {"prev_close": "abc"},
        {"last_buy_price": [1]},
        {"last_sell_price": True},
        {"last_buy_price": float("nan")},
        {"prev_close": -1.0},
        "not an entry",
    ],
)
def test_a_corrupt_book_stats_entry_is_skipped_and_the_file_kept(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, bad: Any
) -> None:
    path = tmp_path / "book_stats.json"
    original = json.dumps({"AAPL": bad, "MSFT": _GOOD_STATS})
    path.write_text(original)

    with caplog.at_level(logging.CRITICAL, logger="edumatcher.engine.persistence"):
        stats, failed = load_book_stats(path)

    assert stats == {"MSFT": _GOOD_STATS}
    assert failed == 1
    (copy,) = _copies(path)
    assert copy.read_text() == original
    (record,) = caplog.records
    assert "AAPL" in record.getMessage()
    assert str(copy) in record.getMessage()


@pytest.mark.parametrize(
    "window",
    [
        {"saved_ns": 1, "reference_price": 10000},  # no trades
        {"saved_ns": "x", "trades": [], "reference_price": 10000},
        {"saved_ns": 1, "trades": [[1, 2, 3]], "reference_price": 10000},
        {"saved_ns": 1, "trades": [[1, 100.5]], "reference_price": 10000},
        {"saved_ns": 1, "trades": [], "reference_price": "x"},
        [],
    ],
)
def test_a_corrupt_breaker_window_is_dropped_and_the_prices_kept(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, window: Any
) -> None:
    path = tmp_path / "book_stats.json"
    path.write_text(json.dumps({"AAPL": {**_GOOD_STATS, "cb_window": window}}))

    with caplog.at_level(logging.CRITICAL, logger="edumatcher.engine.persistence"):
        stats, failed = load_book_stats(path)

    assert stats == {"AAPL": _GOOD_STATS}
    assert failed == 1
    assert len(_copies(path)) == 1
    assert len(caplog.records) == 1


def test_a_well_formed_breaker_window_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "book_stats.json"
    entry = {
        **_GOOD_STATS,
        "cb_window": {"saved_ns": 5, "trades": [[1, 10100]], "reference_price": None},
    }
    path.write_text(json.dumps({"AAPL": entry, "MSFT": {"last_buy_price": None}}))

    assert load_book_stats(path) == (
        {"AAPL": entry, "MSFT": {"last_buy_price": None}},
        0,
    )
    assert _copies(path) == []


@pytest.mark.parametrize("text", ["{ not json", "[]", '"AAPL"'])
def test_an_unreadable_book_stats_file_restores_nothing_and_is_kept(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, text: str
) -> None:
    path = tmp_path / "book_stats.json"
    path.write_text(text)

    with caplog.at_level(logging.CRITICAL, logger="edumatcher.engine.persistence"):
        assert load_book_stats(path) == ({}, 1)

    (copy,) = _copies(path)
    assert copy.read_text() == text
    (record,) = caplog.records
    assert str(copy) in record.getMessage()


def test_a_missing_book_stats_file_is_no_failure(tmp_path: Path) -> None:
    assert load_book_stats(tmp_path / "book_stats.json") == ({}, 0)


def _engine_on_stats_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stats: Any, **kw: Any
) -> tuple[Any, Any]:
    """An engine reading *stats* through the real loader, as ``run`` does."""
    import edumatcher.engine.main as engine_main
    from tests.engine_harness import make_engine

    path = tmp_path / "book_stats.json"
    path.write_text(json.dumps(stats))
    engine, pub = make_engine(monkeypatch, tmp_path, **kw)
    monkeypatch.setattr(engine_main, "load_book_stats", load_book_stats)
    monkeypatch.setattr(engine_main, "BOOK_STATS_FILE", path)
    monkeypatch.setattr(engine_main, "GTC_COMBOS_FILE", tmp_path / "no_combos.json")
    return engine, pub


def test_the_engine_starts_past_a_corrupt_book_stats_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from tests.engine_harness import SYMBOL, msgs

    engine, pub = _engine_on_stats_file(
        monkeypatch,
        tmp_path,
        {SYMBOL: {"prev_close": "abc"}, "MSFT": _GOOD_STATS},
        symbols=(SYMBOL, "MSFT"),
    )

    engine._startup(1)

    (summary,) = msgs(pub, "system.startup_recovery")
    assert summary["failed_book_stats"] == 1
    assert engine.books[SYMBOL].last_trade_price is None
    assert engine.books["MSFT"].last_trade_price == 10100
    assert len(_copies(tmp_path / "book_stats.json")) == 1


def test_a_breaker_without_its_window_is_seeded_from_the_last_price(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from edumatcher.engine.circuit_breaker import (
        CircuitBreakerConfig,
        CircuitBreakerLevel,
    )
    from edumatcher.engine.config_loader import SymbolConfig
    from edumatcher.models.clock import now_ns
    from tests.engine_harness import SYMBOL, msgs

    cb = CircuitBreakerConfig(
        symbol=SYMBOL, levels=[CircuitBreakerLevel("L1", 0.05, 60_000_000_000)]
    )
    window = {"saved_ns": now_ns(), "reference_price": 9000}  # no trades
    engine, pub = _engine_on_stats_file(
        monkeypatch,
        tmp_path,
        {SYMBOL: {**_GOOD_STATS, "cb_window": window}},
        symbol_configs={SYMBOL: SymbolConfig(name=SYMBOL, circuit_breaker=cb)},
    )

    engine._startup(1)

    assert msgs(pub, "system.startup_recovery")[0]["failed_book_stats"] == 1
    assert engine._circuit_breakers[SYMBOL].reference_price == 10100


# --- order and combo fields the restore uses unguarded (WP-ENG04 exit) ---------


@pytest.mark.parametrize(
    "change",
    [
        {"remaining_qty": "4"},
        {"remaining_qty": 0},
        {"remaining_qty": 101},
        {"quantity": 1.5},
        {"ts_ns": "yesterday"},
        {"ts_ns": 10**30},
        {"arrival_seq": None},
        {"symbol": 5},
        {"gateway_id": ["GW01"]},
        {"price_ticks": "100"},
        {"stop_price_ticks": 1.5},
        {"oco_group_id": {"K": 1}},
        {"quote_id": 7},
    ],
)
def test_an_order_with_a_mistyped_field_is_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, change: dict[str, Any]
) -> None:
    path = tmp_path / "gtc_orders.json"
    save_gtc_orders([_order()], path)
    good = json.loads(path.read_text())[0]
    path.write_text(json.dumps([{**good, "id": "bad", **change}, good]))

    with caplog.at_level(logging.CRITICAL, logger="edumatcher.engine.persistence"):
        orders = load_gtc_orders(path)

    assert [o.id for o in orders] == [good["id"]]
    assert len(caplog.records) == 1
    assert len(_copies(path)) == 1


@pytest.mark.parametrize(
    "change",
    [{"timestamp": "today"}, {"timestamp": 10**30}, {"child_order_ids": "abc"}],
)
def test_a_combo_with_a_mistyped_field_is_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, change: dict[str, Any]
) -> None:
    from edumatcher.engine.persistence import save_gtc_combos
    from edumatcher.models.combo import ComboLeg, ComboOrder, ComboType

    combo = ComboOrder(
        id="C1",
        combo_id="c1",
        gateway_id="GW01",
        combo_type=ComboType.AON,
        tif=TIF.DAY,
        legs=[ComboLeg("AAPL", Side.BUY, OrderType.LIMIT, 1, 2, price_ticks=10000)],
        timestamp=1,
        child_order_ids=["L1"],
    )
    path = tmp_path / "gtc_combos.json"
    save_gtc_combos([combo], path)
    good = json.loads(path.read_text())[0]
    path.write_text(json.dumps([{**good, "id": "bad", **change}, good]))

    with caplog.at_level(logging.CRITICAL, logger="edumatcher.engine.persistence"):
        combos = load_gtc_combos(path)

    assert [c.id for c in combos] == ["C1"]
    assert len(caplog.records) == 1


def test_the_engine_starts_past_a_mistyped_day_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import edumatcher.engine.main as engine_main
    from tests.engine_harness import SYMBOL, make_engine, msgs

    path = tmp_path / "gtc_orders.json"
    day = _order()
    day.tif = TIF.DAY
    save_gtc_orders([day], path)
    good = json.loads(path.read_text())[0]
    path.write_text(json.dumps([{**good, "id": "bad", "ts_ns": "x"}, good]))
    engine, pub = make_engine(monkeypatch, tmp_path)
    monkeypatch.setattr(engine_main, "load_gtc_orders", load_gtc_orders)
    monkeypatch.setattr(engine_main, "GTC_ORDERS_FILE", path)
    monkeypatch.setattr(engine_main, "GTC_COMBOS_FILE", tmp_path / "no_combos.json")

    engine._startup(1)

    assert msgs(pub, "system.startup_recovery")[0]["restored_orders"] == 1
    assert [o.id for o in engine.books[SYMBOL].resting_orders()] == [good["id"]]
