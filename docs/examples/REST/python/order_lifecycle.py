"""One order's whole life over REST: submit, retry, amend, replace, cancel.

Shows what a robust trading client does at each step:

* submit a LIMIT order with ``?wait=ack`` and an ``Idempotency-Key``, and
  handle all three outcomes: accepted, rejected (``reject_code``), and a late
  ack (``ack_timeout``) -- the order was sent, so it must not be resent;
* retry the same request with the same key: the gateway replays the first
  reply instead of placing a second order;
* amend the price, replace the order, then cancel the replacement;
* refuse to round: a price off the tick grid is a ``400`` with
  ``reject_code: TICK_VIOLATION``, and nothing was sent.

Usage::

    python3 order_lifecycle.py --symbol AAPL --qty 10

Environment: EDUMATCHER_API_URL (default http://127.0.0.1:8080) and
EDUMATCHER_API_KEY (a trading key).
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from typing import Any

from api_gateway_client import ApiError, ApiGatewayClient


def resting_price(
    client: ApiGatewayClient, symbol: str, price: float | None = None
) -> tuple[float, float]:
    """The buy price to rest at, and the symbol's tick size.

    *price* when given (pick one below the best bid, so the order rests);
    otherwise about 1% under the previous close. A venue whose symbols carry
    no ``prev_close`` needs ``--price``: guessing could cross the spread.
    """
    symbols = client.get_json("/api/v1/symbols")["symbols"]
    info = next(s for s in symbols if s["symbol"] == symbol)
    decimals = info["tick_decimals"]
    tick = 10**-decimals
    if price is None:
        if info.get("prev_close") is None:
            raise SystemExit(f"{symbol} has no prev_close; pass --price below the bid")
        price = info["prev_close"] * 0.99
    return round(round(price / tick) * tick, decimals), tick


def submit(client: ApiGatewayClient, order: dict[str, Any], key: str) -> dict[str, Any]:
    reply = client.post_json("/api/v1/orders?wait=ack", order, idempotency_key=key)
    if reply["ack_timeout"]:
        # Sent, but the verdict was late. Follow it on the private WebSocket
        # or GET /orders; resubmitting would risk a second order.
        print(f"  sent, verdict pending: {reply['order_id']}")
    elif reply["accepted"]:
        print(f"  accepted: {reply['order_id']}")
    else:
        print(f"  rejected by the engine: {reply['reject_code']}")
    return reply


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--qty", type=int, default=10)
    parser.add_argument(
        "--price", type=float, default=None, help="Resting BUY price (below the bid)"
    )
    parser.add_argument(
        "--url", default=os.environ.get("EDUMATCHER_API_URL", "http://127.0.0.1:8080")
    )
    parser.add_argument("--key", default=os.environ.get("EDUMATCHER_API_KEY", ""))
    args = parser.parse_args(argv)
    client = ApiGatewayClient(args.url, args.key)
    symbol = args.symbol.upper()
    price, tick = resting_price(client, symbol, args.price)

    print(f"1. submit BUY {args.qty} {symbol} @ {price}")
    order = {
        "symbol": symbol,
        "side": "BUY",
        "order_type": "LIMIT",
        "quantity": args.qty,
        "price": price,
        "client_tag": "lifecycle-demo",
    }
    key = str(uuid.uuid4())
    first = submit(client, order, key)
    if not first["accepted"]:
        return 1

    print("2. retry with the same Idempotency-Key")
    again = client.post_json("/api/v1/orders?wait=ack", order, idempotency_key=key)
    assert again["order_id"] == first["order_id"], "a retry must not place an order"
    print(f"  same order, no duplicate: {again['order_id']}")

    order_id = first["order_id"]
    print("3. amend the price down one tick")
    amended = client.patch_json(
        f"/api/v1/orders/{order_id}?wait=ack",
        {"price": round(price - tick, 10), "request_tag": "amend-1"},
    )
    print(f"  {amended['status']} (accepted={amended['accepted']})")
    if not amended["accepted"]:
        return 1

    print("4. replace it with a bigger order on the same symbol")
    replaced = client.post_json(
        f"/api/v1/orders/{order_id}/replace?wait=ack",
        {**order, "quantity": args.qty * 2},
        idempotency_key=str(uuid.uuid4()),
    )
    replacement = replaced["replacement_order_id"]
    print(f"  {order_id} -> {replacement} (accepted={replaced['accepted']})")
    if not replaced["accepted"]:
        return 1

    print("5. cancel the replacement")
    cancelled = client.delete_json(
        f"/api/v1/orders/{replacement}?wait=ack&request_tag=cxl-1"
    )
    print(f"  {cancelled['status']} (accepted={cancelled['accepted']})")
    if not cancelled["accepted"]:
        return 1

    print("6. a price off the tick grid is refused, not rounded")
    try:
        client.post_json("/api/v1/orders", {**order, "price": price + tick / 2})
    except ApiError as exc:
        print(f"  {exc.status} {exc.code} reject_code={exc.reject_code}: {exc.message}")
        if exc.reject_code != "TICK_VIOLATION":
            return 1
    else:
        print("  unexpectedly accepted", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
