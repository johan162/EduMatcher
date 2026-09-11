"""Regression test for a case-sensitivity bug Johan found verifying Phase 0
by hand: pm-alf-console rested a LIMIT BUY on AAPL, then rejected every
attempt to cancel it -- both the short id from the order ack and the full
id from `pm-audit-cli` -- with ORDER_NOT_FOUND.

Root cause: order ids are minted by the engine as lowercase hex
(models/ids.py's new_order_id() -- os.urandom(...).hex()) and are never
case-normalized anywhere they're looked up (OrderBook._order_index is a
plain dict keyed by the exact id string). But Gateway._kv(), the console's
KEY=value parser, unconditionally upper-cased every value -- correct for
enum tokens (SIDE, TYPE, TIF, ...) and the symbol/gateway-id convention,
wrong for an opaque id copied verbatim from an order.ack or an audit log
entry. CANCEL|ID=bf870a5f... was silently rewritten to ID=BF870A5F... before
it ever reached the wire, which can never match the lowercase id resting in
the book.

Mirrors test_alf_console_position_query.py's Gateway/mock-socket fixture.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from edumatcher.models.message import decode


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
    return gw, fake_push


def _last_sent_payload(push: MagicMock) -> dict:
    frames = push.send_multipart.call_args[0][0]
    _topic, payload = decode(frames)
    return payload


class TestCancelPreservesOrderIdCase:
    def test_cancel_id_is_sent_verbatim_lowercase(self) -> None:
        """The bug as Johan hit it: a lowercase engine-minted order id typed
        into CANCEL|ID= must reach the wire unchanged, not upper-cased."""
        gw, push = _make_gateway()
        order_id = "bf870a5f7fba3a136ffb0a6a24248185"

        gw._parse_and_send(f"CANCEL|ID={order_id}")

        push.send_multipart.assert_called_once()
        payload = _last_sent_payload(push)
        assert payload["order_id"] == order_id

    def test_cancel_id_with_mixed_case_is_preserved(self) -> None:
        gw, push = _make_gateway()
        order_id = "Bf870A5f7FBA3a136ffB0a6A24248185"

        gw._parse_and_send(f"CANCEL|ID={order_id}")

        payload = _last_sent_payload(push)
        assert payload["order_id"] == order_id

    def test_cancel_request_tag_case_is_preserved(self) -> None:
        gw, push = _make_gateway()

        gw._parse_and_send("CANCEL|ID=abc123|RTAG=req-MixedCase-4")

        payload = _last_sent_payload(push)
        assert payload["request_tag"] == "req-MixedCase-4"


class TestEnumAndSymbolKeysStillCanonicalizeUppercase:
    """The fix must not regress the existing, intentional behavior for
    keys where uppercase genuinely is the canonical wire form. Exercised
    directly against the classmethod (no Gateway/socket machinery, and no
    dependency on symbol/tick-decimals config a bare test fixture doesn't
    have) rather than through the full NEW/POS pipelines."""

    def test_enum_and_symbol_values_are_still_uppercased(self) -> None:
        from edumatcher.alf_console.main import Gateway

        kv = Gateway._kv(
            ["SYM=aapl", "SIDE=buy", "TYPE=limit", "TIF=day", "SMP=cancel_newest"]
        )
        assert kv["SYM"] == "AAPL"
        assert kv["SIDE"] == "BUY"
        assert kv["TYPE"] == "LIMIT"
        assert kv["TIF"] == "DAY"
        assert kv["SMP"] == "CANCEL_NEWEST"

    def test_gw_filter_value_is_still_uppercased(self) -> None:
        from edumatcher.alf_console.main import Gateway

        kv = Gateway._kv(["GW=mm_aapl_01"])
        assert kv["GW"] == "MM_AAPL_01"

    def test_opaque_identifier_values_are_left_exactly_as_typed(self) -> None:
        from edumatcher.alf_console.main import Gateway

        kv = Gateway._kv(
            [
                "ID=bf870a5f7fba3a136ffb0a6a24248185",
                "TAG=myTag-1",
                "RTAG=req-4",
                "COMBO_ID=Combo-A",
                "OCO_ID=Oco-B",
                "QUOTE_ID=Quote-C",
            ]
        )
        assert kv["ID"] == "bf870a5f7fba3a136ffb0a6a24248185"
        assert kv["TAG"] == "myTag-1"
        assert kv["RTAG"] == "req-4"
        assert kv["COMBO_ID"] == "Combo-A"
        assert kv["OCO_ID"] == "Oco-B"
        assert kv["QUOTE_ID"] == "Quote-C"
