"""No typed line or table print ends a pm-alf-console session (WP-ACN02).

An exception out of ``_parse_and_send`` used to leave the prompt loop: the
console sent ``system.gateway_disconnect`` and exited, and the engine then
applied the participant's ``disconnect_behaviour`` (by default cancelling
every quote). A bad value is a parse error naming the field; anything
unforeseen is printed and logged, and the prompt carries on.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.alf_console.display import print_positions, print_status
from edumatcher.models.message import decode
from tests.test_alf_console_quote_ack import _make_gateway

_LIMIT = "NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=100|PRICE=150.00"
_OCO = (
    "NEW|TYPE=OCO|OCO_ID=pair|SYM=AAPL|QTY=100|LEG1_SIDE=SELL|LEG1_TYPE=LIMIT|"
    "LEG1_PRICE=155.00|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=145.00"
)

# (typed line, a word the error message must name)
_BAD_LINES = [
    ("AMEND|ID=abc|PRICE=1O0.5", "PRICE"),
    ("AMEND|ID=abc|QTY=ten", "QTY"),
    ("NEW|SYM=AAPL|SIDE=SELL|TYPE=TRAILING_STOP|QTY=100|TRAIL=0,5", "TRAIL"),
    (_OCO.replace("LEG1_PRICE=155.00", "LEG1_PRICE=abc"), "LEG1_PRICE"),
    (_LIMIT.replace("QTY=100", "QTY=0"), "QTY"),
    (_LIMIT.replace("QTY=100", "QTY=-5"), "QTY"),
    (_LIMIT.replace("PRICE=150.00", "PRICE=nan"), "PRICE"),
    (_LIMIT.replace("PRICE=150.00", "PRICE=inf"), "PRICE"),
    (_LIMIT.replace("PRICE=150.00", "PRICE=1e308"), "PRICE"),
    (
        "NEW|TYPE=COMBO|COMBO_ID=c1|LEG_COUNT=2|LEG0.SYM=AAPL|LEG0.SIDE=BUY|"
        "LEG0.QTY=1|LEG0.PRICE=1e308|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=1|"
        "LEG1.PRICE=300.00",
        "Leg 0",
    ),
    ("QUOTE|SYM=AAPL|BID=nan|ASK=150.10|BID_QTY=5|ASK_QTY=5", "BID"),
    (_LIMIT + "|TAG=" + "x" * 65, "TAG"),
]


def _printed(mock_print: MagicMock) -> list[str]:
    return [" ".join(str(a) for a in c.args) for c in mock_print.call_args_list]


# ---------------------------------------------------------------------------
# 1: every H2 input is a parse error, nothing sent, no ghost PENDING row
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("line", "field"), _BAD_LINES, ids=[f for _, f in _BAD_LINES])
def test_bad_value_is_reported_naming_the_field(line: str, field: str) -> None:
    gw, push = _make_gateway("GW01")

    with patch("edumatcher.alf_console.main.console.print") as mock_print:
        gw._parse_and_send(line)

    lines = _printed(mock_print)
    assert len(lines) == 1, lines
    assert "[red]" in lines[0]
    assert field.lower() in lines[0].lower()
    push.send_multipart.assert_not_called()
    assert gw.order_cache == {}


# ---------------------------------------------------------------------------
# 2 + 3: run() keeps the session after a bad line or an unexpected exception
# ---------------------------------------------------------------------------


class _ScriptedSession:
    """Stands in for prompt_toolkit's PromptSession: returns the lines, then
    raises EOFError like Ctrl-D."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)
        self.app = MagicMock()
        self.prompted = 0

    def prompt(self, *_a: Any, **_kw: Any) -> str:
        self.prompted += 1
        if not self._lines:
            raise EOFError
        return self._lines.pop(0)


def _run_scripted(gw: Any, lines: list[str]) -> Any:
    """``gw.run()`` against a scripted prompt; returns its result."""
    # As if the listener had already handled the logon symbol list.
    gw._symbols_received.set()
    with (
        patch.object(gw, "_authenticate", return_value=True),
        patch.object(gw, "_listen"),
        patch.object(gw, "_heartbeat_loop"),
        patch(
            "edumatcher.alf_console.main.PromptSession",
            return_value=_ScriptedSession(lines),
        ),
        patch("edumatcher.alf_console.main.pt_patch_stdout"),
    ):
        return gw.run()


def _pushed_topics(push: MagicMock) -> list[str]:
    return [decode(c.args[0])[0] for c in push.send_multipart.call_args_list]


def test_bad_line_does_not_end_the_session() -> None:
    gw, push = _make_gateway("GW01")

    with (
        patch("edumatcher.alf_console.main.console.print"),
        patch("edumatcher.alf_console.main.print_status") as mock_status,
    ):
        _run_scripted(gw, ["AMEND|ID=abc|PRICE=1O0.5", "STATUS", "EXIT"])

    mock_status.assert_called_once()
    topics = _pushed_topics(push)
    assert topics.count("system.gateway_disconnect") == 1
    assert topics[-1] == "system.gateway_disconnect"


def test_unexpected_exception_is_printed_logged_and_prompt_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    gw, _push = _make_gateway("GW01")

    with (
        patch("edumatcher.alf_console.main.console.print") as mock_print,
        patch.object(
            gw, "_parse_and_send", side_effect=[RuntimeError("boom"), None]
        ) as mock_parse,
        caplog.at_level(logging.ERROR, logger="edumatcher.alf_console.main"),
    ):
        _run_scripted(gw, ["STATUS", "ORDERS"])

    assert mock_parse.call_count == 2
    assert any("boom" in line and "[red]" in line for line in _printed(mock_print))
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors and errors[0].exc_info is not None


# ---------------------------------------------------------------------------
# 4: printing while the listener inserts
# ---------------------------------------------------------------------------


def _hammer(
    target: dict[str, dict[str, Any]], row: dict[str, Any], stop: threading.Event
) -> None:
    i = 0
    while not stop.is_set():
        i += 1
        target[f"k{i}"] = dict(row)
        if len(target) > 6000:
            target.clear()


@pytest.mark.parametrize("which", ["status", "positions"])
def test_printing_while_the_listener_inserts_does_not_raise(which: str) -> None:
    orders: dict[str, dict[str, Any]] = {
        f"o{i}": {"status": "NEW"} for i in range(5000)
    }
    positions: dict[str, dict[str, Any]] = {
        f"S{i}": {"net_qty": 1, "avg_cost": 1.0, "realized_pnl": 0.0}
        for i in range(5000)
    }
    stop = threading.Event()
    row: dict[str, Any]
    if which == "status":
        target, row = orders, {"status": "NEW"}
    else:
        target, row = positions, {"net_qty": 0, "avg_cost": 0.0, "realized_pnl": 1.0}
    writer = threading.Thread(target=_hammer, args=(target, row, stop))
    writer.start()
    errors = 0
    try:
        with patch("edumatcher.alf_console.display.console.print"):
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                try:
                    if which == "status":
                        print_status("GW01", True, [], orders, {}, {})
                    else:
                        print_positions(positions, {})
                except RuntimeError:
                    errors += 1
    finally:
        stop.set()
        writer.join()
    assert errors == 0


# ---------------------------------------------------------------------------
# 5: valid lines still send what they sent before
# ---------------------------------------------------------------------------


def _sent(line: str) -> tuple[str, dict[str, Any]]:
    gw, push = _make_gateway("GW01")
    with patch("edumatcher.alf_console.main.console.print"):
        gw._parse_and_send(line)
    assert push.send_multipart.call_count == 1
    return decode(push.send_multipart.call_args.args[0])


def test_valid_new_is_sent_and_cached() -> None:
    gw, push = _make_gateway("GW01")
    with patch("edumatcher.alf_console.main.console.print"):
        gw._parse_and_send(_LIMIT + "|TAG=t1")
    topic, payload = decode(push.send_multipart.call_args.args[0])
    assert topic == "order.new"
    assert (payload["symbol"], payload["side"], payload["quantity"]) == (
        "AAPL",
        "BUY",
        100,
    )
    assert payload["price_ticks"] == 15000
    assert payload["client_tag"] == "t1"
    assert gw.order_cache[payload["id"]]["status"] == "PENDING"


def test_valid_trailing_stop_is_sent() -> None:
    topic, payload = _sent(
        "NEW|SYM=AAPL|SIDE=SELL|TYPE=TRAILING_STOP|QTY=100|TRAIL=0.50"
    )
    assert topic == "order.new"
    assert payload["trail_offset_ticks"] == 50


def test_valid_amend_is_sent() -> None:
    topic, payload = _sent("AMEND|ID=abc|PRICE=151.00|QTY=50|RTAG=r1")
    assert topic == "order.amend"
    assert (payload["order_id"], payload["price"], payload["qty"]) == (
        "abc",
        151.0,
        50,
    )
    assert payload["request_tag"] == "r1"


def test_valid_oco_is_sent() -> None:
    topic, payload = _sent(_OCO)
    assert topic == "order.oco"
    assert payload["leg1"]["price_ticks"] == 15500
    assert payload["leg2"]["stop_price_ticks"] == 14500


def test_valid_quote_is_sent() -> None:
    topic, payload = _sent("QUOTE|SYM=AAPL|BID=150.00|ASK=150.10|BID_QTY=5|ASK_QTY=7")
    assert topic == "quote.new"
    assert (payload["bid_price_ticks"], payload["ask_price_ticks"]) == (15000, 15010)
    assert (payload["bid_qty"], payload["ask_qty"]) == (5, 7)
