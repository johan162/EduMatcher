"""A refused or lost pm-alf-console session says why and exits non-zero
(review WP-ACN05, C5).

An engine that never answered the connect used to be reported as
"Gateway not allowed", and a refusal, an unreachable engine and a lost
connection all exited 0 like EXIT. Now: 1 for refused, unreachable and lost;
0 for EXIT/QUIT, Ctrl-D and Ctrl-C at the prompt.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import zmq

from edumatcher.alf_console.main import Gateway
from tests.test_alf_console_input import _run_scripted, _ScriptedSession
from tests.test_alf_console_quote_ack import _make_gateway

_real_authenticate = Gateway._authenticate


def _printed(mock_print: MagicMock) -> str:
    return "\n".join(
        " ".join(str(a) for a in c.args) for c in mock_print.call_args_list
    )


def _main_with(gateway: Any, monkeypatch: pytest.MonkeyPatch) -> int:
    """Run main() for ``--id GW01`` with *gateway* standing in for the
    Gateway it builds; returns main()'s exit status."""
    from edumatcher.alf_console import main as console_main

    monkeypatch.setattr("sys.argv", ["pm-alf-console", "--id", "GW01"])
    monkeypatch.setattr(console_main, "_configure_logging", lambda _args: 30)
    monkeypatch.setattr(console_main, "Gateway", lambda *_a, **_kw: gateway)
    return console_main.main()


# ---------------------------------------------------------------------------
# 1: the connect never leaves the host
# ---------------------------------------------------------------------------


def test_unreachable_engine_says_so_and_exits_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gw, push = _make_gateway("GW01")
    push.send_multipart.side_effect = zmq.Again()
    monkeypatch.setattr(
        gw,
        "_authenticate",
        lambda: _real_authenticate(gw, timeout_sec=0.2),
    )

    with patch("edumatcher.alf_console.main.console.print") as mock_print:
        status = _main_with(gw, monkeypatch)

    assert status == 1
    printed = _printed(mock_print)
    assert "Engine not reachable" in printed
    assert "Gateway not allowed" not in printed


# ---------------------------------------------------------------------------
# 2: the engine refuses the id
# ---------------------------------------------------------------------------


def test_refused_logon_prints_the_engines_reason_and_exits_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gw, _push = _make_gateway("GW01")

    def _refused() -> bool:
        gw._auth_reason = "Gateway already connected: GW01"
        return False

    monkeypatch.setattr(gw, "_authenticate", _refused)

    with patch("edumatcher.alf_console.main.console.print") as mock_print:
        status = _main_with(gw, monkeypatch)

    assert status == 1
    assert "Gateway already connected: GW01" in _printed(mock_print)


# ---------------------------------------------------------------------------
# 3: the engine goes away during the session
# ---------------------------------------------------------------------------


class _LosingSession(_ScriptedSession):
    """The listener notices the engine is gone and ends the prompt, the way
    ``_engine_connection_lost`` does it (``app.exit(KeyboardInterrupt)``)."""

    def __init__(self, gw: Any) -> None:
        super().__init__([])
        self._gw = gw

    def prompt(self, *_a: Any, **_kw: Any) -> str:
        self._gw._engine_connection_lost()
        raise KeyboardInterrupt


def test_lost_engine_connection_exits_1() -> None:
    gw, _push = _make_gateway("GW01")
    gw._symbols_received.set()
    with (
        patch("edumatcher.alf_console.main.console.print"),
        patch.object(gw, "_authenticate", return_value=True),
        patch.object(gw, "_listen"),
        patch.object(gw, "_heartbeat_loop"),
        patch(
            "edumatcher.alf_console.main.PromptSession",
            return_value=_LosingSession(gw),
        ),
        patch("edumatcher.alf_console.main.pt_patch_stdout"),
    ):
        assert gw.run() == 1


# ---------------------------------------------------------------------------
# 4: leaving on purpose is success, unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lines", [["EXIT"], ["QUIT"], []], ids=["EXIT", "QUIT", "^D"])
def test_leaving_on_purpose_exits_0(lines: list[str]) -> None:
    gw, _push = _make_gateway("GW01")
    with patch("edumatcher.alf_console.main.console.print"):
        assert _run_scripted(gw, lines) == 0


def test_ctrl_c_at_the_prompt_exits_0() -> None:
    class _CtrlC(_ScriptedSession):
        def prompt(self, *_a: Any, **_kw: Any) -> str:
            raise KeyboardInterrupt

    gw, _push = _make_gateway("GW01")
    gw._symbols_received.set()
    with (
        patch("edumatcher.alf_console.main.console.print"),
        patch.object(gw, "_authenticate", return_value=True),
        patch.object(gw, "_listen"),
        patch.object(gw, "_heartbeat_loop"),
        patch("edumatcher.alf_console.main.PromptSession", return_value=_CtrlC([])),
        patch("edumatcher.alf_console.main.pt_patch_stdout"),
    ):
        assert gw.run() == 0


def test_main_passes_exit_0_through(monkeypatch: pytest.MonkeyPatch) -> None:
    gw = MagicMock()
    gw.run.return_value = 0
    assert _main_with(gw, monkeypatch) == 0
