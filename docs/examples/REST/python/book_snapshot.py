"""Read the order book over plain REST: no WebSocket needed.

``GET /api/v1/book`` is the venue at a glance (best bid, best ask and last
price per symbol); ``GET /api/v1/book/{symbol}`` is one symbol's ladder, last
trade and last five prints. Every price comes twice: as a display price
(``186.95``) and as ``*_ticks`` (``18695``, the price times
``10**tick_decimals``). Compare and add prices in ticks; floats are for display.

``seq`` is the sequence number of the WebSocket ``book`` frame for the same
snapshot: a client that reads here and then subscribes ignores ``book`` frames
whose ``seq`` is at or below it. ``ts_ns`` is when the engine produced the
snapshot; a quiet book keeps an old one and is still current.

Usage::

    python3 book_snapshot.py --symbol AAPL --levels 5

Environment: EDUMATCHER_API_URL and EDUMATCHER_API_KEY (any key).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from api_gateway_client import ApiError, ApiGatewayClient


def ticks_agree(level: dict[str, Any], tick_decimals: int) -> bool:
    """Whether ``price_ticks`` is the display price at the symbol's scale."""
    return bool(level["price_ticks"] == round(level["price"] * 10**tick_decimals))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--levels", type=int, default=5)
    parser.add_argument(
        "--url", default=os.environ.get("EDUMATCHER_API_URL", "http://127.0.0.1:8080")
    )
    parser.add_argument("--key", default=os.environ.get("EDUMATCHER_API_KEY", ""))
    args = parser.parse_args(argv)
    client = ApiGatewayClient(args.url, args.key)

    overview = client.get_json("/api/v1/book")
    print(f"{overview['count']} symbols")
    for row in overview["books"]:
        bid, ask = row["best_bid"], row["best_ask"]
        print(
            f"  {row['symbol']:<6} bid {bid['price'] if bid else '-':>8}"
            f"  ask {ask['price'] if ask else '-':>8}  last {row['last_price']}"
        )

    book = client.get_json(f"/api/v1/book/{args.symbol}", {"levels": args.levels})
    td = book["tick_decimals"]
    print(f"\n{book['symbol']} at seq {book['seq']} (ts_ns {book['ts_ns']})")
    for ask in reversed(book["asks"]):
        print(f"  ask {ask['price']:>10.{td}f} {ask['qty']:>7} ({ask['count']})")
    for bid in book["bids"]:
        print(f"  bid {bid['price']:>10.{td}f} {bid['qty']:>7} ({bid['count']})")

    levels = [*book["bids"], *book["asks"]]
    assert all(ticks_agree(lvl, td) for lvl in levels), "price_ticks disagrees"
    bids = [lvl["price_ticks"] for lvl in book["bids"]]
    asks = [lvl["price_ticks"] for lvl in book["asks"]]
    assert bids == sorted(bids, reverse=True), "bids are best (highest) first"
    assert asks == sorted(asks), "asks are best (lowest) first"
    assert len(bids) <= args.levels and len(asks) <= args.levels

    try:
        client.get_json("/api/v1/book/NOSUCH")
    except ApiError as exc:
        assert (exc.status, exc.code) == (404, "UNKNOWN_SYMBOL"), exc
        print(f"\nNOSUCH: {exc.code} (HTTP {exc.status}), as expected")
    else:
        raise AssertionError("an unknown symbol answered 200")
    return 0


if __name__ == "__main__":
    sys.exit(main())
