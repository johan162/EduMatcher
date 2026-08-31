"""Phase 5.1a: the five engine→gateway order events.

These messages are why ``nullable`` and ``omit_when_none`` exist (design
section B.7.2). They carry three kinds of field — always present, present but
null, and absent entirely — and the hand-written builders expressed the third
by simply not adding the key.

Every case below is byte-identical to the builder it replaced, with **one
deliberate exception**, tested explicitly: a MARKET order's ack and fill no
longer carry ``"price": null``. See ``TestTheOneDeliberateWireChange``.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models import message as M
from edumatcher.models.generated import order as G
from edumatcher.models.generated._runtime import MessageValidationError

_LIMIT: dict[str, Any] = {
    "symbol": "AAPL",
    "side": "SELL",
    "order_type": "LIMIT",
    "tif": "GTC",
    "quantity": 5,
    "price": 1.5,
    "client_tag": "t1",
    "oco_group_id": "G1",
    "leg_index": 2,
}
_MARKET: dict[str, Any] = {
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "MARKET",
    "tif": "DAY",
    "quantity": 10,
    "price": None,
}


class TestByteIdenticalToTheHandWrittenBuilders:
    """The acceptance bar every family adoption has met."""

    def test_ack_without_order_detail(self) -> None:
        assert M.make_ack_msg("GW1", "O1", True, "") == G.make_order_ack_unchecked(
            gateway_id="GW1", order_id="O1", accepted=True, reason=""
        )

    def test_ack_rejected_carries_the_reason(self) -> None:
        assert M.make_ack_msg("GW1", "O1", False, "bad symbol") == (
            G.make_order_ack_unchecked(
                gateway_id="GW1", order_id="O1", accepted=False, reason="bad symbol"
            )
        )

    def test_ack_rejected_carries_the_reject_code(self) -> None:
        assert M.make_ack_msg(
            "GW1",
            "O1",
            False,
            "bad symbol",
            reject_code="UNKNOWN_SYMBOL",
        ) == G.make_order_ack_unchecked(
            gateway_id="GW1",
            order_id="O1",
            accepted=False,
            reason="bad symbol",
            reject_code="UNKNOWN_SYMBOL",
        )

    def test_ack_with_a_limit_order_tag_and_group(self) -> None:
        assert M.make_ack_msg("GW1", "O1", True, "", order=_LIMIT) == (
            G.make_order_ack_unchecked(
                gateway_id="GW1",
                order_id="O1",
                accepted=True,
                reason="",
                symbol="AAPL",
                side="SELL",
                order_type="LIMIT",
                tif="GTC",
                qty=5,
                price=1.5,
                client_tag="t1",
                oco_group_id="G1",
                leg_index=2,
            )
        )

    def test_fill(self) -> None:
        assert M.make_fill_msg("GW1", "O1", 5, 1.25, 3, "PARTIAL") == (
            G.make_order_fill_unchecked(
                gateway_id="GW1",
                order_id="O1",
                fill_qty=5,
                fill_price=1.25,
                remaining_qty=3,
                status="PARTIAL",
            )
        )

    def test_cancelled_bare(self) -> None:
        assert M.make_cancelled_msg("GW1", "O1") == G.make_order_cancelled_unchecked(
            gateway_id="GW1", order_id="O1"
        )

    def test_cancelled_with_tag_and_group(self) -> None:
        assert M.make_cancelled_msg("GW1", "O1", "t1", order=_LIMIT) == (
            G.make_order_cancelled_unchecked(
                gateway_id="GW1",
                order_id="O1",
                client_tag="t1",
                oco_group_id="G1",
                leg_index=2,
            )
        )

    def test_expired(self) -> None:
        assert M.make_expired_msg("GW1", "O1", "t9") == G.make_order_expired_unchecked(
            gateway_id="GW1", order_id="O1", client_tag="t9"
        )

    @pytest.mark.parametrize("price", [None, 9.5])
    def test_amended(self, price: float | None) -> None:
        assert M.make_amended_msg("GW1", "O1", price, 10, 4, True) == (
            G.make_order_amended_unchecked(
                gateway_id="GW1",
                order_id="O1",
                price=price,
                qty=10,
                remaining_qty=4,
                priority_reset=True,
            )
        )


class TestPresenceSemantics:
    """The three regimes B.7.2 introduced, on the wire."""

    def test_absent_fields_are_absent_not_null(self) -> None:
        _topic, payload = M.decode(M.make_cancelled_msg("GW1", "O1"))
        assert payload == {"order_id": "O1"}
        assert "client_tag" not in payload
        assert "oco_group_id" not in payload

    def test_a_set_group_id_appears(self) -> None:
        _topic, payload = M.decode(
            M.make_cancelled_msg("GW1", "O1", order={"oco_group_id": "G1"})
        )
        assert payload["oco_group_id"] == "G1"
        assert "combo_parent_id" not in payload

    def test_amended_price_is_null_not_absent(self) -> None:
        """``order.amended`` is the one message that emits null deliberately."""
        _topic, payload = M.decode(M.make_amended_msg("GW1", "O1", None, 10, 4, False))
        assert "price" in payload
        assert payload["price"] is None

    def test_the_gateway_id_rides_in_the_topic_only(self) -> None:
        topic, payload = M.decode(M.make_ack_msg("GW1", "O1", True, ""))
        assert topic == "order.ack.GW1"
        assert "gateway_id" not in payload


class TestTheOneDeliberateWireChange:
    """A MARKET order's ack/fill no longer carries ``"price": null``.

    Accepted in Phase 5.1a. Every reader uses ``.get("price")``, so the value
    they see is unchanged; only the key's presence differs. Applying
    ``omit_when_none`` uniformly is what avoids adding a `block` construct to
    the IDL purely to reproduce bytes nothing reads.
    """

    @pytest.mark.parametrize("maker", ["ack", "fill"])
    def test_price_is_omitted_for_a_market_order(self, maker: str) -> None:
        if maker == "ack":
            frames = M.make_ack_msg("GW1", "O1", True, "", order=_MARKET)
        else:
            frames = M.make_fill_msg("GW1", "O1", 5, 1.0, 0, "FILLED", order=_MARKET)
        _topic, payload = M.decode(frames)
        assert "price" not in payload
        assert payload["symbol"] == "AAPL"
        assert payload.get("price") is None

    def test_a_limit_order_still_carries_its_price(self) -> None:
        """The change must not touch orders that have a price."""
        _topic, payload = M.decode(M.make_ack_msg("GW1", "O1", True, "", order=_LIMIT))
        assert payload["price"] == 1.5


class TestTopicHelpers:
    """First production use of the parameterised-topic helpers (section A.4)."""

    @pytest.mark.parametrize(
        "prefix, builder",
        [
            (G.PREFIX_ORDER_ACK, G.topic_order_ack),
            (G.PREFIX_ORDER_FILL, G.topic_order_fill),
            (G.PREFIX_ORDER_CANCELLED, G.topic_order_cancelled),
            (G.PREFIX_ORDER_EXPIRED, G.topic_order_expired),
            (G.PREFIX_ORDER_AMENDED, G.topic_order_amended),
        ],
    )
    def test_topic_starts_with_its_prefix(self, prefix: str, builder: Any) -> None:
        assert builder("GW1").startswith(prefix)

    def test_match_recovers_the_gateway(self) -> None:
        assert G.match_order_ack(G.topic_order_ack("GW1")) == "GW1"
        assert G.match_order_fill("order.ack.GW1") is None

    def test_match_does_not_swallow_a_trailing_segment(self) -> None:
        assert G.match_order_ack("order.ack.GW1.extra") is None


class TestRoundTrip:
    def test_parse_recovers_the_gateway_from_the_topic(self) -> None:
        """``gateway_id`` is not in the payload, so parse must read the topic."""
        frames = G.make_order_cancelled_unchecked(gateway_id="GW7", order_id="O1")
        assert G.parse_order_cancelled(frames).gateway_id == "GW7"

    def test_parse_round_trips_a_full_ack(self) -> None:
        frames = M.make_ack_msg(
            "GW1", "O1", False, "bad symbol", reject_code="UNKNOWN_SYMBOL", order=_LIMIT
        )
        ack = G.parse_order_ack(frames)
        assert ack.order_id == "O1"
        assert ack.reject_code == "UNKNOWN_SYMBOL"
        assert ack.symbol == "AAPL"
        assert ack.oco_group_id == "G1"
        assert ack.combo_parent_id is None

    def test_validation_applies_only_to_fields_that_are_set(self) -> None:
        """A None optional must not trip its own max_len rule."""
        G.OrderCancelled.from_dict({"order_id": "O1"}).validate()

    def test_but_a_set_field_is_still_checked(self) -> None:
        bad = G.OrderCancelled.from_dict({"order_id": "O1", "client_tag": "x" * 65})
        with pytest.raises(MessageValidationError, match="client_tag"):
            bad.validate()

    def test_reject_code_is_validated_when_set(self) -> None:
        bad = G.OrderAck.from_dict(
            {"order_id": "O1", "accepted": False, "reject_code": "NOT_A_CODE"}
        )
        with pytest.raises(MessageValidationError, match="reject_code"):
            bad.validate()

    def test_reject_code_is_omitted_when_absent(self) -> None:
        _topic, payload = M.decode(M.make_ack_msg("GW1", "O1", True, ""))
        assert "reject_code" not in payload


class TestRejectCodeReExport:
    def test_reject_codes_are_reexported_from_models(self) -> None:
        from edumatcher.models.reject import REJECT_CODES

        assert "UNKNOWN_SYMBOL" in REJECT_CODES
        assert "UNKNOWN" in REJECT_CODES
