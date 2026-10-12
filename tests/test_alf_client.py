"""edumatcher.alf_client: line building, parsing and a live session."""

from __future__ import annotations

import threading
import time
from collections.abc import Generator
from typing import Any

import pytest
import zmq

from edumatcher.alf_client import protocol as p
from edumatcher.alf_client.connection import AlfConnection, State
from edumatcher.alf_gwy.config import AlfGatewayConfig
from edumatcher.alf_gwy.gateway import AlfGateway
from edumatcher.models.message import decode, encode
from tests.conftest import free_ports, wait_for_listener


class TestProtocol:
    @pytest.mark.parametrize(
        ("ticks", "decimals", "text"),
        [
            (12345, 2, "123.45"),
            (5, 2, "0.05"),
            (100, 0, "100"),
            (1, 4, "0.0001"),
            (-150, 2, "-1.50"),
        ],
    )
    def test_price_is_exact(self, ticks: int, decimals: int, text: str) -> None:
        assert p.price(ticks, decimals) == text

    def test_hello(self) -> None:
        assert p.hello("AI001", "swarm") == b"HELLO|CLIENT=swarm|PROTO=ALF1|ID=AI001\n"
        assert p.hello("AI001", "s", feed="ORDERS").endswith(b"|FEED=ORDERS\n")

    def test_new_limit(self) -> None:
        line = p.new_order(
            tag="AI001-1",
            symbol="AAPL",
            side="BUY",
            order_type="LIMIT",
            tif="DAY",
            qty=10,
            tick_decimals=2,
            price_ticks=10050,
        )
        assert (
            line
            == b"NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=10|TIF=DAY|TAG=AI001-1|PRICE=100.50\n"
        )

    def test_new_every_optional_field(self) -> None:
        line = p.new_order(
            tag="T",
            symbol="X",
            side="SELL",
            order_type="ICEBERG",
            tif="GTC",
            qty=9,
            tick_decimals=1,
            price_ticks=10,
            stop_price_ticks=9,
            trail_offset_ticks=2,
            visible_qty=3,
        ).decode()
        assert "|PRICE=1.0|" in line and "|STOP=0.9|" in line and "|TRAIL=0.2|" in line
        assert line.endswith("|VISIBLE=3\n")

    def test_oco(self) -> None:
        line = p.new_oco(
            oco_id="AI001-9",
            symbol="AAPL",
            qty=5,
            tif="DAY",
            tick_decimals=2,
            legs=(
                {"side": "SELL", "order_type": "LIMIT", "price_ticks": 11000},
                {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 9000},
            ),
        ).decode()
        assert line.startswith("NEW|TYPE=OCO|OCO_ID=AI001-9|SYM=AAPL|QTY=5|TIF=DAY|")
        assert (
            "LEG1_PRICE=110.00" in line
            and "LEG2_STOP=90.00" in line
            and "TAG=AI001-9" in line
        )

    def test_cancel_and_friends(self) -> None:
        assert p.cancel("abc123", "CXL-1") == b"CANCEL|ID=abc123|RTAG=CXL-1\n"
        assert p.cancel("abc123") == b"CANCEL|ID=abc123\n"
        assert p.cancel_oco("O1") == b"CANCEL|OCO_ID=O1\n"
        assert p.position_request("AI001") == b"POS|GW=AI001\n"
        assert p.ping() == b"PING\n" and p.bye() == b"EXIT\n"

    def test_parse_keeps_value_case(self) -> None:
        msg = p.parse_response(
            "ack|order_id=ab12cd|ACCEPTED=TRUE|TAG=AI001-1|reason=Market is closed"
        )
        assert msg is not None
        assert msg.msg_type == "ACK"
        assert msg.get("ORDER_ID") == "ab12cd"  # lowercase order ids survive
        assert msg.get("REASON") == "Market is closed"
        assert msg.flag("ACCEPTED") and not msg.flag("MISSING")

    def test_parse_edge_cases(self) -> None:
        assert p.parse_response("   ") is None
        msg = p.parse_response("HB|junk|=x|K=a=b")
        assert msg is not None and msg.fields == {"K": "a=b"}


# --- live session against a real AlfGateway (fake engine sockets) ---------------------


@pytest.fixture()
def gateway() -> (
    Generator[tuple[zmq.Socket[bytes], zmq.Socket[bytes], int], None, None]
):
    pull_port, pub_port, gw_port = free_ports(3)
    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
    pull = ctx.socket(zmq.PULL)
    pull.bind(f"tcp://127.0.0.1:{pull_port}")
    pub = ctx.socket(zmq.PUB)
    pub.bind(f"tcp://127.0.0.1:{pub_port}")
    cfg = AlfGatewayConfig(
        name="alf-test",
        bind_address="127.0.0.1",
        port=gw_port,
        engine_pull_addr=f"tcp://127.0.0.1:{pull_port}",
        engine_pub_addr=f"tcp://127.0.0.1:{pub_port}",
        heartbeat_interval_sec=60,
        idle_timeout_sec=60,
        max_connections=16,
        max_commands_per_second=1000,
        gateway_roles=(("AI001", "TRADER"),),
    )
    gw = AlfGateway(cfg)
    t = threading.Thread(target=gw.run, daemon=True)
    t.start()
    wait_for_listener("127.0.0.1", gw_port)
    time.sleep(0.1)
    try:
        yield pull, pub, gw_port
    finally:
        gw.stop()
        t.join(timeout=2.0)
        pull.close()
        pub.close()


def _engine_recv(
    pull: zmq.Socket[bytes], prefix: str, timeout: float = 3.0
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pull.poll(100):
            topic, payload = decode(pull.recv_multipart())
            if topic.startswith(prefix):
                return payload
    raise TimeoutError(prefix)


def _client_wait(
    conn: AlfConnection, msg_type: str, timeout: float = 3.0
) -> p.AlfMessage:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        conn.flush()
        for msg in conn.read():
            if msg.msg_type == msg_type:
                return msg
        time.sleep(0.01)
    raise TimeoutError(msg_type)


def _state(conn: AlfConnection) -> State:
    return conn.state


def _logged_on(
    pull: zmq.Socket[bytes], pub: zmq.Socket[bytes], port: int
) -> AlfConnection:
    conn = AlfConnection("127.0.0.1", port, "ai001", client="test")
    conn.open(now=0.0)
    assert conn.state == State.HELLO_SENT
    _engine_recv(pull, "system.gateway_connect")
    time.sleep(0.1)
    pub.send_multipart(
        encode("system.gateway_auth.AI001", {"gateway_id": "AI001", "accepted": True})
    )
    _client_wait(conn, "WELCOME")
    assert _state(conn) == State.READY
    _engine_recv(pull, "system.symbols_request")  # sent by the gateway on logon
    pub.send_multipart(
        encode(
            "system.symbols.AI001",
            {"symbols": [{"symbol": "AAPL", "tick_decimals": 2}]},
        )
    )
    _client_wait(conn, "SYMBOL")
    return conn


def test_round_trip(gateway: tuple[zmq.Socket[bytes], zmq.Socket[bytes], int]) -> None:
    pull, pub, port = gateway
    conn = _logged_on(pull, pub, port)

    conn.send(
        p.new_order(
            tag="AI001-1",
            symbol="AAPL",
            side="BUY",
            order_type="LIMIT",
            tif="DAY",
            qty=10,
            tick_decimals=2,
            price_ticks=10050,
        ),
        now=0.0,
    )
    conn.flush()
    order = _engine_recv(pull, "order.new")
    assert (order["price_ticks"], order["client_tag"], order["gateway_id"]) == (
        10050,
        "AI001-1",
        "AI001",
    )

    pub.send_multipart(
        encode(
            "order.ack.AI001",
            {
                "gateway_id": "AI001",
                "order_id": "ab12",
                "accepted": True,
                "client_tag": "AI001-1",
                "symbol": "AAPL",
            },
        )
    )
    ack = _client_wait(conn, "ACK")
    assert (ack.get("ORDER_ID"), ack.get("TAG"), ack.flag("ACCEPTED")) == (
        "ab12",
        "AI001-1",
        True,
    )

    conn.send(p.cancel("ab12", "CXL-AI001-1"), now=0.0)
    conn.flush()
    cxl = _engine_recv(pull, "order.cancel")
    assert (cxl["order_id"], cxl["request_tag"]) == (
        "ab12",
        "CXL-AI001-1",
    )  # case preserved end to end

    conn.send(
        p.new_oco(
            oco_id="AI001-2",
            symbol="AAPL",
            qty=5,
            tif="DAY",
            tick_decimals=2,
            legs=(
                {"side": "SELL", "order_type": "LIMIT", "price_ticks": 11000},
                {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 9000},
            ),
        ),
        now=0.0,
    )
    conn.flush()
    oco = _engine_recv(pull, "order.oco")
    assert (
        oco["leg1"]["price_ticks"] == 11000 and oco["leg2"]["stop_price_ticks"] == 9000
    )

    conn.send(p.position_request("AI001"), now=0.0)
    conn.flush()
    _engine_recv(pull, "system.position_request")
    time.sleep(0.1)
    pub.send_multipart(
        encode(
            "system.position_snapshot.AI001",
            {
                "gateway_id": "AI001",
                "positions": [{"symbol": "AAPL", "net_qty": -3, "avg_cost": 100.5}],
            },
        )
    )
    assert _client_wait(conn, "POSITION").get("COUNT") == "1"

    conn.close()
    assert conn.state == State.CLOSED and not conn.is_open


def test_validation_error_comes_back_tagged(
    gateway: tuple[zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    pull, pub, port = gateway
    conn = _logged_on(pull, pub, port)
    conn.send(
        p.new_order(
            tag="AI001-7",
            symbol="NOPE",
            side="BUY",
            order_type="LIMIT",
            tif="DAY",
            qty=1,
            tick_decimals=2,
            price_ticks=1,
        ),
        now=0.0,
    )
    err = _client_wait(conn, "ERR")
    assert err.get("TAG") == "AI001-7" and err.get("REJECT_CODE") == "UNKNOWN_SYMBOL"
    conn.close()


def test_refused_logon(
    gateway: tuple[zmq.Socket[bytes], zmq.Socket[bytes], int],
) -> None:
    pull, pub, port = gateway
    conn = AlfConnection("127.0.0.1", port, "AI001")
    conn.open(now=0.0)
    _engine_recv(pull, "system.gateway_connect")
    time.sleep(0.1)
    pub.send_multipart(
        encode(
            "system.gateway_auth.AI001",
            {
                "gateway_id": "AI001",
                "accepted": False,
                "reason": "Gateway not configured: AI001",
            },
        )
    )
    err = _client_wait(conn, "ERR")
    assert err.get("CODE") == "AUTH_FAILED"
    deadline = time.monotonic() + 3
    while conn.is_open and time.monotonic() < deadline:
        conn.read()
        time.sleep(0.02)
    assert not conn.is_open and conn.close_reason == "closed by gateway"


def test_ping_keeps_the_session_alive() -> None:
    conn = AlfConnection("127.0.0.1", 1, "AI001")
    conn.state = State.READY
    conn._sock = object()  # never flushed: tick() only queues
    conn._out = bytearray()
    conn.flush = lambda: None
    conn.tick(now=11.0)
    assert bytes(conn._out) == b"PING\n"
    conn.tick(now=12.0)
    assert bytes(conn._out) == b"PING\n"  # not again within the interval
    conn._sock = None


def test_unreachable_gateway_raises() -> None:
    (port,) = free_ports(1)
    with pytest.raises(OSError):
        AlfConnection("127.0.0.1", port, "AI001").open(now=0.0, timeout=0.5)
