"""Which orders an agent may send in which session phase.

The engine is the authority; this table keeps agents from sending what it
would refuse (MARKET/IOC/FOK outside CONTINUOUS, ATO/ATC outside their
auction) and encodes the agents' own policy on top: nothing for a halted
symbol, no stops outside continuous trading.
"""

from __future__ import annotations

from edumatcher.models.order import TIF, OrderType

_RESTING = {OrderType.LIMIT, OrderType.ICEBERG}

_ALLOWED: dict[str, tuple[set[OrderType], set[TIF]]] = {
    "PRE_OPEN": (_RESTING, {TIF.DAY, TIF.GTC}),
    "OPENING_AUCTION": (_RESTING, {TIF.DAY, TIF.GTC, TIF.ATO}),
    "CONTINUOUS": (set(OrderType), {TIF.DAY, TIF.GTC}),
    "CLOSING_AUCTION": (_RESTING, {TIF.DAY, TIF.GTC, TIF.ATC}),
}


def order_allowed(phase: str, order_type: OrderType, tif: TIF, halted: bool) -> bool:
    if halted:
        return False
    allowed = _ALLOWED.get(phase)
    if allowed is None:  # CLOSED or unknown
        return False
    types, tifs = allowed
    return order_type in types and tif in tifs


def auction_tif(phase: str) -> TIF | None:
    """The auction-only TIF of a call phase, if the phase has one."""
    if phase == "OPENING_AUCTION":
        return TIF.ATO
    if phase == "CLOSING_AUCTION":
        return TIF.ATC
    return None


def is_call_phase(phase: str) -> bool:
    return phase in ("PRE_OPEN", "OPENING_AUCTION", "CLOSING_AUCTION")
