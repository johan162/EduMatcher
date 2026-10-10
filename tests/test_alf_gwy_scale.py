"""pm-alf-gwy at scale: readiness loop, FEED=ORDERS, FILL fields, fd limit."""

from __future__ import annotations

import resource
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
from edumatcher.alf_gwy.protocol import build_line
from edumatcher.models.message import decode, encode
from tests.conftest import free_ports, wait_for_listener


@pytest.fixture()
def gateway() -> (
    Generator[tuple[AlfGateway, zmq.Socket[bytes], zmq.Socket[bytes], int], None, None]
):
    pull_port, pub_port, gw_port = free_ports(3)
    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
    pull = ctx.socket(zmq.PULL)
    pull.bind(f"tcp://127.0.0.1:{pull_port}")
    pub = ctx.socket(zmq.PUB)
    pub.bind(f"tcp://127.0.0.1:{pub_port}")
    ids = [f"AI{i:03d}" for i in range(1, 401)]
    cfg = AlfGatewayConfig(
        name="alf-test",
        bind_address="127.0.0.1",
        port=gw_port,
        engine_pull_addr=f"tcp://127.0.0.1:{pull_port}",
        engine_pub_addr=f"tcp://127.0.0.1:{pub_port}",
        heartbeat_interval_sec=60,
        idle_timeout_sec=60,
        max_commands_per_second=1000,
        gateway_roles=tuple((i, "TRADER") for i in ids),
    )
    gw = AlfGateway(cfg)
    t = threading.Thread(target=gw.run, daemon=True)
    t.start()
    wait_for_listener("127.0.0.1", gw_port)
    time.sleep(0.1)
    try:
        yield gw, pull, pub, gw_port
    finally:
        gw.stop()
        t.join(timeout=5.0)
        pull.close()
        pub.close()


def _pump(
    conns: list[AlfConnection], until: Any, timeout: float = 5.0
) -> dict[str, list[p.AlfMessage]]:
    got: dict[str, list[p.AlfMessage]] = {c.gateway_id: [] for c in conns}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for c in conns:
            c.flush()
            got[c.gateway_id] += c.read()
        if until(got):
            return got
        time.sleep(0.01)
    raise TimeoutError("condition not met")


def _logon(
    pull: zmq.Socket[bytes],
    pub: zmq.Socket[bytes],
    port: int,
    ids: list[str],
    feed: str | None = None,
) -> list[AlfConnection]:
    conns = []
    for gid in ids:
        c = AlfConnection("127.0.0.1", port, gid, client="t", feed=feed)
        c.open(now=0.0)
        conns.append(c)
    pending = set(ids)
    deadline = time.monotonic() + 10
    while pending and time.monotonic() < deadline:
        for c in conns:
            c.flush()
        if pull.poll(50):
            topic, payload = decode(pull.recv_multipart())
            if topic == "system.gateway_connect":
                gid = payload["gateway_id"]
                pending.discard(gid)
                pub.send_multipart(
                    encode(
                        f"system.gateway_auth.{gid}",
                        {"gateway_id": gid, "accepted": True},
                    )
                )
    assert not pending
    _pump(conns, lambda got: all(c.state == State.READY for c in conns), timeout=10)
    return conns


def test_feed_orders_suppresses_public_broadcasts(gateway: Any) -> None:
    _, pull, pub, port = gateway
    [full] = _logon(pull, pub, port, ["AI001"])
    [orders_only] = _logon(pull, pub, port, ["AI002"], feed="ORDERS")
    time.sleep(0.2)
    pub.send_multipart(
        encode(
            "trade.executed",
            {"symbol": "AAPL", "price": 1.0, "quantity": 1, "aggressor_side": "BUY"},
        )
    )
    pub.send_multipart(
        encode(
            "order.ack.AI002",
            {"gateway_id": "AI002", "order_id": "x1", "accepted": True},
        )
    )
    got = _pump(
        [full, orders_only],
        lambda g: any(m.msg_type == "TRADE" for m in g["AI001"])
        and any(m.msg_type == "ACK" for m in g["AI002"]),
    )
    assert not any(m.msg_type == "TRADE" for m in got["AI002"])  # suppressed
    assert any(m.msg_type == "ACK" for m in got["AI002"])  # own events still delivered


def test_invalid_feed_is_refused(gateway: Any) -> None:
    _, _, _, port = gateway
    c = AlfConnection("127.0.0.1", port, "AI003", feed="SOME")
    c.open(now=0.0)
    got = _pump([c], lambda g: any(m.msg_type == "ERR" for m in g["AI003"]))
    assert any(m.get("CODE") == "INVALID_VALUE" for m in got["AI003"])


def test_fill_names_symbol_and_side(gateway: Any) -> None:
    _, pull, pub, port = gateway
    [c] = _logon(pull, pub, port, ["AI004"])
    time.sleep(0.2)
    pub.send_multipart(
        encode(
            "order.fill.AI004",
            {
                "gateway_id": "AI004",
                "order_id": "ab",
                "fill_qty": 3,
                "fill_price": 1.5,
                "remaining_qty": 0,
                "status": "FILLED",
                "symbol": "AAPL",
                "side": "SELL",
                "trade_ids": ["t1"],
                "client_tag": "AI004-1",
            },
        )
    )
    got = _pump([c], lambda g: any(m.msg_type == "FILL" for m in g["AI004"]))
    fill = next(m for m in got["AI004"] if m.msg_type == "FILL")
    assert (fill.get("SYMBOL"), fill.get("SIDE"), fill.get("TAG")) == (
        "AAPL",
        "SELL",
        "AI004-1",
    )


def test_broadcast_line_is_built_once(
    gateway: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    gw, pull, pub, port = gateway
    _logon(pull, pub, port, [f"AI{i:03d}" for i in range(10, 20)])
    calls: list[str] = []

    def counting(msg_type: str, fields: dict[str, str] | None = None) -> bytes:
        calls.append(msg_type)
        return build_line(msg_type, fields)

    monkeypatch.setattr("edumatcher.alf_gwy.gateway.build_line", counting)
    gw._broadcast("TRADE", {"SYMBOL": "AAPL"})
    assert calls.count("TRADE") == 1


def test_three_hundred_sessions_round_trip(gateway: Any) -> None:
    _, pull, pub, port = gateway
    ids = [f"AI{i:03d}" for i in range(100, 400)]
    conns = _logon(pull, pub, port, ids, feed="ORDERS")
    for c in conns:
        c.send(
            p.new_order(
                tag=f"{c.gateway_id}-1",
                symbol="AAPL",
                side="BUY",
                order_type="LIMIT",
                tif="DAY",
                qty=1,
                tick_decimals=2,
                price_ticks=100,
            ),
            now=0.0,
        )
    # The symbol is unknown to the gateway (no SYMBOLS reply), so every order
    # comes straight back as a tagged ERR: a full round trip per session.
    got = _pump(
        conns,
        lambda g: all(any(m.msg_type == "ERR" for m in v) for v in g.values()),
        timeout=15,
    )
    for gid, msgs in got.items():
        assert any(m.msg_type == "ERR" and m.get("TAG") == f"{gid}-1" for m in msgs)
    for c in conns:
        c.close()


def test_fd_limit_is_raised_or_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    gw = AlfGateway.__new__(AlfGateway)
    gw.config = AlfGatewayConfig(max_connections=5000)
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(resource, "setrlimit", lambda kind, lim: calls.append(lim))
    monkeypatch.setattr(resource, "getrlimit", lambda kind: (1024, 1_000_000))
    gw._ensure_fd_limit()
    assert calls == [(5064, 1_000_000)]
    calls.clear()
    monkeypatch.setattr(resource, "getrlimit", lambda kind: (1024, 2048))
    with pytest.raises(RuntimeError, match="hard limit is 2048"):
        gw._ensure_fd_limit()
    assert calls == [(2048, 2048)]
    calls.clear()
    monkeypatch.setattr(resource, "getrlimit", lambda kind: (100_000, 100_000))
    gw._ensure_fd_limit()
    assert calls == []
