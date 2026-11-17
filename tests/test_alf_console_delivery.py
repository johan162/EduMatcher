"""A burst never silently costs pm-alf-console its own events, and only the
listener thread touches its SUB sockets (review WP-ACN03: C1, C3, P1).

C1: the SUB socket kept ZeroMQ's default 1000-message receive buffer and also
carries every trade on the exchange, so a busy market evicted the console's
own fills without a word. Every published message carries a per-topic
sequence number; a hole in an own topic is now reported and the console asks
the engine for its orders again.

C3: ``DC|STATE=`` and ``POS|GW=`` called ``setsockopt`` from the prompt
thread on sockets the listener thread was polling.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
import time
from typing import Any
from unittest.mock import patch

import pytest

from edumatcher.models.generated.drop_copy import make_drop_copy_event
from edumatcher.models.message import (
    make_fill_msg,
    make_orders_msg,
    make_position_snapshot_msg,
)
from tests.alf_console_harness import console_harness  # noqa: F401
from tests.conftest import free_ports
from tests.test_alf_console_position_query import (
    _make_gateway as _make_gateway_with_socks,
)

_ORDER = {"symbol": "AAPL", "side": "BUY", "quantity": 1, "order_type": "LIMIT"}


def _own_fill(gateway_id: str, order_id: str = "o1") -> list[bytes]:
    return make_fill_msg(gateway_id, order_id, 1, 100.0, 0, "FILLED", order=_ORDER)


# ---------------------------------------------------------------------------
# 1: the C1 burst, engine side in its own process
# ---------------------------------------------------------------------------

_ENGINE_SIDE = textwrap.dedent("""
    import select, sys, time
    from edumatcher.messaging.bus import make_publisher
    from edumatcher.models.message import make_fill_msg
    from tests.alf_console_harness import trade_frames

    addr, gateway_id, n_trades, n_fills = sys.argv[1:5]
    n_trades, n_fills = int(n_trades), int(n_fills)
    order = {"symbol": "AAPL", "side": "BUY", "quantity": 1, "order_type": "LIMIT"}
    fill = make_fill_msg(gateway_id, "o1", 1, 100.0, 0, "FILLED", order=order)
    trade = trade_frames(1)
    pub = make_publisher(addr)

    def marker(price):
        pub.send_multipart(trade_frames(0, "ZZSYNC", price))

    # Until the console has seen a marker, it is not subscribed yet.
    while not select.select([sys.stdin], [], [], 0.01)[0]:
        marker(1.0)
    sys.stdin.readline()
    every = n_trades // n_fills
    start = time.perf_counter()
    for i in range(n_trades):
        pub.send_multipart(trade)
        if i % every == 0:
            pub.send_multipart(fill)
    elapsed = time.perf_counter() - start
    print(f"{n_trades + n_fills} messages in {elapsed:.3f}s", flush=True)
    while not select.select([sys.stdin], [], [], 0.01)[0]:
        marker(2.0)
    pub.close(linger=0)
""")


def test_burst_of_market_trades_loses_no_own_fill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from edumatcher.alf_console import main as console_main

    pub_port, pull_port, dc_port, ipub_port, ipull_port = free_ports(5)
    pub_addr = f"tcp://127.0.0.1:{pub_port}"
    for name, port in (
        ("ENGINE_PUB_ADDR", pub_port),
        ("ENGINE_PULL_ADDR", pull_port),
        ("DROP_COPY_PUB_ADDR", dc_port),
        ("INDEX_PUB_CONNECT_ADDR", ipub_port),
        ("INDEX_PULL_CONNECT_ADDR", ipull_port),
    ):
        monkeypatch.setattr(console_main, name, f"tcp://127.0.0.1:{port}")

    n_trades, n_fills = 40_000, 2_000
    engine = subprocess.Popen(
        [sys.executable, "-c", _ENGINE_SIDE, pub_addr, "TRADER01"]
        + [str(n_trades), str(n_fills)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    gw = console_main.Gateway("TRADER01")
    # Real Rich output (captured by pytest): printing an own fill is the slow
    # path that lets the trade feed fill the buffer (P1).
    listener = threading.Thread(target=gw._listen, daemon=True)
    listener.start()
    try:
        assert engine.stdin is not None and engine.stdout is not None

        def _wait_marker(price: float) -> None:
            deadline = time.monotonic() + 30
            while gw._last_prices.get("ZZSYNC") != price:
                assert time.monotonic() < deadline, "console never saw the marker"
                time.sleep(0.005)

        _wait_marker(1.0)
        engine.stdin.write("go\n")
        engine.stdin.flush()
        rate = engine.stdout.readline().strip()
        _wait_marker(2.0)
        engine.stdin.write("stop\n")
        engine.stdin.flush()
        engine.wait(timeout=10)
    finally:
        gw._running = False
        listener.join(timeout=5)
        if engine.poll() is None:
            engine.kill()
        for sock in (
            gw.push_sock,
            gw._index_push_sock,
            gw.sub_sock,
            gw._index_sub_sock,
            gw._dc_sub_sock,
        ):
            sock.close(linger=0)

    print(f"engine side published {rate}")
    assert gw._positions["AAPL"]["net_qty"] == n_fills, rate


# ---------------------------------------------------------------------------
# 2: a hole in an own topic's sequence is reported and re-synced
# ---------------------------------------------------------------------------


def _skip_seq(harness: Any, topic: str, count: int) -> None:
    """Make the publisher skip *count* numbers on *topic*, as if the PUB had
    dropped that many messages at its high-water mark."""
    seqs = harness.pub._inner._seq
    seqs[topic.encode()] = seqs.get(topic.encode(), 0) + count


def test_gap_in_own_fill_sequence_warns_and_requests_orders(
    console_harness: Any,  # noqa: F811
) -> None:
    h = console_harness("TRADER01")
    h.pushed(timeout=0.2)

    h.pub.send_multipart(_own_fill("TRADER01", "o1"))
    _skip_seq(h, "order.fill.TRADER01", 2)
    h.pub.send_multipart(_own_fill("TRADER01", "o2"))
    h.sync()

    warnings = [line for line in h.lines if "lost" in line]
    assert len(warnings) == 1, h.lines
    assert "red]" in warnings[0]
    assert "2 event(s)" in warnings[0]
    assert "order.fill" in warnings[0]
    topics = [topic for topic, _ in h.pushed()]
    assert topics.count("order.orders_request") == 1
    # Both fills that did arrive are still booked.
    assert h.gw._positions["AAPL"]["net_qty"] == 2


def test_contiguous_own_sequence_is_silent(
    console_harness: Any,  # noqa: F811
) -> None:
    h = console_harness("TRADER01")
    h.pushed(timeout=0.2)
    for i in range(3):
        h.pub.send_multipart(_own_fill("TRADER01", f"o{i}"))
    h.sync()
    assert not [line for line in h.lines if "lost" in line]
    assert h.pushed(timeout=0.2) == []


def test_gap_in_another_gateways_topic_is_ignored(
    console_harness: Any,  # noqa: F811
) -> None:
    h = console_harness("TRADER1")
    h.pushed(timeout=0.2)
    h.pub.send_multipart(_own_fill("TRADER10", "x1"))
    _skip_seq(h, "order.fill.TRADER10", 5)
    h.pub.send_multipart(_own_fill("TRADER10", "x2"))
    h.sync()
    assert not [line for line in h.lines if "lost" in line]
    assert h.pushed(timeout=0.2) == []


def test_resync_reply_closes_orders_that_finished_during_the_gap() -> None:
    """``order.orders`` lists every resting order; a cached NEW/PARTIAL row
    absent from it finished while its last event was lost."""
    from tests.test_alf_console_quote_ack import _make_gateway

    gw, _push = _make_gateway("TRADER01")
    gw.order_cache["gone"] = {"id": "gone", "status": "PARTIAL", "remaining": 4}
    gw.order_cache["rests"] = {"id": "rests", "status": "NEW", "remaining": 5}
    gw.order_cache["sent"] = {"id": "sent", "status": "PENDING", "remaining": 5}
    gw.order_cache["done"] = {"id": "done", "status": "FILLED", "remaining": 0}
    from edumatcher.models.message import decode

    topic, payload = decode(
        make_orders_msg(
            "TRADER01",
            [
                {
                    "id": "rests",
                    "symbol": "AAPL",
                    "side": "BUY",
                    "order_type": "LIMIT",
                    "tif": "DAY",
                    "quantity": 5,
                    "remaining_qty": 5,
                    "price": 1.0,
                    "status": "NEW",
                    "ts_ns": 1,
                }
            ],
        )
    )
    with patch("edumatcher.alf_console.main.console.print"):
        gw._handle_event(topic, payload)

    assert gw.order_cache["gone"]["status"] == "CLOSED"
    assert gw.order_cache["rests"]["status"] == "NEW"
    assert gw.order_cache["sent"]["status"] == "PENDING"
    assert gw.order_cache["done"]["status"] == "FILLED"


# ---------------------------------------------------------------------------
# 3: the prompt thread never calls setsockopt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("line", ["DC|STATE=ON", "DC|STATE=OFF", "POS|GW=MM_X"])
def test_prompt_commands_make_no_setsockopt_call(line: str) -> None:
    gw, _push, sub, index_sub, dc_sub = _make_gateway_with_socks("GW01")
    for sock in (sub, index_sub, dc_sub):
        sock.reset_mock()

    with patch("edumatcher.alf_console.main.console.print"):
        gw._parse_and_send("DC|STATE=ON")
        gw._parse_and_send(line)
        gw._handle_event(
            "system.position_snapshot.MM_X", {"gateway_id": "MM_X", "positions": []}
        )

    for sock in (sub, index_sub, dc_sub):
        sock.setsockopt.assert_not_called()


# ---------------------------------------------------------------------------
# 4: POS|GW= and DC still behave as before, over real sockets
# ---------------------------------------------------------------------------


def test_pos_gw_prints_the_asked_gateway_and_ignores_another(
    console_harness: Any,  # noqa: F811
) -> None:
    h = console_harness("TRADER01")
    with patch("edumatcher.alf_console.main.print_remote_position") as mock_print:
        h.gw._parse_and_send("POS|GW=MM_A")
        h.pub.send_multipart(
            make_position_snapshot_msg(
                "MM_B", [{"symbol": "AAPL", "net_qty": 7, "avg_cost": 1.0}]
            )
        )
        h.pub.send_multipart(
            make_position_snapshot_msg(
                "MM_A", [{"symbol": "AAPL", "net_qty": 5, "avg_cost": 2.0}]
            )
        )
        h.sync()

    mock_print.assert_called_once()
    assert mock_print.call_args.args[0] == "MM_A"
    assert mock_print.call_args.args[1][0]["net_qty"] == 5


def _dc_event(gateway_id: str, seq: int) -> list[bytes]:
    return make_drop_copy_event(
        seq=seq,
        timestamp=time.time_ns(),
        gateway_id=gateway_id,
        event_type="order.fill",
        order_id="o1",
        trade_ids=["t1"],
        symbol="AAPL",
        fill_qty=1,
        fill_price=100.0,
        liquidity_flag="TAKER",
    )


def test_drop_copy_shown_only_while_on(
    console_harness: Any,  # noqa: F811
) -> None:
    h = console_harness("TRADER01")

    def _wait_for(count: int) -> None:
        deadline = time.monotonic() + 5
        while len([x for x in h.lines if "DC_FILL" in x]) < count:
            assert time.monotonic() < deadline, h.lines
            h.dc_pub.send_multipart(_dc_event("TRADER01", 100 + count))
            time.sleep(0.02)

    h.dc_pub.send_multipart(_dc_event("TRADER01", 1))
    time.sleep(0.2)
    assert not [x for x in h.lines if "DC_FILL" in x]

    h.gw._parse_and_send("DC|STATE=ON")
    _wait_for(1)

    h.gw._parse_and_send("DC|STATE=OFF")
    time.sleep(0.1)
    before = len([x for x in h.lines if "DC_FILL" in x])
    h.dc_pub.send_multipart(_dc_event("TRADER01", 999))
    time.sleep(0.2)
    assert len([x for x in h.lines if "DC_FILL" in x]) == before
