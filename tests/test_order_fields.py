"""WP-API16: the one per-order-type field rule (models/order_fields.py).

REST, ALF, BALF and the engine all apply this table; these tests pin the
table itself and the verdicts every transport turns into its reply.
"""

from __future__ import annotations

import pytest

from edumatcher.models.order import OrderType
from edumatcher.models.order_fields import (
    COMBO_LEG_FIELDS,
    OCO_LEG_FIELDS,
    TYPE_FIELDS,
    check_type_fields,
)


def test_every_order_type_has_a_rule() -> None:
    assert set(TYPE_FIELDS) == set(OrderType)


@pytest.mark.parametrize(
    ("order_type", "present"),
    [
        (OrderType.MARKET, set()),
        (OrderType.LIMIT, {"price"}),
        (OrderType.IOC, {"price"}),
        (OrderType.FOK, {"price"}),
        (OrderType.STOP, {"stop_price"}),
        (OrderType.STOP_LIMIT, {"price", "stop_price"}),
        (OrderType.ICEBERG, {"price", "visible_qty"}),
        (OrderType.TRAILING_STOP, {"trail_offset"}),
        (OrderType.TRAILING_STOP, {"trail_offset", "stop_price"}),
    ],
)
def test_a_complete_order_passes(order_type: OrderType, present: set[str]) -> None:
    assert check_type_fields(order_type, present) is None


@pytest.mark.parametrize(
    ("order_type", "present", "reject_code", "message"),
    [
        (OrderType.IOC, set(), "MISSING_FIELD", "IOC requires price"),
        (
            OrderType.STOP_LIMIT,
            {"stop_price"},
            "MISSING_FIELD",
            "STOP_LIMIT requires price",
        ),
        (
            OrderType.ICEBERG,
            set(),
            "MISSING_FIELD",
            "ICEBERG requires price and visible_qty",
        ),
        (OrderType.MARKET, {"price"}, "UNSUPPORTED_FIELD", "MARKET forbids price"),
        (
            OrderType.LIMIT,
            {"price", "trail_offset"},
            "UNSUPPORTED_FIELD",
            "LIMIT forbids trail_offset",
        ),
    ],
)
def test_violations_carry_one_reject_code(
    order_type: OrderType, present: set[str], reject_code: str, message: str
) -> None:
    violation = check_type_fields(order_type, present)
    assert violation is not None
    assert (violation.reject_code, violation.message) == (reject_code, message)


def test_messages_use_the_transports_field_names() -> None:
    names = {"price": "LEG1_PRICE", "trail_offset": "LEG1_TRAIL"}
    violation = check_type_fields(
        OrderType.LIMIT, {"price", "trail_offset"}, names=names
    )
    assert violation is not None
    assert violation.message == "LIMIT forbids LEG1_TRAIL"
    assert violation.field == "trail_offset"


def test_a_type_the_record_cannot_carry_is_an_invalid_value() -> None:
    """An ICEBERG combo leg is not "missing visible_qty": a leg has no such
    field, so the caller could never fix it by sending one."""
    violation = check_type_fields(
        OrderType.ICEBERG, {"price"}, carried=COMBO_LEG_FIELDS, where="on a combo leg"
    )
    assert violation is not None
    assert violation.reject_code == "INVALID_VALUE"
    assert violation.message == (
        "ICEBERG is not supported on a combo leg: it needs visible_qty"
    )
    assert (
        check_type_fields(
            OrderType.TRAILING_STOP, {"trail_offset"}, carried=OCO_LEG_FIELDS
        )
        is None
    )
