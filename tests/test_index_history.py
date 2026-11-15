from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from edumatcher.index.history import STRUCTURAL_RECORD_TYPES, IndexHistory


def test_structural_record_types_are_exactly_the_audit_events() -> None:
    """Pin down the intent of the refactor: the JSONL file is a structural/
    corporate-action audit log, not a level-history store. LEVEL and EOD
    must not appear in the known-type set.
    """
    assert STRUCTURAL_RECORD_TYPES == {
        "INIT",
        "CORP_ACTION",
        "DELIST",
        "ADD_CONSTITUENT",
        "REBALANCE",
    }
    assert "LEVEL" not in STRUCTURAL_RECORD_TYPES
    assert "EOD" not in STRUCTURAL_RECORD_TYPES


def test_append_and_query(tmp_path: Path) -> None:
    path = tmp_path / "index_history.jsonl"
    history = IndexHistory(str(path))
    history.append({"type": "INIT", "ts_ns": 1000, "index_id": "IDX", "level": 1000.0})
    history.append(
        {
            "type": "CORP_ACTION",
            "ts_ns": 2000,
            "index_id": "IDX",
            "level": 1020.0,
        }
    )
    history.flush()

    rows, warnings = history.query(0, 3000, {"INIT", "CORP_ACTION"})
    assert warnings == []
    assert len(rows) == 2
    assert history.path == path


def test_query_includes_exact_timestamp_upper_bound(tmp_path: Path) -> None:
    history = IndexHistory(str(tmp_path / "index_history.jsonl"))
    for ts_ns in (100, 200, 201):
        history.append(
            {
                "type": "CORP_ACTION",
                "ts_ns": ts_ns,
                "index_id": "IDX",
                "level": float(ts_ns),
            }
        )
    history.flush()

    records, warnings = history.query(100, 200, {"CORP_ACTION"})

    assert warnings == []
    assert [record["ts_ns"] for record in records] == [100, 200]


def test_query_type_filter(tmp_path: Path) -> None:
    path = tmp_path / "index_history.jsonl"
    history = IndexHistory(str(path))
    history.append({"type": "INIT", "ts_ns": 1000, "index_id": "IDX", "level": 1000.0})
    history.append(
        {
            "type": "CORP_ACTION",
            "ts_ns": 2000,
            "index_id": "IDX",
            "level": 1020.0,
        }
    )
    history.flush()

    rows, _ = history.query(0, 3000, {"CORP_ACTION"})
    assert len(rows) == 1
    assert rows[0]["type"] == "CORP_ACTION"


def test_query_ignores_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "index_history.jsonl"
    path.write_text(
        "not-json\n" '{"type":"CORP_ACTION","ts_ns":5,"index_id":"IDX","level":1.0}\n',
        encoding="utf-8",
    )
    history = IndexHistory(str(path))

    rows, warnings = history.query(0, 10, {"CORP_ACTION"})
    assert len(rows) == 1
    assert warnings


def test_query_invalid_time_window_rejected(tmp_path: Path) -> None:
    history = IndexHistory(str(tmp_path / "x.jsonl"))
    with pytest.raises(ValueError):
        history.query(10, 0, {"CORP_ACTION"})


def test_query_max_records_limit(tmp_path: Path) -> None:
    history = IndexHistory(str(tmp_path / "x.jsonl"))
    history.append({"type": "CORP_ACTION", "ts_ns": 1, "index_id": "IDX", "level": 1.0})
    history.append({"type": "CORP_ACTION", "ts_ns": 2, "index_id": "IDX", "level": 2.0})
    history.flush()

    rows, _ = history.query(0, 5, {"CORP_ACTION"}, max_records=1)
    assert len(rows) == 1


def test_query_missing_file_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "missing.jsonl"
    history = IndexHistory(str(path))
    history.close()
    path.unlink()

    rows, warnings = history.query(0, 10, {"CORP_ACTION"})
    assert rows == []
    assert warnings == []


def test_query_invalid_type_and_timestamp_warnings(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"type":123,"ts_ns":1}',
                '{"type":"CORP_ACTION","ts_ns":"bad"}',
                '{"type":"WHATEVER","ts_ns":2}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    history = IndexHistory(str(path))
    rows, warnings = history.query(0, 10, {"CORP_ACTION"})
    assert rows == []
    assert len(warnings) == 3


def test_query_invalid_max_records(tmp_path: Path) -> None:
    history = IndexHistory(str(tmp_path / "x.jsonl"))
    with pytest.raises(ValueError):
        history.query(0, 10, {"CORP_ACTION"}, max_records=0)


def test_close_closes_file_handle(tmp_path: Path) -> None:
    history = IndexHistory(str(tmp_path / "x.jsonl"))
    history.close()
    assert history._fh.closed is True


def test_query_treats_level_as_unknown_type(tmp_path: Path) -> None:
    """Design intent: LEVEL is no longer a recognized record type at all —
    a stray LEVEL record (e.g. from data written before this change) should
    surface as an 'unknown record type' warning, not be silently accepted
    the way a still-valid-but-unrequested type would be.
    """
    path = tmp_path / "x.jsonl"
    path.write_text('{"type":"LEVEL","ts_ns":5,"level":100.0}\n', encoding="utf-8")
    history = IndexHistory(str(path))

    rows, warnings = history.query(0, 10, {"CORP_ACTION"})
    assert rows == []
    assert any("unknown record type: LEVEL" in w for w in warnings)


def test_query_treats_eod_as_unknown_type(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text('{"type":"EOD","ts_ns":5,"level":100.0}\n', encoding="utf-8")
    history = IndexHistory(str(path))

    rows, warnings = history.query(0, 10, {"CORP_ACTION"})
    assert rows == []
    assert any("unknown record type: EOD" in w for w in warnings)


class _FullDisk:
    """A buffered handle on a full disk: writes buffer, every flush fails and
    keeps the buffer, as CPython's BufferedWriter does (close() included)."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.closed = False

    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        raise OSError(28, "No space left on device")

    def close(self) -> None:
        self.closed = True
        self._inner.close()
        self.flush()


def test_a_record_that_could_not_be_written_is_not_written_later(
    tmp_path: Path,
) -> None:
    """WP-IDX01: a failed flush leaves the line in the handle's buffer, and the
    next flush would write a record whose command was rejected."""
    path = tmp_path / "index_history.jsonl"
    history = IndexHistory(str(path))
    history.append({"type": "INIT", "ts_ns": 1, "index_id": "IDX", "level": 1.0})
    history.flush()
    history._fh = _FullDisk(history._fh)

    with pytest.raises(OSError):
        history.write_through(
            {"type": "CORP_ACTION", "ts_ns": 2, "index_id": "IDX", "level": 2.0}
        )
    history.write_through(
        {"type": "CORP_ACTION", "ts_ns": 3, "index_id": "IDX", "level": 3.0}
    )
    history.close()

    rows, _ = history.query(0, 10, {"INIT", "CORP_ACTION"})
    assert [r["ts_ns"] for r in rows] == [1, 3]
