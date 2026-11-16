"""Integration tests for pm-dc-gwy: a real DcGateway TCP server relaying a
real DropCopyPublisher's ZMQ feed to plain-socket DC1 clients.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

import pytest
import zmq

from edumatcher.dc_gateway import gateway as gateway_mod
from edumatcher.dc_gateway.config import DcGatewayConfig
from edumatcher.dc_gateway.gateway import DcGateway
from edumatcher.dc_gateway.protocol import iso_utc, parse_line
from edumatcher.engine.drop_copy import DropCopyPublisher
from edumatcher.models.message import decode
from tests.conftest import free_ports

_DEFAULT_TIMEOUT = 5.0
_POLL_INTERVAL = 0.02


def _recv_line(sock: socket.socket, timeout: float = _DEFAULT_TIMEOUT) -> str:
    sock.settimeout(timeout)
    data = bytearray()
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("socket closed")
        data.extend(chunk)
        if b"\n" in data:
            line, _, _ = bytes(data).partition(b"\n")
            return line.decode("utf-8", errors="replace")


def wait_for_listener(host: str, port: int, deadline: float = _DEFAULT_TIMEOUT) -> None:
    last_exc: OSError | None = None
    end_time = time.monotonic() + deadline
    while time.monotonic() < end_time:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError as exc:
            last_exc = exc
            time.sleep(_POLL_INTERVAL)
    raise RuntimeError(
        f"DcGateway never started listening on {host}:{port}"
    ) from last_exc


def _settle_subscription(delay: float = 0.2) -> None:
    """Give the gateway's internal ZMQ SUB socket time to finish its
    handshake with the DropCopyPublisher's PUB socket (classic PUB/SUB
    slow-joiner race) before publishing the event under test. The gateway
    subscribes to a client's gateway_id topic synchronously at HELLO time,
    but the underlying ZMQ SUBSCRIBE still needs a moment to propagate to
    the PUB side.
    """
    time.sleep(delay)


@pytest.fixture()
def running_gateway() -> (
    Generator[tuple[DcGateway, DropCopyPublisher, int], None, None]
):
    dc_pub_port, gateway_port = free_ports(2)

    dc_pub_addr = f"tcp://127.0.0.1:{dc_pub_port}"
    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
    pub = DropCopyPublisher(ctx, addr=dc_pub_addr)

    cfg = DcGatewayConfig(
        name="dc-test",
        bind_address="127.0.0.1",
        port=gateway_port,
        drop_copy_pub_addr=dc_pub_addr,
        heartbeat_interval_sec=60,
        idle_timeout_sec=30,
        max_client_queue=1000,
    )

    gw = DcGateway(cfg)
    t = threading.Thread(target=gw.run, daemon=True)
    t.start()

    wait_for_listener(cfg.bind_address, gateway_port)

    try:
        yield gw, pub, gateway_port
    finally:
        gw.stop()
        t.join(timeout=2)
        pub.close()


def test_hello_welcome_handshake(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    _, _, gateway_port = running_gateway

    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli:
        cli.sendall(b"HELLO|CLIENT=test01|PROTO=DC1|ID=TRADER01\n")
        welcome = parse_line(_recv_line(cli))
        assert welcome.msg_type == "WELCOME"
        assert welcome.fields["PROTO"] == "DC1"
        assert welcome.fields["ID"] == "TRADER01"
        assert welcome.fields["GW"] == "dc-test"


def test_hello_missing_id_rejected() -> None:
    dc_pub_port, gateway_port = free_ports(2)
    dc_pub_addr = f"tcp://127.0.0.1:{dc_pub_port}"
    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
    pub = DropCopyPublisher(ctx, addr=dc_pub_addr)
    cfg = DcGatewayConfig(
        name="dc-test",
        bind_address="127.0.0.1",
        port=gateway_port,
        drop_copy_pub_addr=dc_pub_addr,
    )
    gw = DcGateway(cfg)
    t = threading.Thread(target=gw.run, daemon=True)
    t.start()
    wait_for_listener(cfg.bind_address, gateway_port)

    try:
        with socket.create_connection(
            ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
        ) as cli:
            cli.sendall(b"HELLO|CLIENT=test01|PROTO=DC1\n")
            err = parse_line(_recv_line(cli))
            assert err.msg_type == "ERR"
            assert err.fields["CODE"] == "AUTH_REQUIRED"
    finally:
        gw.stop()
        t.join(timeout=2)
        pub.close()


def test_fill_event_relayed_to_matching_gateway_id(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    gw, pub, gateway_port = running_gateway

    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli:
        cli.sendall(b"HELLO|CLIENT=test02|PROTO=DC1|ID=TRADER01\n")
        _ = _recv_line(cli)  # WELCOME
        _settle_subscription()

        deadline = time.time() + _DEFAULT_TIMEOUT
        got_fill = False
        while time.time() < deadline and not got_fill:
            pub.publish_fill(
                "TRADER01",
                order_id="ord-1",
                trade_ids=["000001-000000001"],
                symbol="AAPL",
                fill_qty=100,
                fill_price=150.25,
                liquidity_flag="MAKER",
            )
            try:
                cli.settimeout(0.3)
                frame = parse_line(_recv_line(cli, timeout=0.3))
            except TimeoutError, RuntimeError:
                continue
            if frame.msg_type == "DC_FILL" and frame.fields.get("ORDER_ID") == "ord-1":
                assert frame.fields["SYMBOL"] == "AAPL"
                assert frame.fields["FILL_QTY"] == "100"
                assert frame.fields["FILL_PRICE"] == "150.25"
                assert frame.fields["LIQUIDITY"] == "MAKER"
                got_fill = True
        assert got_fill


def test_fill_event_not_relayed_to_other_gateway_id(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    _, pub, gateway_port = running_gateway

    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli:
        cli.sendall(b"HELLO|CLIENT=test03|PROTO=DC1|ID=TRADER99\n")
        _ = _recv_line(cli)  # WELCOME
        _settle_subscription()

        # Publish for a different gateway a few times; TRADER99's client
        # should never see a DC_FILL, only its own periodic HB (heartbeat
        # is set to 60s here so none will arrive within the short window).
        for _ in range(5):
            pub.publish_fill(
                "TRADER01",
                order_id="ord-x",
                trade_ids=["000001-000000001"],
                symbol="MSFT",
                fill_qty=10,
                fill_price=1.0,
                liquidity_flag="TAKER",
            )
            time.sleep(0.05)

        cli.settimeout(0.5)
        with pytest.raises((TimeoutError, socket.timeout)):
            cli.recv(4096)


def test_ping_pong(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    _, _, gateway_port = running_gateway

    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli:
        cli.sendall(b"HELLO|CLIENT=test04|PROTO=DC1|ID=TRADER01\n")
        _ = _recv_line(cli)  # WELCOME
        cli.sendall(b"PING\n")
        frame = parse_line(_recv_line(cli))
        assert frame.msg_type == "PONG"


def test_exit_closes_connection(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    _, _, gateway_port = running_gateway

    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli:
        cli.sendall(b"HELLO|CLIENT=test05|PROTO=DC1|ID=TRADER01\n")
        _ = _recv_line(cli)  # WELCOME
        cli.sendall(b"EXIT\n")
        cli.settimeout(_DEFAULT_TIMEOUT)
        # Server should close the connection (recv returns b"").
        end_time = time.time() + _DEFAULT_TIMEOUT
        closed = False
        while time.time() < end_time:
            chunk = cli.recv(4096)
            if not chunk:
                closed = True
                break
        assert closed


def test_two_clients_same_gateway_id_both_receive(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    _, pub, gateway_port = running_gateway

    with (
        socket.create_connection(
            ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
        ) as cli1,
        socket.create_connection(
            ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
        ) as cli2,
    ):
        cli1.sendall(b"HELLO|CLIENT=riskA|PROTO=DC1|ID=TRADER07\n")
        _ = _recv_line(cli1)
        cli2.sendall(b"HELLO|CLIENT=riskB|PROTO=DC1|ID=TRADER07\n")
        _ = _recv_line(cli2)

        _settle_subscription()

        deadline = time.time() + _DEFAULT_TIMEOUT
        seen1 = seen2 = False
        while time.time() < deadline and not (seen1 and seen2):
            pub.publish_fill(
                "TRADER07",
                order_id="ord-2",
                trade_ids=["000001-000000001"],
                symbol="IBM",
                fill_qty=5,
                fill_price=1.0,
                liquidity_flag="TAKER",
            )
            for sock_obj, flag_name in ((cli1, "seen1"), (cli2, "seen2")):
                try:
                    sock_obj.settimeout(0.3)
                    frame = parse_line(_recv_line(sock_obj, timeout=0.3))
                except TimeoutError, RuntimeError:
                    continue
                if (
                    frame.msg_type == "DC_FILL"
                    and frame.fields.get("ORDER_ID") == "ord-2"
                ):
                    if flag_name == "seen1":
                        seen1 = True
                    else:
                        seen2 = True
        assert seen1 and seen2


# ---------------------------------------------------------------------------
# WP-DCG01: per-ID subscriptions, feed-gap accounting, no sleep on a full pass
# ---------------------------------------------------------------------------


def _count_decodes(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Wrap the gateway's ``decode`` so a test sees what its SUB received."""
    calls = [0]
    real = decode

    def counting(frames: Any) -> Any:
        calls[0] += 1
        return real(frames)

    monkeypatch.setattr(gateway_mod, "decode", counting)
    return calls


class _LineReader:
    """Collect every line a client receives, on a thread of its own."""

    def __init__(self, sock: socket.socket) -> None:
        self.lines: list[str] = []
        self._sock = sock
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        buf = bytearray()
        self._sock.settimeout(None)
        while True:
            try:
                chunk = self._sock.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            buf.extend(chunk)
            while (idx := buf.find(b"\n")) >= 0:
                self.lines.append(bytes(buf[:idx]).decode())
                del buf[: idx + 1]

    def fills(self) -> list[dict[str, str]]:
        return [
            f.fields
            for f in (parse_line(line) for line in list(self.lines))
            if f.msg_type == "DC_FILL"
        ]

    def wait_fills(self, n: int, timeout: float = 10.0) -> list[dict[str, str]]:
        end = time.monotonic() + timeout
        while time.monotonic() < end and len(self.fills()) < n:
            time.sleep(_POLL_INTERVAL)
        return self.fills()


def _hello(port: int, gateway_id: str) -> tuple[socket.socket, _LineReader]:
    cli = socket.create_connection(("127.0.0.1", port), timeout=_DEFAULT_TIMEOUT)
    cli.sendall(f"HELLO|CLIENT=t|PROTO=DC1|ID={gateway_id}\n".encode())
    assert parse_line(_recv_line(cli)).msg_type == "WELCOME"
    reader = _LineReader(cli)
    _settle_subscription()
    return cli, reader


def _fill(pub: DropCopyPublisher, gateway_id: str, order_id: str = "O1") -> None:
    pub.publish_fill(
        gateway_id,
        order_id=order_id,
        trade_ids=["000001-000000001"],
        symbol="AAPL",
        fill_qty=1,
        fill_price=1.0,
        liquidity_flag="TAKER",
    )


def _feed_gaps(gw: DcGateway) -> float:
    return sum(s.value for s in gw.metric_samples() if s.name == "gwy.feed_gaps")


def test_unwatched_fills_never_reach_the_gateway(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, pub, _ = running_gateway
    decoded = _count_decodes(monkeypatch)
    _settle_subscription(0.3)  # the SUB's connection to the PUB is up

    for _ in range(1000):
        _fill(pub, "TRADER07")
    time.sleep(0.5)

    assert decoded[0] == 0


def test_burst_for_unwatched_ids_loses_no_watched_fill(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    gw, pub, port = running_gateway
    cli, reader = _hello(port, "TRADER01")
    with cli:
        for i in range(40_000):
            _fill(pub, f"TRADER{10 + i % 20}")
            if i % 20 == 0:
                _fill(pub, "TRADER01")
        time.sleep(0.5)
        _fill(pub, "TRADER01")

        fills = reader.wait_fills(2001)

    assert [int(f["SEQ"]) for f in fills] == list(range(1, 2002))
    assert _feed_gaps(gw) == 0


def test_prefix_id_receives_only_its_own_fills(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    _, pub, port = running_gateway
    cli, reader = _hello(port, "TRADER1")
    with cli:
        _fill(pub, "TRADER10", "O10")
        _fill(pub, "TRADER1", "O1")
        _fill(pub, "TRADER10", "O10")
        _fill(pub, "TRADER1", "O1")
        fills = reader.wait_fills(2)
        time.sleep(0.3)

    assert [f["ORDER_ID"] for f in reader.fills()] == ["O1", "O1"]
    assert [f["SEQ"] for f in fills] == ["1", "2"]


def test_seq_gap_is_counted_and_warned_once(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
    caplog: pytest.LogCaptureFixture,
) -> None:
    gw, pub, port = running_gateway
    caplog.set_level(logging.INFO, logger=gateway_mod.__name__)
    cli, reader = _hello(port, "TRADER01")
    with cli:
        _fill(pub, "TRADER01")  # seq 1
        pub._seq_by_gateway["TRADER01"] += 5
        _fill(pub, "TRADER01")  # seq 7: 2..6 lost
        reader.wait_fills(2)
        assert _feed_gaps(gw) == 5

        pub._seq_by_gateway["TRADER01"] += 2
        _fill(pub, "TRADER01")  # seq 10: 8..9 lost, inside the latch window
        reader.wait_fills(3)

    assert _feed_gaps(gw) == 7
    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "TRADER01" in r.getMessage()
    ]
    assert len(warnings) == 1
    assert "2..6" in warnings[0].getMessage()


def test_seq_back_to_one_is_a_restart_not_a_gap(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
    caplog: pytest.LogCaptureFixture,
) -> None:
    gw, pub, port = running_gateway
    caplog.set_level(logging.INFO, logger=gateway_mod.__name__)
    cli, reader = _hello(port, "TRADER01")
    with cli:
        _fill(pub, "TRADER01")
        _fill(pub, "TRADER01")
        pub._seq_by_gateway.clear()  # what a new engine run starts from
        _fill(pub, "TRADER01")
        fills = reader.wait_fills(3)

    assert [f["SEQ"] for f in fills] == ["1", "2", "1"]
    assert _feed_gaps(gw) == 0
    assert any(
        r.levelno == logging.INFO and "restart" in r.getMessage()
        for r in caplog.records
    )
    assert not any(r.levelno >= logging.WARNING for r in caplog.records)


def test_last_watcher_leaving_removes_the_subscription(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gw, pub, port = running_gateway
    decoded = _count_decodes(monkeypatch)
    cli, reader = _hello(port, "TRADER01")
    with cli:
        _fill(pub, "TRADER01")
        assert len(reader.wait_fills(1)) == 1
        cli.sendall(b"EXIT\n")
        end = time.monotonic() + _DEFAULT_TIMEOUT
        while time.monotonic() < end and gw._clients:
            time.sleep(_POLL_INTERVAL)
    _settle_subscription()
    seen = decoded[0]

    for _ in range(5):
        _fill(pub, "TRADER01")
    time.sleep(0.3)

    assert decoded[0] == seen


def test_fills_while_unwatched_are_not_a_gap_for_the_next_watcher(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    gw, pub, port = running_gateway
    cli, reader = _hello(port, "TRADER01")
    with cli:
        _fill(pub, "TRADER01")
        reader.wait_fills(1)
        cli.sendall(b"EXIT\n")
        end = time.monotonic() + _DEFAULT_TIMEOUT
        while time.monotonic() < end and gw._clients:
            time.sleep(_POLL_INTERVAL)
    _settle_subscription()
    for _ in range(3):
        _fill(pub, "TRADER01")  # seq 2..4, nobody watching

    cli2, reader2 = _hello(port, "TRADER01")
    with cli2:
        _fill(pub, "TRADER01")  # seq 5
        assert [f["SEQ"] for f in reader2.wait_fills(1)] == ["5"]

    assert _feed_gaps(gw) == 0


def test_a_pass_that_used_its_whole_budget_does_not_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dc_pub_port, gateway_port = free_ports(2)
    dc_pub_addr = f"tcp://127.0.0.1:{dc_pub_port}"
    pub = DropCopyPublisher(zmq.Context.instance(), addr=dc_pub_addr)
    gw = DcGateway(
        DcGatewayConfig(
            name="dc-test",
            bind_address="127.0.0.1",
            port=gateway_port,
            drop_copy_pub_addr=dc_pub_addr,
        )
    )
    decoded = _count_decodes(monkeypatch)
    slept_at: list[int] = []

    def fake_sleep(_sec: float) -> None:
        slept_at.append(decoded[0])
        gw.stop()

    monkeypatch.setattr(
        gateway_mod,
        "time",
        SimpleNamespace(monotonic=time.monotonic, time=time.time, sleep=fake_sleep),
    )
    try:
        gw._dc_subscribe("TRADER01", -1)  # watched, by a session not in _clients
        _settle_subscription(0.3)
        for _ in range(2500):
            _fill(pub, "TRADER01")
        time.sleep(0.5)  # all 2500 are in the SUB's receive buffer

        t = threading.Thread(target=gw.run, daemon=True)
        t.start()
        t.join(timeout=_DEFAULT_TIMEOUT)
    finally:
        gw.stop()
        gw.close()
        pub.close()

    assert slept_at[0] == 2500


# ---------------------------------------------------------------------------
# WP-DCG02: DC_FILL carries the fill's time and its public trade id(s)
# ---------------------------------------------------------------------------


def test_dc_fill_carries_ts_and_trade_id(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    _, pub, port = running_gateway
    cli, reader = _hello(port, "TRADER01")
    with cli:
        pub.publish_fill(
            "TRADER01",
            order_id="O1003",
            trade_ids=["000003-000000017"],
            symbol="AAPL",
            fill_qty=100,
            fill_price=100.25,
            liquidity_flag="TAKER",
        )
        published_ns = pub._log[-1].timestamp
        (fill,) = reader.wait_fills(1)

    assert list(fill) == [
        "SEQ",
        "ORDER_ID",
        "SYMBOL",
        "FILL_QTY",
        "FILL_PRICE",
        "LIQUIDITY",
        "TS",
        "TRADE_ID",
    ]
    assert fill["SEQ"] == "1"
    assert fill["ORDER_ID"] == "O1003"
    assert fill["SYMBOL"] == "AAPL"
    assert fill["FILL_QTY"] == "100"
    assert fill["FILL_PRICE"] == "100.25"
    assert fill["LIQUIDITY"] == "TAKER"
    assert fill["TS"] == iso_utc(published_ns / 1e9)
    assert fill["TRADE_ID"] == "000003-000000017"


def test_dc_fill_joins_several_trade_ids_with_commas(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    _, pub, port = running_gateway
    cli, reader = _hello(port, "TRADER01")
    with cli:
        pub.publish_fill(
            "TRADER01",
            order_id="O1",
            trade_ids=["000003-000000017", "000003-000000018"],
            symbol="AAPL",
            fill_qty=2,
            fill_price=1.0,
            liquidity_flag="MAKER",
        )
        (fill,) = reader.wait_fills(1)

    assert fill["TRADE_ID"] == "000003-000000017,000003-000000018"


# ---------------------------------------------------------------------------
# WP-DCG03: poll() over every descriptor, a goodbye on stop, half-close
# ---------------------------------------------------------------------------


def test_a_client_on_a_descriptor_above_1023_is_served(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
    caplog: pytest.LogCaptureFixture,
    descriptors_above_1023: None,
) -> None:
    _, _, port = running_gateway
    caplog.set_level(logging.WARNING, logger=gateway_mod.__name__)
    with socket.create_connection(("127.0.0.1", port), timeout=2) as cli:
        cli.sendall(b"HELLO|CLIENT=t|PROTO=DC1|ID=TRADER01\n")
        assert parse_line(_recv_line(cli, timeout=2)).msg_type == "WELCOME"
        cli.sendall(b"PING\n")
        assert parse_line(_recv_line(cli, timeout=2)).msg_type == "PONG"
    assert not [r for r in caplog.records if "read" in r.getMessage()]


def _read_until_eof(sock: socket.socket, timeout: float = _DEFAULT_TIMEOUT) -> str:
    sock.settimeout(timeout)
    data = bytearray()
    while chunk := sock.recv(65536):
        data.extend(chunk)
    return data.decode()


def test_stop_says_exit_shutdown_before_closing(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    gw, _, port = running_gateway
    with socket.create_connection(("127.0.0.1", port), timeout=2) as cli:
        cli.sendall(b"HELLO|CLIENT=t|PROTO=DC1|ID=TRADER01\n")
        assert parse_line(_recv_line(cli)).msg_type == "WELCOME"
        gw.stop()
        rest = _read_until_eof(cli).splitlines()

    last = parse_line(rest[-1])
    assert last.msg_type == "EXIT"
    assert last.fields["REASON"] == "shutdown"
    assert last.fields["TS"].endswith("Z")
    assert gw._disconnects == {"shutdown": 1}


def test_a_client_that_stopped_reading_holds_the_stop_at_most_a_second() -> None:
    dc_pub_port, gateway_port = free_ports(2)
    dc_pub_addr = f"tcp://127.0.0.1:{dc_pub_port}"
    pub = DropCopyPublisher(zmq.Context.instance(), addr=dc_pub_addr)
    gw = DcGateway(
        DcGatewayConfig(
            name="dc-test",
            bind_address="127.0.0.1",
            port=gateway_port,
            drop_copy_pub_addr=dc_pub_addr,
            heartbeat_interval_sec=60,
            idle_timeout_sec=60,
            max_client_queue=1_000_000,
        )
    )
    t = threading.Thread(target=gw.run, daemon=True)
    t.start()
    wait_for_listener("127.0.0.1", gateway_port)
    cli = socket.socket()
    cli.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    try:
        cli.connect(("127.0.0.1", gateway_port))
        cli.sendall(b"HELLO|CLIENT=t|PROTO=DC1|ID=TRADER01\n")
        assert parse_line(_recv_line(cli)).msg_type == "WELCOME"
        _settle_subscription()
        for _ in range(40_000):  # several MB: more than the socket buffers hold
            _fill(pub, "TRADER01")
        end = time.monotonic() + _DEFAULT_TIMEOUT
        while time.monotonic() < end and not any(
            s.out_queue for s in list(gw._clients.values())
        ):
            time.sleep(_POLL_INTERVAL)
        assert any(s.out_queue for s in list(gw._clients.values()))

        started = time.monotonic()
        gw.stop()
        t.join(timeout=_DEFAULT_TIMEOUT)
        took = time.monotonic() - started
    finally:
        gw.stop()
        cli.close()
        pub.close()

    assert not t.is_alive()
    assert took < 1.5
    assert gw._disconnects.get("shutdown") == 1


def test_a_half_closed_reader_is_disconnected_as_peer_closed(
    running_gateway: tuple[DcGateway, DropCopyPublisher, int],
) -> None:
    """Documented behaviour (review Q5): a half-close ends the session."""
    gw, _, port = running_gateway
    with socket.create_connection(("127.0.0.1", port), timeout=2) as cli:
        cli.sendall(b"HELLO|CLIENT=t|PROTO=DC1|ID=TRADER01\n")
        cli.shutdown(socket.SHUT_WR)
        lines = _read_until_eof(cli).splitlines()

    assert [parse_line(line).msg_type for line in lines] == ["WELCOME"]
    assert gw._disconnects == {"peer_closed": 1}
