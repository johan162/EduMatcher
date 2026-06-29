"""Submit a MARKET order through the API Gateway and print the result.

Usage::

    python3 submit_market_order.py --side BUY  --symbol AAPL --qty 100
    python3 submit_market_order.py --side SELL --symbol MSFT --qty 50 --wait-ack

Environment variables:

    EDUMATCHER_API_URL  Base URL of the API gateway (default: http://127.0.0.1:8080)
    EDUMATCHER_API_KEY  Bearer token              (default: key-trader-demo)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from api_gateway_client import ApiGatewayClient


def _print_result(result: dict) -> None:
    print(f"order_id  : {result.get('order_id', '-')}")
    print(f"status    : {result.get('status', '-')}")
    if result.get("client_order_id"):
        print(f"client_id : {result['client_order_id']}")
    if result.get("accepted") is not None:
        print(f"accepted  : {result['accepted']}")
    if result.get("event"):
        print("engine ack:")
        print(json.dumps(result["event"], indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Submit a MARKET order via the API Gateway"
    )
    parser.add_argument(
        "--side", required=True, choices=["BUY", "SELL"], help="Order side"
    )
    parser.add_argument(
        "--symbol", required=True, help="Instrument symbol, e.g. AAPL"
    )
    parser.add_argument(
        "--qty", required=True, type=int, metavar="N", help="Order quantity"
    )
    parser.add_argument(
        "--wait-ack",
        action="store_true",
        help="Block until the matching engine ACKs the order",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("EDUMATCHER_API_URL", "http://127.0.0.1:8080"),
        help="API gateway base URL",
    )
    parser.add_argument(
        "--key",
        default=os.environ.get("EDUMATCHER_API_KEY", "key-trader-demo"),
        help="Bearer API key",
    )
    args = parser.parse_args()

    client = ApiGatewayClient(args.url, args.key)
    path = "/api/v1/orders" + ("?wait=ack" if args.wait_ack else "")
    payload = {
        "symbol": args.symbol.upper(),
        "side": args.side,
        "order_type": "MARKET",
        "quantity": args.qty,
    }

    try:
        result = client.post_json(path, payload)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    _print_result(result)


if __name__ == "__main__":
    main()
