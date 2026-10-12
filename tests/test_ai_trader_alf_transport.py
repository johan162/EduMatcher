"""AlfTransport: every agent action through a real pm-alf-gwy, and back."""

from __future__ import annotations

import threading
import time
from collections.abc import Generator
from typing import Any

import pytest
import zmq

from edumatcher.ai_trader.actions import (
    CancelOco,
    CancelOrder,
    NewOco,
    NewOrder,
    OcoLegSpec,
)
from edumatcher.ai_trader.transport import (
    RECONNECT_MAX,
    AckEvent,
    AlfTransport,
    DoneEvent,
    FillEvent,
    OcoAckEvent,
    PositionsEvent,
    SessionEvent,
    _Session,
)
from edumatcher.alf_client.connection import AlfConnection
from edumatcher.alf_gwy.config import AlfGatewayConfig
from edumatcher.alf_gwy.gateway import AlfGateway
from edumatcher.models.message import decode, encode
from edumatcher.models.order import TIF, OrderType
from tests.conftest import free_ports, wait_for_listener

IDS = ("AI001", "AI002")


class _Exchange:
    """A real AlfGateway in a thread, with fake engine sockets around it."""

    def __init__(self) -> None:
        self.pull_port, self.pub_port, self.port = free_ports(3)
        ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
        self.pull = ctx.socket(zmq.PULL)
        self.pull.bind(f"tcp://127.0.0.1:{self.pull_port}")
        self.pub = ctx.socket(zmq.PUB)
        self.pub.bind(f"tcp://127.0.0.1:{self.pub_port}")
        self.gw: AlfGateway | None = None
        self.thread: threading.Thread | None = None
        self.auto_auth = True
        self.received: list[tuple[str, dict[str, Any]]] = []

    def start(self) -> None:
        cfg = AlfGatewayConfig(
            name="t",
            bind_address="127.0.0.1",
            port=self.port,
            engine_pull_addr=f"tcp://127.0.0.1:{self.pull_port}",
            engine_pub_addr=f"tcp://127.0.0.1:{self.pub_port}",
            heartbeat_interval_sec=60,
            idle_timeout_sec=60,
            max_commands_per_second=1000,
            gateway_roles=tuple((i, "TRADER") for i in IDS),
        )
        self.gw = AlfGateway(cfg)
        self.thread = threading.Thread(target=self.gw.run, daemon=True)
        self.thread.start()
        wait_for_listener("127.0.0.1", self.port)
        time.sleep(0.1)

    def stop(self) -> None:
        if self.gw is not None and self.thread is not None:
            self.gw.stop()
            self.thread.join(timeout=3.0)
            self.gw = None

    def serve(self, seconds: float = 0.05) -> None:
        """Answer logons and symbol requests; record everything else."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if not self.pull.poll(10):
                continue
            topic, payload = decode(self.pull.recv_multipart())
            if topic == "system.gateway_connect" and self.auto_auth:
                gid = payload["gateway_id"]
                self.pub.send_multipart(
                    encode(
                        f"system.gateway_auth.{gid}",
                        {"gateway_id": gid, "accepted": True},
                    )
                )
            elif topic == "system.symbols_request":
                gid = payload["gateway_id"]
                self.pub.send_multipart(
                    encode(
                        f"system.symbols.{gid}",
                        {"symbols": [{"symbol": "AAPL", "tick_decimals": 2}]},
                    )
                )
            else:
                self.received.append((topic, payload))

    def wait_for(self, prefix: str, timeout: float = 3.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for i, (topic, payload) in enumerate(self.received):
                if topic.startswith(prefix):
                    del self.received[i]
                    return payload
            self.serve(0.02)
        raise TimeoutError(prefix)


@pytest.fixture()
def exchange() -> Generator[_Exchange, None, None]:
    ex = _Exchange()
    ex.start()
    try:
        yield ex
    finally:
        ex.stop()
        ex.pull.close()
        ex.pub.close()


def _connected(ex: _Exchange) -> AlfTransport:
    t = AlfTransport("127.0.0.1", ex.port, seed=1)
    result: dict[str, set[str]] = {}
    th = threading.Thread(
        target=lambda: result.update(ok=t.connect(list(IDS), timeout=5.0))
    )
    th.start()
    while th.is_alive():
        ex.serve(0.02)
    assert result["ok"] == set(IDS)
    ex.serve(0.3)  # symbols replies, so the gateway knows AAPL
    return t


def _events(
    t: AlfTransport, ex: _Exchange, until: Any, timeout: float = 3.0
) -> list[tuple[str, Any]]:
    got: list[tuple[str, Any]] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        got += t.poll_events(list(IDS))
        if until(got):
            return got
        ex.serve(0.02)
    raise TimeoutError(got)


ORDERS: list[tuple[NewOrder, dict[str, object]]] = [
    (
        NewOrder(
            "AI001-1", "AAPL", "BUY", OrderType.LIMIT, TIF.DAY, 10, price_ticks=10050
        ),
        {"order_type": "LIMIT", "price_ticks": 10050, "tif": "DAY"},
    ),
    (
        NewOrder("AI001-2", "AAPL", "SELL", OrderType.MARKET, TIF.DAY, 10),
        {"order_type": "MARKET"},
    ),
    (
        NewOrder(
            "AI001-3", "AAPL", "BUY", OrderType.IOC, TIF.DAY, 5, price_ticks=10001
        ),
        {"order_type": "IOC", "price_ticks": 10001},
    ),
    (
        NewOrder(
            "AI001-4", "AAPL", "BUY", OrderType.FOK, TIF.DAY, 5, price_ticks=10001
        ),
        {"order_type": "FOK"},
    ),
    (
        NewOrder(
            "AI001-5",
            "AAPL",
            "SELL",
            OrderType.ICEBERG,
            TIF.GTC,
            10,
            price_ticks=10100,
            visible_qty=2,
        ),
        {"order_type": "ICEBERG", "visible_qty": 2, "tif": "GTC"},
    ),
    (
        NewOrder(
            "AI001-6",
            "AAPL",
            "SELL",
            OrderType.STOP,
            TIF.DAY,
            10,
            stop_price_ticks=9900,
        ),
        {"order_type": "STOP", "stop_price_ticks": 9900},
    ),
    (
        NewOrder(
            "AI001-7",
            "AAPL",
            "SELL",
            OrderType.STOP_LIMIT,
            TIF.DAY,
            10,
            price_ticks=9890,
            stop_price_ticks=9900,
        ),
        {"order_type": "STOP_LIMIT", "price_ticks": 9890, "stop_price_ticks": 9900},
    ),
    (
        NewOrder(
            "AI001-8",
            "AAPL",
            "SELL",
            OrderType.TRAILING_STOP,
            TIF.DAY,
            10,
            trail_offset_ticks=25,
        ),
        {"order_type": "TRAILING_STOP", "trail_offset_ticks": 25},
    ),
    (
        NewOrder(
            "AI001-9", "AAPL", "BUY", OrderType.LIMIT, TIF.ATO, 1, price_ticks=10000
        ),
        {"tif": "ATO"},
    ),
    (
        NewOrder(
            "AI001-A", "AAPL", "BUY", OrderType.LIMIT, TIF.ATC, 1, price_ticks=10000
        ),
        {"tif": "ATC"},
    ),
]


def test_every_order_type_reaches_the_engine_exactly(exchange: _Exchange) -> None:
    t = _connected(exchange)
    for action, expect in ORDERS:
        assert t.send("AI001", action, 2)
        order = exchange.wait_for("order.new")
        assert order["client_tag"] == action.tag and order["gateway_id"] == "AI001"
        assert order["quantity"] == action.qty and order["side"] == action.side
        for key, value in expect.items():
            assert order[key] == value, (action.tag, key)
    t.close()


def test_cancel_oco_and_cancel_oco(exchange: _Exchange) -> None:
    t = _connected(exchange)
    t.send("AI001", CancelOrder("ab12cd", "AI001-1", "AAPL"), 2)
    cxl = exchange.wait_for("order.cancel")
    assert (cxl["order_id"], cxl["request_tag"]) == ("ab12cd", "CXL-AI001-1")
    oco = NewOco(
        "AI001-B",
        "AAPL",
        7,
        TIF.DAY,
        OcoLegSpec("SELL", OrderType.LIMIT, price_ticks=11000),
        OcoLegSpec("SELL", OrderType.STOP, stop_price_ticks=9000),
    )
    t.send("AI001", oco, 2)
    p = exchange.wait_for("order.oco")
    assert (p["oco_id"], p["quantity"], p["client_tag"]) == ("AI001-B", 7, "AI001-B")
    assert p["leg1"] == {"side": "SELL", "order_type": "LIMIT", "price_ticks": 11000}
    assert p["leg2"] == {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 9000}
    t.send("AI001", CancelOco("AI001-B", "AAPL"), 2)
    assert exchange.wait_for("order.oco_cancel")["oco_id"] == "AI001-B"
    t.close()


def test_events_come_back_as_agent_events(exchange: _Exchange) -> None:
    t = _connected(exchange)
    pub = exchange.pub
    pub.send_multipart(
        encode(
            "order.ack.AI001",
            {
                "gateway_id": "AI001",
                "order_id": "ab12",
                "accepted": True,
                "client_tag": "AI001-1",
            },
        )
    )
    pub.send_multipart(
        encode(
            "order.fill.AI001",
            {
                "gateway_id": "AI001",
                "order_id": "ab12",
                "fill_qty": 4,
                "fill_price": 100.5,
                "remaining_qty": 6,
                "status": "PARTIAL",
                "symbol": "AAPL",
                "side": "BUY",
                "client_tag": "AI001-1",
            },
        )
    )
    pub.send_multipart(
        encode(
            "order.cancelled.AI001",
            {"gateway_id": "AI001", "order_id": "ab12", "client_tag": "AI001-1"},
        )
    )
    pub.send_multipart(
        encode(
            "order.ack.AI001",
            {
                "gateway_id": "AI001",
                "order_id": "zz",
                "accepted": False,
                "reject_code": "ORDER_NOT_FOUND",
                "reason": "Order not found",
                "request_tag": "CXL-AI001-9",
            },
        )
    )
    pub.send_multipart(
        encode(
            "oco.ack.AI002",
            {
                "gateway_id": "AI002",
                "oco_id": "AI002-1",
                "accepted": True,
                "order_id_1": "l1",
                "order_id_2": "l2",
            },
        )
    )
    pub.send_multipart(
        encode(
            "oco.cancelled.AI002",
            {"gateway_id": "AI002", "oco_id": "AI002-1", "cancelled_order_id": "l2"},
        )
    )
    got = _events(t, exchange, lambda g: len(g) >= 6)
    assert ("AI001", AckEvent("ab12", "AI001-1", True, None, "", None)) in got
    assert ("AI001", FillEvent("ab12", "AI001-1", "AAPL", "BUY", 4, 100.5, 6)) in got
    assert ("AI001", DoneEvent("ab12", "AI001-1")) in got
    assert (
        "AI001",
        AckEvent(
            "zz", None, False, "ORDER_NOT_FOUND", "Order not found", "CXL-AI001-9"
        ),
    ) in got
    assert ("AI002", OcoAckEvent("AI002-1", True, ("l1", "l2"), "")) in got
    assert ("AI002", DoneEvent("l2", None)) in got
    t.close()


def test_gateway_refusals_become_rejects(exchange: _Exchange) -> None:
    t = _connected(exchange)
    t.send(
        "AI001",
        NewOrder("AI001-5", "NOPE", "BUY", OrderType.LIMIT, TIF.DAY, 1, price_ticks=1),
        2,
    )
    got = _events(t, exchange, lambda g: g)
    [(gw, ev)] = got
    assert (
        gw == "AI001"
        and ev.tag == "AI001-5"
        and not ev.accepted
        and ev.code == "UNKNOWN_SYMBOL"
    )
    assert ev.request_tag is None
    t.close()


def test_positions(exchange: _Exchange) -> None:
    t = _connected(exchange)
    t.request_positions("AI002")
    exchange.wait_for("system.position_request")
    time.sleep(0.1)
    exchange.pub.send_multipart(
        encode(
            "system.position_snapshot.AI002",
            {
                "gateway_id": "AI002",
                "positions": [
                    {"symbol": "AAPL", "net_qty": -3, "avg_cost": 100.5},
                    {"symbol": "MSFT", "net_qty": 2, "avg_cost": 1.0},
                ],
            },
        )
    )
    got = _events(t, exchange, lambda g: g)
    assert got == [("AI002", PositionsEvent({"AAPL": (-3, 100.5), "MSFT": (2, 1.0)}))]
    t.close()


def test_refused_participant_is_not_accepted(exchange: _Exchange) -> None:
    exchange.auto_auth = False
    t = AlfTransport("127.0.0.1", exchange.port)
    result: dict[str, set[str]] = {}
    th = threading.Thread(
        target=lambda: result.update(ok=t.connect(["AI001"], timeout=3.0))
    )
    th.start()
    payload = None
    while th.is_alive():
        exchange.serve(0.02)
        for topic, p in exchange.received:
            if topic == "system.gateway_connect" and payload is None:
                payload = p
                exchange.pub.send_multipart(
                    encode(
                        "system.gateway_auth.AI001",
                        {
                            "gateway_id": "AI001",
                            "accepted": False,
                            "reason": "Gateway not configured: AI001",
                        },
                    )
                )
    assert result["ok"] == set()
    t.close()


def test_lost_gateway_reconnects_and_reports(exchange: _Exchange) -> None:
    t = _connected(exchange)
    assert t.is_up("AI001")
    exchange.stop()  # gateway gone: sessions close
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and any(
        s.conn.is_open for s in t._sessions.values()
    ):
        t.poll_events(list(IDS))
        time.sleep(0.05)
    assert (
        t.send(
            "AI001",
            NewOrder(
                "AI001-1", "AAPL", "BUY", OrderType.LIMIT, TIF.DAY, 1, price_ticks=1
            ),
            2,
        )
        is False
    )
    assert (
        t.maintain(time.monotonic()) == []
    )  # lost, first retry fails: gateway still down
    exchange.start()  # same port
    events: list[tuple[str, Any]] = []
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and len(events) < 2:
        events += t.maintain(time.monotonic())
        for s in t._sessions.values():
            s.conn.read()
        exchange.serve(0.05)
    assert sorted(events) == [
        ("AI001", SessionEvent(True)),
        ("AI002", SessionEvent(True)),
    ]
    assert t.is_up("AI001") and not t.is_up("NOBODY")
    t.close()


def test_reconnect_backoff_never_exceeds_the_cap() -> None:
    (port,) = free_ports(1)  # nothing listens
    t = AlfTransport("127.0.0.1", port, seed=3)
    t._sessions["AI001"] = _Session(AlfConnection("127.0.0.1", port, "AI001", "x"))
    now = 0.0
    for _ in range(20):
        t.maintain(now)
        gap = t._sessions["AI001"].retry_at - now
        assert 0 < gap <= RECONNECT_MAX
        now = t._sessions["AI001"].retry_at
