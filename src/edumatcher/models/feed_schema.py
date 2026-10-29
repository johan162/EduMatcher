"""
Shared PUB-feed payload schemas.

These dataclasses define the canonical payload shape for the cross-process
topics consumed by clearing.  They make the contract explicit in one place and
document units per field:

- trade.executed:
  - price: display price (float, not ticks)
  - ts_ns: Unix epoch nanoseconds (int), the engine clock unscaled
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
from typing import Any, Mapping, cast

from edumatcher.models.generated.trade import TradeExecutedMatchType


@dataclass(frozen=True)
class TradeExecutedPayload:
    """Payload for topic ``trade.executed``.

    Units:
    - ``price`` is display float; ``price_ticks`` the same price in engine
      ticks, canonical (absent on prints from before it existed).
    - ``ts_ns`` is Unix epoch nanoseconds (int), carried through unscaled.
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
    ts_ns: int
    tick_decimals: int = 2
    price_ticks: int | None = None
    match_type: TradeExecutedMatchType | None = None
    auction_id: str | None = None
    trigger_order_id: str | None = None

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
            ts_ns=int(payload["ts_ns"]),
            tick_decimals=int(payload.get("tick_decimals", 2)),
            price_ticks=(
                None
                if payload.get("price_ticks") is None
                else int(payload["price_ticks"])
            ),
            match_type=cast("TradeExecutedMatchType | None", payload.get("match_type")),
            auction_id=payload.get("auction_id"),
            trigger_order_id=payload.get("trigger_order_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
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
            "ts_ns": self.ts_ns,
            "tick_decimals": self.tick_decimals,
        }
        # Omitted when unset, as the spec's encoder omits them.
        if self.price_ticks is not None:
            out["price_ticks"] = self.price_ticks
        if self.match_type is not None:
            out["match_type"] = self.match_type
        if self.auction_id is not None:
            out["auction_id"] = self.auction_id
        if self.trigger_order_id is not None:
            out["trigger_order_id"] = self.trigger_order_id
        return out
