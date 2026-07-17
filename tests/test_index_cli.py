"""Tests for src/edumatcher/index/cli.py — read-only structural/audit index history query tool.

pm-index's JSONL history is a structural/corporate-action audit log only
(INIT, CORP_ACTION, ADD_CONSTITUENT, DELIST). Level and EOD time-series
history lives in pm-stats' SQLite tables instead (see test_stats_*.py /
pm-stats-cli index-daily / index-snapshots).
"""

from __future__ import annotations

import json
import time
from argparse import Namespace
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.index.cli import (
    _build_parser,
    _cmd_events,
    _cmd_indices,
    _project_event,
    _read_jsonl,
    _render,
    _render_csv,
    _render_json,
    _render_table,
    _resolve_history_files,
    _resolve_index_ids,
    _resolve_time_range,
    _stringify,
    _ts_to_str,
    main,
)
from edumatcher.index.cli import _parse_ts

# ---------------------------------------------------------------------------
# _parse_ts
# ---------------------------------------------------------------------------


class TestParseTs:
    def test_plain_date(self) -> None:
        ts = _parse_ts("2026-06-01")
        from datetime import datetime, timezone

        expected = datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp()
        assert ts == pytest.approx(expected)

    def test_iso8601_with_Z(self) -> None:
        ts = _parse_ts("2026-06-01T09:30:00Z")
        from datetime import datetime, timezone

        expected = datetime(2026, 6, 1, 9, 30, 0, tzinfo=timezone.utc).timestamp()
        assert ts == pytest.approx(expected)

    def test_iso8601_with_offset(self) -> None:
        ts = _parse_ts("2026-06-01T09:30:00+00:00")
        from datetime import datetime, timezone

        expected = datetime(2026, 6, 1, 9, 30, 0, tzinfo=timezone.utc).timestamp()
        assert ts == pytest.approx(expected)

    def test_iso8601_naive(self) -> None:
        # Naive ISO-8601 treated as UTC
        ts = _parse_ts("2026-06-01T09:30:00")
        assert ts > 0

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            _parse_ts("not-a-date")


# ---------------------------------------------------------------------------
# _ts_to_str
# ---------------------------------------------------------------------------


class TestTsHelpers:
    def test_ts_to_str_epoch(self) -> None:
        result = _ts_to_str(0.0)
        assert result == "1970-01-01T00:00:00"

    def test_ts_to_str_roundtrip(self) -> None:
        ts = _parse_ts("2026-06-15")
        s = _ts_to_str(ts)
        assert s.startswith("2026-06-15")


# ---------------------------------------------------------------------------
# _stringify
# ---------------------------------------------------------------------------


class TestStringify:
    def test_none_returns_empty(self) -> None:
        assert _stringify(None) == ""

    def test_float_format(self) -> None:
        assert _stringify(1.5) == "1.5"
        assert _stringify(1.0) == "1"

    def test_list_joins(self) -> None:
        assert _stringify(["a", "b", "c"]) == "a,b,c"

    def test_string_passthrough(self) -> None:
        assert _stringify("hello") == "hello"

    def test_int_passthrough(self) -> None:
        assert _stringify(42) == "42"


# ---------------------------------------------------------------------------
# _read_jsonl
# ---------------------------------------------------------------------------


class TestReadJsonl:
    def _write_jsonl(self, path: Path, records: list[dict]) -> None:
        with path.open("w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    def test_nonexistent_file_returns_empty(self, tmp_path: Path) -> None:
        result = _read_jsonl(tmp_path / "nope.jsonl", 0.0, 1e18, {"INIT"}, 1000)
        assert result == []

    def test_filters_by_type(self, tmp_path: Path) -> None:
        p = tmp_path / "hist.jsonl"
        ts = time.time()
        self._write_jsonl(
            p,
            [
                {"type": "INIT", "timestamp": ts, "level": 100.0},
                {"type": "CORP_ACTION", "timestamp": ts, "level": 99.0},
            ],
        )
        result = _read_jsonl(p, 0.0, 1e18, {"INIT"}, 1000)
        assert len(result) == 1
        assert result[0]["type"] == "INIT"

    def test_filters_by_time_range(self, tmp_path: Path) -> None:
        p = tmp_path / "hist.jsonl"
        now = time.time()
        old = now - 86400 * 10  # 10 days ago
        self._write_jsonl(
            p,
            [
                {"type": "CORP_ACTION", "timestamp": old, "level": 90.0},
                {"type": "CORP_ACTION", "timestamp": now, "level": 100.0},
            ],
        )
        # Only want records from last 5 days
        result = _read_jsonl(p, now - 86400 * 5, now + 1, {"CORP_ACTION"}, 1000)
        assert len(result) == 1
        assert result[0]["level"] == 100.0

    def test_skips_blank_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "hist.jsonl"
        ts = time.time()
        p.write_text(
            "\n" + json.dumps({"type": "INIT", "timestamp": ts, "level": 1.0}) + "\n\n"
        )
        result = _read_jsonl(p, 0.0, 1e18, {"INIT"}, 1000)
        assert len(result) == 1

    def test_skips_malformed_json(self, tmp_path: Path) -> None:
        p = tmp_path / "hist.jsonl"
        ts = time.time()
        p.write_text(
            "NOT JSON\n" + json.dumps({"type": "INIT", "timestamp": ts}) + "\n"
        )
        result = _read_jsonl(p, 0.0, 1e18, {"INIT"}, 1000)
        assert len(result) == 1

    def test_skips_missing_timestamp(self, tmp_path: Path) -> None:
        p = tmp_path / "hist.jsonl"
        p.write_text(json.dumps({"type": "INIT", "level": 100.0}) + "\n")
        result = _read_jsonl(p, 0.0, 1e18, {"INIT"}, 1000)
        assert result == []

    def test_limit_enforced(self, tmp_path: Path) -> None:
        p = tmp_path / "hist.jsonl"
        ts = time.time()
        lines = "\n".join(
            json.dumps({"type": "CORP_ACTION", "timestamp": ts + i}) for i in range(10)
        )
        p.write_text(lines + "\n")
        result = _read_jsonl(p, 0.0, 1e18, {"CORP_ACTION"}, 3)
        assert len(result) == 3

    def test_level_type_never_matches_structural_filter(self, tmp_path: Path) -> None:
        """Design intent: even if a stray LEVEL record exists on disk (e.g.
        left over from before this refactor), pm-index-cli's structural
        query surface must never surface it — LEVEL isn't a valid --type
        value any more.
        """
        p = tmp_path / "hist.jsonl"
        ts = time.time()
        self._write_jsonl(p, [{"type": "LEVEL", "timestamp": ts, "level": 100.0}])
        result = _read_jsonl(
            p, 0.0, 1e18, {"INIT", "CORP_ACTION", "ADD_CONSTITUENT", "DELIST"}, 1000
        )
        assert result == []


# ---------------------------------------------------------------------------
# Projection helpers
# ---------------------------------------------------------------------------


class TestProjectEvent:
    def test_corp_action(self) -> None:
        rec = {
            "timestamp": 0.0,
            "type": "CORP_ACTION",
            "index_id": "IDX",
            "action": "SPLIT",
            "detail": "2:1",
            "old_divisor": 1000.0,
            "new_divisor": 500.0,
        }
        row = _project_event(rec)
        assert row["type"] == "CORP_ACTION"
        assert "SPLIT" in row["detail"]

    def test_add_constituent(self) -> None:
        rec = {
            "timestamp": 0.0,
            "type": "ADD_CONSTITUENT",
            "index_id": "IDX",
            "symbol": "AAPL",
            "reference_price": 150.0,
        }
        row = _project_event(rec)
        assert "ref_price=150.0" in row["detail"]

    def test_delist(self) -> None:
        rec = {
            "timestamp": 0.0,
            "type": "DELIST",
            "index_id": "IDX",
            "symbol": "OLD",
        }
        row = _project_event(rec)
        assert row["detail"] == ""

    def test_init(self) -> None:
        rec = {
            "timestamp": 0.0,
            "type": "INIT",
            "index_id": "IDX",
            "base_value": 1000.0,
            "constituents": ["AAPL", "MSFT"],
        }
        row = _project_event(rec)
        assert "base=1000.0" in row["detail"]
        assert "AAPL" in row["detail"]

    def test_unknown_type(self) -> None:
        rec = {"timestamp": 0.0, "type": "OTHER", "index_id": "IDX"}
        row = _project_event(rec)
        assert row["detail"] == ""


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


class TestRenderTable:
    def test_no_rows_prints_message(self, capsys: pytest.CaptureFixture) -> None:
        _render_table([], ["col_a"], False)
        captured = capsys.readouterr()
        assert "No rows found" in captured.out

    def test_renders_rows(self, capsys: pytest.CaptureFixture) -> None:
        rows = [{"col_a": "foo", "col_b": 1}]
        _render_table(rows, ["col_a", "col_b"], False)
        captured = capsys.readouterr()
        assert "foo" in captured.out
        assert "col_a" in captured.out  # header

    def test_no_header_skips_header(self, capsys: pytest.CaptureFixture) -> None:
        rows = [{"col_a": "foo"}]
        _render_table(rows, ["col_a"], True)
        captured = capsys.readouterr()
        assert "col_a" not in captured.out
        assert "foo" in captured.out


class TestRenderJson:
    def test_outputs_json(self, capsys: pytest.CaptureFixture) -> None:
        rows = [{"ts": "2026-01-01", "level": 100.0}]
        _render_json(rows, ["ts", "level"])
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed[0]["level"] == 100.0

    def test_only_specified_columns(self, capsys: pytest.CaptureFixture) -> None:
        rows = [{"ts": "x", "level": 1.0, "extra": "ignored"}]
        _render_json(rows, ["ts"])
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "extra" not in parsed[0]


class TestRenderCsv:
    def test_outputs_csv_with_header(self, capsys: pytest.CaptureFixture) -> None:
        rows = [{"a": "foo", "b": 1.5}]
        _render_csv(rows, ["a", "b"], False)
        captured = capsys.readouterr()
        lines = captured.out.strip().split("\n")
        assert lines[0] == "a,b"
        assert "foo" in lines[1]

    def test_no_header(self, capsys: pytest.CaptureFixture) -> None:
        rows = [{"a": "foo"}]
        _render_csv(rows, ["a"], True)
        captured = capsys.readouterr()
        assert "a" not in captured.out  # no header line
        assert "foo" in captured.out


class TestRender:
    def test_dispatch_json(self, capsys: pytest.CaptureFixture) -> None:
        _render([{"x": 1}], ["x"], "json", False)
        captured = capsys.readouterr()
        assert json.loads(captured.out)[0]["x"] == 1

    def test_dispatch_csv(self, capsys: pytest.CaptureFixture) -> None:
        _render([{"x": "hi"}], ["x"], "csv", False)
        captured = capsys.readouterr()
        assert "hi" in captured.out

    def test_dispatch_table(self, capsys: pytest.CaptureFixture) -> None:
        _render([{"x": "hi"}], ["x"], "table", False)
        captured = capsys.readouterr()
        assert "hi" in captured.out


# ---------------------------------------------------------------------------
# _resolve_time_range
# ---------------------------------------------------------------------------


class TestResolveTimeRange:
    def _args(self, **kwargs: Any) -> Namespace:
        base = {"days": None, "from_ts": None, "to_ts": None}
        base.update(kwargs)
        return Namespace(**base)

    def test_default_returns_zero_to_now(self) -> None:
        before = time.time()
        from_ts, to_ts = _resolve_time_range(self._args())
        after = time.time()
        assert from_ts == 0.0
        assert before <= to_ts <= after + 1

    def test_days_sets_from_ts(self) -> None:
        from_ts, to_ts = _resolve_time_range(self._args(days=7))
        assert pytest.approx(to_ts - from_ts, abs=5) == 7 * 86400

    def test_days_zero_raises(self) -> None:
        with pytest.raises(SystemExit) as exc:
            _resolve_time_range(self._args(days=0))
        assert exc.value.code == 2

    def test_days_negative_raises(self) -> None:
        with pytest.raises(SystemExit) as exc:
            _resolve_time_range(self._args(days=-1))
        assert exc.value.code == 2

    def test_from_ts_parsed(self) -> None:
        from_ts, _ = _resolve_time_range(self._args(from_ts="2026-01-01"))
        assert from_ts == pytest.approx(_parse_ts("2026-01-01"))

    def test_to_ts_parsed(self) -> None:
        _, to_ts = _resolve_time_range(
            self._args(from_ts="2026-01-01", to_ts="2026-06-01")
        )
        assert to_ts == pytest.approx(_parse_ts("2026-06-01"))

    def test_from_after_to_raises(self) -> None:
        with pytest.raises(SystemExit) as exc:
            _resolve_time_range(self._args(from_ts="2026-06-01", to_ts="2026-01-01"))
        assert exc.value.code == 2

    def test_invalid_from_raises(self) -> None:
        with pytest.raises(SystemExit) as exc:
            _resolve_time_range(self._args(from_ts="not-a-date"))
        assert exc.value.code == 2

    def test_invalid_to_raises(self) -> None:
        with pytest.raises(SystemExit) as exc:
            _resolve_time_range(self._args(from_ts="2026-01-01", to_ts="bad-date"))
        assert exc.value.code == 2


# ---------------------------------------------------------------------------
# _resolve_index_ids
# ---------------------------------------------------------------------------


class TestResolveIndexIds:
    def test_explicit_index_returned_uppercase(self) -> None:
        args = Namespace(index=["idx1", "idx2"])
        result = _resolve_index_ids(args, None)
        assert result == ["IDX1", "IDX2"]

    def test_no_index_no_config_raises(self) -> None:
        args = Namespace(index=None)
        with pytest.raises(SystemExit) as exc:
            _resolve_index_ids(args, None)
        assert exc.value.code == 2

    def test_config_with_empty_indices_raises(self) -> None:
        args = Namespace(index=None)
        with patch("edumatcher.index.cli._config_index_map", return_value={}):
            with pytest.raises(SystemExit) as exc:
                _resolve_index_ids(args, "some_config.yaml")
            assert exc.value.code == 1

    def test_config_returns_ids(self) -> None:
        args = Namespace(index=None)
        fake_map = {"IDX1": MagicMock(), "IDX2": MagicMock()}
        with patch("edumatcher.index.cli._config_index_map", return_value=fake_map):
            result = _resolve_index_ids(args, "some_config.yaml")
        assert set(result) == {"IDX1", "IDX2"}


# ---------------------------------------------------------------------------
# _resolve_history_files
# ---------------------------------------------------------------------------


class TestResolveHistoryFiles:
    def test_no_config_uses_data_dir(self, tmp_path: Path) -> None:
        result = _resolve_history_files(["IDX"], None, str(tmp_path))
        assert result["IDX"] == tmp_path / "IDX_history.jsonl"

    def test_config_overrides_path(self, tmp_path: Path) -> None:
        custom_path = str(tmp_path / "custom.jsonl")
        mock_map = {"IDX": MagicMock(history_file=custom_path)}
        with patch("edumatcher.index.cli._config_index_map", return_value=mock_map):
            result = _resolve_history_files(["IDX"], "config.yaml", str(tmp_path))
        assert result["IDX"] == Path(custom_path)

    def test_config_exception_falls_back_to_data_dir(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        with patch(
            "edumatcher.index.cli._config_index_map",
            side_effect=RuntimeError("oops"),
        ):
            result = _resolve_history_files(["IDX"], "bad_config.yaml", str(tmp_path))
        assert result["IDX"] == tmp_path / "IDX_history.jsonl"
        assert "WARNING" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# _build_parser
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_events_subcommand_with_type(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["events", "--index", "IDX", "--type", "INIT"])
        assert args.command == "events"
        assert args.event_types == ["INIT"]

    def test_indices_subcommand(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["indices"])
        assert args.command == "indices"

    def test_format_choices(self) -> None:
        parser = _build_parser()
        for fmt in ("table", "json", "csv"):
            args = parser.parse_args(["--format", fmt, "events", "--index", "X"])
            assert args.format == fmt

    def test_no_header_flag(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["--no-header", "events", "--index", "X"])
        assert args.no_header is True

    def test_level_and_eod_subcommands_no_longer_exist(self) -> None:
        """Design intent: level/EOD queries were removed from pm-index-cli
        entirely, not just hidden — they now live in pm-stats-cli.
        """
        parser = _build_parser()
        for removed_cmd in ("level", "eod"):
            with pytest.raises(SystemExit) as exc:
                parser.parse_args([removed_cmd, "--index", "X"])
            assert exc.value.code == 2


# ---------------------------------------------------------------------------
# _cmd_events — integration tests with tmp files
# ---------------------------------------------------------------------------


def _make_args(
    tmp_path: Path,
    command: str,
    index_id: str = "TEST",
    fmt: str = "table",
    **extra: Any,
) -> Namespace:
    base: dict[str, Any] = {
        "command": command,
        "index": [index_id],
        "config": None,
        "data_dir": str(tmp_path),
        "format": fmt,
        "no_header": False,
        "days": None,
        "from_ts": None,
        "to_ts": None,
        "limit": 100,
        "event_types": None,
    }
    base.update(extra)
    return Namespace(**base)


def _write_history(path: Path, records: list[dict]) -> None:
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


class TestCmdEvents:
    def test_init_event_rendered(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        ts = time.time()
        _write_history(
            tmp_path / "TEST_history.jsonl",
            [
                {
                    "type": "INIT",
                    "timestamp": ts,
                    "index_id": "TEST",
                    "base_value": 1000.0,
                    "constituents": ["AAPL"],
                }
            ],
        )
        args = _make_args(tmp_path, "events")
        _cmd_events(args)
        out = capsys.readouterr().out
        assert "INIT" in out

    def test_filter_by_event_type(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        ts = time.time()
        _write_history(
            tmp_path / "TEST_history.jsonl",
            [
                {"type": "INIT", "timestamp": ts, "index_id": "TEST"},
                {"type": "CORP_ACTION", "timestamp": ts, "index_id": "TEST"},
            ],
        )
        args = _make_args(tmp_path, "events", event_types=["INIT"])
        _cmd_events(args)
        out = capsys.readouterr().out
        assert "INIT" in out

    def test_invalid_event_type_raises(self, tmp_path: Path) -> None:
        (tmp_path / "TEST_history.jsonl").write_text("")
        args = _make_args(tmp_path, "events", event_types=["BOGUS"])
        with pytest.raises(SystemExit) as exc:
            _cmd_events(args)
        assert exc.value.code == 2

    def test_level_is_an_invalid_event_type(self, tmp_path: Path) -> None:
        """LEVEL/EOD are not valid --type filter values any more — they
        should be rejected the same way an unknown type would be, not
        silently accepted (which would suggest events still stores levels).
        """
        (tmp_path / "TEST_history.jsonl").write_text("")
        args = _make_args(tmp_path, "events", event_types=["LEVEL"])
        with pytest.raises(SystemExit) as exc:
            _cmd_events(args)
        assert exc.value.code == 2

    def test_no_event_rows(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        (tmp_path / "TEST_history.jsonl").write_text("")
        args = _make_args(tmp_path, "events")
        _cmd_events(args)
        assert "No rows" in capsys.readouterr().out


class TestCmdIndices:
    def test_no_config_raises(self, tmp_path: Path) -> None:
        args = Namespace(
            config=None,
            data_dir=str(tmp_path),
            format="table",
            no_header=False,
        )
        with pytest.raises(SystemExit) as exc:
            _cmd_indices(args)
        assert exc.value.code == 2

    def test_with_config_renders_indices(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        mock_cfg = MagicMock()
        idx = MagicMock()
        idx.id = "IDX1"
        idx.description = "Test index"
        idx.history_file = "data/idx1.jsonl"
        idx.state_file = "data/idx1_state.json"
        idx.constituents = ["AAPL", "MSFT"]
        mock_cfg.indices = [idx]
        with patch("edumatcher.index.cli._load_engine_config", return_value=mock_cfg):
            args = Namespace(
                config="dummy.yaml",
                data_dir=str(tmp_path),
                format="table",
                no_header=False,
            )
            _cmd_indices(args)
        out = capsys.readouterr().out
        assert "IDX1" in out

    def test_json_format(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        mock_cfg = MagicMock()
        idx = MagicMock()
        idx.id = "IDX1"
        idx.description = ""
        idx.history_file = "h.jsonl"
        idx.state_file = "s.json"
        idx.constituents = []
        mock_cfg.indices = [idx]
        with patch("edumatcher.index.cli._load_engine_config", return_value=mock_cfg):
            args = Namespace(
                config="dummy.yaml",
                data_dir=str(tmp_path),
                format="json",
                no_header=False,
            )
            _cmd_indices(args)
        parsed = json.loads(capsys.readouterr().out)
        assert parsed[0]["id"] == "IDX1"


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


class TestMain:
    def test_limit_zero_raises(self, tmp_path: Path) -> None:
        with patch(
            "sys.argv",
            ["pm-index-cli", "events", "--index", "IDX", "--limit", "0"],
        ):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 2

    def test_dispatches_events(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        (tmp_path / "IDX_history.jsonl").write_text("")
        with patch(
            "sys.argv",
            [
                "pm-index-cli",
                "--data-dir",
                str(tmp_path),
                "events",
                "--index",
                "IDX",
            ],
        ):
            main()
        assert "No rows" in capsys.readouterr().out

    def test_dispatches_indices(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        mock_cfg = MagicMock()
        mock_cfg.indices = []
        with patch("edumatcher.index.cli._load_engine_config", return_value=mock_cfg):
            with patch(
                "sys.argv",
                ["pm-index-cli", "--config", "dummy.yaml", "indices"],
            ):
                main()
        assert "No rows" in capsys.readouterr().out
