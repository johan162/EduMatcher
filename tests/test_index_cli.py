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
    build_parser,
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
        result = _read_jsonl(tmp_path / "nope.jsonl", 0, 10**27, {"INIT"}, 1000)
        assert result == []

    def test_filters_by_type(self, tmp_path: Path) -> None:
        p = tmp_path / "hist.jsonl"
        ts_ns = time.time_ns()
        self._write_jsonl(
            p,
            [
                {"type": "INIT", "ts_ns": ts_ns, "level": 100.0},
                {"type": "CORP_ACTION", "ts_ns": ts_ns, "level": 99.0},
            ],
        )
        result = _read_jsonl(p, 0, 10**27, {"INIT"}, 1000)
        assert len(result) == 1
        assert result[0]["type"] == "INIT"

    def test_filters_by_time_range(self, tmp_path: Path) -> None:
        p = tmp_path / "hist.jsonl"
        now_ns = time.time_ns()
        old_ns = now_ns - 86400 * 10 * 1_000_000_000  # 10 days ago
        self._write_jsonl(
            p,
            [
                {"type": "CORP_ACTION", "ts_ns": old_ns, "level": 90.0},
                {"type": "CORP_ACTION", "ts_ns": now_ns, "level": 100.0},
            ],
        )
        # Only want records from last 5 days
        result = _read_jsonl(
            p, now_ns - 86400 * 5 * 1_000_000_000, now_ns + 1, {"CORP_ACTION"}, 1000
        )
        assert len(result) == 1
        assert result[0]["level"] == 100.0

    def test_skips_blank_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "hist.jsonl"
        ts_ns = time.time_ns()
        p.write_text(
            "\n" + json.dumps({"type": "INIT", "ts_ns": ts_ns, "level": 1.0}) + "\n\n"
        )
        result = _read_jsonl(p, 0, 10**27, {"INIT"}, 1000)
        assert len(result) == 1

    def test_skips_malformed_json(self, tmp_path: Path) -> None:
        p = tmp_path / "hist.jsonl"
        ts_ns = time.time_ns()
        p.write_text("NOT JSON\n" + json.dumps({"type": "INIT", "ts_ns": ts_ns}) + "\n")
        result = _read_jsonl(p, 0, 10**27, {"INIT"}, 1000)
        assert len(result) == 1

    def test_skips_missing_timestamp(self, tmp_path: Path) -> None:
        p = tmp_path / "hist.jsonl"
        p.write_text(json.dumps({"type": "INIT", "level": 100.0}) + "\n")
        result = _read_jsonl(p, 0, 10**27, {"INIT"}, 1000)
        assert result == []

    def test_limit_enforced(self, tmp_path: Path) -> None:
        p = tmp_path / "hist.jsonl"
        ts_ns = time.time_ns()
        lines = "\n".join(
            json.dumps({"type": "CORP_ACTION", "ts_ns": ts_ns + i}) for i in range(10)
        )
        p.write_text(lines + "\n")
        result = _read_jsonl(p, 0, 10**27, {"CORP_ACTION"}, 3)
        assert len(result) == 3

    def test_level_type_never_matches_structural_filter(self, tmp_path: Path) -> None:
        """Design intent: even if a stray LEVEL record exists on disk (e.g.
        left over from before this refactor), pm-index-cli's structural
        query surface must never surface it — LEVEL isn't a valid --type
        value any more.
        """
        p = tmp_path / "hist.jsonl"
        ts_ns = time.time_ns()
        self._write_jsonl(p, [{"type": "LEVEL", "ts_ns": ts_ns, "level": 100.0}])
        result = _read_jsonl(
            p, 0, 10**27, {"INIT", "CORP_ACTION", "ADD_CONSTITUENT", "DELIST"}, 1000
        )
        assert result == []


# ---------------------------------------------------------------------------
# Projection helpers
# ---------------------------------------------------------------------------


class TestProjectEvent:
    def test_corp_action(self) -> None:
        rec = {
            "ts_ns": 0,
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
            "ts_ns": 0,
            "type": "ADD_CONSTITUENT",
            "index_id": "IDX",
            "symbol": "AAPL",
            "reference_price": 150.0,
        }
        row = _project_event(rec)
        assert "ref_price=150.0" in row["detail"]

    def test_delist(self) -> None:
        rec = {
            "ts_ns": 0,
            "type": "DELIST",
            "index_id": "IDX",
            "symbol": "OLD",
        }
        row = _project_event(rec)
        assert row["detail"] == ""

    def test_init(self) -> None:
        rec = {
            "ts_ns": 0,
            "type": "INIT",
            "index_id": "IDX",
            "base_value": 1000.0,
            "constituents": ["AAPL", "MSFT"],
        }
        row = _project_event(rec)
        assert "base=1000.0" in row["detail"]
        assert "AAPL" in row["detail"]

    def test_unknown_type(self) -> None:
        rec = {"ts_ns": 0, "type": "OTHER", "index_id": "IDX"}
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

    def test_no_index_no_config_falls_back_to_compiled_config(self) -> None:
        """With neither --index nor --config, indices come from the deployed
        exchange's compiled configuration."""
        args = Namespace(index=None)
        fake_map = {"IDX1": MagicMock()}
        with patch("edumatcher.index.cli._config_index_map", return_value=fake_map):
            result = _resolve_index_ids(args, None)
        assert result == ["IDX1"]

    def test_no_index_no_config_and_nothing_compiled_raises(self) -> None:
        args = Namespace(index=None)
        with patch("edumatcher.index.cli._config_index_map", return_value={}):
            with pytest.raises(SystemExit) as exc:
                _resolve_index_ids(args, None)
            assert exc.value.code == 1

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
# build_parser
# ---------------------------------------------------------------------------


class TestBuildParser:
    def test_events_subcommand_with_type(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["events", "--index", "IDX", "--type", "INIT"])
        assert args.command == "events"
        assert args.event_types == ["INIT"]

    def test_indices_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["indices"])
        assert args.command == "indices"

    def test_format_choices(self) -> None:
        parser = build_parser()
        for fmt in ("table", "json", "csv"):
            args = parser.parse_args(["--format", fmt, "events", "--index", "X"])
            assert args.format == fmt

    def test_no_header_flag(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--no-header", "events", "--index", "X"])
        assert args.no_header is True

    def test_level_and_eod_subcommands_no_longer_exist(self) -> None:
        """Design intent: level/EOD queries were removed from pm-index-cli
        entirely, not just hidden — they now live in pm-stats-cli.
        """
        parser = build_parser()
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
        ts_ns = time.time_ns()
        _write_history(
            tmp_path / "TEST_history.jsonl",
            [
                {
                    "type": "INIT",
                    "ts_ns": ts_ns,
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
        ts_ns = time.time_ns()
        _write_history(
            tmp_path / "TEST_history.jsonl",
            [
                {"type": "INIT", "ts_ns": ts_ns, "index_id": "TEST"},
                {"type": "CORP_ACTION", "ts_ns": ts_ns, "index_id": "TEST"},
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
    def test_no_config_falls_back_to_compiled_config(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """With no --config, 'indices' lists the deployed exchange's
        compiled configuration instead of requiring the flag."""
        mock_cfg = MagicMock()
        idx = MagicMock()
        idx.id = "IDX1"
        idx.description = "Test index"
        idx.history_file = "data/idx1.jsonl"
        idx.state_file = "data/idx1_state.json"
        idx.constituents = ["AAPL"]
        mock_cfg.indices = [idx]
        args = Namespace(
            config=None,
            data_dir=str(tmp_path),
            format="table",
            no_header=False,
        )
        with patch("edumatcher.index.cli._load_engine_config", return_value=mock_cfg):
            _cmd_indices(args)
        out = capsys.readouterr().out
        assert "IDX1" in out

    def test_no_config_and_nothing_compiled_raises(self, tmp_path: Path) -> None:
        args = Namespace(
            config=None,
            data_dir=str(tmp_path),
            format="table",
            no_header=False,
        )
        with patch(
            "edumatcher.config_artifact.load_compiled_config", return_value=None
        ):
            with pytest.raises(SystemExit) as exc:
                _cmd_indices(args)
            assert exc.value.code == 1

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


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------

_INIT_TS_NS = 1_781_430_000_000_000_000  # 2026-06-14T09:40:00Z


def _index_files(tmp_path: Path, index_id: str = "EDU100") -> MagicMock:
    """One configured index whose state and history files exist and are sound."""
    state = tmp_path / f"{index_id}_state.json"
    history = tmp_path / f"{index_id}_history.jsonl"
    state.write_text(
        json.dumps(
            {"index_id": index_id, "last_level": 1012.5, "last_updated": 1781430060.0}
        )
    )
    _write_history(
        history,
        [{"type": "INIT", "ts_ns": _INIT_TS_NS, "index_id": index_id, "level": 1000.0}],
    )
    idx = MagicMock()
    idx.id = index_id
    idx.state_file = str(state)
    idx.history_file = str(history)
    return idx


def _with_indices(monkeypatch: pytest.MonkeyPatch, *indices: Any) -> None:
    cfg = MagicMock()
    cfg.indices = list(indices)
    monkeypatch.setattr(
        "edumatcher.index.cli._try_load_engine_config", lambda _p: (cfg, "")
    )


def _healthy_process(monkeypatch: pytest.MonkeyPatch, *, running: bool = True) -> None:
    monkeypatch.setattr(
        "edumatcher.index.cli._find_index_pids", lambda: [1234] if running else []
    )
    monkeypatch.setattr(
        "edumatcher.index.cli._check_zmq_health", lambda: (True, "replied at t")
    )


def _run_health(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> int | str | None:
    monkeypatch.setattr("sys.argv", ["pm-index-cli", *args])
    with pytest.raises(SystemExit) as exc_info:
        main()
    return exc_info.value.code


class TestHealth:
    def test_reports_running_process(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _healthy_process(monkeypatch)

        assert _run_health(monkeypatch, ["health"]) == 0
        out = capsys.readouterr().out
        assert "pm-index process: OK" in out
        assert "index files:      OK - skipped" in out
        assert "index ZMQ ping:   OK" in out
        assert "health: OK" in out

    def test_fails_when_pm_index_is_not_running(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _healthy_process(monkeypatch, running=False)

        assert _run_health(monkeypatch, ["health"]) == 1

    def test_does_not_load_config_or_check_files_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _must_not_load(_p: Any) -> Any:
            raise AssertionError("config loaded without --extended")

        monkeypatch.setattr(
            "edumatcher.index.cli._try_load_engine_config", _must_not_load
        )
        _healthy_process(monkeypatch)

        assert _run_health(monkeypatch, ["health"]) == 0

    def test_extended_passes_for_sound_files(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        _with_indices(monkeypatch, _index_files(tmp_path))
        _healthy_process(monkeypatch)

        assert _run_health(monkeypatch, ["health", "--extended"]) == 0
        assert (
            "index files:      OK - state and history checks passed for 1 index"
            in capsys.readouterr().out
        )

    def test_extended_reports_missing_files_per_index(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        sound = _index_files(tmp_path, "EDU100")
        broken = _index_files(tmp_path, "TECH50")
        Path(broken.state_file).unlink()
        Path(broken.history_file).unlink()
        _with_indices(monkeypatch, sound, broken)
        _healthy_process(monkeypatch)

        assert _run_health(monkeypatch, ["health", "--extended"]) == 1
        out = capsys.readouterr().out
        assert "TECH50: state file not found" in out
        assert "TECH50: history file not found" in out
        assert "EDU100:" not in out

    def test_extended_fails_on_state_file_for_another_index(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        idx = _index_files(tmp_path)
        Path(idx.state_file).write_text(json.dumps({"index_id": "OTHER"}))
        _with_indices(monkeypatch, idx)
        _healthy_process(monkeypatch)

        assert _run_health(monkeypatch, ["health", "--extended"]) == 1

    @pytest.mark.parametrize(
        "last_line",
        ['{"type": "INIT", "ts_ns": 1', '{"type": "LEVEL", "ts_ns": 1}', "[1, 2]"],
    )
    def test_extended_fails_on_bad_last_history_record(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, last_line: str
    ) -> None:
        idx = _index_files(tmp_path)
        with Path(idx.history_file).open("a") as fh:
            fh.write(last_line + "\n")
        _with_indices(monkeypatch, idx)
        _healthy_process(monkeypatch)

        assert _run_health(monkeypatch, ["health", "--extended"]) == 1

    def test_extended_accepts_an_empty_history(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        idx = _index_files(tmp_path)
        Path(idx.history_file).write_text("")
        _with_indices(monkeypatch, idx)
        _healthy_process(monkeypatch)

        assert _run_health(monkeypatch, ["health", "--extended"]) == 0

    def test_extended_with_no_indices_configured_is_healthy(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _with_indices(monkeypatch)
        _healthy_process(monkeypatch)

        assert _run_health(monkeypatch, ["health", "--extended"]) == 0
        assert "no indices configured" in capsys.readouterr().out

    def test_extended_fails_when_config_cannot_load(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setattr(
            "edumatcher.index.cli._try_load_engine_config",
            lambda _p: (None, "No compiled configuration at x"),
        )
        _healthy_process(monkeypatch)

        assert _run_health(monkeypatch, ["health", "--extended"]) == 1
        captured = capsys.readouterr()
        assert "index files:      FAIL - No compiled configuration at x" in captured.out
        assert captured.err == ""

    def test_extended_verbose_reports_per_index_stats(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        idx = _index_files(tmp_path)
        _with_indices(monkeypatch, idx)
        _healthy_process(monkeypatch)

        assert _run_health(monkeypatch, ["health", "--extended", "-v"]) == 0
        out = capsys.readouterr().out
        assert "Index state/history files:     yes" in out
        assert "  EDU100:" in out
        assert f"state:       {idx.state_file}" in out
        assert "last record: INIT at 2026-06-14T09:40:00+00:00" in out
        assert "last level:  1012.5" in out
        assert "state saved: 2026-06-14T09:41:00+00:00" in out

    def test_verbose_without_extended_notes_files_were_skipped(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _healthy_process(monkeypatch)

        assert _run_health(monkeypatch, ["health", "-v"]) == 0
        out = capsys.readouterr().out
        assert "Index state/history files:     no (pass --extended)" in out
        assert "Index files:" not in out

    def test_json_format(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
        tmp_path: Path,
    ) -> None:
        _with_indices(monkeypatch, _index_files(tmp_path))
        _healthy_process(monkeypatch)

        code = _run_health(
            monkeypatch, ["--format", "json", "health", "--extended", "-v"]
        )

        assert code == 0
        report = json.loads(capsys.readouterr().out)
        assert report["healthy"] is True
        assert report["process"]["pids"] == [1234]
        assert report["files"]["stats"][0]["last_record_type"] == "INIT"

    def test_fails_when_zmq_ping_does_not_reply(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setattr("edumatcher.index.cli._find_index_pids", lambda: [1])
        monkeypatch.setattr(
            "edumatcher.index.cli._check_zmq_health",
            lambda: (False, "no reply within 1000ms"),
        )

        assert _run_health(monkeypatch, ["health"]) == 1
        assert (
            "index ZMQ ping:   FAIL - no reply within 1000ms" in capsys.readouterr().out
        )

    def test_quiet_exits_zero_without_output(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _healthy_process(monkeypatch)

        assert _run_health(monkeypatch, ["health", "-q"]) == 0
        assert capsys.readouterr() == ("", "")

    def test_quiet_exits_minus_one_without_output(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """Including when --extended cannot even load the config: -q stays silent."""
        monkeypatch.setattr(
            "edumatcher.index.cli._try_load_engine_config",
            lambda _p: (None, "no config"),
        )
        _healthy_process(monkeypatch)

        assert _run_health(monkeypatch, ["health", "--extended", "-q"]) == -1
        assert capsys.readouterr() == ("", "")

    def test_run_extended_check_times_out_without_waiting_for_the_worker(
        self,
    ) -> None:
        import threading

        from edumatcher.index.cli import _run_extended_index_files_check

        release = threading.Event()

        def _blocks_until_released(
            _config_path: str | None, *, collect_stats: bool = False
        ) -> tuple[bool, str, None]:
            release.wait(timeout=5)
            return True, "finished late", None

        with patch(
            "edumatcher.index.cli._check_index_files_health", _blocks_until_released
        ):
            started = time.monotonic()
            healthy, detail, stats = _run_extended_index_files_check(
                None, timeout_sec=0.1
            )
            elapsed = time.monotonic() - started

        release.set()  # let the abandoned worker finish so it doesn't outlive the test
        assert healthy is False
        assert "did not finish within" in detail
        assert stats is None
        assert elapsed < 2

    def test_zmq_health_check_detects_a_bound_replier(self) -> None:
        import threading

        from edumatcher.config import INDEX_HEALTH_BIND_ADDR
        from edumatcher.index.cli import _check_zmq_health
        from edumatcher.messaging.bus import make_replier

        sock = make_replier(INDEX_HEALTH_BIND_ADDR)
        try:

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
        from edumatcher.index.cli import _check_zmq_health

        healthy, detail = _check_zmq_health(timeout_ms=200)
        assert healthy is False
        assert "no reply" in detail
