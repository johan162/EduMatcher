"""
Domain models: ComboOrder, ComboLeg, and related enums.

A combo order bundles two or more child orders (legs) across different symbols.
The engine decomposes the combo into child orders posted to per-symbol books.
The parent combo tracks whether all legs have filled.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from edumatcher.models.clock import now_ns

from edumatcher.models.order import (
    OrderStatus,
    OrderType,
    Side,
    SmpAction,
    TIF,
)


class ComboType(str, Enum):
    """Combo execution semantics."""

    AON = "AON"  # all-or-none: combo completes only when ALL legs are fully filled


class ComboStatus(str, Enum):
    """Combo-level lifecycle status."""

    PENDING = "PENDING"  # child orders posted, waiting for fills
    PARTIALLY_MATCHED = "PARTIALLY_MATCHED"  # 1+ legs filled, others still resting
    MATCHED = "MATCHED"  # all legs fully filled
    FAILED = "FAILED"  # a leg cancelled/expired; siblings cascade-cancelled
    CANCELLED = "CANCELLED"  # user cancelled the combo
    REJECTED = "REJECTED"  # combo rejected at entry (validation failure)


@dataclass
class ComboLeg:
    """One leg of a combo order."""

    symbol: str
    side: Side
    order_type: OrderType
    quantity: int
    price: Optional[int] = None
    stop_price: Optional[int] = None
    smp_action: SmpAction = SmpAction.NONE

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "quantity": self.quantity,
            "price": self.price,
            "stop_price": self.stop_price,
            "smp_action": self.smp_action.value,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ComboLeg":
        return cls(
            symbol=d["symbol"],
            side=Side(d["side"]),
            order_type=OrderType(d["order_type"]),
            quantity=d["quantity"],
            price=d.get("price"),
            stop_price=d.get("stop_price"),
            smp_action=SmpAction(d.get("smp_action", SmpAction.NONE)),
        )


@dataclass
class ComboOrder:
    """
    Parent combo order that owns one or more child orders (legs).

    The engine creates one child ``Order`` per leg and posts it to the
    per-symbol book.  This object tracks the aggregate status.
    """

    id: str  # internal UUID
    combo_id: str  # user-provided tracking label
    gateway_id: str
    combo_type: ComboType
    tif: TIF
    legs: list[ComboLeg]
    timestamp: int
    status: ComboStatus = ComboStatus.PENDING

    # Populated by the engine after child orders are created
    child_order_ids: list[str] = field(default_factory=list)
    leg_fill_qty: dict[int, int] = field(
        default_factory=dict
    )  # leg_index → qty filled so far
    leg_statuses: dict[int, str] = field(
        default_factory=dict
    )  # leg_index → OrderStatus.value

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    @property
    def is_fully_filled(self) -> bool:
        """True when every leg has status FILLED."""
        if len(self.leg_statuses) != len(self.legs):
            return False
        return all(s == OrderStatus.FILLED.value for s in self.leg_statuses.values())

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------
    @classmethod
    def create(
        cls,
        combo_id: str,
        gateway_id: str,
        combo_type: ComboType,
        tif: TIF,
        legs: list[ComboLeg],
    ) -> "ComboOrder":
        return cls(
            id=str(uuid.uuid4()),
            combo_id=combo_id,
            gateway_id=gateway_id,
            combo_type=combo_type,
            tif=tif,
            legs=legs,
            timestamp=now_ns(),
        )

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "combo_id": self.combo_id,
            "gateway_id": self.gateway_id,
            "combo_type": self.combo_type.value,
            "tif": self.tif.value,
            "legs": [leg.to_dict() for leg in self.legs],
            "timestamp": self.timestamp,
            "status": self.status.value,
            "child_order_ids": self.child_order_ids,
            "leg_fill_qty": {str(k): v for k, v in self.leg_fill_qty.items()},
            "leg_statuses": {str(k): v for k, v in self.leg_statuses.items()},
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ComboOrder":
        combo = cls(
            id=d["id"],
            combo_id=d["combo_id"],
            gateway_id=d["gateway_id"],
            combo_type=ComboType(d["combo_type"]),
            tif=TIF(d["tif"]),
            legs=[ComboLeg.from_dict(leg) for leg in d["legs"]],
            timestamp=d["timestamp"],
            status=ComboStatus(d["status"]),
            child_order_ids=d.get("child_order_ids", []),
        )
        combo.leg_fill_qty = {int(k): v for k, v in d.get("leg_fill_qty", {}).items()}
        combo.leg_statuses = {int(k): v for k, v in d.get("leg_statuses", {}).items()}
        return combo
