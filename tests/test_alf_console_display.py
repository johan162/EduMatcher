"""Stop triggers, dates, DC state and prices are shown as they are
(review WP-ACN06: C6, C7, C8, C9)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from rich.text import Text

from edumatcher.alf_console.display import (
    console,
    print_positions,
    print_quote_bootstrap,
    print_quote_legs,
    print_remote_position,
)
from edumatcher.models import price as price_module
from edumatcher.models.generated.order import make_order_triggered
from edumatcher.models.message import decode
from tests.alf_console_harness import console_harness  # noqa: F401
from tests.test_alf_console_quote_ack import _make_gateway


def _printed(mock_print: MagicMock) -> list[str]:
    return [" ".join(str(a) for a in c.args) for c in mock_print.call_args_list]


def _plain(render: Any) -> str:
    """The rendered text, wide enough that no table column wraps."""
    width = console.width
    console.width = 200
    try:
        with console.capture() as capture:
            render()
    finally:
        console.width = width
    return Text.from_ansi(capture.get()).plain


# ---------------------------------------------------------------------------
# 1 (C6): order.triggered
# ---------------------------------------------------------------------------


def _triggered(gateway_id: str, order_type: str, becomes: str) -> list[bytes]:
    return make_order_triggered(
        gateway_id=gateway_id,
        order_id="stop-1",
        symbol="AAPL",
        order_type=order_type,
        tick_decimals=2,
        stop_price_ticks=14800,
        trigger_trade_id="t9",
        trigger_price_ticks=14795,
        becomes=becomes,
    )


@pytest.mark.parametrize(
    ("order_type", "becomes"),
    [("STOP_LIMIT", "LIMIT"), ("STOP", "MARKET"), ("TRAILING_STOP", "MARKET")],
)
def test_triggered_stop_is_printed_and_its_type_updated(
    order_type: str, becomes: str
) -> None:
    gw, _push = _make_gateway("GW01")
    gw.order_cache["stop-1"] = {"id": "stop-1", "type": order_type, "status": "NEW"}

    with patch("edumatcher.alf_console.main.console.print") as mock_print:
        gw._handle_event(*decode(_triggered("GW01", order_type, becomes)))

    lines = _printed(mock_print)
    assert len(lines) == 1
    assert "TRIGGERED" in lines[0]
    assert "stop-1" in lines[0]
    assert "148.00" in lines[0]
    assert becomes in lines[0]
    assert gw.order_cache["stop-1"]["type"] == becomes


def test_triggered_is_subscribed_and_reaches_the_screen(
    console_harness: Any,  # noqa: F811
) -> None:
    h = console_harness("GW01")
    h.pub.send_multipart(_triggered("GW01", "STOP", "MARKET"))
    h.sync()
    assert [line for line in h.lines if "TRIGGERED" in line]


def test_another_gateways_trigger_is_ignored() -> None:
    gw, _push = _make_gateway("GW1")
    with patch("edumatcher.alf_console.main.console.print") as mock_print:
        gw._handle_event(*decode(_triggered("GW10", "STOP", "MARKET")))
    mock_print.assert_not_called()


# ---------------------------------------------------------------------------
# 2 (C7): INDEX|HISTORY dates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "word"),
    [
        ("INDEX|HISTORY|INDEX=IDX|FROM=2026-13-01", "FROM"),
        ("INDEX|HISTORY|INDEX=IDX|TO=yesterday", "TO"),
        ("INDEX|HISTORY|INDEX=IDX|FROM=2026-11-10|TO=2026-11-01", "after"),
    ],
)
def test_bad_index_history_dates_are_refused(line: str, word: str) -> None:
    gw, _push = _make_gateway("GW01")
    with patch("edumatcher.alf_console.main.console.print") as mock_print:
        gw._parse_and_send(line)
    lines = _printed(mock_print)
    assert len(lines) == 1 and "[red]" in lines[0] and word in lines[0], lines
    gw._index_push_sock.send_multipart.assert_not_called()


def test_good_index_history_range_is_sent() -> None:
    gw, _push = _make_gateway("GW01")
    gw._parse_and_send("INDEX|HISTORY|INDEX=IDX|FROM=2026-11-01|TO=2026-11-01")
    topic, payload = decode(gw._index_push_sock.send_multipart.call_args.args[0])
    assert topic == "index.history_request"
    assert payload["from_ts_ns"] < payload["to_ts_ns"]


# ---------------------------------------------------------------------------
# 3 (C8): DC feedback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", ["ON", "OFF"])
def test_dc_prints_the_new_state(state: str) -> None:
    gw, _push = _make_gateway("GW01")
    with patch("edumatcher.alf_console.main.console.print") as mock_print:
        gw._parse_and_send(f"DC|STATE={state}")
    assert any(f"DC {state}" in line for line in _printed(mock_print))


# ---------------------------------------------------------------------------
# 5 (C9): prices at the symbol's tick size
# ---------------------------------------------------------------------------


@pytest.fixture
def three_decimal_symbol() -> Iterator[str]:
    price_module.register_tick_decimals("TRI3", 3)
    yield "TRI3"
    for cache in (
        price_module._tick_decimals_by_symbol,
        price_module._from_scale_cache,
        price_module._to_scale_cache,
    ):
        cache.pop("TRI3", None)


def test_positions_show_the_symbols_decimals(three_decimal_symbol: str) -> None:
    sym = three_decimal_symbol
    positions = {
        sym: {"net_qty": 3, "avg_cost": 10.1255, "realized_pnl": 0.0},
        "AAPL": {"net_qty": 1, "avg_cost": 150.0, "realized_pnl": 0.0},
    }
    table = _plain(lambda: print_positions(positions, {sym: 10.125, "AAPL": 150.5}))
    assert "10.1255" in table  # average: one digit more than the tick
    assert "10.125 " in table or "10.125│" in table  # last price at the tick
    assert "150.000" in table
    assert "150.50" in table and "150.500" not in table


def test_remote_position_shows_the_symbols_decimals(
    three_decimal_symbol: str,
) -> None:
    table = _plain(
        lambda: print_remote_position(
            "MM", [{"symbol": three_decimal_symbol, "net_qty": 1, "avg_cost": 10.1255}]
        )
    )
    assert "10.1255" in table


def test_quote_legs_and_bootstrap_show_the_symbols_decimals(
    three_decimal_symbol: str,
) -> None:
    sym = three_decimal_symbol
    legs = {
        "o1": {
            "order_id": "o1",
            "quote_id": "q",
            "symbol": sym,
            "leg_side": "BUY",
            "price": 10.125,
            "qty": 1,
            "remaining": 1,
            "filled": 0,
            "status": "NEW",
        },
        "o2": {
            "order_id": "o2",
            "quote_id": "q",
            "symbol": "AAPL",
            "leg_side": "SELL",
            "price": 150.5,
            "qty": 1,
            "remaining": 1,
            "filled": 0,
            "status": "NEW",
        },
    }
    table = _plain(lambda: print_quote_legs("GW01", legs, None, "ALL"))
    assert "10.125" in table
    assert "150.50" in table and "150.500" not in table

    boot = _plain(
        lambda: print_quote_bootstrap(
            "GW01",
            [{"symbol": sym, "quote_id": "q", "bid_price": 10.125, "ask_price": 10.13}],
        )
    )
    assert "10.125" in boot and "10.130" in boot


def test_fill_and_amend_lines_show_the_symbols_decimals(
    three_decimal_symbol: str,
) -> None:
    gw, _push = _make_gateway("GW01")
    with patch("edumatcher.alf_console.main.console.print") as mock_print:
        gw._handle_event(
            "order.fill.GW01",
            {
                "order_id": "o1",
                "fill_qty": 1,
                "fill_price": 10.1,
                "remaining_qty": 0,
                "status": "FILLED",
                "symbol": three_decimal_symbol,
                "side": "BUY",
            },
        )
        gw._handle_event(
            "order.amended.GW01",
            {
                "order_id": "o2",
                "symbol": "AAPL",
                "price": 149.8,
                "qty": 5,
                "remaining_qty": 5,
            },
        )
    fill, amend = _printed(mock_print)
    assert "@10.100" in fill
    assert "price=149.80" in amend
