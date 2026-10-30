"""Follow your own orders on the private WebSocket, and recover from a gap.

The recovery rule (WebSocket API Reference, ``/ws/private``):

1. send ``{"api_key": ...}`` first; the server answers ``authenticated``;
2. rebuild order state from ``orders.snapshot``;
3. apply live events in order; ``stream_seq`` is contiguous, so any jump
   means events were dropped (the client read too slowly) -- reconnect and
   rebuild from the fresh snapshot. There is no replay.

To have something to watch, this example places one resting order over REST
after connecting and cancels it again, then exits once it has seen both.

Needs the ``websockets`` package (``pip install websockets``).

Usage::

    python3 private_stream.py --symbol AAPL --seconds 20

Environment: EDUMATCHER_API_URL and EDUMATCHER_API_KEY (a trading key).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

from websockets.sync.client import ClientConnection, connect

from api_gateway_client import ApiGatewayClient
from order_lifecycle import resting_price


class PrivateStream:
    """Order state kept from one gateway's private stream."""

    def __init__(self, ws_url: str, api_key: str) -> None:
        self.ws_url = ws_url
        self.api_key = api_key
        self.orders: dict[str, dict[str, Any]] = {}
        self.stream_seq = 0
        self.reconnects = 0
        self.ws: ClientConnection | None = None

    def connect(self) -> None:
        """(Re)connect and rebuild state from the snapshot."""
        if self.ws is not None:
            self.ws.close()
            self.reconnects += 1
        self.ws = connect(self.ws_url)
        self.ws.send(json.dumps({"api_key": self.api_key}))
        hello = json.loads(self.ws.recv(timeout=10))
        assert hello["type"] == "authenticated", hello
        snapshot = json.loads(self.ws.recv(timeout=10))
        assert snapshot["type"] == "orders.snapshot", snapshot
        self.orders = {o["order_id"]: o for o in snapshot["data"]["orders"]}
        self.stream_seq = snapshot["stream_seq"]
        print(f"snapshot: {len(self.orders)} orders as of stream_seq {self.stream_seq}")

    def next_event(self, timeout: float) -> dict[str, Any] | None:
        """The next live event, after gap handling; None on timeout."""
        assert self.ws is not None
        try:
            event: dict[str, Any] = json.loads(self.ws.recv(timeout=timeout))
        except TimeoutError:
            return None
        seq = event.get("stream_seq")
        if seq is not None:
            if seq <= self.stream_seq:
                return self.next_event(timeout)  # already in the snapshot
            if seq != self.stream_seq + 1:
                print(f"gap: expected {self.stream_seq + 1}, got {seq}; resyncing")
                self.connect()
                return self.next_event(timeout)
            self.stream_seq = seq
        order_id = event.get("data", {}).get("order_id")
        if order_id:
            self.orders.setdefault(order_id, {}).update(event["data"])
        return event


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--seconds", type=float, default=20.0)
    parser.add_argument(
        "--price", type=float, default=None, help="Resting BUY price (below the bid)"
    )
    parser.add_argument(
        "--url", default=os.environ.get("EDUMATCHER_API_URL", "http://127.0.0.1:8080")
    )
    parser.add_argument("--key", default=os.environ.get("EDUMATCHER_API_KEY", ""))
    args = parser.parse_args(argv)
    ws_url = args.url.replace("http", "ws", 1) + "/api/v1/ws/private"
    rest = ApiGatewayClient(args.url, args.key)

    stream = PrivateStream(ws_url, args.key)
    stream.connect()
    price, _ = resting_price(rest, args.symbol.upper(), args.price)
    placed = rest.post_json(
        "/api/v1/orders",
        {
            "symbol": args.symbol.upper(),
            "side": "BUY",
            "order_type": "LIMIT",
            "quantity": 1,
            "price": price,
        },
    )
    order_id = placed["order_id"]
    rest.delete_json(f"/api/v1/orders/{order_id}")

    seen: list[str] = []
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        event = stream.next_event(timeout=1.0)
        if event is None:
            continue
        if event.get("data", {}).get("order_id") == order_id:
            seen.append(event["type"])
            print(f"  {event['type']:16} stream_seq={event['stream_seq']}")
        if {"order.ack", "order.cancelled"} <= set(seen):
            print(f"done: {len(seen)} events, {stream.reconnects} resyncs")
            return 0
    print(f"timed out; saw {seen}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
