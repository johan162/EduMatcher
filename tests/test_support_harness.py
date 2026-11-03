from __future__ import annotations

import errno
import math
import sqlite3
from pathlib import Path

import pytest

from edumatcher.index.calculator import IndexCalculator
from edumatcher.index.history import IndexHistory
from tests.support.badvalues import ABSENT, BAD_VALUES
from tests.support.counting import (
    CallCounter,
    IterationCounter,
    assert_query_plan_has_no_temp_btree,
)
from tests.support.faults import fail_always, fail_once, fail_oserror
from tests.support.restart import restart_equivalence


def test_restart_equivalence_with_index_history(tmp_path: Path) -> None:
    path = tmp_path / "index.jsonl"
    history = IndexHistory(str(path))
    history.append({"type": "INIT", "ts_ns": 1, "index_id": "IDX", "level": 1000.0})
    history.flush()
    restarted: list[IndexHistory] = []

    def reopen() -> IndexHistory:
        restored = IndexHistory(str(path))
        restarted.append(restored)
        return restored

    try:
        restart_equivalence(
            history,
            restart=reopen,
            snapshot=lambda current: current.query(0, 2, {"INIT"}),
            durable=path.read_bytes,
        )
    finally:
        history.close()
        for restored in restarted:
            restored.close()


def test_restart_equivalence_detects_observable_and_durable_drift() -> None:
    state = {"value": 1, "durable": 1}
    with pytest.raises(AssertionError, match="observables"):
        restart_equivalence(
            state,
            restart=lambda: {"value": 2, "durable": 1},
            snapshot=lambda current: current["value"],
            durable=lambda: state["durable"],
        )
    reads = 0

    def changing_durable() -> int:
        nonlocal reads
        reads += 1
        return reads

    with pytest.raises(AssertionError, match="durable"):
        restart_equivalence(
            state,
            restart=lambda: state,
            snapshot=lambda current: current["value"],
            durable=changing_durable,
        )


def test_fault_injection_restores_callable(monkeypatch: pytest.MonkeyPatch) -> None:
    class Writer:
        def write(self, value: str) -> str:
            return value

    writer = Writer()
    with fail_once(monkeypatch, writer, "write", RuntimeError("disk full")):
        with pytest.raises(RuntimeError, match="disk full"):
            writer.write("first")
        assert writer.write("second") == "second"
    assert writer.write("after") == "after"
    with fail_always(monkeypatch, writer, "write", ValueError("unavailable")):
        with pytest.raises(ValueError, match="unavailable"):
            writer.write("first")
        with pytest.raises(ValueError, match="unavailable"):
            writer.write("second")
    assert writer.write("after") == "after"


def test_oserror_injection(monkeypatch: pytest.MonkeyPatch) -> None:
    class Socket:
        def send(self) -> str:
            return "sent"

    sock = Socket()
    with fail_oserror(monkeypatch, sock, "send", errno.ECONNRESET):
        with pytest.raises(OSError) as exc_info:
            sock.send()
        assert exc_info.value.errno == errno.ECONNRESET
        assert sock.send() == "sent"


def test_actor_fixtures(
    gateway_ids: tuple[str, str],
    symbol_ticks: dict[str, int],
    single_constituent_index: IndexCalculator,
) -> None:
    assert gateway_ids[0] != gateway_ids[1]
    assert len(symbol_ticks) == 2
    assert len(set(symbol_ticks.values())) == 2
    assert len(single_constituent_index.constituent_symbols()) == 1
    assert single_constituent_index.recalculate() == pytest.approx(1000.0)


@pytest.mark.parametrize("bad_value", BAD_VALUES)
def test_bad_value_in_decoded_payload(bad_value: object) -> None:
    payload: dict[str, object] = {"price": 100.0}
    if bad_value is ABSENT:
        payload.pop("price")
        assert "price" not in payload
    else:
        payload["price"] = bad_value
        if isinstance(bad_value, float) and math.isnan(bad_value):
            assert math.isnan(bad_value)
        else:
            assert payload["price"] == bad_value


def test_counting_helpers_on_index_history(tmp_path: Path) -> None:
    history = IndexHistory(str(tmp_path / "index.jsonl"))
    try:
        history.append({"type": "INIT", "ts_ns": 1, "index_id": "IDX", "level": 1.0})
        history.flush()
        counted = CallCounter(history.query)
        rows, warnings = counted(0, 2, {"INIT"})
        visited = IterationCounter(rows)
        assert list(visited) == rows
        assert counted.calls == 1
        assert visited.iterations == 1
        assert warnings == []
    finally:
        history.close()


def test_query_plan_guard(tmp_path: Path) -> None:
    with sqlite3.connect(tmp_path / "plan.db") as conn:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, label TEXT)")
        conn.executemany("INSERT INTO items (label) VALUES (?)", [("b",), ("a",)])
        assert_query_plan_has_no_temp_btree(
            conn, "SELECT id FROM items WHERE id = ?", (1,)
        )
        with pytest.raises(AssertionError, match="TEMP B-TREE"):
            assert_query_plan_has_no_temp_btree(
                conn, "SELECT label FROM items ORDER BY label"
            )
