"""
Shared PUB-feed payload schemas.

These dataclasses define the canonical payload shape for the cross-process
topics consumed by clearing.  They make the contract explicit in one place and
document units per field:

- trade.executed:
  - price: display price (float, not ticks)
  - timestamp: Unix epoch seconds (float, not ns)
  - tick_decimals: decimal scale for display<->ticks conversion
- session.state:
  - state / prev_state: phase labels

``system.eod``, ``system.gateway_auth.{id}`` and ``system.gateway_bye.{id}``
used to live here too. Phase 6.1e declared them in ``spec/messages/system.yaml``
instead, so their dataclasses are generated rather than hand-written -- which
is the point of the generator, and what this module is being emptied into.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class TradeExecutedPayload:
    """Payload for topic ``trade.executed``.

    Units:
    - ``price`` is display float.
    - ``timestamp`` is Unix epoch seconds (float).
    """

    id: str
    run_seq: int
    symbol: str
    buy_order_id: str
    sell_order_id: str
    buy_gateway_id: str
    sell_gateway_id: str
    price: float
    quantity: int
    aggressor_side: str
    timestamp: float
    tick_decimals: int = 2

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TradeExecutedPayload":
        return cls(
            id=str(payload["id"]),
            run_seq=int(payload["run_seq"]),
            symbol=str(payload["symbol"]),
            buy_order_id=str(payload["buy_order_id"]),
            sell_order_id=str(payload["sell_order_id"]),
            buy_gateway_id=str(payload["buy_gateway_id"]),
            sell_gateway_id=str(payload["sell_gateway_id"]),
            price=float(payload["price"]),
            quantity=int(payload["quantity"]),
            aggressor_side=str(payload.get("aggressor_side", "")),
            timestamp=float(payload["timestamp"]),
            tick_decimals=int(payload.get("tick_decimals", 2)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "run_seq": self.run_seq,
            "symbol": self.symbol,
            "buy_order_id": self.buy_order_id,
            "sell_order_id": self.sell_order_id,
            "buy_gateway_id": self.buy_gateway_id,
            "sell_gateway_id": self.sell_gateway_id,
            "price": self.price,
            "quantity": self.quantity,
            "aggressor_side": self.aggressor_side,
            "timestamp": self.timestamp,
            "tick_decimals": self.tick_decimals,
        }
