"""The engine never starts on state it could not read without saying so loudly.

F1 (docs-design/EduMatcher-Log-Ledger.md §6.2): an unreadable GTC orders or
combos file, or an unreadable entry in one, is copied aside before the engine's
first checkpoint overwrites it, and the CRITICAL message names the copy.
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
