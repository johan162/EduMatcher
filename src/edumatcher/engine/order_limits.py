"""
engine/order_limits.py — Pre-trade order-size and notional caps.

Two independent caps, both optional, configured per symbol only
(``symbols.<S>.order_limits``). Unlike a collar there is no risk-level form:
the right cap depends on the instrument's price and trade size, so the loader
rejects ``risk_controls.levels.<L>.order_limits`` (cverifier ``S117``):

``max_order_qty``
  Largest quantity a single order may carry. Catches the fat-finger that
  adds a zero to the size rather than to the price — the case a collar
  cannot see, because the price is perfectly reasonable.

``max_order_value``
  Largest notional (``quantity * price``) a single order may carry, in
  display money. Catches the same error expressed as a plausible size on
  an expensive instrument.

An absent cap is not enforced. That is the same rule an absent ``collar``
follows, and it is deliberate: a limit that lives in code rather than in
the config file is not auditable as a requirement.

An order with no price — a MARKET order, or an IOC sent without one — has
no known notional at validation time, so ``max_order_value`` is skipped for
it, as the collar's price bands are. A priced IOC is checked at its limit.
``max_order_qty`` applies to every order.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from edumatcher.models.reject import RejectCode


@dataclass
class OrderLimitsConfig:
    """A symbol's effective order-size and notional caps.

    Attributes
    ----------
    max_order_qty   : Maximum quantity in shares, or ``None`` for no cap.
    max_order_value : Maximum notional in *display money*, or ``None`` for
                      no cap. Display money, not ticks: the number in the
                      config file is the number an operator reasons about.
    """

    max_order_qty: Optional[int] = None
    max_order_value: Optional[float] = None


def validate_order_limits(
    quantity: int,
    price: Optional[float],
    limits: OrderLimitsConfig,
) -> Optional[tuple[RejectCode, str]]:
    """Check one order against its caps.

    Parameters
    ----------
    quantity : Order quantity in shares.
    price    : Order price in *display money*, or ``None`` when the order
               carries no price (MARKET, unpriced IOC), which skips the notional
               check.
    limits   : The symbol's effective caps.

    Returns
    -------
    ``(reject_code, reason)`` on a breach, or ``None`` when the order
    passes both caps.
    """
    if limits.max_order_qty is not None and quantity > limits.max_order_qty:
        return (
            "MAX_ORDER_QTY",
            f"Quantity {quantity} exceeds max_order_qty {limits.max_order_qty}",
        )
    if limits.max_order_value is not None and price is not None:
        value = quantity * price
        if value > limits.max_order_value:
            return (
                "MAX_ORDER_VALUE",
                f"Order value {value:.2f} exceeds "
                f"max_order_value {limits.max_order_value}",
            )
    return None
