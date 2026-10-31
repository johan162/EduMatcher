"""Which price fields each order type takes: the one rule every transport applies.

REST, ALF, BALF and the engine used to carry four versions of this table, and
they disagreed: ALF dropped a field the type does not use where REST refused
it, ALF and the engine accepted a STOP_LIMIT combo leg without a price, the
engine let an IOC through without one. The same mistake was a synchronous 400
on one transport, an asynchronous engine reject on another and accepted on a
third -- with a different ``reject_code`` each time. Now each applies this
table (the gateways for a synchronous answer, the engine as the backstop for
all of them), so a mistake gets the same verdict and ``reject_code`` however
it arrives. Decided as Q9 of the REST API review (WP-API16).

Field names are the canonical ones (``price``, ``stop_price``,
``visible_qty``, ``trail_offset``); a transport passes ``names`` to word the
message in its own vocabulary (ALF's ``PRICE``, ``LEG1_STOP``, ...).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Literal

from edumatcher.models.order import OrderType

#: Every field a single order carries.
ORDER_FIELDS = ("price", "stop_price", "visible_qty", "trail_offset")
#: An OCO leg has no ``visible_qty``.
OCO_LEG_FIELDS = ("price", "stop_price", "trail_offset")
#: A combo leg has neither ``visible_qty`` nor ``trail_offset``.
COMBO_LEG_FIELDS = ("price", "stop_price")

#: order type -> (required fields, optional fields); any other carried field
#: is refused.
TYPE_FIELDS: dict[OrderType, tuple[tuple[str, ...], tuple[str, ...]]] = {
    OrderType.MARKET: ((), ()),
    OrderType.LIMIT: (("price",), ()),
    OrderType.FOK: (("price",), ()),
    OrderType.IOC: (("price",), ()),
    OrderType.STOP: (("stop_price",), ()),
    OrderType.STOP_LIMIT: (("price", "stop_price"), ()),
    OrderType.ICEBERG: (("price", "visible_qty"), ()),
    # Without stop_price the engine starts the stop at last trade +/- offset.
    OrderType.TRAILING_STOP: (("trail_offset",), ("stop_price",)),
}


@dataclass(frozen=True)
class FieldViolation:
    reject_code: Literal["MISSING_FIELD", "UNSUPPORTED_FIELD", "INVALID_VALUE"]
    message: str
    #: The canonical name of the first offending field; None when the type
    #: itself cannot be carried.
    field: str | None


def check_type_fields(
    order_type: OrderType,
    present: Collection[str],
    *,
    carried: Collection[str] = ORDER_FIELDS,
    names: Mapping[str, str] | None = None,
    where: str = "here",
) -> FieldViolation | None:
    """The verdict on an order of *order_type* with *present* fields set.

    *carried* is what the record can hold at all. A type needing a field it
    cannot hold (an ICEBERG combo leg has no ``visible_qty``) is refused as
    an invalid type rather than reported as missing a field the caller has no
    way to send.
    """
    required, optional = TYPE_FIELDS[order_type]

    def name(field: str) -> str:
        return (names or {}).get(field, field)

    uncarried = [f for f in required if f not in carried]
    if uncarried:
        return FieldViolation(
            "INVALID_VALUE",
            f"{order_type.value} is not supported {where}: it needs "
            + " and ".join(name(f) for f in uncarried),
            None,
        )
    missing = [f for f in required if f not in present]
    if missing:
        return FieldViolation(
            "MISSING_FIELD",
            f"{order_type.value} requires " + " and ".join(name(f) for f in missing),
            missing[0],
        )
    forbidden = [f for f in carried if f in present and f not in required + optional]
    if forbidden:
        return FieldViolation(
            "UNSUPPORTED_FIELD",
            f"{order_type.value} forbids " + " and ".join(name(f) for f in forbidden),
            forbidden[0],
        )
    return None
