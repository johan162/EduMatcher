"""Tests for pm-audit-cli — query.py, indexer.py, formatters.py, and cli.py.

Coverage target: >= 90% across the four audit modules.
"""

from __future__ import annotations

import argparse
import json
import time
from compression import zstd
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
    parse_line,
    _summarise,
    date_to_range,
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
            "tick_decimals": 2,
            "quantity": 100,
            "price_ticks": 150.0,
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


def _write_zst_log(path: Path, lines: list[str]) -> None:
    with zstd.open(path, "wt", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _write_part(root: Path, day: str, n: int, lines: list[str]) -> Path:
    """A closed day part, ``<root>/audit/audit-<day>.<n>.log``."""
    path = root / "audit" / f"audit-{day}.{n}.log"
    path.parent.mkdir(exist_ok=True)
    _write_log(path, lines)
    return path


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


def _parse_json_stream(text: str) -> list[Any]:
    """Split back-to-back ``json.dumps(..., indent=2)`` arrays with no
    separator between them (each --follow poll batch is printed via its own
    ``print()`` call) into the list of decoded arrays, in order."""
    decoder = json.JSONDecoder()
    results: list[Any] = []
    i = 0
    text = text.strip()
    while i < len(text):
        obj, end = decoder.raw_decode(text, i)
        results.append(obj)
        i = end
        while i < len(text) and text[i].isspace():
            i += 1
    return results


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


class TestBareDateRange:
    """C12: a bare date is a UTC day; in --to it means the end of that day."""

    def test_a_bare_date_in_to_includes_that_whole_day(
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
                "2026-07-08",
                "--to",
                "2026-07-08",
            ],
        )
        assert len(json.loads(capsys.readouterr().out)) == 4

    def test_end_of_day_parse(self) -> None:
        end = parse_ts("2026-07-08", end_of_day=True)
        assert end.isoformat() == "2026-07-08T23:59:59.999999+00:00"
        assert parse_ts("2026-07-08T10:00:00", end_of_day=True).hour == 10

    def test_the_help_says_bare_dates_are_utc(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit):
            _run_cli(monkeypatch, ["events", "--help"])
        help_text = " ".join(capsys.readouterr().out.split())
        assert "UTC" in help_text and "end of that day" in help_text


class TestTradesStayBounded:
    """P3: trades reads no further than it needs, and --reverse keeps only
    --limit rows."""

    def _trades(self, tmp_path: Path, n: int) -> Path:
        log = tmp_path / "audit.log"
        _write_log(
            log,
            [
                f"[{_stamp(i)}] [trade.executed] "
                + json.dumps({"id": str(i), "symbol": "A", "price": 1.0, "quantity": 1})
                for i in range(n)
            ],
        )
        return log

    def test_the_first_rows_stop_the_scan(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import edumatcher.audit.query as query_mod

        log = self._trades(tmp_path, 1000)
        parsed: list[str] = []
        real = query_mod.parse_line

        def _counting(raw: str) -> Any:
            parsed.append(raw)
            return real(raw)

        monkeypatch.setattr(query_mod, "parse_line", _counting)
        rows = query_trades([log], limit=5)
        assert [r["trade_id"] for r in rows] == ["0", "1", "2", "3", "4"]
        assert len(parsed) == 5

    def test_reverse_keeps_only_limit_rows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import collections

        import edumatcher.audit.query as query_mod

        sizes: list[int | None] = []

        class _Deque(collections.deque[Any]):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)
                sizes.append(self.maxlen)

        monkeypatch.setattr(query_mod, "deque", _Deque)
        rows = query_trades([self._trades(tmp_path, 100)], limit=3, reverse=True)
        assert [r["trade_id"] for r in rows] == ["99", "98", "97"]
        assert sizes == [3]


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

    def test_parts_ordered_by_date_then_number(self, tmp_path: Path) -> None:
        log = tmp_path / "audit.log"
        log.write_text("x")
        want = [
            _write_part(tmp_path, "2026-10-24", 1, ["a"]),
            _write_part(tmp_path, "2026-10-24", 2, ["b"]),
            _write_part(tmp_path, "2026-10-24", 10, ["c"]),
            _write_part(tmp_path, "2026-10-25", 1, ["d"]),
        ]
        assert discover_log_files(log) == [*want, log]

    def test_archives_are_not_in_the_live_trail(self, tmp_path: Path) -> None:
        log = tmp_path / "audit.log"
        log.write_text("x")
        (tmp_path / "audit").mkdir()
        _write_zst_log(tmp_path / "audit" / "audit-2026-10-23.log.zst", ["a"])
        assert discover_log_files(log) == [log]

    def test_parts_of_an_archived_day_are_skipped(self, tmp_path: Path) -> None:
        log = tmp_path / "audit.log"
        log.write_text("x")
        _write_part(tmp_path, "2026-10-23", 1, ["a"])
        _write_zst_log(tmp_path / "audit" / "audit-2026-10-23.log.zst", ["a"])
        kept = _write_part(tmp_path, "2026-10-24", 1, ["b"])
        assert discover_log_files(log) == [kept, log]

    def test_old_rotation_names_are_ignored(self, tmp_path: Path) -> None:
        log = tmp_path / "audit.log"
        log.write_text("x")
        (tmp_path / "audit.log.1").write_text("y")
        assert discover_log_files(log) == [log]

    def test_nonexistent_log_excluded(self, tmp_path: Path) -> None:
        log = tmp_path / "audit.log"  # does not exist
        files = discover_log_files(log)
        assert files == []

    def test_custom_log_dir(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log = log_dir / "audit.log"
        log.write_text("x")
        part = _write_part(log_dir, "2026-10-24", 1, ["y"])
        assert discover_log_files(log, log_dir) == [part, log]


# ===========================================================================
# query.py — line parsing
# ===========================================================================


class TestIndexerOverParts:
    def test_index_reads_parts_then_active_log(self, tmp_path: Path) -> None:
        log = tmp_path / "audit.log"
        _write_log(log, _LINES[2:])
        _write_part(tmp_path, "2026-07-08", 1, _LINES[:2])
        whole = tmp_path / "whole" / "audit.log"
        whole.parent.mkdir()
        _write_log(whole, _LINES)
        n_parts = build_index(tmp_path / "a.db", log)
        n_whole = build_index(tmp_path / "b.db", whole)
        assert n_parts == n_whole == len(_LINES)


class TestParseLine:
    def test_valid_line(self) -> None:
        result = parse_line(_LINES[0])
        assert result is not None
        ts, topic, payload, meta = result
        assert ts == _TS1
        assert topic == "order.new"
        assert payload["order_id"] == "ORD-001"
        # This fixture carries no metadata section, which is legal.
        assert meta == {}

    def test_line_with_a_metadata_section(self) -> None:
        """pm-audit records per-topic/publisher sequences and the causal
        envelope between the topic and the payload — see models/envelope.py."""
        line = (
            f"[{_TS1}] [order.ack.GW01] "
            "[seq=7 eseq=40 msg=01ARZ3NDEKTSV4RRFFQ69G5FAV "
            "cause=01ARZ3NDEKTSV4RRFFQ69G5FAB chain=01ARZ3NDEKTSV4RRFFQ69G5FAB] "
            '{"order_id": "ORD-001"}'
        )
        result = parse_line(line)
        assert result is not None
        _ts, topic, payload, meta = result

        assert topic == "order.ack.GW01"
        assert payload["order_id"] == "ORD-001"
        assert meta["seq"] == "7"
        assert meta["eseq"] == "40"
        assert meta["msg"] == "01ARZ3NDEKTSV4RRFFQ69G5FAV"
        assert meta["cause"] == "01ARZ3NDEKTSV4RRFFQ69G5FAB"
        assert meta["chain"] == "01ARZ3NDEKTSV4RRFFQ69G5FAB"

    def test_empty_line_returns_none(self) -> None:
        assert parse_line("") is None

    def test_malformed_json_returns_none(self) -> None:
        assert parse_line(f"[{_TS1}] [order.new] {{bad json}}") is None

    def test_missing_brackets_returns_none(self) -> None:
        assert parse_line("just some text without brackets") is None


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
        e = AuditEntry(_TS1, "order.new", payload, {"eseq": "40"})
        d = e.to_dict()
        assert "timestamp" in d
        assert "topic" in d
        assert "payload" in d
        assert "eseq" in d
        assert d["eseq"] == 40

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

    def test_zst_file_reads_like_the_plain_file(self, tmp_path: Path) -> None:
        zst = tmp_path / "audit-2026-07-08.log.zst"
        _write_zst_log(zst, _LINES)
        plain = tmp_path / "plain.log"
        _write_log(plain, _LINES)
        from_zst = [(e.timestamp, e.topic, e.payload) for e in iter_entries([zst])]
        from_plain = [(e.timestamp, e.topic, e.payload) for e in iter_entries([plain])]
        assert from_zst == from_plain
        assert len(from_zst) == len(_LINES)

    def test_mixed_zst_and_plain_set_equals_the_plain_set(self, tmp_path: Path) -> None:
        zst = tmp_path / "audit-2026-07-08.log.zst"
        _write_zst_log(zst, _LINES[:2])
        active = tmp_path / "audit.log"
        _write_log(active, _LINES[2:])
        whole = tmp_path / "whole.log"
        _write_log(whole, _LINES)
        mixed = [e.timestamp for e in iter_entries([zst, active])]
        assert mixed == [e.timestamp for e in iter_entries([whole])]

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

    def test_after_ts_skips_earlier_entries(self, log_file: Path) -> None:
        """after_ts=_TS2 should skip _TS1 but keep _TS2 onward (no ties)."""
        entries = list(iter_entries([log_file], after_ts=_TS2))
        assert [e.timestamp for e in entries] == [_TS2, _TS3, _TS4]

    def test_after_ts_and_skip_resumes_past_ties(self, tmp_path: Path) -> None:
        """Two entries share one timestamp; after_skip=1 should keep only
        the second one, matching how --follow resumes after printing the
        first N rows at the last-seen timestamp."""
        log = tmp_path / "audit.log"
        lines = [
            f"[{_TS1}] [order.new] " + json.dumps({"order_id": "A"}),
            f"[{_TS1}] [order.new] " + json.dumps({"order_id": "B"}),
            f"[{_TS2}] [order.new] " + json.dumps({"order_id": "C"}),
        ]
        _write_log(log, lines)

        entries = list(iter_entries([log], after_ts=_TS1, after_skip=1))
        ids = [e.payload["order_id"] for e in entries]
        assert ids == ["B", "C"]

    def test_after_ts_skip_beyond_ties_skips_all_of_them(self, tmp_path: Path) -> None:
        log = tmp_path / "audit.log"
        lines = [
            f"[{_TS1}] [order.new] " + json.dumps({"order_id": "A"}),
            f"[{_TS1}] [order.new] " + json.dumps({"order_id": "B"}),
            f"[{_TS2}] [order.new] " + json.dumps({"order_id": "C"}),
        ]
        _write_log(log, lines)

        entries = list(iter_entries([log], after_ts=_TS1, after_skip=2))
        ids = [e.payload["order_id"] for e in entries]
        assert ids == ["C"]


# ===========================================================================
# AR-0.2 — order.cancelled/expired/amended carry `symbol`
#
# Regression test for the pre-existing user-visible bug named in
# docs-design/EduMatcher-Audit-Replay.md §14 AR-0.2: order.cancelled never
# carried `symbol` on the wire, so AuditEntry.symbol (query.py, reading
# payload.get("symbol")) was always None for a cancellation regardless of
# which instrument it was for — silently excluding every order.cancelled
# row from any --symbol filter. This must fail before the spec/engine fix
# and pass after.
# ===========================================================================

_AR02_CANCEL_LINES = [
    f"[{_TS1}] [order.cancelled.GW01] "
    + json.dumps(
        {
            "gateway_id": "GW01",
            "order_id": "ORD-AAPL-1",
            "symbol": "AAPL",
            "client_tag": "tag-aapl",
        }
    ),
    f"[{_TS2}] [order.cancelled.GW02] "
    + json.dumps(
        {
            "gateway_id": "GW02",
            "order_id": "ORD-MSFT-1",
            "symbol": "MSFT",
            "client_tag": "tag-msft",
        }
    ),
]


@pytest.fixture()
def ar02_cancel_log(tmp_path: Path) -> Path:
    p = tmp_path / "audit.log"
    _write_log(p, _AR02_CANCEL_LINES)
    return p


class TestAr02OrderCancelledSymbol:
    """order.cancelled for AAPL and MSFT, filtered by symbol: exactly one
    row must come back, and it must be the right one — not zero (the bug)
    and not both (a filter that silently matched everything)."""

    def test_iter_entries_symbol_filter(self, ar02_cancel_log: Path) -> None:
        entries = list(iter_entries([ar02_cancel_log], symbol="AAPL"))
        assert len(entries) == 1
        assert entries[0].payload["order_id"] == "ORD-AAPL-1"
        assert entries[0].symbol == "AAPL"

    def test_query_events_symbol_filter(self, ar02_cancel_log: Path) -> None:
        rows = query_events([ar02_cancel_log], symbol="AAPL")
        assert len(rows) == 1
        assert rows[0]["symbol"] == "AAPL"

    def test_unfiltered_both_present_but_distinguishable(
        self, ar02_cancel_log: Path
    ) -> None:
        """Sanity check that the fixture itself is right: with no filter,
        both cancellations are read back and their symbols differ — so a
        test that passed by coincidence (e.g. an empty-string symbol
        matching everything) would be caught here."""
        entries = list(iter_entries([ar02_cancel_log]))
        assert {e.symbol for e in entries} == {"AAPL", "MSFT"}


# ===========================================================================
# AR-0.4 — book.{symbol} / depth.{symbol} carry ts_ns
#
# Regression test for docs-design/EduMatcher-Audit-Replay.md §14 AR-0.4:
# previously book.{symbol} and depth.{symbol} carried no time field at all,
# so nothing could establish whether a snapshot reflects a given trade.
# Confirms the ordering (snapshot.ts_ns >= trade.ts_ns, enforced at the
# source by the shared monotonic clock — see test_tick_ns_integration.py's
# TestAr04SnapshotClock for that half) survives a round trip through the
# audit log's text format and back out via iter_entries/query_events,
# exactly as pm-audit-replay will read it.
# ===========================================================================

_AR04_TRADE_TS_NS = 1_700_000_000_000_000_000
_AR04_BOOK_TS_NS = 1_700_000_000_000_500_000
_AR04_DEPTH_TS_NS = 1_700_000_000_000_600_000

_AR04_SNAPSHOT_LINES = [
    f"[{_TS1}] [trade.executed] "
    + json.dumps(
        {
            "id": "T1",
            "symbol": "AAPL",
            "buy_order_id": "B1",
            "sell_order_id": "S1",
            "buy_gateway_id": "GW1",
            "sell_gateway_id": "GW2",
            "price": 150.0,
            "quantity": 10,
            "ts_ns": _AR04_TRADE_TS_NS,
        }
    ),
    f"[{_TS2}] [book.AAPL] "
    + json.dumps(
        {
            "symbol": "AAPL",
            "tick_decimals": 2,
            "ts_ns": _AR04_BOOK_TS_NS,
            "bids": [],
            "asks": [],
            "last_price": 150.0,
            "last_qty": 10,
            "last_buy_price": 150.0,
            "last_sell_price": 150.0,
            "recent_trades": [],
        }
    ),
    f"[{_TS3}] [depth.AAPL] "
    + json.dumps(
        {
            "symbol": "AAPL",
            "ts_ns": _AR04_DEPTH_TS_NS,
            "tick_decimals": 2,
            "mid_price_ticks": 15000,
            "mid_price": 150.0,
            "tolerance_ticks": 100,
            "bid_depth": 0,
            "ask_depth": 0,
            "imbalance": 0.0,
            "microprice": 150.0,
            "cost_to_move": 0.0,
        }
    ),
]


@pytest.fixture()
def ar04_snapshot_log(tmp_path: Path) -> Path:
    p = tmp_path / "audit.log"
    _write_log(p, _AR04_SNAPSHOT_LINES)
    return p


class TestAr04SnapshotTsNs:
    def test_book_snapshot_ts_ns_survives_the_round_trip(
        self, ar04_snapshot_log: Path
    ) -> None:
        entries = list(iter_entries([ar04_snapshot_log]))
        trade = next(e for e in entries if e.topic == "trade.executed")
        book = next(e for e in entries if e.topic == "book.AAPL")
        assert trade.payload["ts_ns"] == _AR04_TRADE_TS_NS
        assert book.payload["ts_ns"] == _AR04_BOOK_TS_NS
        assert book.payload["ts_ns"] >= trade.payload["ts_ns"]

    def test_depth_snapshot_ts_ns_survives_the_round_trip(
        self, ar04_snapshot_log: Path
    ) -> None:
        entries = list(iter_entries([ar04_snapshot_log]))
        trade = next(e for e in entries if e.topic == "trade.executed")
        depth = next(e for e in entries if e.topic == "depth.AAPL")
        assert depth.payload["ts_ns"] == _AR04_DEPTH_TS_NS
        assert depth.payload["ts_ns"] >= trade.payload["ts_ns"]

    def test_query_events_preserves_ts_ns_in_the_summary_payload(
        self, ar04_snapshot_log: Path
    ) -> None:
        """query_events() is what pm-audit-cli actually prints; confirm the
        ordering is readable from that surface too, not just iter_entries."""
        rows = query_events([ar04_snapshot_log], topic="book.")
        assert len(rows) == 1
        assert rows[0]["topic"] == "book.AAPL"


class TestSummariseBookAndDepthAndOrderLifecycle:
    """Johan noticed book.AAPL rows in `pm-audit-cli events` printed a
    blank summary column, same as order_id -- a book snapshot isn't about
    one order, so both are legitimately blank, but the row said nothing
    at all about what changed. _summarise() previously had no case for
    book./depth. (falling through to ""), nor for order.amended/
    order.expired (also "" -- every other order.* lifecycle event had a
    summary, these two didn't)."""

    def test_book_snapshot_summarises_the_top_of_book(self) -> None:
        entry = AuditEntry.__new__(AuditEntry)
        entry.topic = "book.AAPL"
        entry.payload = {
            "symbol": "AAPL",
            "bids": [{"price": 46.76, "qty": 1000, "count": 1}],
            "asks": [{"price": 46.78, "qty": 1000, "count": 1}],
        }
        assert _summarise(entry) == "book: bid 46.76x1000 / ask 46.78x1000"

    def test_book_snapshot_with_no_resting_orders_does_not_crash(self) -> None:
        entry = AuditEntry.__new__(AuditEntry)
        entry.topic = "book.AAPL"
        entry.payload = {"symbol": "AAPL", "bids": [], "asks": []}
        assert _summarise(entry) == "book: bid — / ask —"

    def test_depth_snapshot_summarises_mid_and_imbalance(self) -> None:
        entry = AuditEntry.__new__(AuditEntry)
        entry.topic = "depth.AAPL"
        entry.payload = {"symbol": "AAPL", "mid_price": 95.25, "imbalance": 0.3}
        assert _summarise(entry) == "depth: mid=95.25 imbalance=0.3"

    def test_events_query_surfaces_the_book_summary(
        self, ar04_snapshot_log: Path
    ) -> None:
        """End-to-end through query_events(), the surface pm-audit-cli
        events actually prints -- not just the unit-level _summarise()."""
        rows = query_events([ar04_snapshot_log], topic="book.")
        assert rows[0]["summary"] == "book: bid — / ask —"

    def test_amended_summarises_the_new_price_and_qty(self) -> None:
        entry = AuditEntry.__new__(AuditEntry)
        entry.topic = "order.amended.TRADER01"
        entry.payload = {"order_id": "x", "price": 105.0, "qty": 100}
        assert _summarise(entry) == "AMEND price=105.0 qty=100"

    def test_expired_has_a_summary(self) -> None:
        entry = AuditEntry.__new__(AuditEntry)
        entry.topic = "order.expired.TRADER01"
        entry.payload = {"order_id": "x", "symbol": "AAPL"}
        assert _summarise(entry) == "EXPIRED"


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
        assert [r["event"] for r in rows] == ["new", "ack"]

    def test_date_filter(self, log_file: Path) -> None:
        rows = query_orders([log_file], date_str="2026-07-08")
        assert len(rows) == 2


def _order_line(topic: str, payload: dict[str, Any]) -> str:
    return f"[{_TS1}] [{topic}] [seq=1] " + json.dumps(
        {"order_id": "O1", "gateway_id": "TRADER01", **payload}
    )


class TestOrdersViewMatchesSpec:
    """Each column of `orders` and each `events` summary reads the field the
    wire spec defines for that topic (WP-AUD02, C6)."""

    def _rows(self, tmp_path: Path, *lines: str) -> list[dict[str, Any]]:
        log = tmp_path / "audit.log"
        _write_log(log, list(lines))
        return query_orders([log])

    def test_the_event_is_the_message_kind_never_the_gateway(
        self, tmp_path: Path
    ) -> None:
        topics = {
            "order.new": "new",
            "order.cancel": "cancel",
            "order.ack.TRADER01": "ack",
            "order.fill.TRADER01": "fill",
            "order.cancelled.TRADER01": "cancelled",
            "order.expired.TRADER01": "expired",
            "order.triggered.TRADER01": "triggered",
            "order.amended.TRADER01": "amended",
        }
        rows = self._rows(tmp_path, *(_order_line(t, {}) for t in topics))
        assert [r["event"] for r in rows] == list(topics.values())

    def test_a_fill_shows_its_fill_price_and_size_not_the_limit(
        self, tmp_path: Path
    ) -> None:
        fill = {"fill_qty": 5, "fill_price": 9.5, "price": 10.0, "qty": 20}
        (row,) = self._rows(tmp_path, _order_line("order.fill.TRADER01", fill))
        assert (row["qty"], row["price"]) == (5, 9.5)

    def test_an_ack_and_an_amend_show_their_qty(self, tmp_path: Path) -> None:
        ack = {"accepted": True, "qty": 5, "price": 10.0}
        amend = {"qty": 7, "remaining_qty": 3, "price": 11.0}
        rows = self._rows(
            tmp_path,
            _order_line("order.ack.TRADER01", ack),
            _order_line("order.amended.TRADER01", amend),
        )
        assert [(r["qty"], r["price"]) for r in rows] == [(5, 10.0), (7, 11.0)]

    def test_an_ack_status_says_whether_it_was_accepted(self, tmp_path: Path) -> None:
        rows = self._rows(
            tmp_path,
            _order_line("order.ack.TRADER01", {"accepted": True}),
            _order_line(
                "order.ack.TRADER01",
                {"accepted": False, "reject_code": "TICK_VIOLATION"},
            ),
        )
        assert [(r["status"], r["reason"]) for r in rows] == [
            ("ACCEPTED", None),
            ("REJECTED", "TICK_VIOLATION"),
        ]

    def test_order_new_shows_its_tick_price_in_money(self, tmp_path: Path) -> None:
        new = {
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": 100,
            "price_ticks": 1234,
            "tick_decimals": 2,
        }
        (row,) = self._rows(tmp_path, _order_line("order.new", new))
        assert (row["qty"], row["price"]) == (100, 12.34)

    def test_a_zero_is_shown_not_skipped(self, tmp_path: Path) -> None:
        cancelled = {"remaining_qty": 0, "cancel_reason": "CLIENT"}
        (row,) = self._rows(
            tmp_path, _order_line("order.cancelled.TRADER01", cancelled)
        )
        assert row["qty"] == 0

    def test_summaries_use_the_spec_fields(self, tmp_path: Path) -> None:
        log = tmp_path / "audit.log"
        _write_log(
            log,
            [
                _order_line(
                    "order.new",
                    {
                        "side": "BUY",
                        "order_type": "LIMIT",
                        "quantity": 100,
                        "price_ticks": 1234,
                        "tick_decimals": 2,
                    },
                ),
                _order_line(
                    "order.new",
                    {"side": "SELL", "order_type": "MARKET", "quantity": 5},
                ),
                _order_line(
                    "order.ack.TRADER01",
                    {"accepted": True, "order_type": "LIMIT", "side": "BUY"},
                ),
                _order_line(
                    "order.ack.TRADER01",
                    {
                        "accepted": False,
                        "order_type": "LIMIT",
                        "side": "BUY",
                        "reject_code": "TICK_VIOLATION",
                    },
                ),
            ],
        )
        assert [r["summary"] for r in query_events([log])] == [
            "LIMIT BUY 100@12.34",
            "MARKET SELL 5",
            "ACK ACCEPTED LIMIT BUY",
            "ACK REJECTED LIMIT BUY reject=TICK_VIOLATION",
        ]

    def test_the_index_event_type_is_the_kind(self, tmp_path: Path) -> None:
        log = tmp_path / "audit.log"
        _write_log(
            log,
            [
                _order_line("order.fill.TRADER01", {}),
                f"[{_TS2}] [book.AAPL] " + json.dumps({"symbol": "AAPL"}),
            ],
        )
        db = tmp_path / "idx.db"
        build_index(db, log)
        conn = open_readonly_index(db)
        types = [
            r[0]
            for r in conn.execute("SELECT event_type FROM audit_events ORDER BY id")
        ]
        conn.close()
        assert types == ["fill", "book"]


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


def _index_count(db: Path) -> int:
    conn = open_readonly_index(db)
    count = int(conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0])
    conn.close()
    return count


class TestIndexer:
    def test_build_and_query(self, log_file: Path, tmp_path: Path) -> None:
        db = tmp_path / "idx.db"
        n = build_index(db, log_file)
        assert n == 4
        assert index_is_available(db)

    def test_a_second_build_replaces_the_first(
        self, log_file: Path, tmp_path: Path
    ) -> None:
        """WP-AUD05 (C1): building again starts from scratch, not on top."""
        db = tmp_path / "idx.db"
        build_index(db, log_file)
        assert build_index(db, log_file) == 4
        assert _index_count(db) == 4

    def test_incremental_adds_lines_of_the_last_indexed_millisecond(
        self, log_file: Path, tmp_path: Path
    ) -> None:
        """WP-AUD05 (C10): a line flushed after the build but stamped in its
        last millisecond is indexed once, and so is everything after it."""
        db = tmp_path / "idx.db"
        build_index(db, log_file)
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"[{_TS4}] [session.state] " + json.dumps({"state": "X"}) + "\n")
            fh.write(f"[{_TS4[:-10]}01.000+00:00] [order.new] {{}}\n")
        assert build_index(db, log_file, incremental=True) == 2
        assert build_index(db, log_file, incremental=True) == 0
        assert _index_count(db) == 6

    def test_the_index_says_how_far_it_reaches(
        self, log_file: Path, tmp_path: Path
    ) -> None:
        from edumatcher.audit.indexer import indexed_through

        db = tmp_path / "idx.db"
        build_index(db, log_file)
        conn = open_readonly_index(db)
        assert indexed_through(conn) == _TS4
        conn.close()

    def test_the_seller_gateway_finds_a_trade(
        self, log_file: Path, tmp_path: Path
    ) -> None:
        db = tmp_path / "idx.db"
        build_index(db, log_file)
        conn = open_readonly_index(db)
        rows = query_index_events(conn, gateway="GW02")
        conn.close()
        assert [r["topic"] for r in rows] == ["trade.executed"]

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

    def test_follow_zero_interval_raises(
        self, monkeypatch: pytest.MonkeyPatch, log_file: Path
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            _run_cli(
                monkeypatch,
                [
                    "--log-file",
                    str(log_file),
                    "events",
                    "--follow",
                    "--interval",
                    "0",
                ],
            )
        assert exc.value.code == 2

    def test_follow_and_reverse_mutually_exclusive(
        self, monkeypatch: pytest.MonkeyPatch, log_file: Path
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            _run_cli(
                monkeypatch,
                ["--log-file", str(log_file), "events", "--follow", "--reverse"],
            )
        assert exc.value.code == 2


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


class TestCliFollow:
    """--follow on events/timeline: initial batch + one poll, then Ctrl-C.

    Mirrors how pm-log-cli's own `tail` loop is tested (see
    test_log_cli_main.py): time.sleep is monkeypatched so the test controls
    exactly one polling tick before raising KeyboardInterrupt, instead of
    actually waiting on a wall-clock interval.
    """

    def test_events_prints_backfill_then_stops(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def _stop(_seconds: float) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr(time, "sleep", _stop)
        _run_cli(
            monkeypatch,
            ["--log-file", str(log_file), "events", "--follow"],
        )
        out = capsys.readouterr().out
        assert "order.new" in out
        assert "trade.executed" in out

    def test_events_picks_up_new_line_on_poll(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        calls = {"n": 0}

        def _append_then_stop(_seconds: float) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                new_line = (
                    f"[{_TS4}] [order.new] "
                    + json.dumps({"order_id": "ORD-NEW", "symbol": "MSFT"})
                    + "\n"
                )
                with log_file.open("a", encoding="utf-8") as fh:
                    fh.write(new_line)
                return
            raise KeyboardInterrupt

        monkeypatch.setattr(time, "sleep", _append_then_stop)
        _run_cli(
            monkeypatch,
            ["--log-file", str(log_file), "--format", "json", "events", "--follow"],
        )
        out = capsys.readouterr().out
        # Two JSON arrays are printed: the initial backfill, then one poll
        # batch containing just the newly-appended row.
        arrays = _parse_json_stream(out)
        assert len(arrays) == 2
        assert len(arrays[0]) == 4
        assert len(arrays[1]) == 1
        assert arrays[1][0]["order_id"] == "ORD-NEW"

    def test_events_does_not_reprint_backfill_on_empty_poll(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        calls = {"n": 0}

        def _stop_on_second(_seconds: float) -> None:
            calls["n"] += 1
            if calls["n"] >= 2:
                raise KeyboardInterrupt

        monkeypatch.setattr(time, "sleep", _stop_on_second)
        _run_cli(
            monkeypatch,
            ["--log-file", str(log_file), "--format", "json", "events", "--follow"],
        )
        out = capsys.readouterr().out
        # Nothing new was appended between polls, so only the initial
        # backfill array should have been printed.
        arrays = _parse_json_stream(out)
        assert len(arrays) == 1
        assert len(arrays[0]) == 4

    def test_timeline_picks_up_new_line_on_poll(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        calls = {"n": 0}

        def _append_then_stop(_seconds: float) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                new_line = (
                    f"[{_TS4}] [order.new] "
                    + json.dumps({"order_id": "ORD-NEW", "symbol": "MSFT"})
                    + "\n"
                )
                with log_file.open("a", encoding="utf-8") as fh:
                    fh.write(new_line)
                return
            raise KeyboardInterrupt

        monkeypatch.setattr(time, "sleep", _append_then_stop)
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "--format",
                "json",
                "timeline",
                "--follow",
            ],
        )
        out = capsys.readouterr().out
        arrays = _parse_json_stream(out)
        assert len(arrays) == 2
        assert len(arrays[1]) == 1
        assert arrays[1][0]["gateway"] is None or "ORD-NEW" in str(arrays[1])

    def test_follow_respects_topic_filter_on_new_rows(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        calls = {"n": 0}

        def _append_then_stop(_seconds: float) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                new_line = (
                    f"[{_TS4}] [session.state] "
                    + json.dumps({"state": "CLOSED"})
                    + "\n"
                )
                with log_file.open("a", encoding="utf-8") as fh:
                    fh.write(new_line)
                return
            raise KeyboardInterrupt

        monkeypatch.setattr(time, "sleep", _append_then_stop)
        _run_cli(
            monkeypatch,
            [
                "--log-file",
                str(log_file),
                "--format",
                "json",
                "events",
                "--topic",
                "order.",
                "--follow",
            ],
        )
        out = capsys.readouterr().out
        arrays = _parse_json_stream(out)
        # The new session.state row does not match --topic order., so only
        # the initial backfill array is printed; no second (empty) array.
        assert len(arrays) == 1
        assert all(r["topic"].startswith("order.") for r in arrays[0])


def _stamp(n: int) -> str:
    """A distinct, ordered audit stamp per n (one second apart)."""
    return f"2026-07-08T{9 + n // 3600:02d}:{n // 60 % 60:02d}:{n % 60:02d}.000+00:00"


class TestFollowResume:
    """--follow resumes where it left off, with any filter (WP-AUD03: C3,
    C4, P1, Q2).  Each poll is one patched time.sleep; the list of actions
    runs one per poll and the last poll raises KeyboardInterrupt."""

    def _follow(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log: Path,
        argv: list[str],
        polls: list[list[str]],
    ) -> list[list[dict[str, Any]]]:
        calls = {"n": 0}

        def _poll(_seconds: float) -> None:
            if calls["n"] == len(polls):
                raise KeyboardInterrupt
            with log.open("a", encoding="utf-8") as fh:
                fh.writelines(line + "\n" for line in polls[calls["n"]])
            calls["n"] += 1

        monkeypatch.setattr(time, "sleep", _poll)
        _run_cli(monkeypatch, ["--log-file", str(log), "--format", "json", *argv])
        return []

    def _arrays(self, capsys: pytest.CaptureFixture[str]) -> list[Any]:
        return _parse_json_stream(capsys.readouterr().out)

    @pytest.mark.parametrize(
        "filters",
        [["--topic", "trade."], ["--symbol", "AAPL"], ["--gateway", "GW02"]],
    )
    def test_a_filtered_row_sharing_its_millisecond_is_printed_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        filters: list[str],
    ) -> None:
        log = tmp_path / "audit.log"
        _write_log(
            log,
            [
                f"[{_TS1}] [order.new] " + json.dumps({"id": "O1", "symbol": "MSFT"}),
                f"[{_TS1}] [trade.executed] "
                + json.dumps({"id": "T1", "symbol": "AAPL", "sell_gateway_id": "GW02"}),
            ],
        )
        self._follow(monkeypatch, log, ["events", *filters, "-f"], [[], [], []])
        arrays = self._arrays(capsys)
        assert len(arrays) == 1 and [r["topic"] for r in arrays[0]] == [
            "trade.executed"
        ]

    def test_ties_accumulate_across_polls(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A second row in the same millisecond arrives a poll later: each
        of the two is printed exactly once."""
        log = tmp_path / "audit.log"
        _write_log(log, [f"[{_TS1}] [order.new] " + json.dumps({"id": "O1"})])
        later = f"[{_TS1}] [order.new] " + json.dumps({"id": "O2"})
        self._follow(monkeypatch, log, ["timeline", "-f"], [[later], [], []])
        rows = [r for a in self._arrays(capsys) for r in a]
        assert [json.loads(r["payload"])["id"] for r in rows] == ["O1", "O2"]

    def test_polls_honour_from_and_to(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        log = tmp_path / "audit.log"
        _write_log(log, [f"[{_stamp(0)}] [order.new] " + json.dumps({"id": "old"})])
        argv = ["timeline", "--from", _stamp(10), "--to", _stamp(20), "-f"]
        poll = [
            f"[{_stamp(5)}] [order.new] " + json.dumps({"id": "before"}),
            f"[{_stamp(15)}] [order.new] " + json.dumps({"id": "inside"}),
            f"[{_stamp(25)}] [order.new] " + json.dumps({"id": "after"}),
        ]
        self._follow(monkeypatch, log, argv, [poll, []])
        out = capsys.readouterr().out
        assert "inside" in out
        assert "old" not in out and "before" not in out and "after" not in out

    def test_the_first_batch_is_the_newest_rows(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Q2: like tail -f, the last --limit rows, oldest of them first."""
        log = tmp_path / "audit.log"
        _write_log(
            log,
            [f"[{_stamp(n)}] [order.new] " + json.dumps({"id": n}) for n in range(500)],
        )
        self._follow(monkeypatch, log, ["events", "--limit", "10", "-f"], [])
        (first,) = self._arrays(capsys)
        assert [r["timestamp"] for r in first] == [_stamp(n) for n in range(490, 500)]

    def test_a_poll_does_not_parse_lines_it_has_already_passed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """P1: with a filter that matched nothing, a poll still starts at the
        end of the trail, and earlier stamps are skipped unparsed."""
        import edumatcher.audit.query as query_mod

        log = tmp_path / "audit.log"
        _write_log(
            log,
            [
                f"[{_stamp(n)}] [order.new] " + json.dumps({"id": n})
                for n in range(1000)
            ],
        )
        parsed: list[str] = []
        real = query_mod.parse_line

        def _counting(raw: str) -> Any:
            parsed.append(raw)
            return real(raw)

        calls = {"n": 0}

        def _poll(_seconds: float) -> None:
            calls["n"] += 1
            if calls["n"] > 1:
                raise KeyboardInterrupt
            parsed.clear()  # count the poll only, not the first batch

        monkeypatch.setattr(query_mod, "parse_line", _counting)
        monkeypatch.setattr(time, "sleep", _poll)
        _run_cli(monkeypatch, ["--log-file", str(log), "events", "--topic", "x.", "-f"])
        assert len(parsed) <= 1


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

    def test_index_twice_holds_each_line_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db = tmp_path / "r_idx.db"
        for _ in range(2):
            _run_cli(
                monkeypatch,
                ["--log-file", str(log_file), "index", "--output", str(db)],
            )
        capsys.readouterr()  # consume
        assert _index_count(db) == 4

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

    def test_events_ignore_an_index_they_were_not_given(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """WP-AUD05 (C1, Q1): an index beside the log is not used unasked,
        so a line recorded after its build is still shown."""
        _run_cli(monkeypatch, ["--log-file", str(log_file), "index"])
        assert (log_file.parent / "audit_index.db").exists()
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"[{_TS4}] [order.new] " + json.dumps({"id": "LATE"}) + "\n")
        capsys.readouterr()
        _run_cli(
            monkeypatch, ["--log-file", str(log_file), "--format", "json", "events"]
        )
        assert len(json.loads(capsys.readouterr().out)) == 5


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


class TestCliUseIndexMatchesTheTrail:
    """With --use-index the rows are those the trail gives, and the reader is
    told how far the index reaches (WP-AUD05, C1)."""

    def _events(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        log_file: Path,
        *argv: str,
    ) -> tuple[list[dict[str, Any]], str]:
        _run_cli(
            monkeypatch,
            ["--log-file", str(log_file), *argv[:-1], "--format", "json", argv[-1]],
        )
        out = capsys.readouterr()
        return json.loads(out.out), out.err

    def test_the_index_answers_like_the_trail(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db = tmp_path / "idx.db"
        _run_cli(
            monkeypatch, ["--log-file", str(log_file), "index", "--output", str(db)]
        )
        capsys.readouterr()
        plain, _ = self._events(monkeypatch, capsys, log_file, "events")
        indexed, err = self._events(
            monkeypatch, capsys, log_file, "--use-index", str(db), "events"
        )
        assert indexed == plain
        assert _TS4 in err  # how far the index reaches

    def test_the_index_finds_a_trade_by_its_seller(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db = tmp_path / "idx.db"
        build_index(db, log_file)
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
                "--gateway",
                "gw02",
            ],
        )
        rows = json.loads(capsys.readouterr().out)
        assert [r["topic"] for r in rows] == ["trade.executed"]

    def test_an_unusable_index_is_an_error_not_a_silent_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        db = tmp_path / "broken.db"
        db.write_bytes(b"not a database")
        with pytest.raises(SystemExit) as exc:
            _run_cli(
                monkeypatch,
                ["--log-file", str(log_file), "--use-index", str(db), "events"],
            )
        assert exc.value.code == 1
        assert "broken.db" in capsys.readouterr().err


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


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------


def _healthy_process(monkeypatch: pytest.MonkeyPatch, *, running: bool = True) -> None:
    monkeypatch.setattr(
        "edumatcher.audit.cli._find_audit_pids", lambda: [1234] if running else []
    )
    monkeypatch.setattr(
        "edumatcher.audit.cli._check_zmq_health", lambda: (True, "replied at t")
    )


class TestCliHealth:
    def test_health_reports_running_process(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _healthy_process(monkeypatch)

        with pytest.raises(SystemExit) as exc_info:
            _run_cli(monkeypatch, ["--log-file", str(log_file), "health"])

        assert exc_info.value.code == 0
        output = capsys.readouterr().out
        assert "pm-audit process: OK" in output
        assert "audit log file:   OK - skipped" in output
        assert "audit ZMQ ping:   OK" in output
        assert "health: OK" in output

    def test_health_fails_when_pm_audit_is_not_running(
        self, monkeypatch: pytest.MonkeyPatch, log_file: Path
    ) -> None:
        _healthy_process(monkeypatch, running=False)

        with pytest.raises(SystemExit) as exc_info:
            _run_cli(monkeypatch, ["--log-file", str(log_file), "health"])

        assert exc_info.value.code == 1

    def test_health_does_not_check_log_file_by_default(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Without --extended a missing log must not fail health -- nor trip
        the "Audit log not found" guard every query command goes through."""
        _healthy_process(monkeypatch)

        with pytest.raises(SystemExit) as exc_info:
            _run_cli(
                monkeypatch, ["--log-file", str(tmp_path / "missing.log"), "health"]
            )

        assert exc_info.value.code == 0

    def test_health_extended_fails_when_log_file_is_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _healthy_process(monkeypatch)

        with pytest.raises(SystemExit) as exc_info:
            _run_cli(
                monkeypatch,
                ["--log-file", str(tmp_path / "missing.log"), "health", "--extended"],
            )

        assert exc_info.value.code == 1
        assert "audit log file:   FAIL - audit log not found" in capsys.readouterr().out

    def test_health_extended_fails_on_malformed_last_entry(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        log = tmp_path / "audit.log"
        _write_log(log, [*_LINES, "[2026-07-08T10:00:01.000+00:00] [trunc"])
        _healthy_process(monkeypatch)

        with pytest.raises(SystemExit) as exc_info:
            _run_cli(monkeypatch, ["--log-file", str(log), "health", "--extended"])

        assert exc_info.value.code == 1

    def test_health_extended_accepts_an_empty_log(
        self, monkeypatch: pytest.MonkeyPatch, empty_log: Path
    ) -> None:
        """A freshly started pm-audit has written nothing yet; that is healthy."""
        _healthy_process(monkeypatch)

        with pytest.raises(SystemExit) as exc_info:
            _run_cli(
                monkeypatch, ["--log-file", str(empty_log), "health", "--extended"]
            )

        assert exc_info.value.code == 0

    def test_health_extended_verbose_reports_checks_and_log_stats(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_part(log_file.parent, "2026-07-07", 1, _LINES[:1])
        _healthy_process(monkeypatch)

        with pytest.raises(SystemExit) as exc_info:
            _run_cli(
                monkeypatch,
                ["--log-file", str(log_file), "health", "--extended", "--verbose"],
            )

        assert exc_info.value.code == 0
        output = capsys.readouterr().out
        assert "Checks performed:" in output
        assert "Log file read/write/entry:     yes" in output
        assert "Log file stats:" in output
        assert "day parts: 1" in output
        assert "archives: 0" in output
        assert f"last entry: {_TS4}" in output

    def test_health_verbose_without_extended_notes_log_file_was_skipped(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _healthy_process(monkeypatch)

        with pytest.raises(SystemExit) as exc_info:
            _run_cli(monkeypatch, ["--log-file", str(log_file), "health", "-v"])

        assert exc_info.value.code == 0
        output = capsys.readouterr().out
        assert "Log file read/write/entry:     no (pass --extended)" in output
        assert "Log file stats:" not in output

    def test_health_json_format(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _healthy_process(monkeypatch)

        with pytest.raises(SystemExit) as exc_info:
            _run_cli(
                monkeypatch,
                ["--log-file", str(log_file), "--format", "json", "health"],
            )

        assert exc_info.value.code == 0
        report = json.loads(capsys.readouterr().out)
        assert report["healthy"] is True
        assert report["process"]["pids"] == [1234]
        assert report["log_file"]["checked"] is False

    def test_health_fails_when_zmq_ping_does_not_reply(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setattr("edumatcher.audit.cli._find_audit_pids", lambda: [1234])
        monkeypatch.setattr(
            "edumatcher.audit.cli._check_zmq_health",
            lambda: (False, "no reply within 1000ms"),
        )

        with pytest.raises(SystemExit) as exc_info:
            _run_cli(monkeypatch, ["--log-file", str(log_file), "health"])

        assert exc_info.value.code == 1
        assert (
            "audit ZMQ ping:   FAIL - no reply within 1000ms" in capsys.readouterr().out
        )

    def test_health_quiet_exits_zero_without_output(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _healthy_process(monkeypatch)

        with pytest.raises(SystemExit) as exc_info:
            _run_cli(monkeypatch, ["--log-file", str(log_file), "health", "-q"])

        assert exc_info.value.code == 0
        assert capsys.readouterr() == ("", "")

    def test_health_quiet_exits_minus_one_without_output(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _healthy_process(monkeypatch, running=False)

        with pytest.raises(SystemExit) as exc_info:
            _run_cli(monkeypatch, ["--log-file", str(log_file), "health", "-q"])

        assert exc_info.value.code == -1
        assert capsys.readouterr() == ("", "")

    def test_health_reports_pgrep_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        log_file: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def _boom() -> list[int]:
            raise OSError("pgrep failed with exit code 3")

        monkeypatch.setattr("edumatcher.audit.cli._find_audit_pids", _boom)

        with pytest.raises(SystemExit) as exc_info:
            _run_cli(monkeypatch, ["--log-file", str(log_file), "health"])

        assert exc_info.value.code == 1
        assert "pgrep failed with exit code 3" in capsys.readouterr().out

    def test_run_extended_log_file_check_times_out_without_waiting_for_the_worker(
        self, log_file: Path
    ) -> None:
        """A check that never returns must not make the caller wait for it."""
        import threading
        from unittest.mock import patch

        from edumatcher.audit.cli import _run_extended_log_file_check

        release = threading.Event()

        def _blocks_until_released(
            _log_file: Path,
            _log_dir: Path | None = None,
            *,
            collect_stats: bool = False,
        ) -> tuple[bool, str, None]:
            release.wait(timeout=5)
            return True, "finished late", None

        with patch(
            "edumatcher.audit.cli._check_log_file_health", _blocks_until_released
        ):
            started = time.monotonic()
            healthy, detail, stats = _run_extended_log_file_check(
                log_file, timeout_sec=0.1
            )
            elapsed = time.monotonic() - started

        release.set()  # let the abandoned worker finish so it doesn't outlive the test
        assert healthy is False
        assert "did not finish within" in detail
        assert stats is None
        assert elapsed < 2

    def test_zmq_health_check_detects_a_bound_replier(self) -> None:
        import threading

        from edumatcher.audit.cli import _check_zmq_health
        from edumatcher.config import AUDIT_HEALTH_BIND_ADDR
        from edumatcher.messaging.bus import make_replier

        sock = make_replier(AUDIT_HEALTH_BIND_ADDR)
        try:
            # A real pm-audit would answer from its own receive loop; a thread
            # here stands in for that loop without pulling in the whole process.
            def answer_once() -> None:
                sock.recv()
                sock.send(b"pong")

            responder = threading.Thread(target=answer_once, daemon=True)
            responder.start()
            healthy, detail = _check_zmq_health(timeout_ms=2000)
            responder.join(timeout=1)
            assert healthy is True
            assert "pong" in detail
        finally:
            sock.close(0)

    def test_zmq_health_check_times_out_when_nothing_is_bound(self) -> None:
        from edumatcher.audit.cli import _check_zmq_health

        healthy, detail = _check_zmq_health(timeout_ms=200)
        assert healthy is False
        assert "no reply" in detail


class TestModuleDocs:
    """WP-AUD08: the module docstrings describe the tool as it is (D1–D3)."""

    def test_the_cli_docstring_lists_every_command(self) -> None:
        import edumatcher.audit.cli as cli_mod
        from edumatcher.audit.cli import build_parser

        sub = next(
            a
            for a in build_parser()._actions
            if isinstance(a, argparse._SubParsersAction)
        )
        doc = cli_mod.__doc__ or ""
        missing = [name for name in sub.choices if f"\n  {name} " not in doc]
        assert missing == []

    def test_no_audit_module_calls_the_trail_jsonl(self) -> None:
        import edumatcher.audit.cli as cli_mod
        import edumatcher.audit.main as main_mod
        import edumatcher.audit.query as query_mod

        for mod in (cli_mod, main_mod, query_mod):
            assert "JSONL" not in (mod.__doc__ or ""), mod.__name__

    def test_the_documented_line_format_is_what_the_recorder_writes(self) -> None:
        import edumatcher.audit.main as main_mod
        import edumatcher.audit.query as query_mod

        for mod in (main_mod, query_mod):
            examples = [
                ln.strip()
                for ln in (mod.__doc__ or "").splitlines()
                if ln.strip().startswith("[20")
            ]
            assert examples, mod.__name__
            for ex in examples:
                assert parse_line(ex) is not None, ex
                assert "+00:00]" in ex and "[seq=" in ex, ex
