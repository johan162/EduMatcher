from __future__ import annotations

import errno
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import zmq

import edumatcher.index.main as index_main
from edumatcher.index.config_loader import IndexRuntimeConfig


class _FakeSocket:
    def __init__(self) -> None:
        self.closed = False

    def recv_multipart(self) -> list[bytes]:
        return [b"topic", b"payload"]

    def send_multipart(self, _frames: list[bytes]) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class _PollerOneCycleThenEintr:
    def __init__(self, sub_sock: Any, pull_sock: Any) -> None:
        self._sub_sock = sub_sock
        self._pull_sock = pull_sock
        self._count = 0

    def register(self, _sock: Any, _mask: int) -> None:
        return None

    def poll(self, timeout: int) -> list[tuple[Any, int]]:
        _ = timeout
        self._count += 1
        if self._count == 1:
            return [(self._sub_sock, zmq.POLLIN), (self._pull_sock, zmq.POLLIN)]
        raise zmq.ZMQError(errno.EINTR)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def proc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> index_main.IndexProcess:
    sub = _FakeSocket()
    pull = _FakeSocket()
    pub = _FakeSocket()

    monkeypatch.setattr(index_main, "make_subscriber", lambda *_a, **_k: sub)
    monkeypatch.setattr(index_main, "make_puller", lambda *_a, **_k: pull)
    monkeypatch.setattr(index_main, "make_publisher", lambda *_a, **_k: pub)

    cfg = IndexRuntimeConfig(
        id="EDU100",
        description="Education 100",
        base_value=1000.0,
        publish_interval_sec=0.0,
        history_file=str(tmp_path / "index_history.jsonl"),
        state_file=str(tmp_path / "index_state.json"),
        constituents=["AAPL"],
        outstanding_shares={"AAPL": 10_000},
        reference_prices={"AAPL": 100.0},
    )
    monkeypatch.setattr(index_main, "load_index_runtime_configs", lambda _p: [cfg])

    process = index_main.IndexProcess(config_path=tmp_path / "engine.yaml", reset=False)
    yield process
    process.close()


def test_run_dispatches_sub_and_pull_topics(
    proc: index_main.IndexProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Intent: one poll cycle should route sub and pull traffic to the correct
    handlers before exiting cleanly on EINTR.
    """
    trade_calls: list[dict[str, Any]] = []
    history_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        index_main.zmq,
        "Poller",
        lambda: _PollerOneCycleThenEintr(proc._sub_sock, proc._pull_sock),
    )
    monkeypatch.setattr(proc, "_handle_trade", lambda payload: trade_calls.append(payload))
    monkeypatch.setattr(
        proc, "_handle_history_request", lambda payload: history_calls.append(payload)
    )
    decoded = iter(
        [
            ("trade.executed", {"symbol": "AAPL", "price": 101.25}),
            (
                "index.history_request",
                {"gateway_id": "GW1", "index_id": "EDU100", "from_ts": 0.0},
            ),
        ]
    )
    monkeypatch.setattr(index_main, "decode", lambda _frames: next(decoded))

    proc.run()

    assert trade_calls == [{"symbol": "AAPL", "price": 101.25}]
    assert history_calls == [{"gateway_id": "GW1", "index_id": "EDU100", "from_ts": 0.0}]


def test_run_ignores_malformed_frames_without_crashing(
    proc: index_main.IndexProcess,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Intent: malformed frames on either socket should be logged and skipped,
    not terminate the process.
    """
    monkeypatch.setattr(
        index_main.zmq,
        "Poller",
        lambda: _PollerOneCycleThenEintr(proc._sub_sock, proc._pull_sock),
    )
    decoded_errors = iter([ValueError("bad sub"), ValueError("bad pull")])

    def _decode_raises(_frames: list[bytes]) -> tuple[str, dict[str, Any]]:
        err = next(decoded_errors)
        raise err

    monkeypatch.setattr(index_main, "decode", _decode_raises)

    with caplog.at_level("WARNING"):
        proc.run()

    assert "malformed sub frame" in caplog.text
    assert "malformed pull frame" in caplog.text
