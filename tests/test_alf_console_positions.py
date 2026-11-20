"""``POS`` shows what the engine holds, also after a restart (WP-ACN04, C4).

The position table used to be built only from fills seen by this process, so
a restarted console printed "No positions." for a participant who was long.
The console now asks the engine for its own position at connect (and after a
lost-event gap) and seeds net quantity and average cost from the reply;
realised P&L stays session-local.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from rich.text import Text

from edumatcher.alf_console.display import console, print_positions
from edumatcher.models.message import decode, make_position_snapshot_msg
from tests.alf_console_harness import console_harness  # noqa: F401
from tests.test_alf_console_delivery import _own_fill, _skip_seq
from tests.test_alf_console_input import _pushed_topics, _run_scripted
from tests.test_alf_console_quote_ack import _make_gateway


def _snapshot(gateway_id: str, positions: list[dict[str, Any]]):
    return decode(make_position_snapshot_msg(gateway_id, positions))


def _rendered(positions: dict[str, dict[str, Any]], last: dict[str, float]) -> str:
    """The table text, wide enough that no column is cropped whatever the
    terminal running the tests."""
    width = console.width
    console.width = 200
    try:
        with console.capture() as capture:
            print_positions(positions, last)
    finally:
        console.width = width
    return Text.from_ansi(capture.get()).plain


def _rendered_positions(gw: Any) -> str:
    return _rendered(gw._positions, gw._last_prices)


# ---------------------------------------------------------------------------
# 1: the request at connect
# ---------------------------------------------------------------------------


def test_connect_requests_own_position_after_orders() -> None:
    gw, push = _make_gateway("TRADER01")
    with patch("edumatcher.alf_console.main.console.print"):
        _run_scripted(gw, ["EXIT"])

    topics = _pushed_topics(push)
    assert "system.position_request" in topics
    assert topics.index("order.orders_request") < topics.index(
        "system.position_request"
    )
    request = decode(
        push.send_multipart.call_args_list[
            topics.index("system.position_request")
        ].args[0]
    )[1]
    assert request["gateway_id"] == "TRADER01"


# ---------------------------------------------------------------------------
# 2 + 3: the reply seeds the table; later fills build on it
# ---------------------------------------------------------------------------


def test_own_snapshot_seeds_positions() -> None:
    gw, _push = _make_gateway("TRADER01")
    gw._handle_event(
        *_snapshot("TRADER01", [{"symbol": "AAPL", "net_qty": 100, "avg_cost": 150.0}])
    )

    assert gw._positions["AAPL"] == {
        "net_qty": 100,
        "avg_cost": 150.0,
        "realized_pnl": 0.0,
    }
    table = _rendered_positions(gw)
    assert "+100" in table
    assert "150.00" in table
    assert "+0.00" in table
    assert "since connect" in table


def test_fill_after_the_seed_builds_on_it() -> None:
    gw, _push = _make_gateway("TRADER01")
    gw._handle_event(
        *_snapshot("TRADER01", [{"symbol": "AAPL", "net_qty": 100, "avg_cost": 150.0}])
    )
    with patch("edumatcher.alf_console.main.console.print"):
        gw._handle_event(
            "order.fill.TRADER01",
            {
                "order_id": "o1",
                "fill_qty": 40,
                "fill_price": 151.0,
                "remaining_qty": 0,
                "status": "FILLED",
                "symbol": "AAPL",
                "side": "SELL",
            },
        )

    pos = gw._positions["AAPL"]
    assert pos["net_qty"] == 60
    assert pos["avg_cost"] == 150.0
    assert pos["realized_pnl"] == 40.0


def test_seed_keeps_session_pnl_and_flattens_symbols_the_engine_omits() -> None:
    """A re-sync after a gap: the engine's numbers replace quantity and cost;
    realised P&L earned in this session stays; a symbol the snapshot leaves
    out is flat."""
    gw, _push = _make_gateway("TRADER01")
    gw._positions["AAPL"] = {"net_qty": 10, "avg_cost": 1.0, "realized_pnl": 5.0}
    gw._positions["MSFT"] = {"net_qty": 3, "avg_cost": 2.0, "realized_pnl": 1.0}

    gw._handle_event(
        *_snapshot("TRADER01", [{"symbol": "AAPL", "net_qty": 30, "avg_cost": 1.5}])
    )

    assert gw._positions["AAPL"] == {
        "net_qty": 30,
        "avg_cost": 1.5,
        "realized_pnl": 5.0,
    }
    assert gw._positions["MSFT"] == {
        "net_qty": 0,
        "avg_cost": 0.0,
        "realized_pnl": 1.0,
    }


def test_another_gateways_snapshot_does_not_seed() -> None:
    gw, _push = _make_gateway("TRADER1")
    gw._handle_event(
        *_snapshot("TRADER10", [{"symbol": "AAPL", "net_qty": 7, "avg_cost": 1.0}])
    )
    assert gw._positions == {}


# ---------------------------------------------------------------------------
# 4: POS|GW=<own id> still prints the engine table, unchanged
# ---------------------------------------------------------------------------


def test_pos_gw_for_own_id_prints_the_engine_table() -> None:
    gw, _push = _make_gateway("TRADER01")
    gw._parse_and_send("POS|GW=TRADER01")
    with patch("edumatcher.alf_console.main.print_remote_position") as mock_print:
        gw._handle_event(
            *_snapshot("TRADER01", [{"symbol": "AAPL", "net_qty": 5, "avg_cost": 2.0}])
        )
    mock_print.assert_called_once()
    assert mock_print.call_args.args[0] == "TRADER01"


# ---------------------------------------------------------------------------
# A lost-event gap re-syncs the position too
# ---------------------------------------------------------------------------


def test_gap_requests_own_position(
    console_harness: Any,  # noqa: F811
) -> None:
    h = console_harness("TRADER01")
    h.pushed(timeout=0.2)

    h.pub.send_multipart(_own_fill("TRADER01", "o1"))
    _skip_seq(h, "order.fill.TRADER01", 1)
    h.pub.send_multipart(_own_fill("TRADER01", "o2"))
    h.sync()

    pushed = h.pushed()
    requests = [p for t, p in pushed if t == "system.position_request"]
    assert [p["gateway_id"] for p in requests] == ["TRADER01"]


# ---------------------------------------------------------------------------
# Quick Start review 2026-11: no negative zero
# ---------------------------------------------------------------------------


def test_a_short_position_at_its_cost_shows_plus_zero() -> None:
    """(150.00 - 150.00) * -100 is -0.0, which formatted as "-0.00"."""
    text = _rendered(
        {"AAPL": {"net_qty": -100, "avg_cost": 150.0, "realized_pnl": -0.0}},
        {"AAPL": 150.0},
    )
    assert "-0.00" not in text
    assert text.count("+0.00") == 2


def test_a_float_residue_below_a_cent_shows_plus_zero() -> None:
    text = _rendered(
        {
            "AAPL": {"net_qty": 3, "avg_cost": 0.1 + 0.2, "realized_pnl": -1e-12},
            "MSFT": {"net_qty": 0, "avg_cost": 0.0, "realized_pnl": -0.004},
        },
        {"AAPL": 0.3},
    )
    assert "-0.00" not in text
