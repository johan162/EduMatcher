"""Stand-in engine process for tests/test_commands_delivery.py.

Not a test module (no test_ prefix). Run as a script:
``python commands_standin_engine.py PULL_ADDR PUB_ADDR RATE``.
Binds the real ``make_puller``/``make_publisher``, streams ``book.S000``
snapshots at RATE messages per second (0 = none) like a busy market, and
answers connect, session-state, volume and halt-all requests with the
engine's own builders. Prints ``ready`` once bound. A separate process,
because in-process the test's own thread would share the GIL with the
"engine" and the timing of a full SUB queue would not be the real one.
"""

from __future__ import annotations

import sys
import time

from edumatcher.engine.order_book import OrderBook
from edumatcher.messaging.bus import make_publisher, make_puller
from edumatcher.models.message import (
    decode,
    make_book_msg,
    make_circuit_breaker_halt_all_ack_msg,
    make_gateway_auth_msg,
    make_session_status_msg,
    make_volume_msg,
)


def main(pull_addr: str, pub_addr: str, rate: float) -> None:
    pull = make_puller(pull_addr)
    pub = make_publisher(pub_addr)
    snap = OrderBook("S000").snapshot()
    snap["bids"] = [{"price": 100.0 - i, "qty": 100, "count": 1} for i in range(10)]
    snap["asks"] = [{"price": 101.0 + i, "qty": 100, "count": 1} for i in range(10)]
    period = 1.0 / rate if rate > 0 else 0.0
    next_at = time.monotonic()
    print("ready", flush=True)
    while True:
        if pull.poll(0 if period else 10):
            topic, p = decode(pull.recv_multipart())
            gw = str(p.get("gateway_id", "")).upper()
            if topic == "system.gateway_connect":
                pub.send_multipart(make_gateway_auth_msg(gw, True))
            elif topic == "system.session_state_request":
                pub.send_multipart(make_session_status_msg(gw, "CONTINUOUS", "", False))
            elif topic == "system.volume_request":
                pub.send_multipart(make_volume_msg(gw, [], 222, 0.0, 0))
            elif topic == "risk.circuit_breaker_halt_all":
                pub.send_multipart(
                    make_circuit_breaker_halt_all_ack_msg(
                        gw, True, halted_symbols=1, halted_symbol_ids=["S000"]
                    )
                )
        if period:
            now = time.monotonic()
            while next_at <= now:
                pub.send_multipart(make_book_msg("S000", snap))
                next_at += period
            time.sleep(min(0.001, max(0.0, next_at - time.monotonic())))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]))
