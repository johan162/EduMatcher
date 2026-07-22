"""Tests for pm-audit-cli — query.py, indexer.py, formatters.py, and cli.py.

Coverage target: >= 90% across the four audit modules.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from edumatcher.audit.cli import main as cli_main
from edumatcher.audit.formatters import (
    render,
    render_csv,
    render_json,
    render_stats,
    render_table,
    stringify,
)
from edumatcher.audit.indexer import (
    build_index,
    index_is_available,
    open_readonly_index,
    query_index_events,
)
from edumatcher.audit.query import (
    AuditEntry,
    date_to_range,
    _parse_line,
    discover_log_files,
    iter_entries,
    parse_ts,
    query_events,
    query_gateways,
    query_orders,
    query_stats,
    query_timeline,
    query_topics,
    query_trades,
    validate_date,
    validate_iso_ts,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_TS1 = "2026-07-08T09:30:00.123+00:00"
_TS2 = "2026-07-08T09:30:01.456+00:00"
_TS3 = "2026-07-08T09:30:02.789+00:00"
_TS4 = "2026-07-08T10:00:00.000+00:00"

_LINES = [
    f"[{_TS1}] [order.new] "
    + json.dumps(
        {
            "order_id": "ORD-001",
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": 100,
            "price": 150.0,
        }
    ),
    f"[{_TS2}] [order.ack.GW01] "
    + json.dumps(
        {
            "order_id": "ORD-001",
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "side": "BUY",
            "status": "ACCEPTED",
            "order_type": "LIMIT",
        }
    ),
    f"[{_TS3}] [trade.executed] "
    + json.dumps(
        {
            "id": "TRD-001",
            "trade_id": "TRD-001",
            "symbol": "AAPL",
            "price": 150.0,
            "quantity": 100,
            "buy_gateway_id": "GW01",
            "sell_gateway_id": "GW02",
            "aggressor_side": "BUY",
        }
    ),
    f"[{_TS4}] [session.state] "
    + json.dumps({"state": "CONTINUOUS", "phase": "CONTINUOUS"}),
]


def _write_log(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_gz_log(path: Path, lines: list[str]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


@pytest.fixture()
def log_file(tmp_path: Path) -> Path:
    p = tmp_path / "audit.log"
    _write_log(p, _LINES)
    return p


@pytest.fixture()
def empty_log(tmp_path: Path) -> Path:
    p = tmp_path / "audit.log"
    p.write_text("", encoding="utf-8")
    return p


def _run_cli(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    monkeypatch.setattr("sys.argv", ["pm-audit-cli", *argv])
    cli_main()


# ===========================================================================
# query.py — timestamp helpers
# ===========================================================================


class TestParseTs:
    def test_date_only(self) -> None:
        from datetime import timezone

        dt = parse_ts("2026-07-08")
        assert dt.tzinfo == timezone.utc
        assert dt.year == 2026
        assert dt.day == 8

    def test_iso_with_offset(self) -> None:
        dt = parse_ts("2026-07-08T09:30:00+00:00")
        assert dt.hour == 9

    def test_iso_z_suffix(self) -> None:
        dt = parse_ts("2026-07-08T09:30:00Z")
        assert dt.minute == 30

    def test_iso_no_tzinfo_becomes_utc(self) -> None:
        from datetime import timezone

        dt = parse_ts("2026-07-08T09:30:00")
        assert dt.tzinfo == timezone.utc

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_ts("not-a-date")


class TestValidateDate:
    def test_valid(self) -> None:
        validate_date("2026-07-08")  # should not raise

    def test_invalid_format(self) -> None:
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            validate_date("07/08/2026")

    def test_invalid_date(self) -> None:
        with pytest.raises(ValueError):
            validate_date("2026-13-01")


class TestValidateIsoTs:
    def test_valid(self) -> None:
        validate_iso_ts("2026-07-08T09:30:00+00:00")  # no raise

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            validate_iso_ts("garbage")


class TestDateToRange:
    def test_full_day(self) -> None:
        start, end = date_to_range("2026-07-08")
        assert start.hour == 0
        assert end.hour == 23
        assert end.second == 59


# ===========================================================================
# query.py — log file discovery
# ===========================================================================


class TestDiscoverLogFiles:
    def test_only_active_log(self, tmp_path: Path) -> None:
        log = tmp_path / "audit.log"
        log.write_text("x")
        files = discover_log_files(log)
        assert files == [log]

    def test_rotated_backups_ordered_oldest_first(self, tmp_path: Path) -> None:
        log = tmp_path / "audit.log"
        log.write_text("x")
        (tmp_path / "audit.log.1").write_text("y")
        (tmp_path / "audit.log.2").write_text("z")
        files = discover_log_files(log)
        # .2 is older than .1 in RotatingFileHandler convention
        assert files[0].name == "audit.log.2"
        assert files[1].name == "audit.log.1"
        assert files[-1].name == "audit.log"

    def test_gz_rotated_backup(self, tmp_path: Path) -> None:
        log = tmp_path / "audit.log"
        log.write_text("x")
        gz = tmp_path / "audit.log.1.gz"
        gz.write_bytes(b"")
        files = discover_log_files(log)
        names = [f.name for f in files]
        assert "audit.log.1.gz" in names

    def test_nonexistent_log_excluded(self, tmp_path: Path) -> None:
        log = tmp_path / "audit.log"  # does not exist
        files = discover_log_files(log)
        assert files == []

    def test_custom_log_dir(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log = log_dir / "audit.log"
        log.write_text("x")
        (log_dir / "audit.log.1").write_text("y")
        files = discover_log_files(log, log_dir)
        assert any("audit.log.1" in f.name for f in files)


# ===========================================================================
# query.py — line parsing
# ===========================================================================


class TestParseLine:
    def test_valid_line(self) -> None:
        result = _parse_line(_LINES[0])
        assert result is not None
        ts, topic, payload = result
        assert ts == _TS1
        assert topic == "order.new"
        assert payload["order_id"] == "ORD-001"

    def test_empty_line_returns_none(self) -> None:
        assert _parse_line("") is None

    def test_malformed_json_returns_none(self) -> None:
        assert _parse_line(f"[{_TS1}] [order.new] {{bad json}}") is None

    def test_missing_brackets_returns_none(self) -> None:
        assert _parse_line("just some text without brackets") is None


# ===========================================================================
# query.py — AuditEntry
# ===========================================================================


class TestAuditEntry:
    def test_order_entry_fields(self) -> None:
        payload = {
            "order_id": "ORD-001",
            "gateway_id": "GW01",
            "symbol": "AAPL",
            "side": "BUY",
        }
        e = AuditEntry(_TS1, "order.new", payload)
        assert e.gateway_id == "GW01"
        assert e.symbol == "AAPL"
        assert e.order_id == "ORD-001"
        assert e.trade_id is None

    def test_trade_entry_fields(self) -> None:
        payload = {
            "trade_id": "TRD-001",
            "symbol": "AAPL",
            "buy_gateway_id": "GW01",
            "sell_gateway_id": "GW02",
        }
        e = AuditEntry(_TS3, "trade.executed", payload)
        assert e.trade_id == "TRD-001"
        assert e.gateway_id == "GW01"

    def test_to_dict_keys(self) -> None:
        payload = {"gateway_id": "GW01", "symbol": "AAPL"}
        e = AuditEntry(_TS1, "order.new", payload)
        d = e.to_dict()
        assert "timestamp" in d
        assert "topic" in d
        assert "payload" in d

    def test_buy_gateway_fallback(self) -> None:
        payload = {"buy_gateway_id": "GW_BUY"}
        e = AuditEntry(_TS1, "trade.executed", payload)
        assert e.gateway_id == "GW_BUY"


# ===========================================================================
# query.py — iter_entries with filters
# ===========================================================================


class TestIterEntries:
    def test_all_lines_no_filter(self, log_file: Path) -> None:
        entries = list(iter_entries([log_file]))
        assert len(entries) == 4

    def test_topic_prefix_filter(self, log_file: Path) -> None:
        entries = list(iter_entries([log_file], topic_prefix="order."))
        assert all(e.topic.startswith("order.") for e in entries)
        assert len(entries) == 2

    def test_gateway_filter(self, log_file: Path) -> None:
        entries = list(iter_entries([log_file], gateway="GW01"))
        assert all(
            e.gateway_id == "GW01"
            or e.payload.get("buy_gateway_id") == "GW01"
            or e.payload.get("sell_gateway_id") == "GW01"
            for e in entries
        )

    def test_symbol_filter(self, log_file: Path) -> None:
        entries = list(iter_entries([log_file], symbol="AAPL"))
        assert all(e.symbol == "AAPL" for e in entries)

    def test_limit(self, log_file: Path) -> None:
        entries = list(iter_entries([log_file], limit=2))
        assert len(entries) == 2

    def test_from_dt_filter(self, log_file: Path) -> None:
        from_dt = parse_ts("2026-07-08T09:30:01+00:00")
        entries = list(iter_entries([log_file], from_dt=from_dt))
        assert all(parse_ts(e.timestamp) >= from_dt for e in entries)

    def test_to_dt_filter(self, log_file: Path) -> None:
        to_dt = parse_ts("2026-07-08T09:30:01+00:00")
        entries = list(iter_entries([log_file], to_dt=to_dt))
        assert all(parse_ts(e.timestamp) <= to_dt for e in entries)

    def test_nonexistent_file_skipped(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.log"
        entries = list(iter_entries([missing]))
        assert entries == []

    def test_gz_file_readable(self, tmp_path: Path) -> None:
        gz = tmp_path / "audit.log.1.gz"
        _write_gz_log(gz, [_LINES[0]])
        entries = list(iter_entries([gz]))
        assert len(entries) == 1

    def test_empty_file(self, empty_log: Path) -> None:
        entries = list(iter_entries([empty_log]))
        assert entries == []

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        log = tmp_path / "audit.log"
        log.write_text("garbage line\n" + _LINES[0] + "\n")
        entries = list(iter_entries([log]))
        assert len(entries) == 1

    def test_gateway_trade_buy_sell_fallback(self, log_file: Path) -> None:
        """GW02 appears only as sell_gateway_id — should still be found."""
        entries = list(iter_entries([log_file], gateway="GW02"))
        assert len(entries) >= 1


# ===========================================================================
# query.py — command query functions
# ===========================================================================


class TestQueryEvents:
    def test_basic(self, log_file: Path) -> None:
        rows = query_events([log_file])
        assert len(rows) == 4
        assert "timestamp" in rows[0]
        assert "topic" in rows[0]
        assert "summary" in rows[0]

    def test_topic_filter(self, log_file: Path) -> None:
        rows = query_events([log_file], topic="trade.")
        assert all(r["topic"].startswith("trade.") for r in rows)

    def test_limit(self, log_file: Path) -> None:
        rows = query_events([log_file], limit=2)
        assert len(rows) == 2

    def test_reverse(self, log_file: Path) -> None:
        rows = query_events([log_file], limit=2, reverse=True)
        assert rows[0]["timestamp"] > rows[-1]["timestamp"]

    def test_date_filter(self, log_file: Path) -> None:
        rows = query_events([log_file], date_str="2026-07-08")
        assert len(rows) == 4

    def test_date_filter_no_match(self, log_file: Path) -> None:
        rows = query_events([log_file], date_str="2025-01-01")
        assert rows == []

    def test_gateway_filter(self, log_file: Path) -> None:
        rows = query_events([log_file], gateway="GW01")
        assert len(rows) >= 1

    def test_symbol_filter(self, log_file: Path) -> None:
        rows = query_events([log_file], symbol="AAPL")
        assert all(r["symbol"] == "AAPL" for r in rows if r["symbol"])

    def test_summary_trade(self, log_file: Path) -> None:
        rows = query_events([log_file], topic="trade.executed")
        assert "AAPL" in rows[0]["summary"]

    def test_summary_order_ack(self, log_file: Path) -> None:
        rows = query_events([log_file], topic="order.ack")
        assert "ACK" in rows[0]["summary"]

    def test_summary_order_new(self, log_file: Path) -> None:
        rows = query_events([log_file], topic="order.new")
        assert "LIMIT" in rows[0]["summary"] or "BUY" in rows[0]["summary"]

    def test_summary_session(self, log_file: Path) -> None:
        rows = query_events([log_file], topic="session.")
        assert "CONTINUOUS" in rows[0]["summary"]


class TestQueryOrders:
    def test_all_order_events(self, log_file: Path) -> None:
        rows = query_orders([log_file])
        assert len(rows) == 2  # order.new + order.ack.GW01

    def test_filter_by_id(self, log_file: Path) -> None:
        rows = query_orders([log_file], order_ids=["ORD-001"])
        assert all(r["order_id"] == "ORD-001" for r in rows)

    def test_unknown_id_returns_empty(self, log_file: Path) -> None:
        rows = query_orders([log_file], order_ids=["UNKNOWN"])
        assert rows == []

    def test_gateway_filter(self, log_file: Path) -> None:
        rows = query_orders([log_file], gateway="GW01")
        assert len(rows) >= 1

    def test_limit(self, log_file: Path) -> None:
        rows = query_orders([log_file], limit=1)
        assert len(rows) == 1

    def test_event_column(self, log_file: Path) -> None:
        rows = query_orders([log_file])
        events = {r["event"] for r in rows}
        assert "new" in events or "GW01" in events  # topic suffix varies

    def test_date_filter(self, log_file: Path) -> None:
        rows = query_orders([log_file], date_str="2026-07-08")
        assert len(rows) == 2


class TestQueryTrades:
    def test_finds_trade(self, log_file: Path) -> None:
        rows = query_trades([log_file])
        assert len(rows) == 1
        assert rows[0]["trade_id"] == "TRD-001"
        assert rows[0]["symbol"] == "AAPL"

    def test_symbol_filter(self, log_file: Path) -> None:
        rows = query_trades([log_file], symbol="AAPL")
        assert len(rows) == 1

    def test_symbol_no_match(self, log_file: Path) -> None:
        rows = query_trades([log_file], symbol="MSFT")
        assert rows == []

    def test_gateway_filter_buyer(self, log_file: Path) -> None:
        rows = query_trades([log_file], gateway="GW01")
        assert len(rows) == 1

    def test_gateway_filter_seller(self, log_file: Path) -> None:
        rows = query_trades([log_file], gateway="GW02")
        assert len(rows) == 1

    def test_buy_gateway_filter(self, log_file: Path) -> None:
        rows = query_trades([log_file], buy_gateway="GW01")
        assert len(rows) == 1

    def test_sell_gateway_filter(self, log_file: Path) -> None:
        rows = query_trades([log_file], sell_gateway="GW02")
        assert len(rows) == 1

    def test_buy_gateway_no_match(self, log_file: Path) -> None:
        rows = query_trades([log_file], buy_gateway="GW99")
        assert rows == []

    def test_sell_gateway_no_match(self, log_file: Path) -> None:
        rows = query_trades([log_file], sell_gateway="GW99")
        assert rows == []

    def test_gateway_no_match(self, log_file: Path) -> None:
        rows = query_trades([log_file], gateway="GW99")
        assert rows == []

    def test_min_price_filter(self, log_file: Path) -> None:
        rows = query_trades([log_file], min_price=100.0)
        assert len(rows) == 1

    def test_min_price_excludes(self, log_file: Path) -> None:
        rows = query_trades([log_file], min_price=200.0)
        assert rows == []

    def test_max_price_filter(self, log_file: Path) -> None:
        rows = query_trades([log_file], max_price=200.0)
        assert len(rows) == 1

    def test_max_price_excludes(self, log_file: Path) -> None:
        rows = query_trades([log_file], max_price=100.0)
        assert rows == []

    def test_min_qty_filter(self, log_file: Path) -> None:
        rows = query_trades([log_file], min_qty=50)
        assert len(rows) == 1

    def test_min_qty_excludes(self, log_file: Path) -> None:
        rows = query_trades([log_file], min_qty=999)
        assert rows == []

    def test_date_filter(self, log_file: Path) -> None:
        rows = query_trades([log_file], date_str="2026-07-08")
        assert len(rows) == 1

    def test_reverse(self, log_file: Path) -> None:
        # Build log with two trades
        extra_line = f"[{_TS4}] [trade.executed] " + json.dumps(
            {
                "trade_id": "TRD-002",
                "symbol": "MSFT",
                "price": 420.0,
                "quantity": 50,
                "buy_gateway_id": "GW01",
                "sell_gateway_id": "GW02",
            }
        )
        from pathlib import Path as P
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("\n".join(_LINES + [extra_line]) + "\n")
            tmp = P(f.name)
        try:
            rows = query_trades([tmp], reverse=True)
            assert rows[0]["trade_id"] == "TRD-002"
        finally:
            os.unlink(tmp)


class TestQueryTopics:
    def test_all_topics(self, log_file: Path) -> None:
        rows = query_topics([log_file])
        topics = {r["topic"] for r in rows}
        assert "order.new" in topics
        assert "trade.executed" in topics

    def test_prefix_filter(self, log_file: Path) -> None:
        rows = query_topics([log_file], prefix="order.")
        assert all(r["topic"].startswith("order.") for r in rows)

    def test_sort_count(self, log_file: Path) -> None:
        rows = query_topics([log_file], sort_by="count")
        counts = [r["count"] for r in rows]
        assert counts == sorted(counts, reverse=True)

    def test_sort_alpha(self, log_file: Path) -> None:
        rows = query_topics([log_file], sort_by="alpha")
        names = [r["topic"] for r in rows]
        assert names == sorted(names)

    def test_has_timestamps(self, log_file: Path) -> None:
        rows = query_topics([log_file])
        for r in rows:
            assert r["first_seen"]
            assert r["last_seen"]

    def test_date_filter(self, log_file: Path) -> None:
        rows = query_topics([log_file], date_str="2026-07-08")
        assert len(rows) > 0

    def test_date_no_match(self, log_file: Path) -> None:
        rows = query_topics([log_file], date_str="2025-01-01")
        assert rows == []


class TestQueryGateways:
    def test_finds_gateways(self, log_file: Path) -> None:
        rows = query_gateways([log_file])
        gw_ids = {r["gateway_id"] for r in rows}
        assert "GW01" in gw_ids

    def test_counts(self, log_file: Path) -> None:
        rows = query_gateways([log_file])
        gw01 = next(r for r in rows if r["gateway_id"] == "GW01")
        assert gw01["events"] >= 1

    def test_min_events_filter(self, log_file: Path) -> None:
        rows = query_gateways([log_file], min_events=99999)
        assert rows == []

    def test_date_filter(self, log_file: Path) -> None:
        rows = query_gateways([log_file], date_str="2026-07-08")
        assert len(rows) >= 1

    def test_sorted_by_events_desc(self, log_file: Path) -> None:
        rows = query_gateways([log_file])
        counts = [r["events"] for r in rows]
        assert counts == sorted(counts, reverse=True)

    def test_orders_fills_trades_counted(self, log_file: Path) -> None:
        rows = query_gateways([log_file])
        gw01 = next((r for r in rows if r["gateway_id"] == "GW01"), None)
        assert gw01 is not None
        assert gw01["orders"] >= 1
        assert gw01["trades"] >= 1


class TestQueryTimeline:
    def test_returns_all(self, log_file: Path) -> None:
        rows = query_timeline([log_file])
        assert len(rows) == 4

    def test_topic_filter(self, log_file: Path) -> None:
        rows = query_timeline([log_file], topic_prefix="order.")
        assert all(r["topic"].startswith("order.") for r in rows)

    def test_limit(self, log_file: Path) -> None:
        rows = query_timeline([log_file], limit=2)
        assert len(rows) == 2

    def test_payload_is_json_string(self, log_file: Path) -> None:
        rows = query_timeline([log_file])
        # payload should be a JSON string
        parsed = json.loads(rows[0]["payload"])
        assert isinstance(parsed, dict)


class TestQueryStats:
    def test_basic(self, log_file: Path) -> None:
        stats = query_stats([log_file])
        assert stats["total_events"] == 4
        assert stats["file_count"] == 1
        assert stats["topic_count"] == 4

    def test_verbose_includes_file_list(self, log_file: Path) -> None:
        stats = query_stats([log_file], verbose=True)
        assert len(stats["files"]) == 1
        assert stats["files"][0]["events"] == 4

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.log"
        stats = query_stats([missing])
        assert stats["total_events"] == 0

    def test_oldest_newest(self, log_file: Path) -> None:
        stats = query_stats([log_file])
        assert stats["oldest_event"] == _TS1
        assert stats["newest_event"] == _TS4


# ===========================================================================
# indexer.py
# ===========================================================================


class TestIndexer:
    def test_build_and_query(self, log_file: Path, tmp_path: Path) -> None:
        db = tmp_path / "idx.db"
        n = build_index(db, log_file)
        assert n == 4
        assert index_is_available(db)

    def test_rebuild_clears_old_data(self, log_file: Path, tmp_path: Path) -> None:
        db = tmp_path / "idx.db"
        build_index(db, log_file)
        n = build_index(db, log_file, rebuild=True)
        conn = open_readonly_index(db)
        count = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0]
        conn.close()
        assert count == n  # should not be doubled

    def test_incremental_no_duplicate(self, log_file: Path, tmp_path: Path) -> None:
        db = tmp_path / "idx.db"
        build_index(db, log_file)
        n2 = build_index(db, log_file, incremental=True)
        # All entries already indexed — incremental should add 0 new rows
        assert n2 == 0

    def test_days_filter(self, log_file: Path, tmp_path: Path) -> None:
        db = tmp_path / "idx.db"
        # Very old days window — should find nothing for recent log
        n = build_index(db, log_file, days=0)
        # days=0 means now - 0 = now, so from_dt == to_dt, nothing matches
        assert n == 0

    def test_query_events_topic_filter(self, log_file: Path, tmp_path: Path) -> None:
        db = tmp_path / "idx.db"
        build_index(db, log_file)
        conn = open_readonly_index(db)
        rows = query_index_events(conn, topic_prefix="trade.")
        conn.close()
        assert len(rows) == 1

    def test_query_events_gateway_filter(self, log_file: Path, tmp_path: Path) -> None:
        db = tmp_path / "idx.db"
        build_index(db, log_file)
        conn = open_readonly_index(db)
        rows = query_index_events(conn, gateway="GW01")
        conn.close()
        assert len(rows) >= 1

    def test_query_events_symbol_filter(self, log_file: Path, tmp_path: Path) -> None:
        db = tmp_path / "idx.db"
        build_index(db, log_file)
        conn = open_readonly_index(db)
        rows = query_index_events(conn, symbol="AAPL")
        conn.close()
        assert len(rows) >= 1

    def test_query_events_limit(self, log_file: Path, tmp_path: Path) -> None:
        db = tmp_path / "idx.db"
        build_index(db, log_file)
        conn = open_readonly_index(db)
        rows = query_index_events(conn, limit=2)
        conn.close()
        assert len(rows) == 2

    def test_query_events_reverse(self, log_file: Path, tmp_path: Path) -> None:
        db = tmp_path / "idx.db"
        build_index(db, log_file)
        conn = open_readonly_index(db)
        rows = query_index_events(conn, limit=10, reverse=True)
        conn.close()
        if len(rows) >= 2:
            assert rows[0]["timestamp"] >= rows[-1]["timestamp"]

    def test_query_events_date_filter(self, log_file: Path, tmp_path: Path) -> None:
        db = tmp_path / "idx.db"
        build_index(db, log_file)
        conn = open_readonly_index(db)
        rows = query_index_events(conn, date_str="2026-07-08")
        conn.close()
        assert len(rows) == 4

    def test_index_not_available_missing_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.db"
        assert not index_is_available(missing)

    def test_open_readonly_missing_raises(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope.db"
        with pytest.raises(FileNotFoundError):
            open_readonly_index(missing)

    def test_batch_size_respected(self, log_file: Path, tmp_path: Path) -> None:
        db = tmp_path / "idx.db"
        # batch_size=1 forces many small inserts
        n = build_index(db, log_file, batch_size=1)
        assert n == 4

    def test_from_dt_to_dt_filter(self, log_file: Path, tmp_path: Path) -> None:
        db = tmp_path / "idx.db"
        from_dt = parse_ts("2026-07-08T09:30:00+00:00")
        to_dt = parse_ts("2026-07-08T09:30:02+00:00")
        n = build_index(db, log_file, from_dt=from_dt, to_dt=to_dt)
        assert n == 2  # _TS1 and _TS2 only (not _TS3 at 09:30:02.789)


# ===========================================================================
# formatters.py
# ===========================================================================


class TestStringify:
    def test_none(self) -> None:
        assert stringify(None) == ""

    def test_float(self) -> None:
        assert stringify(1.5) == "1.5"
        assert stringify(1.0) == "1"

    def test_dict_to_json(self) -> None:
        result = stringify({"a": 1})
        assert '"a"' in result

    def test_string_passthrough(self) -> None:
        assert stringify("hello") == "hello"

    def test_int(self) -> None:
        assert stringify(42) == "42"


class TestRenderTable:
    def test_empty_rows_prints_no_match(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        render_table([], ["col1"])
        out = capsys.readouterr().out
        assert "No matching events found." in out

    def test_header_row(self, capsys: pytest.CaptureFixture[str]) -> None:
        rows = [{"col1": "val1", "col2": "val2"}]
        render_table(rows, ["col1", "col2"])
        out = capsys.readouterr().out
        assert "col1" in out
        assert "col2" in out
        assert "val1" in out

    def test_no_header_flag(self, capsys: pytest.CaptureFixture[str]) -> None:
        rows = [{"col1": "v"}]
        render_table(rows, ["col1"], no_header=True)
        out = capsys.readouterr().out
        assert "col1" not in out
        assert "v" in out

    def test_alignment(self, capsys: pytest.CaptureFixture[str]) -> None:
        rows = [{"a": "short"}, {"a": "much longer value"}]
        render_table(rows, ["a"])
        out = capsys.readouterr().out
        # All non-header lines should be the same length
        lines = [ln for ln in out.splitlines() if "---" not in ln and "a " not in ln]
        lengths = {len(ln) for ln in lines if ln.strip()}
        assert len(lengths) == 1


class TestRenderJson:
    def test_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        render_json([], ["col"])
        assert capsys.readouterr().out.strip() == "[]"

    def test_projects_columns(self, capsys: pytest.CaptureFixture[str]) -> None:
        rows = [{"a": 1, "b": 2, "c": 3}]
        render_json(rows, ["a", "c"])
        out = json.loads(capsys.readouterr().out)
        assert "b" not in out[0]
        assert out[0]["a"] == 1

    def test_preserves_types(self, capsys: pytest.CaptureFixture[str]) -> None:
        rows = [{"x": None, "y": 3.14}]
        render_json(rows, ["x", "y"])
        out = json.loads(capsys.readouterr().out)
        assert out[0]["x"] is None
        assert abs(out[0]["y"] - 3.14) < 1e-9


class TestRenderCsv:
    def test_header_present(self, capsys: pytest.CaptureFixture[str]) -> None:
        rows = [{"col1": "val1"}]
        render_csv(rows, ["col1"])
        out = capsys.readouterr().out
        assert out.splitlines()[0] == "col1"

    def test_no_header(self, capsys: pytest.CaptureFixture[str]) -> None:
        rows = [{"col1": "val1"}]
        render_csv(rows, ["col1"], no_header=True)
        out = capsys.readouterr().out
        assert out.strip() == "val1"

    def test_empty_rows_prints_only_header(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        render_csv([], ["col1", "col2"])
        out = capsys.readouterr().out.strip()
        assert out == "col1,col2"

    def test_empty_no_header(self, capsys: pytest.CaptureFixture[str]) -> None:
        render_csv([], ["col1"], no_header=True)
        out = capsys.readouterr().out.strip()
        assert out == ""


class TestRender:
    def test_dispatch_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        render([], ["col"], "json")
        assert capsys.readouterr().out.strip() == "[]"

    def test_dispatch_csv(self, capsys: pytest.CaptureFixture[str]) -> None:
        render([], ["col"], "csv")
        assert "col" in capsys.readouterr().out

    def test_dispatch_table(self, capsys: pytest.CaptureFixture[str]) -> None:
        render([], ["col"], "table")
        assert "No matching" in capsys.readouterr().out

    def test_dispatch_unknown_defaults_table(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        render([], ["col"], "unknown_fmt")
        assert "No matching" in capsys.readouterr().out


class TestRenderStats:
    def test_basic_output(self, capsys: pytest.CaptureFixture[str]) -> None:
        stats = {
            "total_events": 1234,
            "total_bytes": 2048,
            "compressed_bytes": 0,
            "file_count": 2,
            "oldest_event": "2026-07-01T09:30:00",
            "newest_event": "2026-07-08T16:00:00",
            "topic_count": 10,
            "gateway_count": 3,
            "files": [],
        }
        render_stats(stats)
        out = capsys.readouterr().out
        assert "1,234" in out
        assert "2.0 KB" in out

    def test_verbose_per_file(self, capsys: pytest.CaptureFixture[str]) -> None:
        stats = {
            "total_events": 10,
            "total_bytes": 100,
            "compressed_bytes": 0,
            "file_count": 1,
            "oldest_event": None,
            "newest_event": None,
            "topic_count": 5,
            "gateway_count": 1,
            "files": [{"file": "/tmp/a.log", "events": 10, "size_bytes": 100}],
        }
        render_stats(stats, verbose=True)
        out = capsys.readouterr().out
        assert "a.log" in out

    def test_compressed_size_shown(self, capsys: pytest.CaptureFixture[str]) -> None:
        stats: dict[str, Any] = {
            "total_events": 5,
            "total_bytes": 2_097_152,
            "compressed_bytes": 1_048_576,
            "file_count": 2,
            "oldest_event": None,
            "newest_event": None,
            "topic_count": 2,
            "gateway_count": 1,
            "files": [],
        }
        render_stats(stats)
        out = capsys.readouterr().out
        assert "compressed" in out

    def test_gb_format(self, capsys: pytest.CaptureFixture[str]) -> None:
        stats: dict[str, Any] = {
            "total_events": 5,
            "total_bytes": 2_000_000_000,
            "compressed_bytes": 0,
            "file_count": 1,
            "oldest_event": None,
            "newest_event": None,
            "topic_count": 1,
            "gateway_count": 0,
            "files": [],
        }
        render_stats(stats)
        out = capsys.readouterr().out
        assert "GB" in out

    def test_na_when_no_events(self, capsys: pytest.CaptureFixture[str]) -> None:
        stats: dict[str, Any] = {
            "total_events": 0,
            "total_bytes": 0,
            "compressed_bytes": 0,
            "file_count": 0,
            "oldest_event": None,
            "newest_event": None,
            "topic_count": 0,
            "gateway_count": 0,
            "files": [],
        }
        render_stats(stats)
        out = capsys.readouterr().out
        assert "n/a" in out


# ===========================================================================
# cli.py — argument validation
# ===========================================================================


class TestValidateArgs:
    def test_invalid_limit_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SystemExit) as exc:
            _run_cli(monkeypatch, ["--log-file", "/dev/null", "events", "--limit", "0"])
        assert exc.value.code == 2

    def test_invalid_date_raises(
        self, monkeypatch: pytest.MonkeyPatch, log_file: Path
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            _run_cli(
                monkeypatch,
                ["--log-file", str(log_file), "events", "--date", "08/07/2026"],
            )
        assert exc.value.code == 2

    def test_invalid_from_ts_raises(
        self, monkeypatch: pytest.MonkeyPatch, log_file: Path
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            _run_cli(
                monkeypatch,
                ["--log-file", str(log_file), "events", "--from", "not-a-ts"],
            )
        assert exc.value.code == 2

    def test_rebuild_and_incremental_mutually_exclusive(
        self, monkeypatch: pytest.MonkeyPatch, log_file: Path
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            _run_cli(
                monkeypatch,
                [
                    "--log-file",
                    str(log_file),
                    "index",
                    "--rebuild",
                    "--incremental",
                ],
            )
        assert exc.value.code == 2

    def test_index_days_zero_invalid(
        self, monkeypatch: pytest.MonkeyPatch, log_file: Path
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            _run_cli(
                monkeypatch,
                ["--log-file", str(log_file), "index", "--days", "0"],
            )
        assert exc.value.code == 2

    def test_missing_log_file_exits_1(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        missing = tmp_path / "nope.log"
        with pytest.raises(SystemExit) as exc:
            _run_cli(monkeypatch, ["--log-file", str(missing), "events"])
        assert exc.value.code == 1


# ===========================================================================
# cli.py — command dispatch (end-to-end via main())
# ===========================================================================


class TestCliEvents:
    def test_table_output(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(monkeypatch, ["--log-file", str(log_file), "events"])
        out = capsys.readouterr().out
        assert "order.new" in out

    def test_json_output(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            ["--log-file", str(log_file), "--format", "json", "events"],
        )
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)
        assert len(data) == 4

    def test_csv_output(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            ["--log-file", str(log_file), "--format", "csv", "events"],
        )
        lines = capsys.readouterr().out.strip().splitlines()
        assert lines[0].startswith("timestamp")
        assert len(lines) == 5  # header + 4 data rows

    def test_no_header_csv(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "--format",
                "csv",
                "--no-header",
                "events",
            ],
        )
        lines = capsys.readouterr().out.strip().splitlines()
        assert len(lines) == 4

    def test_topic_filter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "events",
                "--topic",
                "trade.executed",
            ],
        )
        out = capsys.readouterr().out
        assert "trade.executed" in out

    def test_limit_flag(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "--format",
                "json",
                "events",
                "--limit",
                "2",
            ],
        )
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 2

    def test_reverse_flag(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "--format",
                "json",
                "events",
                "--reverse",
            ],
        )
        data = json.loads(capsys.readouterr().out)
        assert data[0]["timestamp"] >= data[-1]["timestamp"]

    def test_empty_result_table(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "events",
                "--symbol",
                "NONEXISTENT",
            ],
        )
        out = capsys.readouterr().out
        assert "No matching" in out

    def test_gateway_filter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "--format",
                "json",
                "events",
                "--gateway",
                "GW01",
            ],
        )
        data = json.loads(capsys.readouterr().out)
        assert len(data) >= 1

    def test_date_filter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "--format",
                "json",
                "events",
                "--date",
                "2026-07-08",
            ],
        )
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 4


class TestCliOrders:
    def test_basic(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(monkeypatch, ["--log-file", str(log_file), "orders"])
        out = capsys.readouterr().out
        assert "ORD-001" in out

    def test_id_filter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            ["--log-file", str(log_file), "orders", "--id", "ORD-001"],
        )
        out = capsys.readouterr().out
        assert "ORD-001" in out

    def test_json_format(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            ["--log-file", str(log_file), "--format", "json", "orders"],
        )
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)


class TestCliTrades:
    def test_basic(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(monkeypatch, ["--log-file", str(log_file), "trades"])
        out = capsys.readouterr().out
        assert "TRD-001" in out or "AAPL" in out

    def test_symbol_filter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "--format",
                "json",
                "trades",
                "--symbol",
                "AAPL",
            ],
        )
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 1

    def test_min_qty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "--format",
                "json",
                "trades",
                "--min-qty",
                "999",
            ],
        )
        data = json.loads(capsys.readouterr().out)
        assert data == []

    def test_buy_sell_gateway(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "--format",
                "json",
                "trades",
                "--buy-gateway",
                "GW01",
                "--sell-gateway",
                "GW02",
            ],
        )
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 1

    def test_csv_export(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            ["--log-file", str(log_file), "--format", "csv", "trades"],
        )
        lines = capsys.readouterr().out.strip().splitlines()
        assert "timestamp" in lines[0]


class TestCliTopics:
    def test_basic(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(monkeypatch, ["--log-file", str(log_file), "topics"])
        out = capsys.readouterr().out
        assert "order.new" in out

    def test_sort_alpha(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            ["--log-file", str(log_file), "topics", "--sort", "alpha"],
        )
        out = capsys.readouterr().out
        assert "order" in out

    def test_prefix_filter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "--format",
                "json",
                "topics",
                "--prefix",
                "order.",
            ],
        )
        data = json.loads(capsys.readouterr().out)
        assert all(r["topic"].startswith("order.") for r in data)


class TestCliGateways:
    def test_basic(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(monkeypatch, ["--log-file", str(log_file), "gateways"])
        out = capsys.readouterr().out
        assert "GW01" in out

    def test_min_events_excludes_all(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            ["--log-file", str(log_file), "gateways", "--min-events", "9999"],
        )
        out = capsys.readouterr().out
        assert "No matching" in out

    def test_json_format(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            ["--log-file", str(log_file), "--format", "json", "gateways"],
        )
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)
        assert any(r["gateway_id"] == "GW01" for r in data)


class TestCliTimeline:
    def test_basic(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(monkeypatch, ["--log-file", str(log_file), "timeline"])
        out = capsys.readouterr().out
        assert "order.new" in out

    def test_limit(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "--format",
                "json",
                "timeline",
                "--limit",
                "2",
            ],
        )
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 2

    def test_topic_filter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "--format",
                "json",
                "timeline",
                "--topic",
                "trade.",
            ],
        )
        data = json.loads(capsys.readouterr().out)
        assert all(r["topic"].startswith("trade.") for r in data)


class TestCliStats:
    def test_basic(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(monkeypatch, ["--log-file", str(log_file), "stats"])
        out = capsys.readouterr().out
        assert "Total events" in out
        assert "4" in out

    def test_verbose(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            ["--log-file", str(log_file), "stats", "--verbose"],
        )
        out = capsys.readouterr().out
        assert "Per-file" in out

    def test_empty_log(
        self,
        monkeypatch: pytest.MonkeyPatch,
        empty_log: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(monkeypatch, ["--log-file", str(empty_log), "stats"])
        out = capsys.readouterr().out
        assert "0" in out


class TestCliIndex:
    def test_build_index(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db = tmp_path / "test_idx.db"
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "index",
                "--output",
                str(db),
            ],
        )
        out = capsys.readouterr().out
        assert "Done" in out
        assert db.exists()

    def test_rebuild_flag(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db = tmp_path / "r_idx.db"
        _run_cli(
            monkeypatch,
            ["--log-file", str(log_file), "index", "--output", str(db)],
        )
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "index",
                "--output",
                str(db),
                "--rebuild",
            ],
        )
        capsys.readouterr()  # consume
        assert db.exists()

    def test_incremental_flag(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db = tmp_path / "inc_idx.db"
        _run_cli(
            monkeypatch,
            ["--log-file", str(log_file), "index", "--output", str(db)],
        )
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "index",
                "--output",
                str(db),
                "--incremental",
            ],
        )
        out = capsys.readouterr().out
        # Second incremental run should report 0 new rows
        assert "0 rows" in out

    def test_events_use_index(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When index exists events command should use it transparently."""
        db = log_file.parent / "audit_index.db"
        _run_cli(
            monkeypatch,
            ["--log-file", str(log_file), "index", "--output", str(db)],
        )
        capsys.readouterr()
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "--format",
                "json",
                "events",
            ],
        )
        data = json.loads(capsys.readouterr().out)
        assert len(data) >= 1


class TestCliIndexTimeRange:
    def test_index_with_from_to(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db = tmp_path / "range_idx.db"
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "index",
                "--output",
                str(db),
                "--from",
                "2026-07-08T09:30:00+00:00",
                "--to",
                "2026-07-08T10:00:00+00:00",
            ],
        )
        out = capsys.readouterr().out
        assert "Done" in out
        assert db.exists()

    def test_events_from_to_filter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "--format",
                "json",
                "events",
                "--from",
                "2026-07-08T09:30:00+00:00",
                "--to",
                "2026-07-08T09:30:02+00:00",
            ],
        )
        data = json.loads(capsys.readouterr().out)
        assert len(data) <= 4


class TestCliUseIndexFlag:
    def test_explicit_use_index_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db = tmp_path / "explicit.db"
        _run_cli(
            monkeypatch,
            ["--log-file", str(log_file), "index", "--output", str(db)],
        )
        capsys.readouterr()
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "--use-index",
                str(db),
                "--format",
                "json",
                "events",
            ],
        )
        data = json.loads(capsys.readouterr().out)
        assert len(data) >= 1


class TestCliLogDir:
    def test_log_dir_used_for_rotated_files(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log = log_dir / "audit.log"
        _write_log(log, _LINES)
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log),
                "--log-dir",
                str(log_dir),
                "--format",
                "json",
                "events",
            ],
        )
        data = json.loads(capsys.readouterr().out)
        assert len(data) == 4
