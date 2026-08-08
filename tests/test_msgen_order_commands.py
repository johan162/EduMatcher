"""Phase 5.1b: the three inbound gateway -> engine commands.

``order.new``, ``order.cancel`` and ``order.amend`` are the messages that reach
the matching engine, so the acceptance bar is the same as every other family's:
the generated frames must be byte-identical to what the hand-written builders
produced, and ``Order.from_dict`` must read them unchanged.

Two things here are deliberately *unlike* Phase 5.1a, and both are asserted
rather than left to the spec comment:

* ``order.new`` uses ``nullable`` **without** ``omit_when_none`` - it emits
  nulls where 5.1a omitted. The spec follows the consumer, and the consumer
  (``Order.from_dict``) reads absent and null alike for exactly those fields.
* ``price`` on ``order.new`` is **ticks**; ``price`` on ``order.amend`` is
  **display money**. Same name, different unit, one wire.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models import message as M
from edumatcher.models.generated import order as G
from edumatcher.models.order import Order, OrderStatus, OrderType, Side, TIF

_ORDER = Order(
    id="O1",
    symbol="AAPL",
    side=Side.BUY,
    order_type=OrderType.LIMIT,
    tif=TIF.GTC,
    quantity=100,
    remaining_qty=100,
    gateway_id="GW1",
    timestamp=1_700_000_000_000_000_000,
    status=OrderStatus.NEW,
    price=15000,
)


class TestOrderNewIsByteIdentical:
    """The bar every family adoption has met."""

    def test_a_limit_order(self) -> None:
        payload = _ORDER.to_dict()
        assert M.make_order_new_msg(payload) == G.make_order_new_unchecked(**payload)

    def test_a_market_order_with_eleven_nulls(self) -> None:
        """The shape that made 5.1a's omit_when_none the wrong choice here."""
        market = Order.create(
            symbol="AAPL",
            side=Side.SELL,
            order_type=OrderType.MARKET,
            quantity=10,
            gateway_id="GW1",
        )
        payload = market.to_dict()
        assert M.make_order_new_msg(payload) == G.make_order_new_unchecked(**payload)

    def test_the_key_order_is_to_dicts_not_a_tidied_one(self) -> None:
        """Byte-identity depends on field order, including its oddities.

        ``trail_offset`` and ``oco_group_id`` sit at positions 9-10, before
        ``timestamp``, which looks like an accident of editing but is the wire.
        """
        _topic, payload = M.decode(G.make_order_new_unchecked(**_ORDER.to_dict()))
        assert list(payload) == list(_ORDER.to_dict())


class TestPresenceFollowsTheConsumer:
    """``nullable`` without ``omit_when_none``: unset fields are null, present."""

    @pytest.mark.parametrize(
        "field",
        [
            "trail_offset",
            "oco_group_id",
            "stop_price",
            "visible_qty",
            "displayed_qty",
            "smp_action",
            "combo_parent_id",
            "leg_index",
            "quote_id",
            "client_tag",
        ],
    )
    def test_an_unset_field_is_null_not_absent(self, field: str) -> None:
        _topic, payload = M.decode(G.make_order_new_unchecked(**_ORDER.to_dict()))
        assert field in payload, "5.1a omits; 5.1b must not"
        assert payload[field] is None

    def test_the_two_defaulted_fields_carry_their_defaults(self) -> None:
        """``origin`` and ``arrival_seq`` are ``default:``, not ``nullable``."""
        _topic, payload = M.decode(G.make_order_new_unchecked(**_ORDER.to_dict()))
        assert payload["origin"] == "ORDER"
        assert payload["arrival_seq"] == 0

    def test_a_producer_that_omits_is_still_read_the_same(self) -> None:
        """balf_gwy builds its dict by hand and omits some of the eleven.

        ``Order.from_dict`` uses ``.get()`` for all of them, so omitting and
        emitting null must produce the same Order. This is the finding that
        collapsed the "two shapes" question into one contract.
        """
        full = _ORDER.to_dict()
        trimmed = {k: v for k, v in full.items() if v is not None}
        assert Order.from_dict(trimmed).to_dict() == Order.from_dict(full).to_dict()


class TestTheEngineStillReadsIt:
    def test_from_dict_round_trips_a_generated_payload(self) -> None:
        """The whole point: the engine's consumer is unaffected."""
        _topic, payload = M.decode(G.make_order_new_unchecked(**_ORDER.to_dict()))
        assert Order.from_dict(payload).to_dict() == _ORDER.to_dict()

    def test_validate_accepts_a_real_order(self) -> None:
        G.OrderNew.from_dict(_ORDER.to_dict()).validate()


class TestCancelAndAmend:
    def test_cancel_is_byte_identical(self) -> None:
        assert M.make_order_cancel_msg("O1", "GW1") == G.make_order_cancel_unchecked(
            order_id="O1", gateway_id="GW1"
        )

    @pytest.mark.parametrize(
        "price, qty",
        [(150.0, 200), (99.0, None), (None, 50), (None, None)],
    )
    def test_amend_is_byte_identical(
        self, price: float | None, qty: int | None
    ) -> None:
        assert M.make_order_amend_msg("O1", "GW1", price=price, qty=qty) == (
            G.make_order_amend_unchecked(
                order_id="O1", gateway_id="GW1", price=price, qty=qty
            )
        )

    @pytest.mark.parametrize("field", ["price", "qty"])
    def test_amend_omits_rather_than_nulls(self, field: str) -> None:
        """Unlike order.new. The engine reads absence as "leave unchanged"."""
        _topic, payload = M.decode(
            G.make_order_amend_unchecked(order_id="O1", gateway_id="GW1")
        )
        assert field not in payload


class TestStructureCancels:
    """Phase 5.1c, part one: ``order.combo_cancel`` and ``order.oco_cancel``.

    These two were the only members of the combo/OCO group the IDL could
    describe at the time. ``order.oco`` and ``order.combo`` have since joined
    them, once ``nested`` and ``list[T]`` landed. See design section 15.
    """

    def test_combo_cancel_is_byte_identical(self) -> None:
        assert M.make_combo_cancel_msg("C1", "GW1") == (
            G.make_order_combo_cancel_unchecked(combo_id="C1", gateway_id="GW1")
        )

    def test_oco_cancel_is_byte_identical(self) -> None:
        assert M.make_oco_cancel_msg("X1", "GW1") == (
            G.make_order_oco_cancel_unchecked(oco_id="X1", gateway_id="GW1")
        )

    @pytest.mark.parametrize(
        "cls, key",
        [(G.OrderComboCancel, "combo_id"), (G.OrderOcoCancel, "oco_id")],
    )
    def test_the_id_is_optional_because_the_engine_tolerates_it(
        self, cls: Any, key: str
    ) -> None:
        """The consumer uses ``.get(k, "")``, so the spec must not be stricter.

        Declaring these required would make ``validate()`` reject a frame the
        engine handles today - a behaviour change this migration has no
        business making. 5.1b's ``order.cancel`` *is* required, because
        ``_handle_cancel`` subscripts it strictly. The spec follows each
        consumer rather than imposing one rule on both.
        """
        assert getattr(cls.from_dict({}), key) == ""

    def test_an_empty_payload_still_validates(self) -> None:
        G.OrderComboCancel.from_dict({}).validate()
        G.OrderOcoCancel.from_dict({}).validate()

    def test_order_oco_arrived_with_its_legs_intact(self) -> None:
        """This test used to assert ``order.oco`` was absent, and it fired.

        The condition it guarded was never "stay absent" but "if you appear, do
        it because the IDL grew ``nested`` — not because the legs were
        flattened away". ``nested`` landed, so the assertion becomes the
        positive one: the legs are still records.
        """
        assert hasattr(G, "TOPIC_ORDER_OCO")
        assert hasattr(G, "OcoLeg")
        declared = {f["name"] for f in G.describe_order_oco()}
        assert {"leg1", "leg2"} <= declared

    def test_order_combo_arrived_with_its_legs_as_a_list(self) -> None:
        """The second guard in this class to fire, and for the same reason.

        It asserted ``order.combo`` was absent until ``list[T]`` landed. It
        has, so the assertion becomes what the guard was really protecting: the
        legs are a list of records, not flattened into leg1/leg2 scalars.
        """
        assert hasattr(G, "TOPIC_ORDER_COMBO")
        assert hasattr(G, "ComboLeg")
        combo = G.OrderCombo.from_dict(
            {
                "combo_id": "C1",
                "gateway_id": "GW1",
                "combo_type": "AON",
                "tif": "DAY",
                "legs": [
                    {
                        "symbol": "AAPL",
                        "side": "BUY",
                        "order_type": "LIMIT",
                        "quantity": 1,
                    },
                    {
                        "symbol": "MSFT",
                        "side": "SELL",
                        "order_type": "LIMIT",
                        "quantity": 1,
                    },
                ],
            }
        )
        assert isinstance(combo.legs, list)
        assert isinstance(combo.legs[0], G.ComboLeg)


class TestUnits:
    """``price`` means ticks inbound and display money outbound."""

    def test_order_new_price_is_ticks(self) -> None:
        spec = {f["name"]: f for f in G.describe_order_new()}
        assert spec["price"]["unit"] == "ticks"

    def test_order_amend_price_is_display_money(self) -> None:
        spec = {f["name"]: f for f in G.describe_order_amend()}
        assert spec["price"]["unit"] == "display_price"

    def test_a_tick_price_survives_as_an_int(self) -> None:
        """Coercion must not turn ticks into a float on the way out."""
        _topic, payload = M.decode(G.make_order_new_unchecked(**_ORDER.to_dict()))
        assert payload["price"] == 15000
        assert isinstance(payload["price"], int)


class TestTopicConstants:
    """What the migration replaced the literals with."""

    @pytest.mark.parametrize(
        "constant, literal",
        [
            (G.TOPIC_ORDER_NEW, "order.new"),
            (G.TOPIC_ORDER_CANCEL, "order.cancel"),
            (G.TOPIC_ORDER_AMEND, "order.amend"),
        ],
    )
    def test_the_constant_is_the_old_literal(self, constant: str, literal: str) -> None:
        assert constant == literal

    @pytest.mark.parametrize(
        "frames, expected",
        [
            (M.make_order_new_msg(_ORDER.to_dict()), "order.new"),
            (M.make_order_cancel_msg("O1", "GW1"), "order.cancel"),
            (M.make_order_amend_msg("O1", "GW1", price=1.0), "order.amend"),
        ],
    )
    def test_the_builders_publish_that_topic(
        self, frames: list[bytes], expected: str
    ) -> None:
        topic, _payload = M.decode(frames)
        assert topic == expected


class TestTheLiteralAliases:
    """5.1b's generator change: enums are named types, not inline Literals."""

    def test_an_alias_exists_for_each_enum(self) -> None:
        for name in (
            "OrderNewSide",
            "OrderNewOrderType",
            "OrderNewTif",
            "OrderNewStatus",
            "OrderNewSmpAction",
            "OrderNewOrigin",
        ):
            assert hasattr(G, name), name

    def test_generated_files_are_black_clean(self) -> None:
        """The invariant the aliases exist to keep, asserted directly.

        The emitter reproduces black's formatting rather than running black, so
        that ``pm-msgen check`` cannot go flaky when the installed black version
        changes (risk R9). Nothing was checking that the reproduction was still
        accurate - an eight-value enum was the first spec to push a line past 88
        columns, and it found three constructs the emitter split wrongly.

        Running black *here* is the right place for that dependency: a version
        bump failing this test is a true report that the emitter needs updating,
        whereas the same bump at generation time would silently change committed
        output.
        """
        from pathlib import Path

        black = pytest.importorskip("black")
        mode = black.Mode(line_length=88)
        offenders = []
        root = Path(__file__).resolve().parents[1]
        for path in sorted((root / "src/edumatcher/models/generated").glob("*.py")):
            source = path.read_text(encoding="utf-8")
            if black.format_str(source, mode=mode) != source:
                offenders.append(path.name)
        assert offenders == [], f"emitter drifted from black: {offenders}"


class TestSpecCompleteness:
    def test_order_new_declares_every_field_order_to_dict_emits(self) -> None:
        """A field the spec forgets is a field the wire silently loses."""
        declared = {f["name"] for f in G.describe_order_new()}
        assert declared == set(_ORDER.to_dict())
