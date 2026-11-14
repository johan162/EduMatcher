"""WP-STA08: small items (C7, C11)."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.models.message import encode
from edumatcher.stats.cli import _check_database_health
from edumatcher.stats.main import SCHEMA, SCHEMA_VERSION, StatsProcess

TRADE = {
    "id": "000001-000000001",
    "symbol": "AAPL",
    "price": 100.0,
    "quantity": 10,
    "ts_ns": 1_792_850_048_220_023_754,
    "tick_decimals": 2,
}


# --- C7 ----------------------------------------------------------------------


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_the_health_write_check_fails_on_a_read_only_database(tmp_path: Path) -> None:
    db = tmp_path / "stats.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    conn.close()
    db.chmod(0o444)
    try:
        healthy, detail, _ = _check_database_health(db)
    finally:
        db.chmod(0o644)
    assert not healthy
    assert "read/write" in detail


def test_the_health_write_check_passes_on_a_writable_database(tmp_path: Path) -> None:
    db = tmp_path / "stats.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    conn.close()
    healthy, _, _ = _check_database_health(db)
    assert healthy
    check = sqlite3.connect(db)
    tables = [row[0] for row in check.execute("SELECT name FROM sqlite_master")]
    check.close()
    assert "pm_stats_health_check" not in tables  # rolled back


# --- C11 ---------------------------------------------------------------------


@pytest.fixture
def sp(tmp_path: Path) -> Iterator[StatsProcess]:
    with (
        patch("edumatcher.stats.main.make_subscriber", return_value=MagicMock()),
        patch("edumatcher.stats.main.make_pusher", return_value=MagicMock()),
        patch("edumatcher.stats.main.make_replier", return_value=MagicMock()),
    ):
        proc = StatsProcess(tmp_path / "stats.db")
    yield proc
    proc._running = False
    proc.close()


@pytest.mark.parametrize("missing", [{"id": ""}, {"id": None}])
def test_a_trade_without_an_id_is_refused_not_deduplicated(
    sp: StatsProcess, missing: dict[str, Any]
) -> None:
    sub: Any = sp.sub
    for payload in (
        {**TRADE, **missing},
        {**TRADE, **missing, "quantity": 20},
        TRADE,
    ):
        sub.recv_multipart.return_value = encode("trade.executed", payload)
        sp._receive_one_engine_message()
    ids = [row[0] for row in sp._conn.execute("SELECT trade_id FROM trade_log")]
    assert ids == [TRADE["id"]]
    metrics = {m.name: m.value for m in sp.metric_samples()}
    assert metrics["stats.records_dropped"] == 2
    assert not sp._trade_seq_disabled
