"""Subscribe to market data, detect gaps per topic, and resume trades.

The rules (WebSocket API Reference, ``/ws/market-data``):

* subscribe with ``items``: independent (symbols x channels) rules, here
  "book for one symbol, trades for every symbol";
* ``seq`` counts per ``topic`` (``book.AAPL``, ``trade.executed``), so gaps
  are tracked per topic, never per ``type``;
* ``trade.executed`` is one topic for every symbol, so its ``seq`` is only
  contiguous on a ``*`` trades subscription -- one symbol's prints skip the
  numbers spent on the others. That is why trades are taken for ``*`` here;
* snapshot channels heal themselves (ask for a ``snapshot``); trades are
  replayed with ``resume`` from the last ``seq`` seen, or ``trades.reset``
  when that is older than the replay window. A replay can overlap what was
  already seen, so trades are de-duplicated by ``id``.

``--trade`` sends one small marketable order (with ``--key`` a trading key)
so the run is sure to see a print.

Needs the ``websockets`` package (``pip install websockets``).

Usage::

    python3 market_data.py --symbol AAPL --seconds 15 --trade
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

from websockets.sync.client import connect

from api_gateway_client import ApiGatewayClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--seconds", type=float, default=15.0)
    parser.add_argument("--trade", action="store_true")
    parser.add_argument(
        "--url", default=os.environ.get("EDUMATCHER_API_URL", "http://127.0.0.1:8080")
    )
    parser.add_argument("--key", default=os.environ.get("EDUMATCHER_API_KEY", ""))
    args = parser.parse_args(argv)
    symbol = args.symbol.upper()
    ws = connect(args.url.replace("http", "ws", 1) + "/api/v1/ws/market-data")
    ws.send(json.dumps({"api_key": args.key}))
    assert json.loads(ws.recv(timeout=10))["type"] == "authenticated"

    ws.send(
        json.dumps(
            {
                "action": "subscribe",
                "items": [
                    {"symbols": [symbol], "channels": ["book"]},
                    {"symbols": ["*"], "channels": ["trades"]},
                ],
            }
        )
    )
    if args.trade:
        ApiGatewayClient(args.url, args.key).post_json(
            "/api/v1/orders",
            {"symbol": symbol, "side": "BUY", "order_type": "MARKET", "quantity": 1},
        )

    last_seq: dict[str, int] = {}
    counts: dict[str, int] = {}
    seen_trades: set[str] = set()
    own_trades = 0
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        try:
            frame: dict[str, Any] = json.loads(ws.recv(timeout=1.0))
        except TimeoutError:
            continue
        kind = frame["type"]
        counts[kind] = counts.get(kind, 0) + 1
        if kind == "subscription":
            print(
                f"subscribed: {frame['data']['items']}, always {frame['data']['always']}"
            )
            continue
        topic, seq = frame.get("topic"), frame.get("seq")
        if topic is not None and seq is not None:
            previous = last_seq.get(topic)
            if previous is not None and seq > previous + 1:
                print(f"gap on {topic}: {previous} -> {seq}")
                if topic == "trade.executed":
                    # No `symbols`: replay every symbol's prints, matching the
                    # `*` subscription the seq was counted on.
                    ws.send(
                        json.dumps(
                            {"action": "resume", "topic": topic, "from_seq": previous}
                        )
                    )
                else:
                    ws.send(
                        json.dumps(
                            {
                                "action": "snapshot",
                                "symbols": [symbol],
                                "channels": ["book"],
                            }
                        )
                    )
            last_seq[topic] = max(seq, previous or 0)
        if kind == "trade":
            data = frame["data"]
            if data["id"] in seen_trades:
                continue  # replayed, already seen
            seen_trades.add(data["id"])
            if data["symbol"] == symbol:
                own_trades += 1
                print(f"trade {data['symbol']} {data['quantity']} @ {data['price']}")
        if counts.get("book") and (own_trades or not args.trade):
            print(f"done: {counts}")
            ws.close()
            return 0
    print(f"timed out: {counts}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
