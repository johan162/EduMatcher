"""A dead engine listener stops the process (API gateway review C5).

The receive thread ended on any ZMQError other than EINTR and the process
kept serving: every engine call then waited its full timeout, the WebSockets
went silent, and only ``/healthz`` knew. Lessons-learned A4: a dying worker
thread makes the process exit non-zero.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import uvicorn
import zmq

from edumatcher.api_gateway import main
from edumatcher.api_gateway.config import ApiGatewayConfig
from edumatcher.api_gateway.engine_client import EngineClient


class _FailingPoller:
    def register(self, *_: Any) -> None:
        return None

    def poll(self, timeout: int = 0) -> list[Any]:
        raise zmq.ZMQError(errno.EFAULT)


class _IdlePoller(_FailingPoller):
    def poll(self, timeout: int = 0) -> list[Any]:
        return []


def _engine() -> EngineClient:
    with (
        patch(
            "edumatcher.api_gateway.engine_client.make_pusher",
            return_value=MagicMock(closed=False),
        ),
        patch(
            "edumatcher.api_gateway.engine_client.make_subscriber",
            return_value=MagicMock(),
        ),
    ):
        engine = EngineClient(
            "tcp://127.0.0.1:1", "tcp://127.0.0.1:2", asyncio.get_running_loop()
        )
    return engine


@pytest.mark.anyio
async def test_a_dying_listener_is_logged_and_reported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    died = asyncio.Event()
    with patch("edumatcher.api_gateway.engine_client.zmq.Poller", _FailingPoller):
        engine = _engine()
        engine.on_listener_failure = died.set
        with caplog.at_level(logging.ERROR):
            engine.start_listener()
            await asyncio.wait_for(died.wait(), timeout=2.0)
    assert not engine.is_running()
    assert any(
        r.levelno == logging.ERROR and "engine listener died" in r.getMessage()
        for r in caplog.records
    )
    engine.stop_listener()


@pytest.mark.anyio
async def test_a_normal_stop_reports_nothing(caplog: pytest.LogCaptureFixture) -> None:
    called: list[bool] = []
    with patch("edumatcher.api_gateway.engine_client.zmq.Poller", _IdlePoller):
        engine = _engine()
        engine.on_listener_failure = lambda: called.append(True)
        with caplog.at_level(logging.ERROR):
            engine.start_listener()
            await asyncio.sleep(0.05)
            engine.stop_listener()
            await asyncio.sleep(0.05)
    assert called == []
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_main_exits_non_zero_when_the_listener_died(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lifespan marks the failure and asks the server to stop; once the
    server has returned, main() turns that into exit status 1."""
    root = logging.getLogger()
    original_level = root.level
    config = ApiGatewayConfig(host="127.0.0.9", port=9191, log_level="info")
    monkeypatch.setattr(sys, "argv", ["pm-api-gwy"])
    monkeypatch.setattr(main, "_config_with_overrides", lambda _args: config)

    class _Server:
        def __init__(self, server_config: uvicorn.Config) -> None:
            self.app: Any = server_config.app
            self.should_exit = False

        def run(self) -> None:
            # What the lifespan's failure callback does.
            self.app.state.listener_failed = True
            self.app.state.server.should_exit = True

    monkeypatch.setattr(uvicorn, "Server", _Server)
    try:
        with pytest.raises(SystemExit) as exited:
            main.main()
    finally:
        root.setLevel(original_level)
    assert exited.value.code == 1
