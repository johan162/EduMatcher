"""K5 (C3, C7): clearing starts loudly and its receive loop survives bad values.

C3: a failure while hydrating the ledger from ``gateway_symbol_positions`` was
logged and ignored, so the process ran with an empty ledger and its next flush
UPSERTed flat positions over the persisted ones.
C7: ``gateway_auth`` / ``gateway_bye`` handlers decoded their payload outside
any per-message guard, so a decodable but malformed payload killed the loop.
See docs-design/EduMatcher-Key-Component-Fixes-Workplan.md K5.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from edumatcher.clearing import main as clearing_main
from edumatcher.clearing.main import ClearingProcess
from edumatcher.clearing.store import open_writer_connection, query_trades

from tests.support.badvalues import ABSENT, BAD_VALUES
from tests.support.faults import fail_always
from tests.test_clearing_main import _InprocPublisher, _make_trade, _seed_position

_TOPICS = [
    "trade.executed",
    "system.eod",
    "session.state",
    "system.gateway_auth.GW01",
    "system.gateway_bye.GW01",
    "system.gateway_connect",
    "system.gateway_disconnect",
]
_FIELDS = ["gateway_id", "accepted", "state", "ts_ns", "price", "quantity", "symbol"]


@pytest.fixture()
def zmq_addr(request: pytest.FixtureRequest) -> str:
    return f"inproc://k5-{request.node.name}"


def _process(db_path: Path) -> ClearingProcess:
    return ClearingProcess(
        pub_addr="inproc://k5-unused",
        db_path=db_path,
        flush_size=1,
        flush_interval_sec=3600.0,
        print_every=0,
        retention_days=3650,
    )


def _frames(topic: str, payload: dict[str, Any]) -> list[bytes]:
    return [topic.encode(), json.dumps(payload).encode()]


def test_hydration_failure_is_fatal_not_an_empty_ledger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = tmp_path / "c.db"
    seeded = _process(db)
    _seed_position(seeded, net_qty=500)
    seeded._conn.close()

    with fail_always(
        monkeypatch, clearing_main, "fetch_all_positions", RuntimeError("db locked")
    ):
        with pytest.raises(RuntimeError, match="db locked"):
            _process(db)


@pytest.mark.parametrize("topic", _TOPICS)
@pytest.mark.parametrize("field", _FIELDS)
@pytest.mark.parametrize("bad", BAD_VALUES)
def test_no_handler_raises_out_of_the_loop_on_a_bad_value(
    tmp_path: Path, topic: str, field: str, bad: Any
) -> None:
    process = _process(tmp_path / "c.db")
    payload: dict[str, Any] = {} if bad is ABSENT else {field: bad}

    process._handle_message(_frames(topic, payload))  # must not raise

    process._conn.close()


@pytest.mark.parametrize(
    "topic", ["system.gateway_auth.GW01", "system.gateway_bye.GW01"]
)
def test_loop_keeps_processing_trades_after_a_malformed_gateway_message(
    tmp_path: Path, zmq_addr: str, topic: str
) -> None:
    db = tmp_path / "c.db"
    pub = _InprocPublisher(zmq_addr)
    process = ClearingProcess(
        pub_addr=zmq_addr,
        db_path=db,
        flush_size=1,
        flush_interval_sec=3600.0,
        print_every=0,
        retention_days=3650,
    )
    thread = threading.Thread(target=process.run, daemon=True)
    thread.start()
    time.sleep(0.2)

    pub._pub.send_multipart(_frames(topic, {}))
    pub._pub.send_multipart(_frames(topic, {"gateway_id": None, "accepted": None}))
    pub.publish(_make_trade("1-1"))
    time.sleep(0.3)
    process.stop()
    thread.join(timeout=3.0)
    pub.close()

    assert not thread.is_alive()
    conn = open_writer_connection(db)
    assert [r["id"] for r in query_trades(conn)] == ["1-1"]
    conn.close()
