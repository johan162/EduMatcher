from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.index.history import IndexHistory


def test_append_and_query(tmp_path: Path) -> None:
    path = tmp_path / "index_history.jsonl"
    history = IndexHistory(str(path))
    history.append({"type": "LEVEL", "timestamp": 1000.0, "level": 1010.0})
    history.append({"type": "EOD", "timestamp": 2000.0, "level": 1020.0})
    history.flush()

    rows, warnings = history.query(0.0, 3000.0, {"LEVEL", "EOD"})
    assert warnings == []
    assert len(rows) == 2
    assert history.path == path


def test_query_type_filter(tmp_path: Path) -> None:
    path = tmp_path / "index_history.jsonl"
    history = IndexHistory(str(path))
    history.append({"type": "LEVEL", "timestamp": 1000.0, "level": 1010.0})
    history.append({"type": "EOD", "timestamp": 2000.0, "level": 1020.0})
    history.flush()

    rows, _ = history.query(0.0, 3000.0, {"EOD"})
    assert len(rows) == 1
    assert rows[0]["type"] == "EOD"


def test_query_ignores_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "index_history.jsonl"
    path.write_text('not-json\n{"type":"LEVEL","timestamp":5.0}\n', encoding="utf-8")
    history = IndexHistory(str(path))

    rows, warnings = history.query(0.0, 10.0, {"LEVEL"})
    assert len(rows) == 1
    assert warnings


def test_query_invalid_time_window_rejected(tmp_path: Path) -> None:
    history = IndexHistory(str(tmp_path / "x.jsonl"))
    with pytest.raises(ValueError):
        history.query(10.0, 0.0, {"LEVEL"})


def test_query_max_records_limit(tmp_path: Path) -> None:
    history = IndexHistory(str(tmp_path / "x.jsonl"))
    history.append({"type": "LEVEL", "timestamp": 1.0})
    history.append({"type": "LEVEL", "timestamp": 2.0})
    history.flush()

    rows, _ = history.query(0.0, 5.0, {"LEVEL"}, max_records=1)
    assert len(rows) == 1


def test_query_missing_file_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "missing.jsonl"
    history = IndexHistory(str(path))
    history.close()
    path.unlink()

    rows, warnings = history.query(0.0, 10.0, {"LEVEL"})
    assert rows == []
    assert warnings == []


def test_query_invalid_type_and_timestamp_warnings(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"type":123,"timestamp":1.0}',
                '{"type":"LEVEL","timestamp":"bad"}',
                '{"type":"WHATEVER","timestamp":2.0}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    history = IndexHistory(str(path))
    rows, warnings = history.query(0.0, 10.0, {"LEVEL"})
    assert rows == []
    assert len(warnings) == 3


def test_query_invalid_max_records(tmp_path: Path) -> None:
    history = IndexHistory(str(tmp_path / "x.jsonl"))
    with pytest.raises(ValueError):
        history.query(0.0, 10.0, {"LEVEL"}, max_records=0)


def test_close_closes_file_handle(tmp_path: Path) -> None:
    history = IndexHistory(str(tmp_path / "x.jsonl"))
    history.close()
    assert history._fh.closed is True
