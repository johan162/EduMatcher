"""A console whose terminal closes, or that is killed, logs out at once.

Without a handler, SIGHUP (the terminal window closed) and SIGTERM (kill) end
the process without the logout, so the participant ID stayed connected, and
its orders resting, until the engine had missed three heartbeats -- three
minutes at the old 60 s interval. Now both signals take the same exit as
EXIT, and the interactive consoles beat every 5 s, so a console that dies
without any chance to log out frees its ID within ~15 s.
"""

from __future__ import annotations

import os
import signal
import threading
from contextlib import nullcontext
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.cli_signals import logout_on_hangup
from edumatcher.commands import console as console_mod
from edumatcher.models.message import INTERACTIVE_HEARTBEAT_INTERVAL_SEC, decode
from tests.test_alf_console_input import _pushed_topics, _run_scripted
from tests.test_alf_console_quote_ack import _make_gateway

_SIGNALS = [signal.SIGHUP, signal.SIGTERM]


# ---------------------------------------------------------------------------
# The helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("signum", _SIGNALS)
def test_logout_on_hangup_routes_the_signal_to_the_callback(signum: int) -> None:
    before = signal.getsignal(signum)
    called: list[str] = []

    with logout_on_hangup(lambda: called.append("exit")):
        os.kill(os.getpid(), signum)

    assert called == ["exit"]
    assert signal.getsignal(signum) == before


def test_logout_on_hangup_is_a_no_op_off_the_main_thread() -> None:
    """signal.signal() raises outside the main thread; the helper must not."""
    errors: list[BaseException] = []
    before = signal.getsignal(signal.SIGHUP)

    def _worker() -> None:
        try:
            with logout_on_hangup(lambda: None):
                assert signal.getsignal(signal.SIGHUP) == before
        except BaseException as exc:  # pragma: no cover - reported below
            errors.append(exc)

    worker = threading.Thread(target=_worker)
    worker.start()
    worker.join()

    assert errors == []


# ---------------------------------------------------------------------------
# pm-alf-console
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("signum", _SIGNALS)
def test_alf_console_logs_out_on_hangup_and_term(signum: int) -> None:
    gw, push = _make_gateway("GW01")
    before = signal.getsignal(signum)

    class _SignalledSession:
        def __init__(self) -> None:
            self.app = MagicMock()
            self.prompted = 0

        def prompt(self, *_a: Any, **_kw: Any) -> str:
            self.prompted += 1
            assert self.prompted == 1, "prompted again after the signal"
            os.kill(os.getpid(), signum)
            return ""

    session = _SignalledSession()
    with (
        patch("edumatcher.alf_console.main.console.print"),
        patch("edumatcher.alf_console.main.PromptSession", return_value=session),
    ):
        status = _run_scripted(gw, [])

    assert status == 0
    topics = _pushed_topics(push)
    assert topics.count("system.gateway_disconnect") == 1
    assert signal.getsignal(signum) == before


def test_alf_console_heartbeat_uses_the_interactive_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gw, _push = _make_gateway("GW01")
    own_push = MagicMock()
    waits: list[float] = []

    def _wait(timeout: float) -> bool:
        waits.append(timeout)
        return True

    monkeypatch.setattr(gw._heartbeat_stop, "wait", _wait)
    with patch("edumatcher.alf_console.main.make_pusher", return_value=own_push):
        gw._heartbeat_loop()

    _topic, payload = decode(own_push.send_multipart.call_args.args[0])
    assert payload["interval_sec"] == INTERACTIVE_HEARTBEAT_INTERVAL_SEC == 5
    assert waits == [INTERACTIVE_HEARTBEAT_INTERVAL_SEC]


# ---------------------------------------------------------------------------
# pm-admin
# ---------------------------------------------------------------------------


class _AdminClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def connect(self) -> dict[str, Any]:
        return {"accepted": True}

    def symbol_list(self) -> list[str]:
        return []

    def engine_disconnect_monitor(self) -> MagicMock:
        return MagicMock()

    def close_engine_disconnect_monitor(self, _monitor: Any) -> None:
        pass

    def disconnect(self) -> None:
        self.calls.append("disconnect")

    def close(self) -> None:
        self.calls.append("close")


@pytest.mark.parametrize("signum", _SIGNALS)
def test_admin_console_logs_out_on_hangup_and_term(
    monkeypatch: pytest.MonkeyPatch, signum: int
) -> None:
    client = _AdminClient()
    before = signal.getsignal(signum)
    monkeypatch.setattr(console_mod, "ExchangeCommandClient", lambda _gw: client)
    monkeypatch.setattr(console_mod, "make_pusher", lambda _addr: MagicMock())
    monkeypatch.setattr(console_mod.console, "print", lambda *_a, **_kw: None)
    monkeypatch.setattr(console_mod, "pt_patch_stdout", lambda raw=True: nullcontext())

    class _SignalledSession:
        def __init__(self, **_kwargs: Any) -> None:
            self.app = MagicMock()
            self.prompted = 0

        def prompt(self, *_a: Any, **_kw: Any) -> str:
            self.prompted += 1
            assert self.prompted == 1, "prompted again after the signal"
            os.kill(os.getpid(), signum)
            return ""

    monkeypatch.setattr(console_mod, "PromptSession", _SignalledSession)

    console_mod.AdminConsole("GW_ADMIN").run()

    assert client.calls == ["disconnect", "close"]
    assert signal.getsignal(signum) == before


def test_admin_heartbeat_uses_the_interactive_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pusher = MagicMock()
    monkeypatch.setattr(
        console_mod, "ExchangeCommandClient", lambda _gw: _AdminClient()
    )
    monkeypatch.setattr(console_mod, "make_pusher", lambda _addr: pusher)
    admin = console_mod.AdminConsole("GW_ADMIN")
    waits: list[float] = []

    def _wait(timeout: float) -> bool:
        waits.append(timeout)
        return True

    monkeypatch.setattr(admin._heartbeat_stop, "wait", _wait)
    admin._heartbeat_loop()

    _topic, payload = decode(pusher.send_multipart.call_args.args[0])
    assert payload["interval_sec"] == INTERACTIVE_HEARTBEAT_INTERVAL_SEC
    assert waits == [INTERACTIVE_HEARTBEAT_INTERVAL_SEC]
