"""A trader can only cancel/amend an order by its full id (see AR-0.3's
sibling fix, "stop upper-casing order ids ... in CANCEL etc." for the
case-sensitivity half of this bug). But every place pm-alf-console showed
an order id -- the ACK/FILL/CANCELLED/AMENDED/OCO/QUOTE event lines, the
ORDERS table, and the quote-legs table -- truncated it to 8 characters.
A trader working from what the console showed them had no way to get the
id CANCEL actually needs: Johan hit this verifying Phase 0 by hand.

Every id[:8] truncation site in alf_console/main.py and
alf_console/display.py now prints the full id. These tests pin that down
so it doesn't quietly regress.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

from edumatcher.alf_console.display import print_orders, print_quote_legs

FULL_ID = "bf870a5f7fba3a136ffb0a6a24248185"


def _make_gateway(gw_id: str = "GW01"):
    from edumatcher.alf_console.main import Gateway

    fake_push = MagicMock()
    fake_sub = MagicMock()
    with patch("edumatcher.alf_console.main.make_pusher", return_value=fake_push):
        with patch(
            "edumatcher.alf_console.main.make_subscriber", return_value=fake_sub
        ):
            gw = Gateway(gw_id)
    return gw


class TestEventLinesShowTheFullOrderId:
    def test_ack_line_shows_the_full_id(self) -> None:
        gw = _make_gateway()
        with patch("edumatcher.alf_console.main.console.print") as mock_print:
            gw._handle_event("order.ack.GW01", {"order_id": FULL_ID, "accepted": True})
        printed = str(mock_print.call_args.args[0])
        assert FULL_ID in printed

    def test_rejected_line_shows_the_full_id(self) -> None:
        gw = _make_gateway()
        with patch("edumatcher.alf_console.main.console.print") as mock_print:
            gw._handle_event(
                "order.ack.GW01",
                {"order_id": FULL_ID, "accepted": False, "reason": "no liquidity"},
            )
        printed = str(mock_print.call_args.args[0])
        assert FULL_ID in printed

    def test_fill_line_shows_the_full_id(self) -> None:
        gw = _make_gateway()
        with patch("edumatcher.alf_console.main.console.print") as mock_print:
            gw._handle_event(
                "order.fill.GW01",
                {
                    "order_id": FULL_ID,
                    "fill_qty": 50,
                    "fill_price": 100.0,
                    "remaining_qty": 50,
                    "status": "PARTIAL",
                    "symbol": "AAPL",
                    "side": "BUY",
                },
            )
        printed = str(mock_print.call_args.args[0])
        assert FULL_ID in printed

    def test_cancelled_line_shows_the_full_id(self) -> None:
        gw = _make_gateway()
        with patch("edumatcher.alf_console.main.console.print") as mock_print:
            gw._handle_event("order.cancelled.GW01", {"order_id": FULL_ID})
        printed = str(mock_print.call_args.args[0])
        assert FULL_ID in printed

    def test_amended_line_shows_the_full_id(self) -> None:
        gw = _make_gateway()
        with patch("edumatcher.alf_console.main.console.print") as mock_print:
            gw._handle_event(
                "order.amended.GW01",
                {
                    "order_id": FULL_ID,
                    "price": 105.0,
                    "qty": 100,
                    "remaining_qty": 100,
                },
            )
        printed = str(mock_print.call_args.args[0])
        assert FULL_ID in printed

    def test_oco_ack_line_shows_both_full_leg_ids(self) -> None:
        gw = _make_gateway()
        other_id = "c" * 32
        with patch("edumatcher.alf_console.main.console.print") as mock_print:
            gw._handle_event(
                "oco.ack.GW01",
                {
                    "oco_id": "OCO-1",
                    "accepted": True,
                    "order_id_1": FULL_ID,
                    "order_id_2": other_id,
                },
            )
        printed = str(mock_print.call_args.args[0])
        assert FULL_ID in printed
        assert other_id in printed

    def test_oco_cancelled_line_shows_the_full_sibling_id(self) -> None:
        gw = _make_gateway()
        with patch("edumatcher.alf_console.main.console.print") as mock_print:
            gw._handle_event(
                "oco.cancelled.GW01",
                {
                    "oco_id": "OCO-1",
                    "cancelled_order_id": FULL_ID,
                    "reason": "sibling filled",
                },
            )
        printed = str(mock_print.call_args.args[0])
        assert FULL_ID in printed

    def test_quote_ack_line_shows_both_full_leg_ids(self) -> None:
        gw = _make_gateway()
        ask_id = "d" * 32
        with patch("edumatcher.alf_console.main.console.print") as mock_print:
            gw._handle_event(
                "quote.ack.GW01",
                {
                    "quote_id": "Q1",
                    "accepted": True,
                    "bid_order_id": FULL_ID,
                    "ask_order_id": ask_id,
                },
            )
        printed = str(mock_print.call_args.args[0])
        assert FULL_ID in printed
        assert ask_id in printed

    def test_drop_copy_event_line_shows_the_full_id(self) -> None:
        gw = _make_gateway()
        with patch("edumatcher.alf_console.main.console.print") as mock_print:
            gw._handle_dc_event(
                "drop_copy.event.GW01",
                {
                    "order_id": FULL_ID,
                    "seq": 1,
                    "symbol": "AAPL",
                    "fill_qty": 10,
                    "fill_price": 100.0,
                    "liquidity_flag": "MAKER",
                },
            )
        printed = str(mock_print.call_args.args[0])
        assert FULL_ID in printed


class TestTablesShowTheFullOrderId:
    """print_orders/print_quote_legs render through rich's real Table, so
    exercise them directly with a captured Console rather than mocking
    console.print with a bare string (the arg here is a Table object)."""

    def test_orders_table_shows_the_full_id(self) -> None:
        from rich.console import Console

        import edumatcher.alf_console.display as display_module

        buf = io.StringIO()
        with patch.object(display_module, "console", Console(file=buf, width=200)):
            print_orders(
                "TRADER01",
                {
                    FULL_ID: {
                        "id": FULL_ID,
                        "symbol": "AAPL",
                        "side": "BUY",
                        "type": "LIMIT",
                        "tif": "DAY",
                        "qty": 170,
                        "remaining": 170,
                        "price": 46.00,
                        "status": "NEW",
                        "time": "14:32:58",
                    }
                },
            )
        assert FULL_ID in buf.getvalue()

    def test_quote_legs_table_shows_the_full_id(self) -> None:
        from rich.console import Console

        import edumatcher.alf_console.display as display_module

        buf = io.StringIO()
        with patch.object(display_module, "console", Console(file=buf, width=200)):
            print_quote_legs(
                "TRADER01",
                {
                    FULL_ID: {
                        "symbol": "AAPL",
                        "quote_id": "Q1",
                        "leg_side": "BID",
                        "order_id": FULL_ID,
                        "price": 46.00,
                        "qty": 100,
                        "remaining": 100,
                        "filled": 0,
                        "status": "ACTIVE",
                        "quote_status": "ACTIVE",
                        "last_event_time": "14:32:58",
                    }
                },
                None,
                "ALL",
            )
        assert FULL_ID in buf.getvalue()
