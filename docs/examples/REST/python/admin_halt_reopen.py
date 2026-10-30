"""An operator incident flow: halt a symbol, inspect, and reopen it.

1. ``POST /admin/symbols/{symbol}/halt`` stops matching on one symbol;
2. ``GET /admin/symbols/{symbol}/orders`` shows every resting order on it,
   across all participants;
3. ``POST /admin/symbols/{symbol}/reopen`` with ``dry_run`` reports the
   indicative uncross without changing anything;
4. a real reopen uncrosses and clears the halt -- or, when there is nothing
   to uncross, ``POST /admin/symbols/{symbol}/resume`` lifts it.

A refusal is a ``409`` whose ``message`` is the engine's reason (for example
``HALT_REJECTED: Unknown symbol: XYZ``). Needs an ADMIN key.

Usage::

    python3 admin_halt_reopen.py --symbol AAPL
"""

from __future__ import annotations

import argparse
import os
import sys

from api_gateway_client import ApiError, ApiGatewayClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument(
        "--url", default=os.environ.get("EDUMATCHER_API_URL", "http://127.0.0.1:8080")
    )
    parser.add_argument("--key", default=os.environ.get("EDUMATCHER_API_KEY", ""))
    args = parser.parse_args(argv)
    client = ApiGatewayClient(args.url, args.key)
    symbol = args.symbol.upper()
    base = f"/api/v1/admin/symbols/{symbol}"

    halted = client.post_json(f"{base}/halt", {"reason": "example: incident drill"})
    print(
        f"1. halted {halted['symbol']} (quotes cancelled: {halted['cancelled_quotes']})"
    )

    book = client.get_json(f"{base}/orders")
    owners = sorted({o["gateway_id"] for o in book["orders"]})
    print(f"2. {book['count']} resting orders, from {owners}")

    peek = client.post_json(f"{base}/reopen", {"dry_run": True})
    print(
        f"3. dry run: would print {peek['indicative_qty']} @ "
        f"{peek['indicative_price']} (surplus {peek['surplus']})"
    )

    try:
        if peek["indicative_qty"] > 0:
            opened = client.post_json(f"{base}/reopen", {"reason": "example"})
            print(f"4. reopened: {opened['traded_qty']} @ {opened['printed_price']}")
        else:
            client.post_json(f"{base}/resume", {"reason": "example"})
            print("4. nothing to uncross; resumed")
    except ApiError as exc:
        print(f"refused: {exc.code}: {exc.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
