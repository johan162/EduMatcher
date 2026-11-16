"""pm-alf-console sends prices at each symbol's tick size (review H3,
WP-ACN06).

The console converted every typed price at the two-decimal default, because
nothing registered the tick sizes the engine lists in ``system.symbols``; on a
3-decimal symbol ``PRICE=10.12`` went out as 1012 ticks, which the engine
reads as 1.012. The console now asks for the symbol list at logon, registers
each tick size, and opens the prompt only once it has them.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest

from edumatcher.models import price as price_module
from edumatcher.models.message import decode, make_symbols_msg
from tests.test_alf_console_input import (
    _pushed_topics,
    _run_scripted,
    _ScriptedSession,
)
from tests.test_alf_console_quote_ack import _make_gateway

_SYM = "TRI3"


@pytest.fixture
def three_decimal_symbol() -> Iterator[str]:
    """The tick registry is process-wide: take the test symbol out again."""
    yield _SYM
    for cache in (
        price_module._tick_decimals_by_symbol,
        price_module._from_scale_cache,
        price_module._to_scale_cache,
    ):
        cache.pop(_SYM, None)


def _symbols_reply(gateway_id: str) -> tuple[str, dict[str, Any]]:
    return decode(
        make_symbols_msg(
            gateway_id,
            [
                {"symbol": _SYM, "tick_decimals": 3},
                {"symbol": "AAPL", "tick_decimals": 2},
            ],
        )
    )


def _sent(gw: Any, push: Any, line: str) -> dict[str, Any]:
    push.reset_mock()
    with patch("edumatcher.alf_console.main.console.print") as mock_print:
        gw._parse_and_send(line)
    assert push.send_multipart.call_count == 1, mock_print.call_args_list
    return decode(push.send_multipart.call_args.args[0])[1]


def test_logon_requests_the_symbol_list() -> None:
    gw, push = _make_gateway("GW01")
    with patch("edumatcher.alf_console.main.console.print"):
        _run_scripted(gw, ["EXIT"])
    assert "system.symbols_request" in _pushed_topics(push)


def test_reply_registers_tick_sizes_without_printing(
    three_decimal_symbol: str,
) -> None:
    gw, _push = _make_gateway("GW01")
    with patch("edumatcher.alf_console.main.print_symbols_table") as mock_table:
        gw._handle_event(*_symbols_reply("GW01"))
    mock_table.assert_not_called()
    assert price_module.get_tick_decimals(three_decimal_symbol) == 3
    assert gw._symbols_received.is_set()


def test_typed_symbols_still_prints_the_table(three_decimal_symbol: str) -> None:
    gw, _push = _make_gateway("GW01")
    gw._parse_and_send("SYMBOLS")
    with patch("edumatcher.alf_console.main.print_symbols_table") as mock_table:
        gw._handle_event(*_symbols_reply("GW01"))
        gw._handle_event(*_symbols_reply("GW01"))
    mock_table.assert_called_once()


def test_new_is_sent_at_the_symbols_tick_size(three_decimal_symbol: str) -> None:
    gw, push = _make_gateway("GW01")
    gw._handle_event(*_symbols_reply("GW01"))

    sym = three_decimal_symbol
    payload = _sent(gw, push, f"NEW|SYM={sym}|SIDE=SELL|TYPE=LIMIT|QTY=1|PRICE=10.12")
    assert payload["price_ticks"] == 10120
    assert payload["tick_decimals"] == 3
    payload = _sent(gw, push, f"NEW|SYM={sym}|SIDE=SELL|TYPE=LIMIT|QTY=1|PRICE=10.125")
    assert payload["price_ticks"] == 10125


def test_quote_oco_and_combo_are_sent_at_the_symbols_tick_size(
    three_decimal_symbol: str,
) -> None:
    gw, push = _make_gateway("GW01")
    gw._handle_event(*_symbols_reply("GW01"))
    sym = three_decimal_symbol

    quote = _sent(gw, push, f"QUOTE|SYM={sym}|BID=10.125|ASK=10.13|BID_QTY=1|ASK_QTY=1")
    assert (quote["bid_price_ticks"], quote["ask_price_ticks"]) == (10125, 10130)

    oco = _sent(
        gw,
        push,
        f"NEW|TYPE=OCO|OCO_ID=p|SYM={sym}|QTY=1|LEG1_SIDE=SELL|LEG1_TYPE=LIMIT|"
        "LEG1_PRICE=10.125|LEG2_SIDE=SELL|LEG2_TYPE=STOP|LEG2_STOP=9.875",
    )
    assert oco["leg1"]["price_ticks"] == 10125
    assert oco["leg2"]["stop_price_ticks"] == 9875

    combo = _sent(
        gw,
        push,
        f"NEW|TYPE=COMBO|COMBO_ID=c|LEG_COUNT=2|LEG0.SYM={sym}|LEG0.SIDE=BUY|"
        "LEG0.QTY=1|LEG0.PRICE=10.125|LEG1.SYM=AAPL|LEG1.SIDE=SELL|LEG1.QTY=1|"
        "LEG1.PRICE=150.00",
    )
    legs = {leg["symbol"]: leg for leg in combo["legs"]}
    assert (legs[sym]["price_ticks"], legs[sym]["tick_decimals"]) == (10125, 3)
    assert (legs["AAPL"]["price_ticks"], legs["AAPL"]["tick_decimals"]) == (
        15000,
        2,
    )


def test_no_symbol_list_means_no_prompt_and_exit_1() -> None:
    gw, push = _make_gateway("GW01")
    gw._symbols_timeout_sec = 0.1
    session = _ScriptedSession(["NEW|SYM=AAPL|SIDE=BUY|TYPE=MARKET|QTY=1"])
    with (
        patch("edumatcher.alf_console.main.console.print") as mock_print,
        patch.object(gw, "_authenticate", return_value=True),
        patch.object(gw, "_listen"),
        patch.object(gw, "_heartbeat_loop"),
        patch("edumatcher.alf_console.main.PromptSession", return_value=session),
        patch("edumatcher.alf_console.main.pt_patch_stdout"),
    ):
        status = gw.run()

    assert status == 1
    assert session.prompted == 0
    printed = " ".join(str(c.args) for c in mock_print.call_args_list)
    assert "symbol list" in printed
    assert _pushed_topics(push)[-1] == "system.gateway_disconnect"
