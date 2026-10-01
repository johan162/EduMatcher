"""The new symbol's entry: IPO price, seed quote and optional sections."""

from __future__ import annotations

import argparse
import re
from decimal import Decimal
from typing import Any

import yaml

from edumatcher.engine.config_loader import EngineConfig
from edumatcher.models.participant import ParticipantRole

# The tightest symbol constraint on the wire: the BALF execution report
# carries the symbol as char[8] matching this pattern (spec/messages/order.yaml).
# The config loader does not check it, so a longer name would pass validation
# and fail at the first fill.
_SYMBOL = re.compile(r"[A-Z0-9._]{1,8}")

# The per-symbol sections --field may set. Everything else a symbol takes has
# its own option, and the loader ignores unknown keys, so a misspelt key would
# otherwise be dropped without a word.
FIELDS = ("level", "collar", "order_limits", "circuit_breaker")


def _seed_quote(
    args: argparse.Namespace,
    engine: EngineConfig,
    symbol: str,
    price: Decimal,
    tick: Decimal,
) -> dict[str, Any] | None:
    mm_ids = [
        gw.id
        for gw in engine.fix_gateways.values()
        if gw.role == ParticipantRole.MARKET_MAKER
    ]
    if (args.mm_bid_price is None) != (args.mm_ask_price is None):
        raise ValueError("give both --mm-bid-price and --mm-ask-price, or neither")
    if args.mm_gateway_id is None:
        if not (mm_ids and engine.require_mm_seed_quotes):
            if args.mm_bid_price is not None:
                raise ValueError(
                    "this configuration needs no seed quote; name the gateway "
                    "that should post one with --mm-gateway-id"
                )
            return None
        if len(mm_ids) > 1:
            raise ValueError(
                f"several MARKET_MAKER gateways ({', '.join(mm_ids)}); choose "
                f"the one that seeds {symbol} with --mm-gateway-id"
            )
        gateway_id = mm_ids[0]
    else:
        gateway_id = args.mm_gateway_id.strip().upper()
        if gateway_id not in mm_ids:
            raise ValueError(f"{gateway_id} is not a MARKET_MAKER gateway")

    # The engine's precedence for a quote's obligation is gateway+symbol, then
    # global symbol, then gateway (whose fields default to the global ones).
    # A global per-symbol policy cannot name a symbol that is not listed yet.
    gateway = engine.fix_gateways[gateway_id]
    policy = gateway.mm_obligation_policies.get(symbol)
    enforce = policy.enforce_mm_obligation if policy else gateway.enforce_mm_obligation
    max_spread = policy.mm_max_spread_ticks if policy else gateway.mm_max_spread_ticks
    min_qty = policy.mm_min_qty if policy else gateway.mm_min_qty

    if args.mm_bid_price is None:
        # Exactly the widest spread the market maker may quote, around the
        # IPO price; an odd width puts the extra tick on the ask.
        bid = price - (max_spread // 2) * tick
        ask = bid + max_spread * tick
        if bid <= 0:
            raise ValueError(
                f"a {max_spread}-tick seed around {price} has a bid of {bid}; "
                "give --mm-bid-price and --mm-ask-price"
            )
    else:
        bid, ask = args.mm_bid_price, args.mm_ask_price
    for label, value in (("bid", bid), ("ask", ask)):
        if value % tick:
            raise ValueError(f"seed {label} {value} is not on the {tick} tick grid")
    if not bid < ask or not bid <= price <= ask:
        raise ValueError(
            f"seed quote {bid} / {ask} must be ordered and straddle the IPO "
            f"price {price}"
        )
    if args.mm_bid_qty <= 0 or args.mm_ask_qty <= 0:
        raise ValueError("seed quantities must be positive")
    if enforce:
        spread = int((ask - bid) / tick)
        if spread > max_spread:
            raise ValueError(
                f"seed spread of {spread} ticks exceeds {gateway_id}'s "
                f"obligation of {max_spread}"
            )
        if min(args.mm_bid_qty, args.mm_ask_qty) < min_qty:
            raise ValueError(
                f"seed quantities are below {gateway_id}'s obligation of {min_qty}"
            )
    return {
        "gateway_id": gateway_id,
        "bid_price": float(bid),
        "ask_price": float(ask),
        "bid_qty": args.mm_bid_qty,
        "ask_qty": args.mm_ask_qty,
        "tif": args.mm_tif,
        "seed_once": args.mm_seed_once,
    }


def build_listing(
    args: argparse.Namespace, engine: EngineConfig
) -> tuple[str, dict[str, Any]]:
    symbol = args.symbol.upper()
    if not _SYMBOL.fullmatch(symbol):
        raise ValueError(
            f"symbol {args.symbol!r} must be 1-8 characters of A-Z, 0-9, '.' or '_'"
        )
    if symbol in engine.symbols:
        raise ValueError(f"symbol {symbol} is already listed")
    if args.outstanding_shares <= 0:
        raise ValueError("--outstanding-shares must be positive")
    if not 0 <= args.tick_decimals <= 8:
        raise ValueError("--tick-decimals must be in 0..8")
    tick = Decimal(1).scaleb(-args.tick_decimals)
    price: Decimal = args.ipo_price
    if price % tick:
        raise ValueError(f"IPO price {price} is not on the {tick} tick grid")

    # No trade has happened yet, so both last prices are the offer price:
    # it is what the collar and the circuit breaker take as their reference.
    payload: dict[str, Any] = {
        "tick_decimals": args.tick_decimals,
        "last_buy_price": float(price),
        "last_sell_price": float(price),
        "outstanding_shares": args.outstanding_shares,
    }
    for field in args.field:
        key, separator, value = field.partition("=")
        if not separator or key not in FIELDS or key in payload:
            raise ValueError(
                f"--field {field!r}: the key must be one of {', '.join(FIELDS)}, "
                "each given once"
            )
        payload[key] = yaml.safe_load(value)
    quote = _seed_quote(args, engine, symbol, price, tick)
    if quote is not None:
        payload["market_maker_quotes"] = [quote]
    return symbol, payload
