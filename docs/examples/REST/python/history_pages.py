"""Read a whole history list by following ``next_cursor``.

History endpoints answer one page at a time: ``{<items>, count, has_more,
next_cursor}``. Pass ``next_cursor`` back as ``after`` until ``has_more`` is
false (``next_cursor`` is then ``null``). The cursor is opaque: never build
one yourself.

Usage::

    python3 history_pages.py --limit 50          # today's trades, all pages

Environment: EDUMATCHER_API_URL and EDUMATCHER_API_KEY (any key).
"""

from __future__ import annotations

import argparse
import os
import sys

from api_gateway_client import ApiError, ApiGatewayClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=50, help="Page size")
    parser.add_argument("--symbol", default=None)
    parser.add_argument(
        "--url", default=os.environ.get("EDUMATCHER_API_URL", "http://127.0.0.1:8080")
    )
    parser.add_argument("--key", default=os.environ.get("EDUMATCHER_API_KEY", ""))
    args = parser.parse_args(argv)
    client = ApiGatewayClient(args.url, args.key)

    try:
        trades = list(
            client.pages(
                "/api/v1/history/trades",
                "trades",
                {"limit": args.limit, "symbol": args.symbol},
            )
        )
    except ApiError as exc:
        if exc.code == "STATS_DB":
            # A fresh venue has no pm-stats database yet: not an error to retry.
            print("no history yet (pm-stats has not written its database)")
            return 0
        raise
    ids = [t["trade_id"] for t in trades]
    assert len(ids) == len(set(ids)), "a page boundary repeated a trade"
    volume = sum(t["quantity"] for t in trades)
    print(f"{len(trades)} trades today, {volume} shares, in pages of {args.limit}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
