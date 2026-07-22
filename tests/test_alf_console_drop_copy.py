"""Tests for pm-alf-console's drop-copy relay: --drop-copy flag, DC|ON/OFF,
and DC_FILL rendering.

Gateway.__init__ calls make_subscriber() three times (order events, index
events, drop-copy events), so tests here return a distinct MagicMock per
call rather than reusing a single fake -- this matters specifically for
verifying which socket receives the SUBSCRIBE/UNSUBSCRIBE calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import zmq


def _make_gateway(gw_id: str = "GW01", drop_copy: bool = False):
    from edumatcher.alf_console.main import Gateway

    fake_push = MagicMock()
    fake_index_push = MagicMock()
    fake_sub = MagicMock(name="sub_sock")
    fake_index_sub = MagicMock(name="index_sub_sock")
    fake_dc_sub = MagicMock(name="dc_sub_sock")

    sub_calls = [fake_sub, fake_index_sub, fake_dc_sub]

    def _fake_make_subscriber(_addr, *_topics):
        return sub_calls.pop(0)

    push_calls = [fake_push, fake_index_push]

    def _fake_make_pusher(_addr):
        return push_calls.pop(0)

    with (
        patch("edumatcher.alf_console.main.make_pusher", side_effect=_fake_make_pusher),
        patch(
            "edumatcher.alf_console.main.make_subscriber",
            side_effect=_fake_make_subscriber,
        ),
    ):
        gw = Gateway(gw_id, drop_copy=drop_copy)
    return gw, fake_sub, fake_index_sub, fake_dc_sub


# ---------------------------------------------------------------------------
# --drop-copy CLI flag parsing
# ---------------------------------------------------------------------------


def test_build_parser_drop_copy_default_off() -> None:
    from edumatcher.alf_console.main import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["--id", "GW01"])
    assert args.drop_copy is False


def test_build_parser_drop_copy_flag() -> None:
    from edumatcher.alf_console.main import _build_parser

    parser = _build_parser()
    args = parser.parse_args(["--id", "GW01", "--drop-copy"])
    assert args.drop_copy is True


# ---------------------------------------------------------------------------
# Gateway construction and topic wiring
# ---------------------------------------------------------------------------


def test_dc_topic_is_gateway_scoped() -> None:
    gw, _sub, _index_sub, _dc_sub = _make_gateway("trader01")
    assert gw._dc_topic == b"drop_copy.event.TRADER01"


def test_dc_disabled_by_default_no_subscribe_call() -> None:
    gw, _sub, _index_sub, dc_sub = _make_gateway("GW01", drop_copy=False)
    assert gw._dc_enabled is False
    dc_sub.setsockopt.assert_not_called()


# ---------------------------------------------------------------------------
# DC|STATE=ON / DC|STATE=OFF command
# ---------------------------------------------------------------------------


def test_dc_command_on_subscribes_dc_socket_only() -> None:
    gw, sub, index_sub, dc_sub = _make_gateway("GW01")

    gw._parse_and_send("DC|STATE=ON")

    dc_sub.setsockopt.assert_called_once_with(zmq.SUBSCRIBE, b"drop_copy.event.GW01")
    sub.setsockopt.assert_not_called()
    index_sub.setsockopt.assert_not_called()
    assert gw._dc_enabled is True


def test_dc_command_off_unsubscribes() -> None:
    gw, _sub, _index_sub, dc_sub = _make_gateway("GW01")

    gw._parse_and_send("DC|STATE=ON")
    dc_sub.reset_mock()
    gw._parse_and_send("DC|STATE=OFF")

    dc_sub.setsockopt.assert_called_once_with(zmq.UNSUBSCRIBE, b"drop_copy.event.GW01")
    assert gw._dc_enabled is False


def test_dc_command_on_twice_is_idempotent() -> None:
    gw, _sub, _index_sub, dc_sub = _make_gateway("GW01")

    gw._parse_and_send("DC|STATE=ON")
    dc_sub.reset_mock()
    gw._parse_and_send("DC|STATE=ON")

    dc_sub.setsockopt.assert_not_called()  # no-op: already enabled


def test_dc_command_missing_state_prints_error() -> None:
    gw, _sub, _index_sub, dc_sub = _make_gateway("GW01")

    with patch("edumatcher.alf_console.main.console.print") as mock_print:
        gw._parse_and_send("DC")

    dc_sub.setsockopt.assert_not_called()
    assert any("STATE=ON or STATE=OFF" in str(c) for c in mock_print.call_args_list)


def test_dc_command_invalid_state_prints_error() -> None:
    gw, _sub, _index_sub, dc_sub = _make_gateway("GW01")

    with patch("edumatcher.alf_console.main.console.print") as mock_print:
        gw._parse_and_send("DC|STATE=MAYBE")

    dc_sub.setsockopt.assert_not_called()
    assert any("STATE=ON or STATE=OFF" in str(c) for c in mock_print.call_args_list)


# ---------------------------------------------------------------------------
# --drop-copy startup flag wired into run()
# ---------------------------------------------------------------------------


def test_set_drop_copy_helper_direct() -> None:
    gw, _sub, _index_sub, dc_sub = _make_gateway("GW01")

    gw._set_drop_copy(True)
    dc_sub.setsockopt.assert_called_once_with(zmq.SUBSCRIBE, b"drop_copy.event.GW01")

    dc_sub.reset_mock()
    gw._set_drop_copy(True)  # idempotent
    dc_sub.setsockopt.assert_not_called()

    gw._set_drop_copy(False)
    dc_sub.setsockopt.assert_called_once_with(zmq.UNSUBSCRIBE, b"drop_copy.event.GW01")


def test_drop_copy_requested_on_startup_flag_stored() -> None:
    gw, _sub, _index_sub, _dc_sub = _make_gateway("GW01", drop_copy=True)
    assert gw._dc_requested_on_startup is True
    # Not applied until run() calls _set_drop_copy -- confirm it's not
    # already flipped as a side effect of construction alone.
    assert gw._dc_enabled is False


# ---------------------------------------------------------------------------
# DC_FILL rendering
# ---------------------------------------------------------------------------


def test_handle_dc_event_prints_dc_fill_line() -> None:
    gw, _sub, _index_sub, _dc_sub = _make_gateway("GW01")

    with patch("edumatcher.alf_console.main.console.print") as mock_print:
        gw._handle_dc_event(
            "drop_copy.event.GW01",
            {
                "seq": 42,
                "gateway_id": "GW01",
                "event_type": "order.fill",
                "order_id": "ord-001",
                "symbol": "AAPL",
                "fill_qty": 100,
                "fill_price": 150.05,
                "liquidity_flag": "TAKER",
            },
        )

    assert mock_print.call_count == 1
    rendered = str(mock_print.call_args[0][0])
    assert "DC_FILL" in rendered
    assert "AAPL" in rendered
    assert "100" in rendered
    assert "150.05" in rendered
    assert "TAKER" in rendered
    assert "#42" in rendered
