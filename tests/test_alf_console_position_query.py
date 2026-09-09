"""Tests for pm-alf-console's POS|GW=<gateway_id> command: querying
another gateway's (typically a running pm-mm-bot's) position via the
existing system.position_request / system.position_snapshot.{GW_ID} pair.

Mirrors test_alf_console_drop_copy.py's fixture and mocking approach --
Gateway.__init__ calls make_subscriber() three times (order events, index
events, drop-copy events), so a distinct MagicMock per call is needed to
tell which socket a SUBSCRIBE/UNSUBSCRIBE call landed on.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import zmq


def _make_gateway(gw_id: str = "GW01"):
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
        gw = Gateway(gw_id)
    return gw, fake_push, fake_sub, fake_index_sub, fake_dc_sub


# ---------------------------------------------------------------------------
# POS (no GW=) keeps today's local-ledger behavior
# ---------------------------------------------------------------------------


def test_pos_without_gw_does_not_send_or_subscribe() -> None:
    gw, push, sub, _index_sub, _dc_sub = _make_gateway("GW01")

    with patch("edumatcher.alf_console.main.print_positions") as mock_print:
        gw._parse_and_send("POS")

    mock_print.assert_called_once()
    push.setsockopt.assert_not_called()
    sub.setsockopt.assert_not_called()


# ---------------------------------------------------------------------------
# POS|GW=<gateway_id> — issuing the query
# ---------------------------------------------------------------------------


def test_pos_gw_sends_position_request_and_subscribes() -> None:
    gw, push, sub, _index_sub, _dc_sub = _make_gateway("GW01")

    gw._parse_and_send("POS|GW=MM_AAPL_01")

    sub.setsockopt.assert_called_once_with(
        zmq.SUBSCRIBE, b"system.position_snapshot.MM_AAPL_01"
    )
    assert push.send_multipart.call_count == 1
    frames = push.send_multipart.call_args[0][0]
    assert frames[0] == b"system.position_request"
    assert gw._pos_query_gateway_id == "MM_AAPL_01"
    assert gw._pos_query_topic == b"system.position_snapshot.MM_AAPL_01"


def test_pos_gw_lowercase_is_normalized_via_kv_uppercasing() -> None:
    """Gateway._kv() uppercases values, matching how gateway ids are
    normalized everywhere else in this file (Gateway.gateway_id itself is
    upper-cased in __init__)."""
    gw, _push, sub, _index_sub, _dc_sub = _make_gateway("GW01")

    gw._parse_and_send("POS|GW=mm_aapl_01")

    sub.setsockopt.assert_called_once_with(
        zmq.SUBSCRIBE, b"system.position_snapshot.MM_AAPL_01"
    )


def test_second_pos_gw_query_unsubscribes_the_first() -> None:
    gw, _push, sub, _index_sub, _dc_sub = _make_gateway("GW01")

    gw._parse_and_send("POS|GW=MM_AAPL_01")
    sub.reset_mock()
    gw._parse_and_send("POS|GW=MM_MSFT_01")

    sub.setsockopt.assert_any_call(
        zmq.UNSUBSCRIBE, b"system.position_snapshot.MM_AAPL_01"
    )
    sub.setsockopt.assert_any_call(
        zmq.SUBSCRIBE, b"system.position_snapshot.MM_MSFT_01"
    )
    assert gw._pos_query_gateway_id == "MM_MSFT_01"


# ---------------------------------------------------------------------------
# Receiving the system.position_snapshot.<gw> reply
# ---------------------------------------------------------------------------


def test_matching_reply_prints_and_unsubscribes() -> None:
    gw, _push, sub, _index_sub, _dc_sub = _make_gateway("GW01")
    gw._parse_and_send("POS|GW=MM_AAPL_01")
    sub.reset_mock()

    with patch("edumatcher.alf_console.main.print_remote_position") as mock_print:
        gw._handle_position_snapshot_reply(
            "system.position_snapshot.MM_AAPL_01",
            {"positions": [{"symbol": "AAPL", "net_qty": 300, "avg_cost": 150.25}]},
        )

    mock_print.assert_called_once_with(
        "MM_AAPL_01", [{"symbol": "AAPL", "net_qty": 300, "avg_cost": 150.25}]
    )
    sub.setsockopt.assert_called_once_with(
        zmq.UNSUBSCRIBE, b"system.position_snapshot.MM_AAPL_01"
    )
    assert gw._pos_query_gateway_id is None
    assert gw._pos_query_topic is None


def test_reply_for_a_different_gateway_is_ignored() -> None:
    """A stray reply that doesn't match the outstanding query (e.g. a
    race after a previous query never got a clean unsubscribe) must not
    clobber state or print anything."""
    gw, _push, sub, _index_sub, _dc_sub = _make_gateway("GW01")
    gw._parse_and_send("POS|GW=MM_AAPL_01")
    sub.reset_mock()

    with patch("edumatcher.alf_console.main.print_remote_position") as mock_print:
        gw._handle_position_snapshot_reply(
            "system.position_snapshot.MM_MSFT_01",
            {"positions": [{"symbol": "MSFT", "net_qty": 100, "avg_cost": 200.0}]},
        )

    mock_print.assert_not_called()
    sub.setsockopt.assert_not_called()
    # Still outstanding -- the real MM_AAPL_01 reply can still arrive.
    assert gw._pos_query_gateway_id == "MM_AAPL_01"


def test_reply_with_no_outstanding_query_is_ignored() -> None:
    gw, _push, sub, _index_sub, _dc_sub = _make_gateway("GW01")

    with patch("edumatcher.alf_console.main.print_remote_position") as mock_print:
        gw._handle_position_snapshot_reply(
            "system.position_snapshot.MM_AAPL_01",
            {"positions": []},
        )

    mock_print.assert_not_called()
    sub.setsockopt.assert_not_called()


def test_flat_reply_renders_empty_positions_list() -> None:
    gw, _push, sub, _index_sub, _dc_sub = _make_gateway("GW01")
    gw._parse_and_send("POS|GW=MM_AAPL_01")

    with patch("edumatcher.alf_console.main.print_remote_position") as mock_print:
        gw._handle_position_snapshot_reply(
            "system.position_snapshot.MM_AAPL_01", {"positions": []}
        )

    mock_print.assert_called_once_with("MM_AAPL_01", [])
