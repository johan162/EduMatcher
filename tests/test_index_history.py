from __future__ import annotations

from pathlib import Path

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
    }
    assert "LEVEL" not in STRUCTURAL_RECORD_TYPES
    assert "EOD" not in STRUCTURAL_RECORD_TYPES


def test_append_and_query(tmp_path: Path) -> None:
    path = tmp_path / "index_history.jsonl"
    history = IndexHistory(str(path))
    history.append({"type": "INIT", "timestamp": 1000.0, "level": 1000.0})
    history.append({"type": "CORP_ACTION", "timestamp": 2000.0, "level": 1020.0})
    history.flush()

    rows, warnings = history.query(0.0, 3000.0, {"INIT", "CORP_ACTION"})
    assert warnings == []
    assert len(rows) == 2
    assert history.path == path


def test_query_type_filter(tmp_path: Path) -> None:
    path = tmp_path / "index_history.jsonl"
    history = IndexHistory(str(path))
    history.append({"type": "INIT", "timestamp": 1000.0, "level": 1000.0})
    history.append({"type": "CORP_ACTION", "timestamp": 2000.0, "level": 1020.0})
    history.flush()

    rows, _ = history.query(0.0, 3000.0, {"CORP_ACTION"})
    assert len(rows) == 1
    assert rows[0]["type"] == "CORP_ACTION"


def test_query_ignores_malformed_lines(tmp_path: Path) -> None:
    path = tmp_path / "index_history.jsonl"
    path.write_text(
        'not-json\n{"type":"CORP_ACTION","timestamp":5.0}\n', encoding="utf-8"
    )
    history = IndexHistory(str(path))

    rows, warnings = history.query(0.0, 10.0, {"CORP_ACTION"})
    assert len(rows) == 1
    assert warnings


def test_query_invalid_time_window_rejected(tmp_path: Path) -> None:
    history = IndexHistory(str(tmp_path / "x.jsonl"))
    with pytest.raises(ValueError):
        history.query(10.0, 0.0, {"CORP_ACTION"})


def test_query_max_records_limit(tmp_path: Path) -> None:
    history = IndexHistory(str(tmp_path / "x.jsonl"))
    history.append({"type": "CORP_ACTION", "timestamp": 1.0})
    history.append({"type": "CORP_ACTION", "timestamp": 2.0})
    history.flush()

    rows, _ = history.query(0.0, 5.0, {"CORP_ACTION"}, max_records=1)
    assert len(rows) == 1


def test_query_missing_file_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "missing.jsonl"
    history = IndexHistory(str(path))
    history.close()
    path.unlink()

    rows, warnings = history.query(0.0, 10.0, {"CORP_ACTION"})
    assert rows == []
    assert warnings == []


def test_query_invalid_type_and_timestamp_warnings(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text(
        "\n".join(
            [
                '{"type":123,"timestamp":1.0}',
                '{"type":"CORP_ACTION","timestamp":"bad"}',
                '{"type":"WHATEVER","timestamp":2.0}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    history = IndexHistory(str(path))
    rows, warnings = history.query(0.0, 10.0, {"CORP_ACTION"})
    assert rows == []
    assert len(warnings) == 3


def test_query_invalid_max_records(tmp_path: Path) -> None:
    history = IndexHistory(str(tmp_path / "x.jsonl"))
    with pytest.raises(ValueError):
        history.query(0.0, 10.0, {"CORP_ACTION"}, max_records=0)


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
    path.write_text(
        '{"type":"LEVEL","timestamp":5.0,"level":100.0}\n', encoding="utf-8"
    )
    history = IndexHistory(str(path))

    rows, warnings = history.query(0.0, 10.0, {"CORP_ACTION"})
    assert rows == []
    assert any("unknown record type: LEVEL" in w for w in warnings)


def test_query_treats_eod_as_unknown_type(tmp_path: Path) -> None:
    path = tmp_path / "x.jsonl"
    path.write_text('{"type":"EOD","timestamp":5.0,"level":100.0}\n', encoding="utf-8")
    history = IndexHistory(str(path))

    rows, warnings = history.query(0.0, 10.0, {"CORP_ACTION"})
    assert rows == []
    assert any("unknown record type: EOD" in w for w in warnings)
