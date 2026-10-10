"""ALF line building and parsing for clients.

Outbound lines are built with the gateway's own ``build_line``. Inbound
lines need a different parser from the gateway's: ``alf_gwy.protocol.
parse_alf_line`` uppercases every value except ``ID`` (right for commands a
client sends), but responses carry ``ORDER_ID=`` values in lowercase hex,
and an uppercased order id would never match on a later ``CANCEL|ID=``.
Here keys and the message type are uppercased and values keep their case.

Prices on the ALF wire are display money; these helpers take integer ticks
and the symbol's tick decimals.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from edumatcher.alf_gwy.protocol import build_line

PROTO = "ALF1"


@dataclass(frozen=True)
class AlfMessage:
    msg_type: str
    fields: dict[str, str]

    def get(self, key: str, default: str = "") -> str:
        return self.fields.get(key, default)

    def flag(self, key: str) -> bool:
        return self.fields.get(key, "").upper() == "TRUE"


def parse_response(line: str) -> AlfMessage | None:
    """Parse one inbound line; None for a blank line."""
    line = line.strip()
    if not line:
        return None
    head, *rest = line.split("|")
    fields: dict[str, str] = {}
    for seg in rest:
        key, sep, value = seg.partition("=")
        if sep and key.strip():
            fields[key.strip().upper()] = value.strip()
    return AlfMessage(head.strip().upper(), fields)


def price(ticks: int, tick_decimals: int) -> str:
    """Integer ticks as an exact display-money string."""
    if tick_decimals <= 0:
        return str(ticks * 10 ** (-tick_decimals))
    sign = "-" if ticks < 0 else ""
    whole, frac = divmod(abs(ticks), 10**tick_decimals)
    return f"{sign}{whole}.{frac:0{tick_decimals}d}"


def hello(gateway_id: str, client: str, feed: str | None = None) -> bytes:
    """``feed="ORDERS"`` turns off the gateway's public broadcasts."""
    fields = {"CLIENT": client, "PROTO": PROTO, "ID": gateway_id}
    if feed:
        fields["FEED"] = feed
    return build_line("HELLO", fields)


def new_order(
    *,
    tag: str,
    symbol: str,
    side: str,
    order_type: str,
    tif: str,
    qty: int,
    tick_decimals: int,
    price_ticks: int | None = None,
    stop_price_ticks: int | None = None,
    trail_offset_ticks: int | None = None,
    visible_qty: int | None = None,
) -> bytes:
    fields = {
        "SYM": symbol,
        "SIDE": side,
        "TYPE": order_type,
        "QTY": str(qty),
        "TIF": tif,
        "TAG": tag,
    }
    if price_ticks is not None:
        fields["PRICE"] = price(price_ticks, tick_decimals)
    if stop_price_ticks is not None:
        fields["STOP"] = price(stop_price_ticks, tick_decimals)
    if trail_offset_ticks is not None:
        fields["TRAIL"] = price(trail_offset_ticks, tick_decimals)
    if visible_qty is not None:
        fields["VISIBLE"] = str(visible_qty)
    return build_line("NEW", fields)


def new_oco(
    *,
    oco_id: str,
    symbol: str,
    qty: int,
    tif: str,
    tick_decimals: int,
    legs: tuple[Mapping[str, object], Mapping[str, object]],
) -> bytes:
    """``legs``: two mappings with side, order_type and optional
    price_ticks / stop_price_ticks."""
    fields = {
        "TYPE": "OCO",
        "OCO_ID": oco_id,
        "SYM": symbol,
        "QTY": str(qty),
        "TIF": tif,
    }
    for i, leg in enumerate(legs, 1):
        p = f"LEG{i}_"
        fields[p + "SIDE"] = str(leg["side"])
        fields[p + "TYPE"] = str(leg["order_type"])
        for key, wire in (("price_ticks", "PRICE"), ("stop_price_ticks", "STOP")):
            value = leg.get(key)
            if value is not None:
                fields[p + wire] = price(int(value), tick_decimals)  # type: ignore[call-overload]
    fields["TAG"] = oco_id
    return build_line("NEW", fields)


def cancel(order_id: str, rtag: str | None = None) -> bytes:
    fields = {"ID": order_id}
    if rtag:
        fields["RTAG"] = rtag
    return build_line("CANCEL", fields)


def cancel_oco(oco_id: str) -> bytes:
    return build_line("CANCEL", {"OCO_ID": oco_id})


def position_request(gateway_id: str) -> bytes:
    return build_line("POS", {"GW": gateway_id})


def ping() -> bytes:
    return build_line("PING")


def bye() -> bytes:
    return build_line("EXIT")
