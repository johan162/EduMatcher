# GENERATED FROM spec/messages/system.yaml - DO NOT EDIT
#
# Regenerate with:  poetry run pm-msgen generate
"""Generated bindings for the ``system`` message family.

Family version 1. Every symbol here is derived from ``spec/messages/system.yaml``; edit
the spec, not this file.

``pm-msgen check`` fails the build if this file and the spec disagree. See
docs/developer/06-msgen.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, cast

from edumatcher.models import message as _msg
from edumatcher.models.generated._runtime import MessageValidationError

FAMILY = "system"
FAMILY_VERSION = 1


@dataclass(frozen=True, slots=True)
class SymbolInfo:
    """One tradable instrument, as the engine sees it for a given caller. What used
    to be one entry of `symbols` and one entry of `symbol_meta`, which were always
    the same instrument written twice. The market-maker fields are resolved per
    caller, not per symbol: the engine layers the gateway's own policy, the global
    per-symbol policy and the gateway's per-symbol override before publishing. Two
    gateways asking at the same moment get different values for the same
    instrument, which is why they travel on this reply rather than in the
    reference bundle.
    """

    symbol: str
    tick_decimals: int  # unit: dimensionless
    enforce_mm_obligation: bool | None = None
    mm_max_spread_ticks: int | None = None  # unit: ticks
    mm_min_qty: int | None = None  # unit: shares
    prev_close: float | None = None  # unit: display_price

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if self.tick_decimals < 0:
            raise MessageValidationError(
                f"tick_decimals: {self.tick_decimals!r} must be >= 0"
            )
        if self.tick_decimals > 9:
            raise MessageValidationError(
                f"tick_decimals: {self.tick_decimals!r} must be <= 9"
            )
        if self.mm_max_spread_ticks is not None:
            if self.mm_max_spread_ticks < 0:
                raise MessageValidationError(
                    f"mm_max_spread_ticks: {self.mm_max_spread_ticks!r} must be >= 0"
                )
        if self.mm_min_qty is not None:
            if self.mm_min_qty < 0:
                raise MessageValidationError(
                    f"mm_min_qty: {self.mm_min_qty!r} must be >= 0"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SymbolInfo":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
            tick_decimals=int(p["tick_decimals"]),
            enforce_mm_obligation=(
                None
                if p.get("enforce_mm_obligation") is None
                else bool(p["enforce_mm_obligation"])
            ),
            mm_max_spread_ticks=(
                None
                if p.get("mm_max_spread_ticks") is None
                else int(p["mm_max_spread_ticks"])
            ),
            mm_min_qty=None if p.get("mm_min_qty") is None else int(p["mm_min_qty"]),
            prev_close=None if p.get("prev_close") is None else float(p["prev_close"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "tick_decimals": self.tick_decimals,
        }
        if self.enforce_mm_obligation is not None:
            payload["enforce_mm_obligation"] = self.enforce_mm_obligation
        if self.mm_max_spread_ticks is not None:
            payload["mm_max_spread_ticks"] = self.mm_max_spread_ticks
        if self.mm_min_qty is not None:
            payload["mm_min_qty"] = self.mm_min_qty
        if self.prev_close is not None:
            payload["prev_close"] = self.prev_close
        return payload


@dataclass(frozen=True, slots=True)
class Collar:
    """Price-band configuration. The two bands `CollarConfig` reads; a deployment
    writing other keys under `collar:` in its YAML had them carried onto the wire
    and read by nothing, and they no longer travel.
    """

    static_band_pct: float  # unit: percent
    dynamic_band_pct: float  # unit: percent

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.static_band_pct < 0:
            raise MessageValidationError(
                f"static_band_pct: {self.static_band_pct!r} must be >= 0"
            )
        if self.dynamic_band_pct < 0:
            raise MessageValidationError(
                f"dynamic_band_pct: {self.dynamic_band_pct!r} must be >= 0"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "Collar":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            static_band_pct=float(p["static_band_pct"]),
            dynamic_band_pct=float(p["dynamic_band_pct"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "static_band_pct": self.static_band_pct,
            "dynamic_band_pct": self.dynamic_band_pct,
        }


@dataclass(frozen=True, slots=True)
class OrderLimits:
    """Pre-trade order-size and notional caps, as configured on a symbol. Each cap is
    independently optional: an absent cap is not enforced, the same way an absent
    `collar` leaves a symbol uncollared.
    """

    max_order_qty: int | None = None  # unit: shares
    max_order_value: float | None = None  # unit: money

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.max_order_qty is not None:
            if self.max_order_qty <= 0:
                raise MessageValidationError(
                    f"max_order_qty: {self.max_order_qty!r} must be > 0"
                )
        if self.max_order_value is not None:
            if self.max_order_value <= 0:
                raise MessageValidationError(
                    f"max_order_value: {self.max_order_value!r} must be > 0"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "OrderLimits":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            max_order_qty=(
                None if p.get("max_order_qty") is None else int(p["max_order_qty"])
            ),
            max_order_value=(
                None
                if p.get("max_order_value") is None
                else float(p["max_order_value"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {}
        if self.max_order_qty is not None:
            payload["max_order_qty"] = self.max_order_qty
        if self.max_order_value is not None:
            payload["max_order_value"] = self.max_order_value
        return payload


@dataclass(frozen=True, slots=True)
class CircuitBreakerLevel:
    """One rung of a symbol's circuit-breaker ladder, as configured. `name` is the
    string `circuit_breaker.halt.level` and `admin.action.scope.level` carry
    onward, and is bounded here to match them.
    """

    name: str
    price_shift_pct: float  # unit: percent
    halt_duration_ns: int  # unit: duration_nanos

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.name) > 32:
            raise MessageValidationError(
                f"name: length {len(self.name)} exceeds max_len 32"
            )
        if self.price_shift_pct <= 0:
            raise MessageValidationError(
                f"price_shift_pct: {self.price_shift_pct!r} must be > 0"
            )
        if self.halt_duration_ns < 0:
            raise MessageValidationError(
                f"halt_duration_ns: {self.halt_duration_ns!r} must be >= 0"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "CircuitBreakerLevel":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            name=str(p["name"]),
            price_shift_pct=float(p["price_shift_pct"]),
            halt_duration_ns=int(p["halt_duration_ns"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "name": self.name,
            "price_shift_pct": self.price_shift_pct,
            "halt_duration_ns": self.halt_duration_ns,
        }


@dataclass(frozen=True, slots=True)
class SymbolCircuitBreaker:
    """A symbol's configured circuit-breaker ladder and its lookback."""

    reference_window_ns: int  # unit: duration_nanos
    levels: list[CircuitBreakerLevel]

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.reference_window_ns < 0:
            raise MessageValidationError(
                f"reference_window_ns: {self.reference_window_ns!r} must be >= 0"
            )
        for levels_item in self.levels:
            levels_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SymbolCircuitBreaker":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            reference_window_ns=int(p["reference_window_ns"]),
            levels=[CircuitBreakerLevel.from_dict(item) for item in p["levels"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "reference_window_ns": self.reference_window_ns,
            "levels": [item.to_dict() for item in self.levels],
        }


@dataclass(frozen=True, slots=True)
class ReferenceSymbol:
    """One instrument's static configuration. Distinct from `SymbolInfo`, which is
    the same instrument as a *caller* sees it: this record is identical for every
    caller and changes only on reload, which is why the bundle can be cached and
    hashed and the symbols reply cannot.
    """

    symbol: str
    tick_decimals: int  # unit: dimensionless
    level: str | None = None
    collar: Collar | None = None
    order_limits: OrderLimits | None = None
    circuit_breaker: SymbolCircuitBreaker | None = None

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if self.tick_decimals < 0:
            raise MessageValidationError(
                f"tick_decimals: {self.tick_decimals!r} must be >= 0"
            )
        if self.tick_decimals > 9:
            raise MessageValidationError(
                f"tick_decimals: {self.tick_decimals!r} must be <= 9"
            )
        if self.level is not None:
            if len(self.level) > 32:
                raise MessageValidationError(
                    f"level: length {len(self.level)} exceeds max_len 32"
                )
        if self.collar is not None:
            self.collar.validate()
        if self.order_limits is not None:
            self.order_limits.validate()
        if self.circuit_breaker is not None:
            self.circuit_breaker.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "ReferenceSymbol":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
            tick_decimals=int(p["tick_decimals"]),
            level=None if p.get("level") is None else str(p["level"]),
            collar=None if p.get("collar") is None else Collar.from_dict(p["collar"]),
            order_limits=(
                None
                if p.get("order_limits") is None
                else OrderLimits.from_dict(p["order_limits"])
            ),
            circuit_breaker=(
                None
                if p.get("circuit_breaker") is None
                else SymbolCircuitBreaker.from_dict(p["circuit_breaker"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "tick_decimals": self.tick_decimals,
        }
        if self.level is not None:
            payload["level"] = self.level
        if self.collar is not None:
            payload["collar"] = self.collar.to_dict()
        if self.order_limits is not None:
            payload["order_limits"] = self.order_limits.to_dict()
        if self.circuit_breaker is not None:
            payload["circuit_breaker"] = self.circuit_breaker.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class RiskLevel:
    """One named risk-control level. Was a map entry keyed by `name`; section 19.2's
    shape, with the key as a field.
    """

    name: str
    collar: Collar | None = None

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.name) > 32:
            raise MessageValidationError(
                f"name: length {len(self.name)} exceeds max_len 32"
            )
        if self.collar is not None:
            self.collar.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "RiskLevel":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            name=str(p["name"]),
            collar=None if p.get("collar") is None else Collar.from_dict(p["collar"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "name": self.name,
        }
        if self.collar is not None:
            payload["collar"] = self.collar.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class ReferenceRisk:
    """The risk-control ladder as configured, and which rung is the default."""

    levels: list[RiskLevel]
    default_level: str | None = None

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.default_level is not None:
            if len(self.default_level) > 32:
                raise MessageValidationError(
                    f"default_level: length {len(self.default_level)} exceeds max_len 32"
                )
        for levels_item in self.levels:
            levels_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "ReferenceRisk":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            default_level=(
                None if p.get("default_level") is None else str(p["default_level"])
            ),
            levels=[RiskLevel.from_dict(item) for item in p["levels"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "levels": [item.to_dict() for item in self.levels],
        }
        if self.default_level is not None:
            payload["default_level"] = self.default_level
        return payload


@dataclass(frozen=True, slots=True)
class SessionTimes:
    """The trading day's clock, as five wall-clock times. Carried by
    `system.session_schedule` and, nested inside `ReferenceSchedule`, by
    `system.reference` -- one shape declared once rather than two declarations
    that can drift apart. The values are strings because that is what the config
    file holds and what every consumer renders. Nullable individually because a
    partial `schedule:` block is a legal config.
    """

    pre_open: str | None = None
    opening_auction_start: str | None = None
    continuous_start: str | None = None
    closing_auction_start: str | None = None
    closing_auction_end: str | None = None

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.pre_open is not None:
            if len(self.pre_open) > 32:
                raise MessageValidationError(
                    f"pre_open: length {len(self.pre_open)} exceeds max_len 32"
                )
        if self.opening_auction_start is not None:
            if len(self.opening_auction_start) > 32:
                raise MessageValidationError(
                    f"opening_auction_start: length {len(self.opening_auction_start)} exceeds max_len 32"
                )
        if self.continuous_start is not None:
            if len(self.continuous_start) > 32:
                raise MessageValidationError(
                    f"continuous_start: length {len(self.continuous_start)} exceeds max_len 32"
                )
        if self.closing_auction_start is not None:
            if len(self.closing_auction_start) > 32:
                raise MessageValidationError(
                    f"closing_auction_start: length {len(self.closing_auction_start)} exceeds max_len 32"
                )
        if self.closing_auction_end is not None:
            if len(self.closing_auction_end) > 32:
                raise MessageValidationError(
                    f"closing_auction_end: length {len(self.closing_auction_end)} exceeds max_len 32"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SessionTimes":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            pre_open=None if p.get("pre_open") is None else str(p["pre_open"]),
            opening_auction_start=(
                None
                if p.get("opening_auction_start") is None
                else str(p["opening_auction_start"])
            ),
            continuous_start=(
                None
                if p.get("continuous_start") is None
                else str(p["continuous_start"])
            ),
            closing_auction_start=(
                None
                if p.get("closing_auction_start") is None
                else str(p["closing_auction_start"])
            ),
            closing_auction_end=(
                None
                if p.get("closing_auction_end") is None
                else str(p["closing_auction_end"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "pre_open": self.pre_open,
            "opening_auction_start": self.opening_auction_start,
            "continuous_start": self.continuous_start,
            "closing_auction_start": self.closing_auction_start,
            "closing_auction_end": self.closing_auction_end,
        }


@dataclass(frozen=True, slots=True)
class ReferenceSchedule:
    """The venue's calendar configuration: whether sessions run at all, which
    country's holidays they observe, and the clock itself. `schedule` is nested
    rather than flattened beside its two siblings, which is a change to `GET
    /reference/schedule`. The alternative was declaring `SessionTimes`'s five
    fields a second time inline, and a shape described twice is the drift section
    1 is about.
    """

    sessions_enabled: bool
    country: str | None = None
    schedule: SessionTimes | None = None

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.country is not None:
            if len(self.country) > 2:
                raise MessageValidationError(
                    f"country: length {len(self.country)} exceeds max_len 2"
                )
        if self.schedule is not None:
            self.schedule.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "ReferenceSchedule":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            sessions_enabled=bool(p["sessions_enabled"]),
            country=None if p.get("country") is None else str(p["country"]),
            schedule=(
                None
                if p.get("schedule") is None
                else SessionTimes.from_dict(p["schedule"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "sessions_enabled": self.sessions_enabled,
            "schedule": None if self.schedule is None else self.schedule.to_dict(),
        }
        if self.country is not None:
            payload["country"] = self.country
        return payload


@dataclass(frozen=True, slots=True)
class IndexDefinition:
    """One index as configured -- its membership and its starting level, not its
    current one. `GET /history/index-daily` serves the live value; see
    `index.rebalance`.
    """

    id: str
    base_value: float  # unit: dimensionless
    constituents: list[str]
    description: str = ""

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.id) > 32:
            raise MessageValidationError(
                f"id: length {len(self.id)} exceeds max_len 32"
            )
        if len(self.description) > 128:
            raise MessageValidationError(
                f"description: length {len(self.description)} exceeds max_len 128"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "IndexDefinition":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            id=str(p["id"]),
            description=str(p.get("description", "")),
            base_value=float(p["base_value"]),
            constituents=[str(item) for item in p["constituents"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "id": self.id,
            "description": self.description,
            "base_value": self.base_value,
            "constituents": self.constituents,
        }


@dataclass(frozen=True, slots=True)
class EodBookLevel:
    """One aggregated price level of a closing book. The same three fields as
    `book.BookLevel`, redeclared because records are family-scoped and the IDL has
    no cross-family reference -- see design section 28.5 on why that stays a known
    duplication rather than becoming a shared-types construct on the strength of
    one instance. `price` is required here. `BookLevelPayload`, the hand-written
    dataclass this replaces, made it optional; the only producer is
    `OrderBook.snapshot()`, which has never emitted a level without one.
    """

    price: float  # unit: display_price
    qty: int  # unit: shares
    count: int  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        return None

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "EodBookLevel":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            price=float(p["price"]),
            qty=int(p["qty"]),
            count=int(p["count"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "price": self.price,
            "qty": self.qty,
            "count": self.count,
        }


@dataclass(frozen=True, slots=True)
class EodBook:
    """One symbol's closing book. A deliberately trimmed `book.book_snapshot`:
    `SystemEodPayload.from_dict` has always dropped `last_qty`, `last_buy_price`,
    `last_sell_price` and `recent_trades` from the snapshot it is handed, and this
    record says so rather than leaving it to a `from_dict` a reader has to go and
    find.
    """

    symbol: str
    tick_decimals: int  # unit: dimensionless
    bids: list[EodBookLevel]
    asks: list[EodBookLevel]
    last_price: float | None = None  # unit: display_price

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if self.tick_decimals < 0:
            raise MessageValidationError(
                f"tick_decimals: {self.tick_decimals!r} must be >= 0"
            )
        if self.tick_decimals > 9:
            raise MessageValidationError(
                f"tick_decimals: {self.tick_decimals!r} must be <= 9"
            )
        for bids_item in self.bids:
            bids_item.validate()
        for asks_item in self.asks:
            asks_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "EodBook":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
            tick_decimals=int(p["tick_decimals"]),
            bids=[EodBookLevel.from_dict(item) for item in p["bids"]],
            asks=[EodBookLevel.from_dict(item) for item in p["asks"]],
            last_price=None if p.get("last_price") is None else float(p["last_price"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "symbol": self.symbol,
            "tick_decimals": self.tick_decimals,
            "bids": [item.to_dict() for item in self.bids],
            "asks": [item.to_dict() for item in self.asks],
        }
        if self.last_price is not None:
            payload["last_price"] = self.last_price
        return payload


@dataclass(frozen=True, slots=True)
class HaltedSymbol:
    """One currently-halted instrument. The circuit-breaker detail is present only
    when a circuit breaker is what halted it: an ADMIN halt sets the flag without
    a breaker behind it, so the three fields travel together or not at all --
    section 16.2's combination, expressed as three regime-3 fields rather than a
    record because they are three independent CALF-side values and no reader holds
    them as a unit (section 26.2's reasoning, second application).
    """

    symbol: str
    resume_at_ns: int | None = None  # unit: epoch_nanos
    level: str | None = None
    halt_source: str | None = None

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if self.level is not None:
            if len(self.level) > 32:
                raise MessageValidationError(
                    f"level: length {len(self.level)} exceeds max_len 32"
                )
        if self.halt_source is not None:
            if len(self.halt_source) > 32:
                raise MessageValidationError(
                    f"halt_source: length {len(self.halt_source)} exceeds max_len 32"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "HaltedSymbol":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
            resume_at_ns=(
                None if p.get("resume_at_ns") is None else int(p["resume_at_ns"])
            ),
            level=None if p.get("level") is None else str(p["level"]),
            halt_source=None if p.get("halt_source") is None else str(p["halt_source"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "symbol": self.symbol,
        }
        if self.resume_at_ns is not None:
            payload["resume_at_ns"] = self.resume_at_ns
        if self.level is not None:
            payload["level"] = self.level
        if self.halt_source is not None:
            payload["halt_source"] = self.halt_source
        return payload


@dataclass(frozen=True, slots=True)
class Position:
    """One instrument the gateway is not flat in. Only non-zero net positions are
    reported, so an empty list means flat everywhere.
    """

    symbol: str
    net_qty: int  # unit: shares
    avg_cost: float  # unit: display_price

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if self.avg_cost < 0:
            raise MessageValidationError(f"avg_cost: {self.avg_cost!r} must be >= 0")

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "Position":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
            net_qty=int(p["net_qty"]),
            avg_cost=float(p["avg_cost"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "symbol": self.symbol,
            "net_qty": self.net_qty,
            "avg_cost": self.avg_cost,
        }


@dataclass(frozen=True, slots=True)
class ActiveQuote:
    """One active two-sided quote, with both legs' live order state. What a market
    maker reads on reconnect to find out what it already has resting. A leg whose
    order is gone reports `MISSING` with zero quantities rather than being
    omitted: the quote still exists as far as the engine's index is concerned, and
    a bootstrap that silently dropped one side would let a bot re-quote into its
    own resting order.
    """

    quote_id: str
    gateway_id: str
    symbol: str
    state: str
    bid_order_id: str
    ask_order_id: str
    bid_qty: int  # unit: shares
    ask_qty: int  # unit: shares
    bid_remaining_qty: int  # unit: shares
    ask_remaining_qty: int  # unit: shares
    bid_status: str
    ask_status: str
    bid_price: float | None = None  # unit: display_price
    ask_price: float | None = None  # unit: display_price

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.quote_id) > 64:
            raise MessageValidationError(
                f"quote_id: length {len(self.quote_id)} exceeds max_len 64"
            )
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if len(self.state) > 32:
            raise MessageValidationError(
                f"state: length {len(self.state)} exceeds max_len 32"
            )
        if len(self.bid_order_id) > 64:
            raise MessageValidationError(
                f"bid_order_id: length {len(self.bid_order_id)} exceeds max_len 64"
            )
        if len(self.ask_order_id) > 64:
            raise MessageValidationError(
                f"ask_order_id: length {len(self.ask_order_id)} exceeds max_len 64"
            )
        if self.bid_qty < 0:
            raise MessageValidationError(f"bid_qty: {self.bid_qty!r} must be >= 0")
        if self.ask_qty < 0:
            raise MessageValidationError(f"ask_qty: {self.ask_qty!r} must be >= 0")
        if self.bid_remaining_qty < 0:
            raise MessageValidationError(
                f"bid_remaining_qty: {self.bid_remaining_qty!r} must be >= 0"
            )
        if self.ask_remaining_qty < 0:
            raise MessageValidationError(
                f"ask_remaining_qty: {self.ask_remaining_qty!r} must be >= 0"
            )
        if len(self.bid_status) > 32:
            raise MessageValidationError(
                f"bid_status: length {len(self.bid_status)} exceeds max_len 32"
            )
        if len(self.ask_status) > 32:
            raise MessageValidationError(
                f"ask_status: length {len(self.ask_status)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "ActiveQuote":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            quote_id=str(p["quote_id"]),
            gateway_id=str(p["gateway_id"]),
            symbol=str(p["symbol"]),
            state=str(p["state"]),
            bid_order_id=str(p["bid_order_id"]),
            ask_order_id=str(p["ask_order_id"]),
            bid_price=None if p.get("bid_price") is None else float(p["bid_price"]),
            ask_price=None if p.get("ask_price") is None else float(p["ask_price"]),
            bid_qty=int(p["bid_qty"]),
            ask_qty=int(p["ask_qty"]),
            bid_remaining_qty=int(p["bid_remaining_qty"]),
            ask_remaining_qty=int(p["ask_remaining_qty"]),
            bid_status=str(p["bid_status"]),
            ask_status=str(p["ask_status"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "quote_id": self.quote_id,
            "gateway_id": self.gateway_id,
            "symbol": self.symbol,
            "state": self.state,
            "bid_order_id": self.bid_order_id,
            "ask_order_id": self.ask_order_id,
            "bid_price": self.bid_price,
            "ask_price": self.ask_price,
            "bid_qty": self.bid_qty,
            "ask_qty": self.ask_qty,
            "bid_remaining_qty": self.bid_remaining_qty,
            "ask_remaining_qty": self.ask_remaining_qty,
            "bid_status": self.bid_status,
            "ask_status": self.ask_status,
        }


_QUOTE_LEG_LEG_SIDE_VALUES = ("BUY", "SELL")
QuoteLegLegSide = Literal["BUY", "SELL"]


@dataclass(frozen=True, slots=True)
class QuoteLeg:
    """One live leg of an active quote, with its order's current state."""

    quote_id: str
    order_id: str
    symbol: str
    leg_side: QuoteLegLegSide
    qty: int  # unit: shares
    remaining: int  # unit: shares
    filled: int  # unit: shares
    status: str
    quote_status: str
    price: float | None = None  # unit: display_price

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.quote_id) > 64:
            raise MessageValidationError(
                f"quote_id: length {len(self.quote_id)} exceeds max_len 64"
            )
        if len(self.order_id) > 64:
            raise MessageValidationError(
                f"order_id: length {len(self.order_id)} exceeds max_len 64"
            )
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if self.leg_side not in _QUOTE_LEG_LEG_SIDE_VALUES:
            raise MessageValidationError(
                f"leg_side: {self.leg_side!r} is not one of {_QUOTE_LEG_LEG_SIDE_VALUES!r}"
            )
        if self.qty < 0:
            raise MessageValidationError(f"qty: {self.qty!r} must be >= 0")
        if self.remaining < 0:
            raise MessageValidationError(f"remaining: {self.remaining!r} must be >= 0")
        if self.filled < 0:
            raise MessageValidationError(f"filled: {self.filled!r} must be >= 0")
        if len(self.status) > 32:
            raise MessageValidationError(
                f"status: length {len(self.status)} exceeds max_len 32"
            )
        if len(self.quote_status) > 32:
            raise MessageValidationError(
                f"quote_status: length {len(self.quote_status)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "QuoteLeg":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            quote_id=str(p["quote_id"]),
            order_id=str(p["order_id"]),
            symbol=str(p["symbol"]),
            leg_side=cast(QuoteLegLegSide, str(p["leg_side"])),
            price=None if p.get("price") is None else float(p["price"]),
            qty=int(p["qty"]),
            remaining=int(p["remaining"]),
            filled=int(p["filled"]),
            status=str(p["status"]),
            quote_status=str(p["quote_status"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "quote_id": self.quote_id,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "leg_side": self.leg_side,
            "qty": self.qty,
            "remaining": self.remaining,
            "filled": self.filled,
            "status": self.status,
            "quote_status": self.quote_status,
        }
        if self.price is not None:
            payload["price"] = self.price
        return payload


@dataclass(frozen=True, slots=True)
class QuoteLegSnapshot:
    """A leg as it stood when its quote left the book. No live qty/remaining here in
    the sense the name suggests -- these are the final values, recorded at
    removal, because once an order leaves the book its state is not available
    anywhere in the engine.
    """

    order_id: str
    qty: int  # unit: shares
    remaining: int  # unit: shares
    filled: int  # unit: shares
    status: str

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.order_id) > 64:
            raise MessageValidationError(
                f"order_id: length {len(self.order_id)} exceeds max_len 64"
            )
        if self.qty < 0:
            raise MessageValidationError(f"qty: {self.qty!r} must be >= 0")
        if self.remaining < 0:
            raise MessageValidationError(f"remaining: {self.remaining!r} must be >= 0")
        if self.filled < 0:
            raise MessageValidationError(f"filled: {self.filled!r} must be >= 0")
        if len(self.status) > 32:
            raise MessageValidationError(
                f"status: length {len(self.status)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "QuoteLegSnapshot":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            order_id=str(p["order_id"]),
            qty=int(p["qty"]),
            remaining=int(p["remaining"]),
            filled=int(p["filled"]),
            status=str(p["status"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "order_id": self.order_id,
            "qty": self.qty,
            "remaining": self.remaining,
            "filled": self.filled,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class RecentQuote:
    """One recently-removed quote, from the engine's bounded per-gateway inactivation
    history. A quote-level summary rather than a per-leg one. Does not survive an
    engine restart.
    """

    quote_id: str
    symbol: str
    bid_order_id: str
    ask_order_id: str
    quote_status: str
    reason: str
    removed_at_ns: int  # unit: epoch_nanos
    bid_leg: QuoteLegSnapshot | None = None
    ask_leg: QuoteLegSnapshot | None = None

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.quote_id) > 64:
            raise MessageValidationError(
                f"quote_id: length {len(self.quote_id)} exceeds max_len 64"
            )
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if len(self.bid_order_id) > 64:
            raise MessageValidationError(
                f"bid_order_id: length {len(self.bid_order_id)} exceeds max_len 64"
            )
        if len(self.ask_order_id) > 64:
            raise MessageValidationError(
                f"ask_order_id: length {len(self.ask_order_id)} exceeds max_len 64"
            )
        if len(self.quote_status) > 32:
            raise MessageValidationError(
                f"quote_status: length {len(self.quote_status)} exceeds max_len 32"
            )
        if len(self.reason) > 64:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 64"
            )
        if self.bid_leg is not None:
            self.bid_leg.validate()
        if self.ask_leg is not None:
            self.ask_leg.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "RecentQuote":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            quote_id=str(p["quote_id"]),
            symbol=str(p["symbol"]),
            bid_order_id=str(p["bid_order_id"]),
            ask_order_id=str(p["ask_order_id"]),
            quote_status=str(p["quote_status"]),
            reason=str(p["reason"]),
            removed_at_ns=int(p["removed_at_ns"]),
            bid_leg=(
                None
                if p.get("bid_leg") is None
                else QuoteLegSnapshot.from_dict(p["bid_leg"])
            ),
            ask_leg=(
                None
                if p.get("ask_leg") is None
                else QuoteLegSnapshot.from_dict(p["ask_leg"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "quote_id": self.quote_id,
            "symbol": self.symbol,
            "bid_order_id": self.bid_order_id,
            "ask_order_id": self.ask_order_id,
            "quote_status": self.quote_status,
            "reason": self.reason,
            "removed_at_ns": self.removed_at_ns,
            "bid_leg": None if self.bid_leg is None else self.bid_leg.to_dict(),
            "ask_leg": None if self.ask_leg is None else self.ask_leg.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class LiveCircuitBreaker:
    """A symbol's circuit breaker as it stands right now. The live counterpart to
    `ReferenceSymbol.circuit_breaker`, which is the configuration.
    """

    halted: bool
    reference_price: float | None = None  # unit: display_price
    trigger_price: float | None = None  # unit: display_price
    triggered_level: str | None = None
    expansion_index: int | None = None  # unit: dimensionless
    corridor_low: float | None = None  # unit: display_price
    corridor_high: float | None = None  # unit: display_price
    corridor_expansion: int | None = None  # unit: dimensionless
    resume_at_ns: int | None = None  # unit: epoch_nanos

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if self.triggered_level is not None:
            if len(self.triggered_level) > 32:
                raise MessageValidationError(
                    f"triggered_level: length {len(self.triggered_level)} exceeds max_len 32"
                )
        if self.expansion_index is not None:
            if self.expansion_index < 0:
                raise MessageValidationError(
                    f"expansion_index: {self.expansion_index!r} must be >= 0"
                )
        if self.corridor_expansion is not None:
            if self.corridor_expansion < 0:
                raise MessageValidationError(
                    f"corridor_expansion: {self.corridor_expansion!r} must be >= 0"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "LiveCircuitBreaker":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            halted=bool(p["halted"]),
            reference_price=(
                None
                if p.get("reference_price") is None
                else float(p["reference_price"])
            ),
            trigger_price=(
                None if p.get("trigger_price") is None else float(p["trigger_price"])
            ),
            triggered_level=(
                None if p.get("triggered_level") is None else str(p["triggered_level"])
            ),
            expansion_index=(
                None if p.get("expansion_index") is None else int(p["expansion_index"])
            ),
            corridor_low=(
                None if p.get("corridor_low") is None else float(p["corridor_low"])
            ),
            corridor_high=(
                None if p.get("corridor_high") is None else float(p["corridor_high"])
            ),
            corridor_expansion=(
                None
                if p.get("corridor_expansion") is None
                else int(p["corridor_expansion"])
            ),
            resume_at_ns=(
                None if p.get("resume_at_ns") is None else int(p["resume_at_ns"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "halted": self.halted,
            "reference_price": self.reference_price,
            "trigger_price": self.trigger_price,
            "triggered_level": self.triggered_level,
            "expansion_index": self.expansion_index,
            "corridor_low": self.corridor_low,
            "corridor_high": self.corridor_high,
            "corridor_expansion": self.corridor_expansion,
            "resume_at_ns": self.resume_at_ns,
        }


@dataclass(frozen=True, slots=True)
class SymbolRiskState:
    """One symbol's live risk state. Was a map entry keyed by symbol -- section
    19.2's shape for the twelfth time.
    """

    symbol: str
    collar_reference_price: float | None = None  # unit: display_price
    circuit_breaker: LiveCircuitBreaker | None = None

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if self.circuit_breaker is not None:
            self.circuit_breaker.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SymbolRiskState":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
            collar_reference_price=(
                None
                if p.get("collar_reference_price") is None
                else float(p["collar_reference_price"])
            ),
            circuit_breaker=(
                None
                if p.get("circuit_breaker") is None
                else LiveCircuitBreaker.from_dict(p["circuit_breaker"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "symbol": self.symbol,
        }
        if self.collar_reference_price is not None:
            payload["collar_reference_price"] = self.collar_reference_price
        if self.circuit_breaker is not None:
            payload["circuit_breaker"] = self.circuit_breaker.to_dict()
        return payload


@dataclass(frozen=True, slots=True)
class GatewayInfo:
    """One configured participant, and whether it is connected right now."""

    id: str
    role: str
    connected: bool
    description: str = ""

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.id) > 32:
            raise MessageValidationError(
                f"id: length {len(self.id)} exceeds max_len 32"
            )
        if len(self.role) > 32:
            raise MessageValidationError(
                f"role: length {len(self.role)} exceeds max_len 32"
            )
        if len(self.description) > 128:
            raise MessageValidationError(
                f"description: length {len(self.description)} exceeds max_len 128"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "GatewayInfo":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            id=str(p["id"]),
            role=str(p["role"]),
            description=str(p.get("description", "")),
            connected=bool(p["connected"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "id": self.id,
            "role": self.role,
            "description": self.description,
            "connected": self.connected,
        }


@dataclass(frozen=True, slots=True)
class SymbolVolume:
    """One instrument's traded volume so far today. Was a map entry keyed by symbol;
    the key is a field now, as everywhere else in this family.
    """

    symbol: str
    qty: int  # unit: shares
    value: float  # unit: money
    trades: int  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if self.qty < 0:
            raise MessageValidationError(f"qty: {self.qty!r} must be >= 0")
        if self.value < 0:
            raise MessageValidationError(f"value: {self.value!r} must be >= 0")
        if self.trades < 0:
            raise MessageValidationError(f"trades: {self.trades!r} must be >= 0")

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SymbolVolume":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            symbol=str(p["symbol"]),
            qty=int(p["qty"]),
            value=float(p["value"]),
            trades=int(p["trades"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "symbol": self.symbol,
            "qty": self.qty,
            "value": self.value,
            "trades": self.trades,
        }


TOPIC_GATEWAY_CONNECT = "system.gateway_connect"
_TOPIC_GATEWAY_CONNECT_BYTES = "system.gateway_connect".encode()


_GATEWAY_CONNECT_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Who is connecting. The engine's PULL socket is a boundary of its own -- section 22.3 -- so this is clamped on arrival.",
        "constraints": {"max_len": 32},
    },
)


@dataclass(frozen=True, slots=True)
class GatewayConnect:
    """Gateway to engine: authenticate this participant. Sent over PUSH/PULL rather
    than the pub bus; it carries a topic so the audit log can classify it
    alongside everything else.
    """

    gateway_id: str

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "GatewayConnect":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateway_id": self.gateway_id,
        }


def is_gateway_connect(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_GATEWAY_CONNECT


def make_gateway_connect(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = GatewayConnect.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_GATEWAY_CONNECT, obj.to_dict())


def make_gateway_connect_unchecked(
    *,
    gateway_id: str,
) -> list[bytes]:
    """Identical frames to ``make_gateway_connect``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_GATEWAY_CONNECT_BYTES,
        _msg.dumps(
            {
                "gateway_id": str(gateway_id),
            }
        ),
    ]


def parse_gateway_connect(frames: list[bytes]) -> "GatewayConnect":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = GatewayConnect.from_dict(payload)
    obj.validate()
    return obj


def describe_gateway_connect() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _GATEWAY_CONNECT_FIELDS


TOPIC_GATEWAY_AUTH = "system.gateway_auth.{gateway_id}"
PREFIX_GATEWAY_AUTH = "system.gateway_auth."
_GATEWAY_AUTH_RE = re.compile("system\\.gateway_auth\\.(?P<gateway_id>[^.]+)")


_GATEWAY_AUTH_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "accepted",
        "type": "bool",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "reason",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": 'Why it was rejected; "" on acceptance. Regime 1, because `GatewayAuthPayload.to_dict` has always emitted the key.',
        "constraints": {"max_len": 512},
    },
    {
        "name": "description",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "The gateway's configured display name. Regime 1, as above.",
        "constraints": {"max_len": 128},
    },
)


@dataclass(frozen=True, slots=True)
class GatewayAuth:
    """Engine to all subscribers: a participant's connection was accepted or
    rejected. The PUB-side answer to `system.gateway_connect`, and the widest-read
    message in this half -- five consumers structurally, and it is in
    `PRIVATE_PREFIXES`.

    `gateway_id` is in the topic AND the body, and every consumer reads it from the body
    -- `balf_gwy` dispatches on the topic suffix and then reads the payload's copy. So
    the field is listed in `include:` explicitly. Section 26.4: `include: all` means
    "every field except the topic parameters", and taking the default here would have
    dropped the key from the wire with `pm-msgen check` still passing.
    """

    gateway_id: str
    accepted: bool
    reason: str = ""
    description: str = ""

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.reason) > 512:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 512"
            )
        if len(self.description) > 128:
            raise MessageValidationError(
                f"description: length {len(self.description)} exceeds max_len 128"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "GatewayAuth":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
            accepted=bool(p["accepted"]),
            reason=str(p.get("reason", "")),
            description=str(p.get("description", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateway_id": self.gateway_id,
            "accepted": self.accepted,
            "reason": self.reason,
            "description": self.description,
        }


def topic_gateway_auth(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"system.gateway_auth.{gateway_id}"


def match_gateway_auth(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _GATEWAY_AUTH_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_gateway_auth(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = GatewayAuth.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_gateway_auth(obj.gateway_id), obj.to_dict())


def make_gateway_auth_unchecked(
    *,
    gateway_id: str,
    accepted: bool,
    reason: str = "",
    description: str = "",
) -> list[bytes]:
    """Identical frames to ``make_gateway_auth``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        topic_gateway_auth(gateway_id).encode(),
        _msg.dumps(
            {
                "gateway_id": str(gateway_id),
                "accepted": bool(accepted),
                "reason": str(reason),
                "description": str(description),
            }
        ),
    ]


def parse_gateway_auth(frames: list[bytes]) -> "GatewayAuth":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_gateway_auth(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_GATEWAY_AUTH!r}")
    payload = {**payload, "gateway_id": matched}
    obj = GatewayAuth.from_dict(payload)
    obj.validate()
    return obj


def describe_gateway_auth() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _GATEWAY_AUTH_FIELDS


TOPIC_GATEWAY_DISCONNECT = "system.gateway_disconnect"
_TOPIC_GATEWAY_DISCONNECT_BYTES = "system.gateway_disconnect".encode()


_GATEWAY_DISCONNECT_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "reason",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 512},
    },
)


@dataclass(frozen=True, slots=True)
class GatewayDisconnect:
    """Gateway to engine: I am leaving cleanly. PUSH/PULL, like `gateway_connect`;
    the engine republishes it as `gateway_bye` so PUB subscribers hear about it at
    all.
    """

    gateway_id: str
    reason: str = ""

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.reason) > 512:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 512"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "GatewayDisconnect":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
            reason=str(p.get("reason", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateway_id": self.gateway_id,
            "reason": self.reason,
        }


def is_gateway_disconnect(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_GATEWAY_DISCONNECT


def make_gateway_disconnect(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = GatewayDisconnect.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_GATEWAY_DISCONNECT, obj.to_dict())


def make_gateway_disconnect_unchecked(
    *,
    gateway_id: str,
    reason: str = "",
) -> list[bytes]:
    """Identical frames to ``make_gateway_disconnect``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_GATEWAY_DISCONNECT_BYTES,
        _msg.dumps(
            {
                "gateway_id": str(gateway_id),
                "reason": str(reason),
            }
        ),
    ]


def parse_gateway_disconnect(frames: list[bytes]) -> "GatewayDisconnect":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = GatewayDisconnect.from_dict(payload)
    obj.validate()
    return obj


def describe_gateway_disconnect() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _GATEWAY_DISCONNECT_FIELDS


TOPIC_GATEWAY_BYE = "system.gateway_bye.{gateway_id}"
PREFIX_GATEWAY_BYE = "system.gateway_bye."
_GATEWAY_BYE_RE = re.compile("system\\.gateway_bye\\.(?P<gateway_id>[^.]+)")


_GATEWAY_BYE_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "reason",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "",
        "constraints": {"max_len": 512},
    },
)


@dataclass(frozen=True, slots=True)
class GatewayBye:
    """Engine to all subscribers: a participant has disconnected. The PUB-side
    counterpart to `gateway_auth`. The inbound `system.gateway_disconnect` is a
    PULL message and never reaches subscribers, so without this broadcast clearing
    could not close the matching session.

    `gateway_id` is in the topic and the body, and `clearing` -- the only structural
    reader -- takes it from the body. Enumerated for the same reason as `gateway_auth`.
    """

    gateway_id: str
    reason: str = ""

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.reason) > 512:
            raise MessageValidationError(
                f"reason: length {len(self.reason)} exceeds max_len 512"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "GatewayBye":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
            reason=str(p.get("reason", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateway_id": self.gateway_id,
            "reason": self.reason,
        }


def topic_gateway_bye(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"system.gateway_bye.{gateway_id}"


def match_gateway_bye(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _GATEWAY_BYE_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_gateway_bye(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = GatewayBye.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_gateway_bye(obj.gateway_id), obj.to_dict())


def make_gateway_bye_unchecked(
    *,
    gateway_id: str,
    reason: str = "",
) -> list[bytes]:
    """Identical frames to ``make_gateway_bye``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        topic_gateway_bye(gateway_id).encode(),
        _msg.dumps(
            {
                "gateway_id": str(gateway_id),
                "reason": str(reason),
            }
        ),
    ]


def parse_gateway_bye(frames: list[bytes]) -> "GatewayBye":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_gateway_bye(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_GATEWAY_BYE!r}")
    payload = {**payload, "gateway_id": matched}
    obj = GatewayBye.from_dict(payload)
    obj.validate()
    return obj


def describe_gateway_bye() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _GATEWAY_BYE_FIELDS


TOPIC_EOD = "system.eod"
_TOPIC_EOD_BYTES = "system.eod".encode()


_EOD_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "books",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "One per instrument the engine had a book for, unordered.",
    },
)


@dataclass(frozen=True, slots=True)
class Eod:
    """Engine to all subscribers, once, before shutdown: the closing book of every
    instrument. Four consumers -- clearing, index, stats and the RALF gateway --
    which is the widest fan-out in this half, and the reason the record is
    declared rather than left to a `from_dict`.

    A broadcast with no request: nothing asks for end of day, the engine announces it.
    That is why it has no `_request` sibling and why it is in this half rather than
    6.1f's request/reply pairs.
    """

    books: list[EodBook]

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        for books_item in self.books:
            books_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "Eod":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            books=[EodBook.from_dict(item) for item in p["books"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "books": [item.to_dict() for item in self.books],
        }


def is_eod(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_EOD


def make_eod(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = Eod.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_EOD, obj.to_dict())


def parse_eod(frames: list[bytes]) -> "Eod":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = Eod.from_dict(payload)
    obj.validate()
    return obj


def describe_eod() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _EOD_FIELDS


TOPIC_SYMBOLS_REQUEST = "system.symbols_request"
_TOPIC_SYMBOLS_REQUEST_BYTES = "system.symbols_request".encode()


_SYMBOLS_REQUEST_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Both the correlation key for the reply topic and the identity the market-maker fields are resolved against.",
        "constraints": {"max_len": 32},
    },
)


@dataclass(frozen=True, slots=True)
class SymbolsRequest:
    """Caller to engine: which instruments are tradable, and on what terms for me."""

    gateway_id: str

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SymbolsRequest":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateway_id": self.gateway_id,
        }


def is_symbols_request(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_SYMBOLS_REQUEST


def make_symbols_request(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = SymbolsRequest.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_SYMBOLS_REQUEST, obj.to_dict())


def make_symbols_request_unchecked(
    *,
    gateway_id: str,
) -> list[bytes]:
    """Identical frames to ``make_symbols_request``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_SYMBOLS_REQUEST_BYTES,
        _msg.dumps(
            {
                "gateway_id": str(gateway_id),
            }
        ),
    ]


def parse_symbols_request(frames: list[bytes]) -> "SymbolsRequest":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = SymbolsRequest.from_dict(payload)
    obj.validate()
    return obj


def describe_symbols_request() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _SYMBOLS_REQUEST_FIELDS


TOPIC_SYMBOLS = "system.symbols.{gateway_id}"
PREFIX_SYMBOLS = "system.symbols."
_SYMBOLS_RE = re.compile("system\\.symbols\\.(?P<gateway_id>[^.]+)")


_SYMBOLS_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Topic-only; dropped from the body by the default projection.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "symbols",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "Sorted by symbol, as the engine iterates its books.",
    },
)


@dataclass(frozen=True, slots=True)
class Symbols:
    """Engine to caller: the tradable instruments, with the tick scale and this
    caller's market-making terms for each.

    The default projection is right here: `gateway_id` names the caller in the topic and
    has never been in the body. Verified against the producer rather than assumed --
    section 26.4 is the case where assuming cost five wires a field. One collection, not
    two. The old payload carried `symbols` as a list of strings beside `symbol_meta` as
    a map from those same strings to their metadata, built in the same loop; nine
    readers joined them back together. The join is gone.
    """

    gateway_id: str
    symbols: list[SymbolInfo]

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        for symbols_item in self.symbols:
            symbols_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "Symbols":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            symbols=[SymbolInfo.from_dict(item) for item in p["symbols"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "symbols": [item.to_dict() for item in self.symbols],
        }


def topic_symbols(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"system.symbols.{gateway_id}"


def match_symbols(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _SYMBOLS_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_symbols(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = Symbols.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_symbols(obj.gateway_id), obj.to_dict())


def parse_symbols(frames: list[bytes]) -> "Symbols":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_symbols(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_SYMBOLS!r}")
    payload = {**payload, "gateway_id": matched}
    obj = Symbols.from_dict(payload)
    obj.validate()
    return obj


def describe_symbols() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _SYMBOLS_FIELDS


TOPIC_REFERENCE_REQUEST = "system.reference_request"
_TOPIC_REFERENCE_REQUEST_BYTES = "system.reference_request".encode()


_REFERENCE_REQUEST_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Correlation key only. The API gateway passes an API key here for read-only callers, since the bundle does not vary by caller and this only has to be unique.",
        "constraints": {"max_len": 32},
    },
)


@dataclass(frozen=True, slots=True)
class ReferenceRequest:
    """Any caller to engine: the compiled reference-data bundle. Static configuration
    only -- nothing that changes during a session.
    """

    gateway_id: str

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "ReferenceRequest":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateway_id": self.gateway_id,
        }


def is_reference_request(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_REFERENCE_REQUEST


def make_reference_request(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = ReferenceRequest.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_REFERENCE_REQUEST, obj.to_dict())


def make_reference_request_unchecked(
    *,
    gateway_id: str,
) -> list[bytes]:
    """Identical frames to ``make_reference_request``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_REFERENCE_REQUEST_BYTES,
        _msg.dumps(
            {
                "gateway_id": str(gateway_id),
            }
        ),
    ]


def parse_reference_request(frames: list[bytes]) -> "ReferenceRequest":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = ReferenceRequest.from_dict(payload)
    obj.validate()
    return obj


def describe_reference_request() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _REFERENCE_REQUEST_FIELDS


TOPIC_REFERENCE = "system.reference.{gateway_id}"
PREFIX_REFERENCE = "system.reference."
_REFERENCE_RE = re.compile("system\\.reference\\.(?P<gateway_id>[^.]+)")


_REFERENCE_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Topic-only; dropped from the body by the default projection. Bounded at 64 rather than 32 because the API gateway passes an API key here for read-only callers.",
        "constraints": {"max_len": 64},
    },
    {
        "name": "symbols",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "Sorted by symbol. Was a map keyed by it.",
    },
    {
        "name": "risk",
        "type": "nested",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "indexes",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "Already a list of records before this phase.",
    },
    {
        "name": "schedule",
        "type": "nested",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "config_version",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "Truncated SHA-256 of the bundle. Null before a config is loaded, which is the only remaining difference between the two states the old two-shape reply used to distinguish. Regime 2: every consumer compares it, so the key has to be there to compare.",
        "constraints": {"max_len": 64},
    },
)


@dataclass(frozen=True, slots=True)
class Reference:
    """Engine to caller: every piece of static venue configuration in one round trip
    -- tick scales, risk levels, circuit-breaker ladders, index definitions and
    the calendar -- with a hash that changes when any of it does.

    The whole payload was a `dict[str, Any]` passed to `encode` unread. One producer
    builds it -- `_rebuild_reference_cache` -- with five fixed top-level keys, so it was
    a record nobody had written down. ONE SHAPE, ALWAYS. Before an engine config is
    loaded the reply used to be `{"config_version": null}` and nothing else: a second
    payload shape for the same topic, which every slicing endpoint compensated for with
    a `.get(key, {})` default. The bundle is now always complete, with empty collections
    and a null version, and the compensating defaults go with it. REST-VISIBLE.
    `api_gateway/routers/reference.py` returns slices of this bundle verbatim, so
    `reference.symbols` becoming a list of records and `reference.schedule` gaining a
    level of nesting change `GET /reference/symbols` and `GET /reference/schedule`.
    Sanctioned, and the better JSON in both cases -- a list of objects each carrying its
    own `symbol` is what a client can iterate without knowing the keys. `260-api-
    gateway.md` moves with it.
    """

    gateway_id: str
    symbols: list[ReferenceSymbol]
    risk: ReferenceRisk
    indexes: list[IndexDefinition]
    schedule: ReferenceSchedule
    config_version: str | None = None

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 64:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 64"
            )
        for symbols_item in self.symbols:
            symbols_item.validate()
        self.risk.validate()
        for indexes_item in self.indexes:
            indexes_item.validate()
        self.schedule.validate()
        if self.config_version is not None:
            if len(self.config_version) > 64:
                raise MessageValidationError(
                    f"config_version: length {len(self.config_version)} exceeds max_len 64"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "Reference":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            symbols=[ReferenceSymbol.from_dict(item) for item in p["symbols"]],
            risk=ReferenceRisk.from_dict(p["risk"]),
            indexes=[IndexDefinition.from_dict(item) for item in p["indexes"]],
            schedule=ReferenceSchedule.from_dict(p["schedule"]),
            config_version=(
                None if p.get("config_version") is None else str(p["config_version"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "symbols": [item.to_dict() for item in self.symbols],
            "risk": self.risk.to_dict(),
            "indexes": [item.to_dict() for item in self.indexes],
            "schedule": self.schedule.to_dict(),
            "config_version": self.config_version,
        }


def topic_reference(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"system.reference.{gateway_id}"


def match_reference(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _REFERENCE_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_reference(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = Reference.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_reference(obj.gateway_id), obj.to_dict())


def parse_reference(frames: list[bytes]) -> "Reference":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_reference(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_REFERENCE!r}")
    payload = {**payload, "gateway_id": matched}
    obj = Reference.from_dict(payload)
    obj.validate()
    return obj


def describe_reference() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _REFERENCE_FIELDS


TOPIC_REFERENCE_RELOAD = "system.reference_reload"
_TOPIC_REFERENCE_RELOAD_BYTES = "system.reference_reload".encode()


_REFERENCE_RELOAD_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "command_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Correlated by the ack. Read off the wire unclamped before this phase, and quoted straight into a bounded ack field -- section 22.3's silent non-answer, four reply paths.",
        "constraints": {"max_len": 64},
    },
)


@dataclass(frozen=True, slots=True)
class ReferenceReload:
    """ADMIN to engine: re-read static reference data from disk. Deliberately
    narrower than a startup load -- it never re-seeds quotes, creates or removes
    books, or touches session and halt state, so a reload that changed the symbol
    set is rejected rather than partially applied.
    """

    gateway_id: str
    command_id: str

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.command_id) > 64:
            raise MessageValidationError(
                f"command_id: length {len(self.command_id)} exceeds max_len 64"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "ReferenceReload":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
            command_id=str(p["command_id"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateway_id": self.gateway_id,
            "command_id": self.command_id,
        }


def is_reference_reload(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_REFERENCE_RELOAD


def make_reference_reload(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = ReferenceReload.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_REFERENCE_RELOAD, obj.to_dict())


def make_reference_reload_unchecked(
    *,
    gateway_id: str,
    command_id: str,
) -> list[bytes]:
    """Identical frames to ``make_reference_reload``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_REFERENCE_RELOAD_BYTES,
        _msg.dumps(
            {
                "gateway_id": str(gateway_id),
                "command_id": str(command_id),
            }
        ),
    ]


def parse_reference_reload(frames: list[bytes]) -> "ReferenceReload":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = ReferenceReload.from_dict(payload)
    obj.validate()
    return obj


def describe_reference_reload() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _REFERENCE_RELOAD_FIELDS


TOPIC_REFERENCE_RELOAD_ACK = "system.reference_reload_ack.{gateway_id}"
PREFIX_REFERENCE_RELOAD_ACK = "system.reference_reload_ack."
_REFERENCE_RELOAD_ACK_RE = re.compile(
    "system\\.reference_reload_ack\\.(?P<gateway_id>[^.]+)"
)


_REFERENCE_RELOAD_ACK_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Topic-only; dropped from the body by the default projection.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "command_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 64},
    },
    {
        "name": "accepted",
        "type": "bool",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "config_version",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "Present on acceptance.",
        "constraints": {"max_len": 64},
    },
    {
        "name": "reason",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": "Present on rejection.",
        "constraints": {"max_len": 512},
    },
)


@dataclass(frozen=True, slots=True)
class ReferenceReloadAck:
    """Engine to ADMIN: the reload verdict, and the new configuration hash when it
    took.

    The default projection is right: `gateway_id` is topic-only and has never been in
    the body. `config_version` and `reason` are the two halves of the verdict and never
    travel together -- an accepted reload carries the version, a rejected one carries
    the reason.
    """

    gateway_id: str
    command_id: str
    accepted: bool
    config_version: str | None = None
    reason: str | None = None

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.command_id) > 64:
            raise MessageValidationError(
                f"command_id: length {len(self.command_id)} exceeds max_len 64"
            )
        if self.config_version is not None:
            if len(self.config_version) > 64:
                raise MessageValidationError(
                    f"config_version: length {len(self.config_version)} exceeds max_len 64"
                )
        if self.reason is not None:
            if len(self.reason) > 512:
                raise MessageValidationError(
                    f"reason: length {len(self.reason)} exceeds max_len 512"
                )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "ReferenceReloadAck":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            command_id=str(p["command_id"]),
            accepted=bool(p["accepted"]),
            config_version=(
                None if p.get("config_version") is None else str(p["config_version"])
            ),
            reason=None if p.get("reason") is None else str(p["reason"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        payload: dict[str, Any] = {
            "command_id": self.command_id,
            "accepted": self.accepted,
        }
        if self.config_version is not None:
            payload["config_version"] = self.config_version
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload


def topic_reference_reload_ack(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"system.reference_reload_ack.{gateway_id}"


def match_reference_reload_ack(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _REFERENCE_RELOAD_ACK_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_reference_reload_ack(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = ReferenceReloadAck.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_reference_reload_ack(obj.gateway_id), obj.to_dict())


def make_reference_reload_ack_unchecked(
    *,
    gateway_id: str,
    command_id: str,
    accepted: bool,
    config_version: str | None = None,
    reason: str | None = None,
) -> list[bytes]:
    """Identical frames to ``make_reference_reload_ack``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    payload: dict[str, Any] = {
        "command_id": str(command_id),
        "accepted": bool(accepted),
    }
    if config_version is not None:
        payload["config_version"] = str(config_version)
    if reason is not None:
        payload["reason"] = str(reason)
    return [
        topic_reference_reload_ack(gateway_id).encode(),
        _msg.dumps(payload),
    ]


def parse_reference_reload_ack(frames: list[bytes]) -> "ReferenceReloadAck":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_reference_reload_ack(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_REFERENCE_RELOAD_ACK!r}"
        )
    payload = {**payload, "gateway_id": matched}
    obj = ReferenceReloadAck.from_dict(payload)
    obj.validate()
    return obj


def describe_reference_reload_ack() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _REFERENCE_RELOAD_ACK_FIELDS


TOPIC_SESSION_STATE_REQUEST = "system.session_state_request"
_TOPIC_SESSION_STATE_REQUEST_BYTES = "system.session_state_request".encode()


_SESSION_STATE_REQUEST_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
)


@dataclass(frozen=True, slots=True)
class SessionStateRequest:
    """Caller to engine: what session are we in, without advancing it. The scheduler
    is the dominant producer -- it asks rather than assuming, because it is not
    the only thing that can move the session.
    """

    gateway_id: str

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SessionStateRequest":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateway_id": self.gateway_id,
        }


def is_session_state_request(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_SESSION_STATE_REQUEST


def make_session_state_request(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = SessionStateRequest.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_SESSION_STATE_REQUEST, obj.to_dict())


def make_session_state_request_unchecked(
    *,
    gateway_id: str,
) -> list[bytes]:
    """Identical frames to ``make_session_state_request``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_SESSION_STATE_REQUEST_BYTES,
        _msg.dumps(
            {
                "gateway_id": str(gateway_id),
            }
        ),
    ]


def parse_session_state_request(frames: list[bytes]) -> "SessionStateRequest":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = SessionStateRequest.from_dict(payload)
    obj.validate()
    return obj


def describe_session_state_request() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _SESSION_STATE_REQUEST_FIELDS


TOPIC_SESSION_STATUS = "system.session_status.{gateway_id}"
PREFIX_SESSION_STATUS = "system.session_status."
_SESSION_STATUS_RE = re.compile("system\\.session_status\\.(?P<gateway_id>[^.]+)")


_SESSION_STATUS_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Topic-only; dropped from the body by the default projection.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "state",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Same values as `session.state.state`.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "sessions_enabled",
        "type": "bool",
        "unit": None,
        "required": True,
        "doc": "False when the deployment runs continuously with no session schedule at all, which makes `state` advisory.",
    },
)


@dataclass(frozen=True, slots=True)
class SessionStatus:
    """Engine to caller: the current session state, on request. The polled answer to
    the `session.state` broadcast, for a caller that has just started and missed
    the last transition.

    Default projection: `gateway_id` is topic-only. `state` is a plain bounded string
    rather than an enum, matching `session.state.state` -- the value set lives in the
    session machine, and enumerating it in two specs would be two places to update.
    """

    gateway_id: str
    state: str
    sessions_enabled: bool

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.state) > 32:
            raise MessageValidationError(
                f"state: length {len(self.state)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SessionStatus":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            state=str(p["state"]),
            sessions_enabled=bool(p["sessions_enabled"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "state": self.state,
            "sessions_enabled": self.sessions_enabled,
        }


def topic_session_status(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"system.session_status.{gateway_id}"


def match_session_status(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _SESSION_STATUS_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_session_status(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = SessionStatus.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_session_status(obj.gateway_id), obj.to_dict())


def make_session_status_unchecked(
    *,
    gateway_id: str,
    state: str,
    sessions_enabled: bool,
) -> list[bytes]:
    """Identical frames to ``make_session_status``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        topic_session_status(gateway_id).encode(),
        _msg.dumps(
            {
                "state": str(state),
                "sessions_enabled": bool(sessions_enabled),
            }
        ),
    ]


def parse_session_status(frames: list[bytes]) -> "SessionStatus":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_session_status(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_SESSION_STATUS!r}")
    payload = {**payload, "gateway_id": matched}
    obj = SessionStatus.from_dict(payload)
    obj.validate()
    return obj


def describe_session_status() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _SESSION_STATUS_FIELDS


TOPIC_SESSION_SCHEDULE_REQUEST = "system.session_schedule_request"
_TOPIC_SESSION_SCHEDULE_REQUEST_BYTES = "system.session_schedule_request".encode()


_SESSION_SCHEDULE_REQUEST_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
)


@dataclass(frozen=True, slots=True)
class SessionScheduleRequest:
    """Operator to engine: the configured session schedule."""

    gateway_id: str

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SessionScheduleRequest":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateway_id": self.gateway_id,
        }


def is_session_schedule_request(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_SESSION_SCHEDULE_REQUEST


def make_session_schedule_request(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = SessionScheduleRequest.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_SESSION_SCHEDULE_REQUEST, obj.to_dict())


def make_session_schedule_request_unchecked(
    *,
    gateway_id: str,
) -> list[bytes]:
    """Identical frames to ``make_session_schedule_request``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_SESSION_SCHEDULE_REQUEST_BYTES,
        _msg.dumps(
            {
                "gateway_id": str(gateway_id),
            }
        ),
    ]


def parse_session_schedule_request(frames: list[bytes]) -> "SessionScheduleRequest":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = SessionScheduleRequest.from_dict(payload)
    obj.validate()
    return obj


def describe_session_schedule_request() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _SESSION_SCHEDULE_REQUEST_FIELDS


TOPIC_SESSION_SCHEDULE = "system.session_schedule.{gateway_id}"
PREFIX_SESSION_SCHEDULE = "system.session_schedule."
_SESSION_SCHEDULE_RE = re.compile("system\\.session_schedule\\.(?P<gateway_id>[^.]+)")


_SESSION_SCHEDULE_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Topic-only; dropped from the body by the default projection.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "sessions_enabled",
        "type": "bool",
        "unit": None,
        "required": True,
        "doc": "",
    },
    {
        "name": "schedule",
        "type": "nested",
        "unit": None,
        "required": False,
        "doc": "Null when no `schedule:` block is configured.",
    },
)


@dataclass(frozen=True, slots=True)
class SessionSchedule:
    """Engine to operator: the trading day's clock as configured. The same
    `SessionTimes` record `system.reference` carries, which is what forced these
    two topics into one phase.

    Default projection: `gateway_id` is topic-only. Both readers -- `commands/client.py`
    and `GET /admin/schedule` -- pass the payload through to a caller without touching a
    key, so nothing structural constrains the presence regime here; `schedule` is regime
    2 to match the copy inside `ReferenceSchedule` rather than because a reader needs
    it. It was `schedule or {}` before, so an unconfigured venue sent an empty object
    where it now sends null.
    """

    gateway_id: str
    sessions_enabled: bool
    schedule: SessionTimes | None = None

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if self.schedule is not None:
            self.schedule.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "SessionSchedule":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            sessions_enabled=bool(p["sessions_enabled"]),
            schedule=(
                None
                if p.get("schedule") is None
                else SessionTimes.from_dict(p["schedule"])
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "sessions_enabled": self.sessions_enabled,
            "schedule": None if self.schedule is None else self.schedule.to_dict(),
        }


def topic_session_schedule(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"system.session_schedule.{gateway_id}"


def match_session_schedule(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _SESSION_SCHEDULE_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_session_schedule(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = SessionSchedule.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_session_schedule(obj.gateway_id), obj.to_dict())


def parse_session_schedule(frames: list[bytes]) -> "SessionSchedule":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_session_schedule(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_SESSION_SCHEDULE!r}"
        )
    payload = {**payload, "gateway_id": matched}
    obj = SessionSchedule.from_dict(payload)
    obj.validate()
    return obj


def describe_session_schedule() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _SESSION_SCHEDULE_FIELDS


TOPIC_HALT_STATUS_REQUEST = "system.halt_status_request"
_TOPIC_HALT_STATUS_REQUEST_BYTES = "system.halt_status_request".encode()


_HALT_STATUS_REQUEST_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
)


@dataclass(frozen=True, slots=True)
class HaltStatusRequest:
    """Any process to engine: which instruments are halted now."""

    gateway_id: str

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "HaltStatusRequest":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateway_id": self.gateway_id,
        }


def is_halt_status_request(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_HALT_STATUS_REQUEST


def make_halt_status_request(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = HaltStatusRequest.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_HALT_STATUS_REQUEST, obj.to_dict())


def make_halt_status_request_unchecked(
    *,
    gateway_id: str,
) -> list[bytes]:
    """Identical frames to ``make_halt_status_request``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_HALT_STATUS_REQUEST_BYTES,
        _msg.dumps(
            {
                "gateway_id": str(gateway_id),
            }
        ),
    ]


def parse_halt_status_request(frames: list[bytes]) -> "HaltStatusRequest":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = HaltStatusRequest.from_dict(payload)
    obj.validate()
    return obj


def describe_halt_status_request() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _HALT_STATUS_REQUEST_FIELDS


TOPIC_HALT_STATUS = "system.halt_status.{gateway_id}"
PREFIX_HALT_STATUS = "system.halt_status."
_HALT_STATUS_RE = re.compile("system\\.halt_status\\.(?P<gateway_id>[^.]+)")


_HALT_STATUS_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Topic-only; dropped by the default projection.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "halted",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class HaltStatus:
    """Engine to caller: every currently-halted instrument, with the breaker state
    behind it where a breaker is what halted it. The polled answer to the
    `circuit_breaker.halt` broadcast, for a caller that has just started and
    missed it.

    An empty list means nothing is halted, which is the normal reply. The three optional
    fields are present together or not at all: an ADMIN halt sets the flag with no
    breaker behind it.
    """

    gateway_id: str
    halted: list[HaltedSymbol]

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        for halted_item in self.halted:
            halted_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "HaltStatus":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            halted=[HaltedSymbol.from_dict(item) for item in p["halted"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "halted": [item.to_dict() for item in self.halted],
        }


def topic_halt_status(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"system.halt_status.{gateway_id}"


def match_halt_status(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _HALT_STATUS_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_halt_status(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = HaltStatus.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_halt_status(obj.gateway_id), obj.to_dict())


def parse_halt_status(frames: list[bytes]) -> "HaltStatus":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_halt_status(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_HALT_STATUS!r}")
    payload = {**payload, "gateway_id": matched}
    obj = HaltStatus.from_dict(payload)
    obj.validate()
    return obj


def describe_halt_status() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _HALT_STATUS_FIELDS


TOPIC_POSITION_REQUEST = "system.position_request"
_TOPIC_POSITION_REQUEST_BYTES = "system.position_request".encode()


_POSITION_REQUEST_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Both the correlation key and the account being asked about. A gateway can only ask about itself: the handler answers from `_gateway_positions[gateway_id]` and nothing else.",
        "constraints": {"max_len": 32},
    },
)


@dataclass(frozen=True, slots=True)
class PositionRequest:
    """Gateway to engine: what am I holding."""

    gateway_id: str

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "PositionRequest":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateway_id": self.gateway_id,
        }


def is_position_request(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_POSITION_REQUEST


def make_position_request(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = PositionRequest.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_POSITION_REQUEST, obj.to_dict())


def make_position_request_unchecked(
    *,
    gateway_id: str,
) -> list[bytes]:
    """Identical frames to ``make_position_request``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_POSITION_REQUEST_BYTES,
        _msg.dumps(
            {
                "gateway_id": str(gateway_id),
            }
        ),
    ]


def parse_position_request(frames: list[bytes]) -> "PositionRequest":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = PositionRequest.from_dict(payload)
    obj.validate()
    return obj


def describe_position_request() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _POSITION_REQUEST_FIELDS


TOPIC_POSITION_SNAPSHOT = "system.position_snapshot.{gateway_id}"
PREFIX_POSITION_SNAPSHOT = "system.position_snapshot."
_POSITION_SNAPSHOT_RE = re.compile("system\\.position_snapshot\\.(?P<gateway_id>[^.]+)")


_POSITION_SNAPSHOT_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Topic-only; dropped by the default projection.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "positions",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    """Engine to gateway: per-symbol net position and average cost, for the asking
    gateway only.

    An unauthenticated or unknown gateway gets an empty list rather than a rejection --
    flat and not-a-gateway are the same answer here, which is deliberate: the
    alternative tells an unauthenticated caller whether an id exists. This pair has no
    consumer in `src/` at all. It is exercised only by
    `tests/test_position_snapshot.py`, which is section 27.4's shape -- a capability
    exercised only by its own tests. It is specified rather than removed because unlike
    `drop_copy.replay_request` it is fully implemented on both sides and reachable by
    any gateway; what it lacks is a caller, not an implementation. Recorded here so the
    next phase to touch it knows the difference.
    """

    gateway_id: str
    positions: list[Position]

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        for positions_item in self.positions:
            positions_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "PositionSnapshot":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            positions=[Position.from_dict(item) for item in p["positions"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "positions": [item.to_dict() for item in self.positions],
        }


def topic_position_snapshot(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"system.position_snapshot.{gateway_id}"


def match_position_snapshot(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _POSITION_SNAPSHOT_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_position_snapshot(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = PositionSnapshot.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_position_snapshot(obj.gateway_id), obj.to_dict())


def parse_position_snapshot(frames: list[bytes]) -> "PositionSnapshot":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_position_snapshot(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_POSITION_SNAPSHOT!r}"
        )
    payload = {**payload, "gateway_id": matched}
    obj = PositionSnapshot.from_dict(payload)
    obj.validate()
    return obj


def describe_position_snapshot() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _POSITION_SNAPSHOT_FIELDS


TOPIC_QUOTE_BOOTSTRAP_REQUEST = "system.quote_bootstrap_request"
_TOPIC_QUOTE_BOOTSTRAP_REQUEST_BYTES = "system.quote_bootstrap_request".encode()


_QUOTE_BOOTSTRAP_REQUEST_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": 'Narrows the reply to one instrument. "" means all.',
        "constraints": {"max_len": 16},
    },
)


@dataclass(frozen=True, slots=True)
class QuoteBootstrapRequest:
    """Market maker to engine, on reconnect: what quotes do I already have resting.
    Without it a bot cannot tell a fresh start from a reconnect and will quote
    into its own orders.
    """

    gateway_id: str
    symbol: str = ""

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "QuoteBootstrapRequest":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
            symbol=str(p.get("symbol", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateway_id": self.gateway_id,
            "symbol": self.symbol,
        }


def is_quote_bootstrap_request(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_QUOTE_BOOTSTRAP_REQUEST


def make_quote_bootstrap_request(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = QuoteBootstrapRequest.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_QUOTE_BOOTSTRAP_REQUEST, obj.to_dict())


def make_quote_bootstrap_request_unchecked(
    *,
    gateway_id: str,
    symbol: str = "",
) -> list[bytes]:
    """Identical frames to ``make_quote_bootstrap_request``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_QUOTE_BOOTSTRAP_REQUEST_BYTES,
        _msg.dumps(
            {
                "gateway_id": str(gateway_id),
                "symbol": str(symbol),
            }
        ),
    ]


def parse_quote_bootstrap_request(frames: list[bytes]) -> "QuoteBootstrapRequest":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = QuoteBootstrapRequest.from_dict(payload)
    obj.validate()
    return obj


def describe_quote_bootstrap_request() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _QUOTE_BOOTSTRAP_REQUEST_FIELDS


TOPIC_QUOTE_BOOTSTRAP = "system.quote_bootstrap.{gateway_id}"
PREFIX_QUOTE_BOOTSTRAP = "system.quote_bootstrap."
_QUOTE_BOOTSTRAP_RE = re.compile("system\\.quote_bootstrap\\.(?P<gateway_id>[^.]+)")


_QUOTE_BOOTSTRAP_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Topic-only; dropped by the default projection.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "quotes",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "",
    },
)


@dataclass(frozen=True, slots=True)
class QuoteBootstrap:
    """Engine to market maker: the active quotes it already holds."""

    gateway_id: str
    quotes: list[ActiveQuote]

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        for quotes_item in self.quotes:
            quotes_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "QuoteBootstrap":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            quotes=[ActiveQuote.from_dict(item) for item in p["quotes"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "quotes": [item.to_dict() for item in self.quotes],
        }


def topic_quote_bootstrap(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"system.quote_bootstrap.{gateway_id}"


def match_quote_bootstrap(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _QUOTE_BOOTSTRAP_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_quote_bootstrap(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = QuoteBootstrap.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_quote_bootstrap(obj.gateway_id), obj.to_dict())


def parse_quote_bootstrap(frames: list[bytes]) -> "QuoteBootstrap":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_quote_bootstrap(topic)
    if matched is None:
        raise MessageValidationError(
            f"topic {topic!r} is not {TOPIC_QUOTE_BOOTSTRAP!r}"
        )
    payload = {**payload, "gateway_id": matched}
    obj = QuoteBootstrap.from_dict(payload)
    obj.validate()
    return obj


def describe_quote_bootstrap() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _QUOTE_BOOTSTRAP_FIELDS


TOPIC_QUOTE_LEGS_REQUEST = "system.quote_legs_request"
_TOPIC_QUOTE_LEGS_REQUEST_BYTES = "system.quote_legs_request".encode()
_QUOTE_LEGS_REQUEST_SHOW_VALUES = ("ACTIVE", "RECENT", "ALL")
QuoteLegsRequestShow = Literal["ACTIVE", "RECENT", "ALL"]


_QUOTE_LEGS_REQUEST_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
    {
        "name": "symbol",
        "type": "string",
        "unit": None,
        "required": False,
        "doc": 'Narrows the reply to one instrument. "" means all.',
        "constraints": {"max_len": 16},
    },
    {
        "name": "show",
        "type": "enum",
        "unit": None,
        "required": False,
        "doc": "Which half to return. `ACTIVE` is live legs, `RECENT` is the removal history, `ALL` is both. Enumerated rather than a free string because the handler branches on exactly these three and treats anything else as `ACTIVE` -- a typo currently answers, quietly, with the wrong half.",
        "values": _QUOTE_LEGS_REQUEST_SHOW_VALUES,
    },
)


@dataclass(frozen=True, slots=True)
class QuoteLegsRequest:
    """Operator or market maker to engine: the per-leg detail behind this gateway's
    quotes, live and recently removed. What `QLEGS` asks for.
    """

    gateway_id: str
    symbol: str = ""
    show: QuoteLegsRequestShow = "ALL"

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        if len(self.symbol) > 16:
            raise MessageValidationError(
                f"symbol: length {len(self.symbol)} exceeds max_len 16"
            )
        if self.show not in _QUOTE_LEGS_REQUEST_SHOW_VALUES:
            raise MessageValidationError(
                f"show: {self.show!r} is not one of {_QUOTE_LEGS_REQUEST_SHOW_VALUES!r}"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "QuoteLegsRequest":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
            symbol=str(p.get("symbol", "")),
            show=cast(QuoteLegsRequestShow, str(p.get("show", "ALL"))),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateway_id": self.gateway_id,
            "symbol": self.symbol,
            "show": self.show,
        }


def is_quote_legs_request(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_QUOTE_LEGS_REQUEST


def make_quote_legs_request(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = QuoteLegsRequest.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_QUOTE_LEGS_REQUEST, obj.to_dict())


def make_quote_legs_request_unchecked(
    *,
    gateway_id: str,
    symbol: str = "",
    show: QuoteLegsRequestShow = "ALL",
) -> list[bytes]:
    """Identical frames to ``make_quote_legs_request``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_QUOTE_LEGS_REQUEST_BYTES,
        _msg.dumps(
            {
                "gateway_id": str(gateway_id),
                "symbol": str(symbol),
                "show": str(show),
            }
        ),
    ]


def parse_quote_legs_request(frames: list[bytes]) -> "QuoteLegsRequest":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = QuoteLegsRequest.from_dict(payload)
    obj.validate()
    return obj


def describe_quote_legs_request() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _QUOTE_LEGS_REQUEST_FIELDS


TOPIC_QUOTE_LEGS = "system.quote_legs.{gateway_id}"
PREFIX_QUOTE_LEGS = "system.quote_legs."
_QUOTE_LEGS_RE = re.compile("system\\.quote_legs\\.(?P<gateway_id>[^.]+)")
_QUOTE_LEGS_SHOW_REQUESTED_VALUES = ("ACTIVE", "RECENT", "ALL")
QuoteLegsShowRequested = Literal["ACTIVE", "RECENT", "ALL"]


_QUOTE_LEGS_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Topic-only; dropped by the default projection.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "legs",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "Live legs. Empty unless `show` was `ACTIVE` or `ALL`.",
    },
    {
        "name": "show_requested",
        "type": "enum",
        "unit": None,
        "required": True,
        "doc": "Echo of the request's `show`, so replies can be told apart.",
        "values": _QUOTE_LEGS_SHOW_REQUESTED_VALUES,
    },
    {
        "name": "complete",
        "type": "bool",
        "unit": None,
        "required": True,
        "doc": "False when the reply could not fully answer what was asked. Always true today; kept because the recent-history buffer is bounded and a truncated answer needs a way to say so.",
    },
    {
        "name": "recent",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "Removal history. Empty unless `show` was `RECENT` or `ALL`.",
    },
)


@dataclass(frozen=True, slots=True)
class QuoteLegs:
    """Engine to caller: live quote legs, recently-removed quotes, or both.

    `legs` and `recent` are both always present, empty when the requested half does not
    include them. Regime 4 would be the IDL's default instinct -- absent and `[]` are
    the same value to `alf_gwy`, the only structural reader -- but `GET /quotes/legs`
    returns this payload verbatim, and a REST client should not have to guess whether a
    key exists. `[]` is a true statement here rather than an invented one: both halves
    always mean something on this message. `show_requested` echoes what was asked, so a
    caller that pipelined two requests can tell the replies apart.
    """

    gateway_id: str
    legs: list[QuoteLeg]
    show_requested: QuoteLegsShowRequested
    complete: bool
    recent: list[RecentQuote]

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        for legs_item in self.legs:
            legs_item.validate()
        if self.show_requested not in _QUOTE_LEGS_SHOW_REQUESTED_VALUES:
            raise MessageValidationError(
                f"show_requested: {self.show_requested!r} is not one of {_QUOTE_LEGS_SHOW_REQUESTED_VALUES!r}"
            )
        for recent_item in self.recent:
            recent_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "QuoteLegs":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            legs=[QuoteLeg.from_dict(item) for item in p["legs"]],
            show_requested=cast(QuoteLegsShowRequested, str(p["show_requested"])),
            complete=bool(p["complete"]),
            recent=[RecentQuote.from_dict(item) for item in p["recent"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "legs": [item.to_dict() for item in self.legs],
            "show_requested": self.show_requested,
            "complete": self.complete,
            "recent": [item.to_dict() for item in self.recent],
        }


def topic_quote_legs(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"system.quote_legs.{gateway_id}"


def match_quote_legs(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _QUOTE_LEGS_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_quote_legs(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = QuoteLegs.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_quote_legs(obj.gateway_id), obj.to_dict())


def parse_quote_legs(frames: list[bytes]) -> "QuoteLegs":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_quote_legs(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_QUOTE_LEGS!r}")
    payload = {**payload, "gateway_id": matched}
    obj = QuoteLegs.from_dict(payload)
    obj.validate()
    return obj


def describe_quote_legs() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _QUOTE_LEGS_FIELDS


TOPIC_RISK_STATE_REQUEST = "system.risk_state_request"
_TOPIC_RISK_STATE_REQUEST_BYTES = "system.risk_state_request".encode()


_RISK_STATE_REQUEST_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
)


@dataclass(frozen=True, slots=True)
class RiskStateRequest:
    """ADMIN to engine: the live collar and circuit-breaker state of every symbol
    that has either configured, halted or not.
    """

    gateway_id: str

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "RiskStateRequest":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateway_id": self.gateway_id,
        }


def is_risk_state_request(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_RISK_STATE_REQUEST


def make_risk_state_request(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = RiskStateRequest.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_RISK_STATE_REQUEST, obj.to_dict())


def make_risk_state_request_unchecked(
    *,
    gateway_id: str,
) -> list[bytes]:
    """Identical frames to ``make_risk_state_request``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_RISK_STATE_REQUEST_BYTES,
        _msg.dumps(
            {
                "gateway_id": str(gateway_id),
            }
        ),
    ]


def parse_risk_state_request(frames: list[bytes]) -> "RiskStateRequest":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = RiskStateRequest.from_dict(payload)
    obj.validate()
    return obj


def describe_risk_state_request() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _RISK_STATE_REQUEST_FIELDS


TOPIC_RISK_STATE = "system.risk_state.{gateway_id}"
PREFIX_RISK_STATE = "system.risk_state."
_RISK_STATE_RE = re.compile("system\\.risk_state\\.(?P<gateway_id>[^.]+)")


_RISK_STATE_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Topic-only; dropped by the default projection.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "symbols",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "Sorted by symbol. Was a map keyed by it.",
    },
)


@dataclass(frozen=True, slots=True)
class RiskState:
    """Engine to ADMIN: live risk state per symbol. The counterpart to
    `reference.risk`, which is the static definitions, and to `halt_status`, which
    is only the symbols currently halted.

    The fourth `symbols` field in this family and the fourth different thing: a list of
    `SymbolInfo` on `system.symbols`, of `ReferenceSymbol` on `reference`, of
    `SymbolRiskState` here and of `SymbolVolume` on `volume`. Same name, four types, no
    relationship -- which is why a find-and-replace across them would be the worst
    available mistake.
    """

    gateway_id: str
    symbols: list[SymbolRiskState]

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        for symbols_item in self.symbols:
            symbols_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "RiskState":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            symbols=[SymbolRiskState.from_dict(item) for item in p["symbols"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "symbols": [item.to_dict() for item in self.symbols],
        }


def topic_risk_state(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"system.risk_state.{gateway_id}"


def match_risk_state(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _RISK_STATE_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_risk_state(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = RiskState.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_risk_state(obj.gateway_id), obj.to_dict())


def parse_risk_state(frames: list[bytes]) -> "RiskState":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_risk_state(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_RISK_STATE!r}")
    payload = {**payload, "gateway_id": matched}
    obj = RiskState.from_dict(payload)
    obj.validate()
    return obj


def describe_risk_state() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _RISK_STATE_FIELDS


TOPIC_GATEWAYS_REQUEST = "system.gateways_request"
_TOPIC_GATEWAYS_REQUEST_BYTES = "system.gateways_request".encode()


_GATEWAYS_REQUEST_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
)


@dataclass(frozen=True, slots=True)
class GatewaysRequest:
    """Operator to engine: which participants exist, and who is on."""

    gateway_id: str

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "GatewaysRequest":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateway_id": self.gateway_id,
        }


def is_gateways_request(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_GATEWAYS_REQUEST


def make_gateways_request(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = GatewaysRequest.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_GATEWAYS_REQUEST, obj.to_dict())


def make_gateways_request_unchecked(
    *,
    gateway_id: str,
) -> list[bytes]:
    """Identical frames to ``make_gateways_request``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_GATEWAYS_REQUEST_BYTES,
        _msg.dumps(
            {
                "gateway_id": str(gateway_id),
            }
        ),
    ]


def parse_gateways_request(frames: list[bytes]) -> "GatewaysRequest":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = GatewaysRequest.from_dict(payload)
    obj.validate()
    return obj


def describe_gateways_request() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _GATEWAYS_REQUEST_FIELDS


TOPIC_GATEWAYS = "system.gateways.{gateway_id}"
PREFIX_GATEWAYS = "system.gateways."
_GATEWAYS_RE = re.compile("system\\.gateways\\.(?P<gateway_id>[^.]+)")


_GATEWAYS_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Topic-only; dropped by the default projection.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "gateways",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "Sorted by id. Empty when no config is loaded.",
    },
)


@dataclass(frozen=True, slots=True)
class Gateways:
    """Engine to operator: every configured participant with its role and current
    connection status. The polled counterpart to the `gateway_auth` /
    `gateway_bye` broadcasts.
    """

    gateway_id: str
    gateways: list[GatewayInfo]

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        for gateways_item in self.gateways:
            gateways_item.validate()

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "Gateways":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            gateways=[GatewayInfo.from_dict(item) for item in p["gateways"]],
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateways": [item.to_dict() for item in self.gateways],
        }


def topic_gateways(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"system.gateways.{gateway_id}"


def match_gateways(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _GATEWAYS_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_gateways(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = Gateways.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_gateways(obj.gateway_id), obj.to_dict())


def parse_gateways(frames: list[bytes]) -> "Gateways":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_gateways(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_GATEWAYS!r}")
    payload = {**payload, "gateway_id": matched}
    obj = Gateways.from_dict(payload)
    obj.validate()
    return obj


def describe_gateways() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _GATEWAYS_FIELDS


TOPIC_VOLUME_REQUEST = "system.volume_request"
_TOPIC_VOLUME_REQUEST_BYTES = "system.volume_request".encode()


_VOLUME_REQUEST_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "",
        "constraints": {"max_len": 32},
    },
)


@dataclass(frozen=True, slots=True)
class VolumeRequest:
    """Operator to engine: how much has traded today."""

    gateway_id: str

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "VolumeRequest":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p["gateway_id"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "gateway_id": self.gateway_id,
        }


def is_volume_request(topic: str) -> bool:
    """True when ``topic`` is this message's topic."""
    return topic == TOPIC_VOLUME_REQUEST


def make_volume_request(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = VolumeRequest.from_dict(kw)
    obj.validate()
    return _msg.encode(TOPIC_VOLUME_REQUEST, obj.to_dict())


def make_volume_request_unchecked(
    *,
    gateway_id: str,
) -> list[bytes]:
    """Identical frames to ``make_volume_request``, without ``validate()``.

    For measured hot paths only; every other caller should use the validating
    constructor. Builds the payload directly rather than via the dataclass, which is
    what makes it cheap enough to be worth having — see the generator's _unchecked_block
    docstring for the measurements.

    Coerces exactly as ``make_*`` does, so for any input the two emit byte-identical
    frames.
    """
    return [
        _TOPIC_VOLUME_REQUEST_BYTES,
        _msg.dumps(
            {
                "gateway_id": str(gateway_id),
            }
        ),
    ]


def parse_volume_request(frames: list[bytes]) -> "VolumeRequest":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    _topic, payload = _msg.decode(frames)
    obj = VolumeRequest.from_dict(payload)
    obj.validate()
    return obj


def describe_volume_request() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _VOLUME_REQUEST_FIELDS


TOPIC_VOLUME = "system.volume.{gateway_id}"
PREFIX_VOLUME = "system.volume."
_VOLUME_RE = re.compile("system\\.volume\\.(?P<gateway_id>[^.]+)")


_VOLUME_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "gateway_id",
        "type": "string",
        "unit": None,
        "required": True,
        "doc": "Topic-only; dropped by the default projection.",
        "constraints": {"max_len": 32},
    },
    {
        "name": "symbols",
        "type": "list",
        "unit": None,
        "required": True,
        "doc": "Sorted by symbol. Was a map keyed by it.",
    },
    {
        "name": "total_qty",
        "type": "int",
        "unit": "shares",
        "required": True,
        "doc": "",
        "constraints": {"ge": 0},
    },
    {
        "name": "total_value",
        "type": "float",
        "unit": "money",
        "required": True,
        "doc": "",
        "constraints": {"ge": 0},
    },
    {
        "name": "total_trades",
        "type": "int",
        "unit": "dimensionless",
        "required": True,
        "doc": "",
        "constraints": {"ge": 0},
    },
)


@dataclass(frozen=True, slots=True)
class Volume:
    """Engine to operator: traded quantity, notional and trade count, per instrument
    and exchange-wide.

    The totals are carried rather than left to the caller to sum. That is redundant on
    the wire and load-bearing off it: they are the engine's own running counters, not a
    sum of the rows, so a caller adding up `symbols` would silently disagree with the
    engine about any instrument whose book was removed mid-session.
    """

    gateway_id: str
    symbols: list[SymbolVolume]
    total_qty: int  # unit: shares
    total_value: float  # unit: money
    total_trades: int  # unit: dimensionless

    def validate(self) -> None:
        """Raise MessageValidationError if any declared rule fails.

        The only strictness gate: ``from_dict`` coerces but never validates, so a reader
        of historical data can opt out of the rules by calling ``from_dict`` alone
        (design section 5.1.1).
        """
        if len(self.gateway_id) > 32:
            raise MessageValidationError(
                f"gateway_id: length {len(self.gateway_id)} exceeds max_len 32"
            )
        for symbols_item in self.symbols:
            symbols_item.validate()
        if self.total_qty < 0:
            raise MessageValidationError(f"total_qty: {self.total_qty!r} must be >= 0")
        if self.total_value < 0:
            raise MessageValidationError(
                f"total_value: {self.total_value!r} must be >= 0"
            )
        if self.total_trades < 0:
            raise MessageValidationError(
                f"total_trades: {self.total_trades!r} must be >= 0"
            )

    @classmethod
    def from_dict(cls, p: Mapping[str, Any]) -> "Volume":
        """Coerce a payload mapping into this message. Does NOT validate.

        Mirrors the hand-written payload's coercion exactly, including its lenient
        fallbacks, so it is a drop-in replacement for readers of already-published data
        (design section 5.1.1).
        """
        return cls(
            gateway_id=str(p.get("gateway_id", "")),
            symbols=[SymbolVolume.from_dict(item) for item in p["symbols"]],
            total_qty=int(p["total_qty"]),
            total_value=float(p["total_value"]),
            total_trades=int(p["total_trades"]),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the bus payload, in the spec's declared field order."""
        return {
            "symbols": [item.to_dict() for item in self.symbols],
            "total_qty": self.total_qty,
            "total_value": self.total_value,
            "total_trades": self.total_trades,
        }


def topic_volume(gateway_id: str) -> str:
    """Build this message's topic without a string literal."""
    return f"system.volume.{gateway_id}"


def match_volume(topic: str) -> str | None:
    """Return ``gateway_id`` when ``topic`` matches, else None."""
    m = _VOLUME_RE.fullmatch(topic)
    return m.group("gateway_id") if m else None


def make_volume(**kw: Any) -> list[bytes]:
    """Coerce, validate, and return the TWO bus frames [topic, payload].

    The per-topic sequence third frame is NOT added here; it is appended by
    SequencedPublisher.send_multipart() at publish time (edumatcher/messaging/bus.py).

    Routes through ``from_dict`` rather than the dataclass constructor, so a caller
    passing ``price=100`` puts a float on the wire rather than an int (design section
    5.1.1).
    """
    obj = Volume.from_dict(kw)
    obj.validate()
    return _msg.encode(topic_volume(obj.gateway_id), obj.to_dict())


def parse_volume(frames: list[bytes]) -> "Volume":
    """Decode bus frames into a validated message.

    Raises MessageValidationError if the payload breaks a declared rule. Call
    ``from_dict`` on a decoded payload instead to read without validating.
    """
    topic, payload = _msg.decode(frames)
    matched = match_volume(topic)
    if matched is None:
        raise MessageValidationError(f"topic {topic!r} is not {TOPIC_VOLUME!r}")
    payload = {**payload, "gateway_id": matched}
    obj = Volume.from_dict(payload)
    obj.validate()
    return obj


def describe_volume() -> tuple[dict[str, Any], ...]:
    """Return field metadata, for spy tools and runtime pretty-printing."""
    return _VOLUME_FIELDS


FAMILY_TOPICS: tuple[str, ...] = (
    TOPIC_GATEWAY_CONNECT,
    TOPIC_GATEWAY_AUTH,
    TOPIC_GATEWAY_DISCONNECT,
    TOPIC_GATEWAY_BYE,
    TOPIC_EOD,
    TOPIC_SYMBOLS_REQUEST,
    TOPIC_SYMBOLS,
    TOPIC_REFERENCE_REQUEST,
    TOPIC_REFERENCE,
    TOPIC_REFERENCE_RELOAD,
    TOPIC_REFERENCE_RELOAD_ACK,
    TOPIC_SESSION_STATE_REQUEST,
    TOPIC_SESSION_STATUS,
    TOPIC_SESSION_SCHEDULE_REQUEST,
    TOPIC_SESSION_SCHEDULE,
    TOPIC_HALT_STATUS_REQUEST,
    TOPIC_HALT_STATUS,
    TOPIC_POSITION_REQUEST,
    TOPIC_POSITION_SNAPSHOT,
    TOPIC_QUOTE_BOOTSTRAP_REQUEST,
    TOPIC_QUOTE_BOOTSTRAP,
    TOPIC_QUOTE_LEGS_REQUEST,
    TOPIC_QUOTE_LEGS,
    TOPIC_RISK_STATE_REQUEST,
    TOPIC_RISK_STATE,
    TOPIC_GATEWAYS_REQUEST,
    TOPIC_GATEWAYS,
    TOPIC_VOLUME_REQUEST,
    TOPIC_VOLUME,
)
