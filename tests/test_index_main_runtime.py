from __future__ import annotations

import errno
import json
from pathlib import Path
from collections.abc import Generator
from collections.abc import Callable
import time
from typing import Any, cast

import pytest
import zmq

import edumatcher.index.main as index_main
from edumatcher.index.config_loader import IndexRuntimeConfig
from edumatcher.models.message import decode as decode_message


class _FakeSocket:
    def __init__(self) -> None:
        self.options: list[tuple[int, bytes]] = []
        self.closed = False
        self.sent: list[list[bytes]] = []
        self.inbound: list[list[bytes]] = []

    def poll(self, timeout: int = 0) -> bool:
        _ = timeout
        return bool(self.inbound)

    def recv_multipart(self) -> list[bytes]:
        return self.inbound.pop(0)

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True

    def setsockopt(self, option: int, value: bytes) -> None:
        self.options.append((option, value))


class _PollerOneCycleThenStop:
    def __init__(self, proc: index_main.IndexProcess) -> None:
        self._proc = proc
        self._count = 0

    def register(self, _sock: Any, _mask: int) -> None:
        return None

    def poll(self, timeout: int) -> list[tuple[Any, int]]:
        _ = timeout
        self._count += 1
        if self._count == 1:
            for sock in (self._proc._sub_sock, self._proc._pull_sock):
                cast(_FakeSocket, sock).inbound.append([b"topic", b"payload"])
            return [
                (self._proc._sub_sock, zmq.POLLIN),
                (self._proc._pull_sock, zmq.POLLIN),
            ]
        self._proc.stop()
        return []


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def proc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[index_main.IndexProcess, None, None]:
    sub = _FakeSocket()
    pull = _FakeSocket()
    pub = _FakeSocket()
    engine_push = _FakeSocket()

    monkeypatch.setattr(index_main, "make_subscriber", lambda *_a, **_k: sub)
    monkeypatch.setattr(index_main, "make_pusher", lambda *_a, **_k: engine_push)
    monkeypatch.setattr(index_main, "make_puller", lambda *_a, **_k: pull)
    monkeypatch.setattr(index_main, "make_publisher", lambda *_a, **_k: pub)
    monkeypatch.setattr(index_main, "make_replier", lambda *_a, **_k: _FakeSocket())

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
        tradeable_symbols=frozenset({"AAPL", "MSFT", "GOOG", "AMZN"}),
    )
    monkeypatch.setattr(index_main, "load_index_runtime_configs", lambda _p: [cfg])

    process = index_main.IndexProcess(config_path=tmp_path / "engine.yaml", reset=False)
    yield process
    process.close()


def test_run_dispatches_sub_and_pull_topics(
    proc: index_main.IndexProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Intent: one poll cycle should route sub and pull traffic to the correct
    handlers before the loop stops.
    """
    trade_calls: list[dict[str, Any]] = []
    history_calls: list[dict[str, Any]] = []

    monkeypatch.setattr(
        zmq,
        "Poller",
        lambda: _PollerOneCycleThenStop(proc),
    )
    monkeypatch.setattr(
        proc, "_handle_trade", lambda payload: trade_calls.append(payload)
    )
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
    assert history_calls == [
        {"gateway_id": "GW1", "index_id": "EDU100", "from_ts": 0.0}
    ]
    engine_push = cast(_FakeSocket, proc._engine_push)
    assert decode_message(engine_push.sent[0]) == (
        "system.session_state_request",
        {"gateway_id": "PM_INDEX"},
    )


def test_run_ignores_malformed_frames_without_crashing(
    proc: index_main.IndexProcess,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Intent: malformed frames on either socket should be logged and skipped,
    not terminate the process.
    """
    monkeypatch.setattr(
        zmq,
        "Poller",
        lambda: _PollerOneCycleThenStop(proc),
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


# --- WP-IDX03 (C1): the throttle publishes the trailing level ----------------


class _ScriptedIdlePoller:
    """An idle poller that runs ``script`` steps once their time has come and
    stops the process ``until`` seconds after the loop started."""

    def __init__(
        self,
        proc: index_main.IndexProcess,
        script: list[tuple[float, Callable[[], None]]],
        until: float,
    ) -> None:
        self._proc = proc
        self._script = list(script)
        self._until = until
        self._start: float | None = None

    def register(self, _sock: Any, _mask: int) -> None:
        return None

    def poll(self, timeout: int) -> list[tuple[Any, int]]:
        _ = timeout
        now = time.monotonic()
        if self._start is None:
            self._start = now
        elapsed = now - self._start
        while self._script and self._script[0][0] <= elapsed:
            self._script.pop(0)[1]()
        if elapsed >= self._until:
            self._proc.stop()
        time.sleep(0.005)
        return []


def _timed_updates(
    proc: index_main.IndexProcess, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[float, dict[str, Any]]]:
    """Record every index.update with the monotonic time it was sent."""
    out: list[tuple[float, dict[str, Any]]] = []
    pub = cast(_FakeSocket, proc._pub_sock)
    send = pub.send_multipart

    def record(frames: list[bytes]) -> None:
        topic, payload = decode_message(frames)
        if topic == "index.update":
            out.append((time.monotonic(), payload))
        send(frames)

    monkeypatch.setattr(pub, "send_multipart", record)
    return out


def _with_interval(seconds: float) -> None:
    """Set the fixture's (frozen) index config's publish interval."""
    (cfg,) = getattr(index_main, "load_index_runtime_configs")(Path("unused"))
    object.__setattr__(cfg, "publish_interval_sec", seconds)


def _trade(proc: index_main.IndexProcess, price: float) -> Callable[[], None]:
    return lambda: proc._handle_trade({"symbol": "AAPL", "price": price})


def test_a_throttled_level_is_published_once_the_interval_has_passed(
    proc: index_main.IndexProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_interval(0.3)
    updates = _timed_updates(proc, monkeypatch)
    script = [(0.0, _trade(proc, 110.0)), (0.1, _trade(proc, 120.0))]
    monkeypatch.setattr(
        zmq, "Poller", lambda: _ScriptedIdlePoller(proc, script, until=0.6)
    )

    proc.run()

    assert updates[-1][1]["level"] == pytest.approx(1200.0)


def test_a_steady_stream_still_publishes_at_most_once_per_interval(
    proc: index_main.IndexProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_interval(0.2)
    updates = _timed_updates(proc, monkeypatch)
    script = [(i * 0.01, _trade(proc, 100.0 + i)) for i in range(60)]
    monkeypatch.setattr(
        zmq, "Poller", lambda: _ScriptedIdlePoller(proc, script, until=0.9)
    )

    proc.run()

    trade_updates = [t for t, u in updates if u["session_state"] == "UNKNOWN"]
    gaps = [b - a for a, b in zip(trade_updates, trade_updates[1:])]
    assert gaps and min(gaps) >= 0.2 - 1e-3
    assert updates[-1][1]["level"] == pytest.approx(1590.0)


def test_a_forced_publish_clears_the_pending_level(
    proc: index_main.IndexProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    _with_interval(0.3)
    updates = _timed_updates(proc, monkeypatch)

    def corp_action() -> None:
        proc._handle_corp_action(
            {
                "gateway_id": "GW1",
                "index_id": "EDU100",
                "action": "SHARES_ISSUANCE",
                "symbol": "AAPL",
                "new_shares_outstanding": 20_000,
            }
        )

    script = [
        (0.0, _trade(proc, 110.0)),
        (0.05, _trade(proc, 120.0)),
        (0.1, corp_action),
    ]
    monkeypatch.setattr(
        zmq, "Poller", lambda: _ScriptedIdlePoller(proc, script, until=0.6)
    )

    proc.run()

    levels = [u["level"] for _, u in updates]
    assert levels == [pytest.approx(1100.0), pytest.approx(1200.0)]


# --- WP-IDX04 (C8, C9): the loop survives a write failure and EINTR ----------


def _enospc() -> OSError:
    return OSError(errno.ENOSPC, "No space left on device")


def test_a_failing_checkpoint_does_not_end_the_loop_and_is_retried(
    proc: index_main.IndexProcess,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(index_main, "CHECKPOINT_INTERVAL_SEC", 0.0)
    real_write = getattr(index_main, "atomic_write_text")
    failures = {"left": 0}

    def write(path: Path, text: str) -> None:
        if failures["left"]:
            failures["left"] -= 1
            raise _enospc()
        real_write(path, text)

    def trade_with_full_disk() -> None:
        failures["left"] = 1
        proc._handle_trade({"symbol": "AAPL", "price": 120.0})

    monkeypatch.setattr(index_main, "atomic_write_text", write)
    monkeypatch.setattr(
        zmq,
        "Poller",
        lambda: _ScriptedIdlePoller(proc, [(0.0, trade_with_full_disk)], until=0.1),
    )

    with caplog.at_level("ERROR"):
        proc.run()  # returns: the failure did not end the loop

    assert failures["left"] == 0
    assert "No space left on device" in caplog.text
    state = json.loads(Path(proc._indices["EDU100"].cfg.state_file).read_text())
    assert state["last_prices"]["AAPL"] == 120.0
    assert proc._indices["EDU100"].dirty is False


def test_a_failing_history_flush_does_not_end_the_loop(
    proc: index_main.IndexProcess,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = {"flush": 0}

    def break_flush() -> None:
        history = proc._indices["EDU100"].history
        real_flush = history.flush

        def flush() -> None:
            calls["flush"] += 1
            if calls["flush"] == 1:
                raise _enospc()
            real_flush()

        monkeypatch.setattr(history, "flush", flush)

    monkeypatch.setattr(
        zmq,
        "Poller",
        lambda: _ScriptedIdlePoller(proc, [(0.0, break_flush)], until=0.1),
    )

    with caplog.at_level("ERROR"):
        proc.run()

    assert calls["flush"] >= 2
    assert "No space left on device" in caplog.text


def test_eintr_from_poll_does_not_end_the_loop(
    proc: index_main.IndexProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    polls = {"n": 0}

    class _EintrThenStop:
        def register(self, _sock: Any, _mask: int) -> None:
            return None

        def poll(self, timeout: int) -> list[tuple[Any, int]]:
            polls["n"] += 1
            if polls["n"] == 1:
                raise zmq.ZMQError(errno.EINTR)
            proc.stop()
            return []

    monkeypatch.setattr(zmq, "Poller", _EintrThenStop)

    proc.run()

    assert polls["n"] == 2


def test_close_after_a_failing_write_logs_and_closes_every_socket(
    proc: index_main.IndexProcess,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    proc._initialise()
    proc._indices["EDU100"].dirty = True

    def write(_path: Path, _text: str) -> None:
        raise _enospc()

    monkeypatch.setattr(index_main, "atomic_write_text", write)

    with caplog.at_level("ERROR"):
        proc.close()

    assert "No space left on device" in caplog.text
    for sock in (proc._sub_sock, proc._engine_push, proc._pull_sock, proc._pub_sock):
        assert cast(_FakeSocket, sock).closed


def test_a_failing_write_at_the_close_still_finalises_every_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pub = _FakeSocket()
    for name in ("make_subscriber", "make_pusher", "make_puller", "make_replier"):
        monkeypatch.setattr(index_main, name, lambda *_a, **_k: _FakeSocket())
    monkeypatch.setattr(index_main, "make_publisher", lambda *_a, **_k: pub)
    configs = [
        IndexRuntimeConfig(
            id=index_id,
            description=index_id,
            base_value=1000.0,
            publish_interval_sec=0.0,
            history_file=str(tmp_path / f"{index_id}-history.jsonl"),
            state_file=str(tmp_path / f"{index_id}-state.json"),
            constituents=["AAPL"],
            outstanding_shares={"AAPL": 10_000},
            reference_prices={"AAPL": 100.0},
            tradeable_symbols=frozenset({"AAPL", "MSFT", "GOOG", "AMZN"}),
        )
        for index_id in ("EDU100", "TECH2")
    ]
    monkeypatch.setattr(index_main, "load_index_runtime_configs", lambda _p: configs)
    proc = index_main.IndexProcess(config_path=tmp_path / "engine.yaml")
    proc._initialise()

    def write(_path: Path, _text: str) -> None:
        raise _enospc()

    monkeypatch.setattr(index_main, "atomic_write_text", write)
    try:
        proc._handle_session_state({"state": "CLOSED"})

        closes = {
            p["index_id"]
            for t, p in map(decode_message, pub.sent)
            if t == "index.update" and p["session_state"] == "CLOSED"
        }
        assert closes == {"EDU100", "TECH2"}
        assert all(i.dirty for i in proc._indices.values())
    finally:
        monkeypatch.undo()
        proc.close()


# --- WP-IDX06 (P2): drain queued messages per wake-up ------------------------


def test_queued_trades_are_handled_in_one_wake_up(
    proc: index_main.IndexProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edumatcher.models.message import encode

    sub = cast(_FakeSocket, proc._sub_sock)
    sub.inbound = [
        encode("trade.executed", {"symbol": "AAPL", "price": 100.0 + i / 100})
        for i in range(300)
    ]
    handled: list[float] = []
    real_trade = proc._handle_trade

    def trade(payload: dict[str, Any]) -> None:
        handled.append(payload["price"])
        real_trade(payload)

    monkeypatch.setattr(proc, "_handle_trade", trade)
    polls = {"n": 0}

    class _OneWakeUp:
        def register(self, _sock: Any, _mask: int) -> None:
            return None

        def poll(self, timeout: int) -> list[tuple[Any, int]]:
            polls["n"] += 1
            if polls["n"] == 1:
                return [(sub, zmq.POLLIN)]
            proc.stop()
            return []

    monkeypatch.setattr(zmq, "Poller", _OneWakeUp)

    proc.run()

    assert len(handled) == 300
    assert polls["n"] == 2  # the wake-up, then the one that stopped the loop
    assert sub.inbound == []
