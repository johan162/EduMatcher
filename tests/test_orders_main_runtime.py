from __future__ import annotations

import threading
from typing import Any
from unittest.mock import patch

import pytest
import zmq

from edumatcher.orders.main import OrderMonitor


class _FakeSub:
    def __init__(self) -> None:
        self.closed = False

    def recv_multipart(self) -> list[bytes]:
        return [b"topic", b"payload"]

    def close(self) -> None:
        self.closed = True


class _PollerOneEventThenStop:
    def __init__(self, monitor: OrderMonitor, sub: Any) -> None:
        self._monitor = monitor
        self._sub = sub
        self._count = 0

    def register(self, _sock: Any, _mask: int) -> None:
        return None

    def poll(self, timeout: int) -> list[tuple[Any, int]]:
        _ = timeout
        self._count += 1
        if self._count == 1:
            return [(self._sub, zmq.POLLIN)]
        self._monitor._running = False
        return []


class _InlineThread:
    def __init__(self, target: Any, daemon: bool = False) -> None:
        _ = daemon
        self._target = target

    def start(self) -> None:
        self._target()

    def join(self, timeout: float | None = None) -> None:
        _ = timeout
        return None


class _FakeLive:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        _ = (args, kwargs)

    def __enter__(self) -> "_FakeLive":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        _ = (exc_type, exc, tb)
        return False

    def update(self, _table: Any) -> None:
        return None


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_receive_tracks_fill_even_without_prior_ack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Intent: if monitor starts late and misses an ack, fill events must still
    produce a visible row with gateway/status/remaining.
    """
    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter=None)

    with (
        patch(
            "edumatcher.orders.main.zmq.Poller",
            return_value=_PollerOneEventThenStop(monitor, fake_sub),
        ),
        patch(
            "edumatcher.orders.main.decode",
            return_value=(
                "order.fill.GW77",
                {
                    "order_id": "ORD-LATE",
                    "remaining_qty": 3,
                    "status": "PARTIAL",
                    "symbol": "AAPL",
                },
            ),
        ),
    ):
        monitor._receive()

    with monitor._lock:
        row = monitor._orders["ORD-LATE"]
        assert row["gateway_id"] == "GW77"
        assert row["status"] == "PARTIAL"
        assert row["remaining"] == 3


def test_run_closes_subscriber_on_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    """Intent: run loop should always close subscriber resources when exiting."""
    fake_sub = _FakeSub()
    with patch("edumatcher.orders.main.make_subscriber", return_value=fake_sub):
        monitor = OrderMonitor(gw_filter="GW01")

    def _receive_once_then_stop() -> None:
        monitor._running = False

    with (
        patch("edumatcher.orders.main.threading.Thread", _InlineThread),
        patch("edumatcher.orders.main.Live", _FakeLive),
        patch.object(threading, "Event"),
        patch.object(monitor, "_receive", side_effect=_receive_once_then_stop),
        patch("edumatcher.orders.main.signal.signal", lambda *_a, **_k: None),
        patch("edumatcher.orders.main.time.sleep", lambda *_a, **_k: None),
    ):
        monitor.run()

    assert fake_sub.closed is True
