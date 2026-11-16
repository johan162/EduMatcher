from __future__ import annotations

import logging
import socket
import threading
import time
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

import pytest
import zmq

from edumatcher.messaging.bus import CausalPublisher, make_publisher
from edumatcher.models.message import decode, dumps
from edumatcher.ralf_gateway import gateway as gateway_mod
from edumatcher.ralf_gateway.config import RalfGatewayConfig
from edumatcher.ralf_gateway.gateway import RalfGateway
from edumatcher.ralf_gateway.protocol import RalfFrame, parse_line
from tests.conftest import free_ports

# Generous upper bounds for CI/parallel test runs under CPU contention. These
# are deadlines for polling loops, not blind sleeps, so fast machines finish
# almost immediately while slow/busy ones get much more headroom than the
# fixed 0.1-0.15s sleeps this file used to rely on.
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


def _recv_all_lines(
    sock: socket.socket,
    quiet_period: float = 0.3,
    deadline: float = _DEFAULT_TIMEOUT,
) -> list[str]:
    """Accumulate every line the peer sends until it goes quiet or times out.

    A single `recv()` call is not guaranteed to return everything the server
    has queued (TCP may deliver it across several packets), so this keeps
    reading until no new data has arrived for `quiet_period` seconds (or the
    overall `deadline` elapses), instead of assuming one fixed-size read is
    enough.
    """
    sock.settimeout(quiet_period)
    buf = bytearray()
    end_time = time.monotonic() + deadline
    while time.monotonic() < end_time:
        try:
            chunk = sock.recv(65536)
        except TimeoutError:
            break
        if not chunk:
            break
        buf.extend(chunk)
    return [
        ln for ln in buf.decode("utf-8", errors="replace").splitlines() if ln.strip()
    ]


def wait_for_listener(host: str, port: int, deadline: float = _DEFAULT_TIMEOUT) -> None:
    """Poll until the gateway's TCP listener accepts connections.

    Replaces a blind post-thread-start sleep: on a fast/idle machine this
    returns almost instantly, on a slow/contended one it keeps retrying
    instead of racing a fixed guess.
    """
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
        f"RalfGateway never started listening on {host}:{port}"
    ) from last_exc


def _prime_subscriber(
    gw: RalfGateway, pub: zmq.Socket[bytes], deadline: float = _DEFAULT_TIMEOUT
) -> None:
    """Resolve the ZMQ PUB/SUB "slow joiner" race deterministically.

    A freshly-bound PUB socket will silently drop messages published before
    a SUB has finished connecting, so publishing a real test event right
    after `pub.bind()` is inherently racy. Since the gateway thread lives in
    this same process, we can detect the moment its subscriber has actually
    received something by watching `_next_seq` advance, instead of guessing
    a fixed sleep duration. The warmup event is sent before any test client
    subscribes, so it never reaches a real client and only pollutes the
    (unasserted) journal sequence numbers.
    """
    warmup_payload = dumps(
        {
            "id": "WARMUP",
            "symbol": "__WARMUP__",
            "buy_order_id": "W",
            "sell_order_id": "W",
            "buy_gateway_id": "W",
            "sell_gateway_id": "W",
            "price": 0.0,
            "quantity": 0,
            "aggressor_side": "BUY",
            "ts_ns": time.time_ns(),
        }
    )
    initial_next_seq = gw._next_seq
    end_time = time.monotonic() + deadline
    while gw._next_seq == initial_next_seq and time.monotonic() < end_time:
        pub.send_multipart([b"trade.executed", warmup_payload])
        time.sleep(_POLL_INTERVAL)
    if gw._next_seq == initial_next_seq:
        raise RuntimeError("ZMQ PUB/SUB handshake did not complete before the deadline")


def _wait_for_seq_advance(
    gw: RalfGateway, baseline_seq: int, deadline: float = _DEFAULT_TIMEOUT
) -> None:
    """Poll until the gateway has journaled at least one event past baseline."""
    end_time = time.monotonic() + deadline
    while gw._next_seq <= baseline_seq and time.monotonic() < end_time:
        time.sleep(_POLL_INTERVAL)


@pytest.fixture()
def running_gateway() -> (
    Generator[tuple[RalfGateway, zmq.Socket[bytes], int], None, None]
):
    engine_port, gateway_port = free_ports(2)

    engine_addr = f"tcp://127.0.0.1:{engine_port}"
    cfg = RalfGatewayConfig(
        name="ralf-test",
        bind_address="127.0.0.1",
        port=gateway_port,
        engine_pub_addr=engine_addr,
        replay_retention_sec=60,
        heartbeat_interval_sec=60,
        idle_timeout_sec=30,
        max_client_queue=1000,
    )

    gw = RalfGateway(cfg)
    t = threading.Thread(target=gw.run, daemon=True)
    t.start()

    # Wait for the gateway's TCP listener to actually be accepting
    # connections rather than assuming a fixed startup delay.
    wait_for_listener(cfg.bind_address, gateway_port)

    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
    pub = ctx.socket(zmq.PUB)
    pub.bind(engine_addr)
    # Resolve the PUB/SUB slow-joiner race deterministically instead of a
    # fixed handshake-window sleep.
    _prime_subscriber(gw, pub)

    try:
        yield gw, pub, gateway_port
    finally:
        gw.stop()
        t.join(timeout=2)
        pub.close()


def test_hello_and_subscribe_flow(
    running_gateway: tuple[RalfGateway, zmq.Socket[bytes], int],
) -> None:
    _, _, gateway_port = running_gateway

    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli:
        cli.sendall(b"HELLO|CLIENT=test01|PROTO=RALF1|ROLE=CLEARING|LASTSEQ=0\n")
        welcome = parse_line(_recv_line(cli))
        assert welcome.msg_type == "WELCOME"
        assert welcome.fields["PROTO"] == "RALF1"

        cli.sendall(b"SUB|CH=CLEARING|SYM=AAPL\n")
        snap = parse_line(_recv_line(cli))
        assert snap.msg_type == "SNAP"


def test_trade_event_emits_exec(
    running_gateway: tuple[RalfGateway, zmq.Socket[bytes], int],
) -> None:
    _, pub, gateway_port = running_gateway

    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli:
        cli.sendall(b"HELLO|CLIENT=test02|PROTO=RALF1|ROLE=CLEARING|LASTSEQ=0\n")
        _ = _recv_line(cli)  # WELCOME
        cli.sendall(b"SUB|CH=CLEARING|SYM=AAPL\n")
        _ = _recv_line(cli)  # SNAP

        pub.send_multipart(
            [
                b"trade.executed",
                dumps(
                    {
                        "id": "T1",
                        "symbol": "AAPL",
                        "buy_order_id": "B1",
                        "sell_order_id": "S1",
                        "buy_gateway_id": "GW1",
                        "sell_gateway_id": "GW2",
                        "price": 150.25,
                        "quantity": 100,
                        "aggressor_side": "BUY",
                        "ts_ns": time.time_ns(),
                    }
                ),
            ]
        )

        # Receive until EXEC (ignore any extra lines if present).
        deadline = time.time() + _DEFAULT_TIMEOUT
        got_exec = False
        while time.time() < deadline:
            frame = parse_line(_recv_line(cli, timeout=_DEFAULT_TIMEOUT))
            if frame.msg_type == "EXEC":
                assert frame.fields["CH"] == "CLEARING"
                assert frame.fields["SYM"] == "AAPL"
                assert frame.fields["EXEC_ID"] == "T1"
                got_exec = True
                break
        assert got_exec


def test_replay_from_lastseq(
    running_gateway: tuple[RalfGateway, zmq.Socket[bytes], int],
) -> None:
    gw, pub, gateway_port = running_gateway
    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli1:
        cli1.sendall(b"HELLO|CLIENT=test03a|PROTO=RALF1|ROLE=CLEARING|LASTSEQ=0\n")
        epoch = parse_line(_recv_line(cli1)).fields["EPOCH"]
        cli1.sendall(b"SUB|CH=CLEARING|SYM=AAPL\n")
        _ = _recv_line(cli1)  # SNAP

        pub.send_multipart(
            [
                b"trade.executed",
                dumps(
                    {
                        "id": "R1",
                        "symbol": "AAPL",
                        "buy_order_id": "B1",
                        "sell_order_id": "S1",
                        "buy_gateway_id": "GW1",
                        "sell_gateway_id": "GW2",
                        "price": 150.25,
                        "quantity": 100,
                        "aggressor_side": "BUY",
                        "ts_ns": time.time_ns(),
                    }
                ),
            ]
        )
        live = parse_line(_recv_line(cli1))
        assert live.msg_type == "EXEC"
        last_seq = int(live.fields["SEQ"])

    seq_before_r2 = gw._next_seq
    pub.send_multipart(
        [
            b"trade.executed",
            dumps(
                {
                    "id": "R2",
                    "symbol": "AAPL",
                    "buy_order_id": "B2",
                    "sell_order_id": "S2",
                    "buy_gateway_id": "GW1",
                    "sell_gateway_id": "GW2",
                    "price": 150.50,
                    "quantity": 50,
                    "aggressor_side": "SELL",
                    "ts_ns": time.time_ns(),
                }
            ),
        ]
    )
    # Wait until R2 has actually been journaled instead of guessing a fixed
    # delay, so cli2's replay-from-lastseq below never races the engine
    # event loop.
    _wait_for_seq_advance(gw, seq_before_r2)

    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli2:
        cli2.sendall(
            f"HELLO|CLIENT=test03b|PROTO=RALF1|ROLE=CLEARING|LASTSEQ={last_seq}"
            f"|EPOCH={epoch}\n".encode("utf-8")
        )
        cli2.sendall(b"SUB|CH=CLEARING|SYM=AAPL\n")
        frames = [parse_line(ln) for ln in _recv_all_lines(cli2)]

        assert any(f.msg_type == "WELCOME" for f in frames)
        replay_frames = [f for f in frames if f.msg_type == "EXEC"]
        assert replay_frames
        assert int(replay_frames[0].fields["SEQ"]) > last_seq


def test_reject_non_allowed_role(
    running_gateway: tuple[RalfGateway, zmq.Socket[bytes], int],
) -> None:
    gw, _, gateway_port = running_gateway
    gw.config = RalfGatewayConfig(
        name=gw.config.name,
        bind_address=gw.config.bind_address,
        port=gw.config.port,
        engine_pub_addr=gw.config.engine_pub_addr,
        replay_retention_sec=gw.config.replay_retention_sec,
        heartbeat_interval_sec=gw.config.heartbeat_interval_sec,
        idle_timeout_sec=gw.config.idle_timeout_sec,
        max_client_queue=gw.config.max_client_queue,
        allowed_roles=("CLEARING",),
    )

    with socket.create_connection(
        ("127.0.0.1", gateway_port), timeout=_DEFAULT_TIMEOUT
    ) as cli:
        cli.sendall(b"HELLO|CLIENT=test04|PROTO=RALF1|ROLE=AUDIT|LASTSEQ=0\n")
        err = parse_line(_recv_line(cli))
        assert err.msg_type == "ERR"
        assert err.fields["CODE"] == "ENTITLEMENT_DENIED"


# ---------------------------------------------------------------------------
# Review 2026-11 harness: the engine's sequenced publisher, trade.yaml-shaped
# payloads, a gateway that can be restarted on the same port, and a client
# that collects every line on a thread of its own.
# ---------------------------------------------------------------------------


def _trade_payload(n: int, symbol: str = "AAPL") -> dict[str, object]:
    return {
        "id": f"000001-{n:09d}",
        "run_seq": 1,
        "symbol": symbol,
        "buy_order_id": f"B{n}",
        "sell_order_id": f"S{n}",
        "buy_gateway_id": "GW1",
        "sell_gateway_id": "GW2",
        "price": 100.25,
        "quantity": 10,
        "aggressor_side": "BUY",
        "ts_ns": time.time_ns(),
    }


def _publish_trade(pub: CausalPublisher, n: int, symbol: str = "AAPL") -> None:
    pub.send_multipart([b"trade.executed", dumps(_trade_payload(n, symbol))])


def _ralf_config(engine_addr: str, port: int, **overrides: Any) -> RalfGatewayConfig:
    values: dict[str, Any] = {
        "name": "ralf-test",
        "bind_address": "127.0.0.1",
        "port": port,
        "engine_pub_addr": engine_addr,
        "replay_retention_sec": 600,
        "heartbeat_interval_sec": 60,
        "idle_timeout_sec": 30,
    }
    values.update(overrides)
    return RalfGatewayConfig(**values)


def _start(cfg: RalfGatewayConfig) -> tuple[RalfGateway, threading.Thread]:
    gw = RalfGateway(cfg)
    t = threading.Thread(target=gw.run, daemon=True)
    t.start()
    wait_for_listener(cfg.bind_address, cfg.port)
    return gw, t


def _prime(gw: RalfGateway, pub: CausalPublisher) -> None:
    """Publish warm-up trades (symbol __WARMUP__) until the SUB receives one."""
    end = time.monotonic() + _DEFAULT_TIMEOUT
    n = 0
    while gw._next_seq == 1 and time.monotonic() < end:
        n += 1
        _publish_trade(pub, n, "__WARMUP__")
        time.sleep(_POLL_INTERVAL)
    assert gw._next_seq > 1, "engine SUB never connected"


def _latest(gw: RalfGateway, channel: str = "CLEARING") -> int:
    return gw._next_seq_by_channel[channel] - 1


def _wait_latest(gw: RalfGateway, value: int, channel: str = "CLEARING") -> None:
    end = time.monotonic() + _DEFAULT_TIMEOUT
    while _latest(gw, channel) < value and time.monotonic() < end:
        time.sleep(_POLL_INTERVAL)
    assert _latest(gw, channel) >= value


class _Client:
    """A RALF client whose lines are collected by a reader thread."""

    def __init__(self, port: int, rcvbuf: int | None = None) -> None:
        self.sock = socket.socket()
        if rcvbuf is not None:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
        self.sock.connect(("127.0.0.1", port))
        self.lines: list[str] = []
        self.eof = False
        self._paused = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "_Client":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        buf = bytearray()
        self.sock.settimeout(None)
        while True:
            try:
                chunk = self.sock.recv(65536)
            except OSError:
                break
            if not chunk:
                break
            buf.extend(chunk)
            while (idx := buf.find(b"\n")) >= 0:
                self.lines.append(bytes(buf[:idx]).decode())
                del buf[: idx + 1]
        self.eof = True

    def send(self, line: str) -> None:
        self.sock.sendall(line.encode() + b"\n")

    def frames(self, msg_type: str | None = None) -> list[RalfFrame]:
        parsed = [parse_line(line) for line in list(self.lines)]
        return [f for f in parsed if msg_type is None or f.msg_type == msg_type]

    def wait(self, msg_type: str, n: int = 1, timeout: float = 10.0) -> list[RalfFrame]:
        prefix = msg_type + "|"

        def count() -> int:
            return sum(
                1 for ln in list(self.lines) if ln.startswith(prefix) or ln == msg_type
            )

        end = time.monotonic() + timeout
        while time.monotonic() < end and count() < n:
            if self.eof:
                break
            time.sleep(_POLL_INTERVAL)
        return self.frames(msg_type)

    def wait_eof(self, timeout: float = _DEFAULT_TIMEOUT) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end and not self.eof:
            time.sleep(_POLL_INTERVAL)
        assert self.eof

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def _exec_seqs(cli: _Client, channel: str = "CLEARING") -> list[int]:
    return [
        int(f.fields["SEQ"]) for f in cli.frames("EXEC") if f.fields["CH"] == channel
    ]


@pytest.fixture()
def engine() -> Generator[tuple[CausalPublisher, str], None, None]:
    (engine_port,) = free_ports(1)
    addr = f"tcp://127.0.0.1:{engine_port}"
    pub = make_publisher(addr)
    try:
        yield pub, addr
    finally:
        pub.close()


# ---------------------------------------------------------------------------
# WP-RALF01: a checkpoint names the gateway run it came from (EPOCH)
# ---------------------------------------------------------------------------


def _welcome(port: int, extra: str = "") -> tuple[_Client, RalfFrame]:
    cli = _Client(port).start()
    cli.send(f"HELLO|CLIENT=t|PROTO=RALF1|ROLE=CLEARING{extra}")
    welcome = cli.wait("WELCOME")
    assert welcome, cli.lines
    return cli, welcome[0]


def test_welcome_carries_one_epoch_per_run(
    engine: tuple[CausalPublisher, str],
) -> None:
    _, addr = engine
    (port,) = free_ports(1)
    gw, t = _start(_ralf_config(addr, port))
    try:
        a, wa = _welcome(port)
        b, wb = _welcome(port)
        a.close()
        b.close()
    finally:
        gw.stop()
        t.join(timeout=_DEFAULT_TIMEOUT)
    gw2, t2 = _start(_ralf_config(addr, port))
    try:
        c, wc = _welcome(port)
        c.close()
    finally:
        gw2.stop()
        t2.join(timeout=_DEFAULT_TIMEOUT)

    epoch = wa.fields["EPOCH"]
    assert len(epoch) == 8 and int(epoch, 16) >= 0
    assert wb.fields["EPOCH"] == epoch
    assert wc.fields["EPOCH"] != epoch


def test_checkpoint_from_the_previous_run_is_a_replay_miss(
    engine: tuple[CausalPublisher, str],
) -> None:
    """Review H1: the new run's events above an old LASTSEQ are not the old
    run's continuation."""
    pub, addr = engine
    (port,) = free_ports(1)
    gw, t = _start(_ralf_config(addr, port))
    try:
        _prime(gw, pub)
        base = _latest(gw)
        for n in range(1, 51):
            _publish_trade(pub, n)
        _wait_latest(gw, base + 50)
        old_last = _latest(gw)
        cli, welcome = _welcome(port)
        old_epoch = welcome.fields["EPOCH"]
        cli.close()
    finally:
        gw.stop()
        t.join(timeout=_DEFAULT_TIMEOUT)

    gw2, t2 = _start(_ralf_config(addr, port))
    try:
        _prime(gw2, pub)
        base2 = _latest(gw2)
        for n in range(51, 131):
            _publish_trade(pub, n, "MSFT")
        _wait_latest(gw2, base2 + 80)
        new_last = _latest(gw2)
        assert new_last > old_last

        cli = _Client(port).start()
        cli.send(
            f"HELLO|CLIENT=t|PROTO=RALF1|ROLE=CLEARING|LASTSEQ={old_last}"
            f"|EPOCH={old_epoch}"
        )
        cli.wait("WELCOME")
        cli.send("SUB|CH=CLEARING|SYM=*")
        snaps = cli.wait("SNAP")
        time.sleep(0.3)
        errs = cli.frames("ERR")
        cli.close()
    finally:
        gw2.stop()
        t2.join(timeout=_DEFAULT_TIMEOUT)

    assert [e.fields["CODE"] for e in errs] == ["REPLAY_MISS"]
    assert not cli.frames("EXEC")
    assert int(snaps[-1].fields["SEQ"]) == new_last


def test_lastseq_without_epoch_is_a_bad_message(
    running_gateway: tuple[RalfGateway, zmq.Socket[bytes], int],
) -> None:
    _, _, port = running_gateway
    cli = _Client(port).start()
    cli.send("HELLO|CLIENT=t|PROTO=RALF1|ROLE=CLEARING|LASTSEQ=50")
    cli.wait_eof()
    cli.close()
    frames = cli.frames()
    assert [f.msg_type for f in frames] == ["ERR"]
    assert frames[0].fields["CODE"] == "BAD_MESSAGE"
    assert "EPOCH" in frames[0].fields["DETAIL"]


def test_lastseq_zero_or_absent_needs_no_epoch(
    running_gateway: tuple[RalfGateway, zmq.Socket[bytes], int],
) -> None:
    _, _, port = running_gateway
    for extra in ("", "|LASTSEQ=0"):
        cli, welcome = _welcome(port, extra)
        cli.close()
        assert welcome.msg_type == "WELCOME"


# ---------------------------------------------------------------------------
# WP-RALF02: a burst is not lost at the engine SUB, and a loss is counted
# ---------------------------------------------------------------------------


def _bus_gaps(gw: RalfGateway) -> dict[str, float]:
    return {s.label: s.value for s in gw.metric_samples() if s.name == "gwy.bus_gaps"}


def _bump_bus_seq(pub: CausalPublisher, topic: bytes, by: int) -> None:
    """Make the publisher skip ``by`` sequence numbers on ``topic``."""
    seqs = pub._inner._seq
    seqs[topic] = seqs.get(topic, 0) + by


def test_a_20000_trade_burst_reaches_every_channel(
    engine: tuple[CausalPublisher, str],
) -> None:
    """Review H2: ten AUDIT sessions, the engine publishing as fast as it can."""
    pub, addr = engine
    (port,) = free_ports(1)
    gw, t = _start(_ralf_config(addr, port, max_client_queue=1_000_000))
    clients: list[_Client] = []
    try:
        _prime(gw, pub)
        for _ in range(10):
            cli = _Client(port).start()
            cli.send("HELLO|CLIENT=t|PROTO=RALF1|ROLE=AUDIT")
            cli.send("SUB|CH=CLEARING,DROP_COPY,AUDIT|SYM=*")
            cli.wait("SNAP")
            clients.append(cli)
        base = {ch: _latest(gw, ch) for ch in ("CLEARING", "DROP_COPY", "AUDIT")}
        payload = dumps(_trade_payload(1))
        for _ in range(20_000):
            pub.send_multipart([b"trade.executed", payload])
        end = time.monotonic() + 30
        while time.monotonic() < end and _latest(gw, "AUDIT") < base["AUDIT"] + 20_000:
            time.sleep(0.05)
        time.sleep(0.2)
        emitted = {ch: _latest(gw, ch) - base[ch] for ch in base}
    finally:
        gw.stop()
        t.join(timeout=_DEFAULT_TIMEOUT)
        for cli in clients:
            cli.close()

    assert emitted == {"CLEARING": 20_000, "DROP_COPY": 20_000, "AUDIT": 20_000}
    assert _bus_gaps(gw) == {}


def test_a_bus_sequence_jump_is_counted_and_warned_once(
    engine: tuple[CausalPublisher, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    pub, addr = engine
    (port,) = free_ports(1)
    caplog.set_level(logging.INFO, logger=gateway_mod.__name__)
    gw, t = _start(_ralf_config(addr, port))
    try:
        _prime(gw, pub)
        base = _latest(gw)
        _publish_trade(pub, 1)
        _wait_latest(gw, base + 1)
        _bump_bus_seq(pub, b"trade.executed", 5)
        _publish_trade(pub, 2)  # 5 never sent: a gap of 5
        _wait_latest(gw, base + 2)
        assert _bus_gaps(gw) == {"trade.executed": 5}
        _bump_bus_seq(pub, b"trade.executed", 2)
        _publish_trade(pub, 3)  # inside the latch window
        _wait_latest(gw, base + 3)
        gaps = _bus_gaps(gw)
    finally:
        gw.stop()
        t.join(timeout=_DEFAULT_TIMEOUT)

    assert gaps == {"trade.executed": 7}
    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "trade.executed" in r.getMessage()
    ]
    assert len(warnings) == 1
    assert "dropped 5" in warnings[0].getMessage()


def test_a_bus_sequence_back_to_one_is_a_restart_not_a_gap(
    engine: tuple[CausalPublisher, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    pub, addr = engine
    (port,) = free_ports(1)
    caplog.set_level(logging.INFO, logger=gateway_mod.__name__)
    gw, t = _start(_ralf_config(addr, port))
    try:
        _prime(gw, pub)
        base = _latest(gw)
        _publish_trade(pub, 1)
        _publish_trade(pub, 2)
        _wait_latest(gw, base + 2)
        pub._inner._seq.clear()  # the engine restarted: sequences begin at 1
        _publish_trade(pub, 3)
        _wait_latest(gw, base + 3)
        gaps = _bus_gaps(gw)
    finally:
        gw.stop()
        t.join(timeout=_DEFAULT_TIMEOUT)

    assert gaps == {}
    assert any(
        r.levelno == logging.INFO and "publisher restart" in r.getMessage()
        for r in caplog.records
    )


def test_a_pass_that_used_its_whole_budget_does_not_sleep(
    engine: tuple[CausalPublisher, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pub, addr = engine
    (port,) = free_ports(1)
    gw = RalfGateway(_ralf_config(addr, port))
    decoded = [0]
    real_decode = decode

    def counting(frames: Any) -> Any:
        decoded[0] += 1
        return real_decode(frames)

    slept_at: list[int] = []

    def fake_sleep(_sec: float) -> None:
        slept_at.append(decoded[0])
        gw.stop()

    monkeypatch.setattr(gateway_mod, "decode", counting)
    monkeypatch.setattr(
        gateway_mod,
        "time",
        SimpleNamespace(monotonic=time.monotonic, time=time.time, sleep=fake_sleep),
    )
    try:
        time.sleep(0.3)  # the SUB's connection to the PUB is up
        payload = dumps(_trade_payload(1))
        for _ in range(2500):
            pub.send_multipart([b"trade.executed", payload])
        time.sleep(0.5)  # all 2500 are in the SUB's receive buffer
        t = threading.Thread(target=gw.run, daemon=True)
        t.start()
        t.join(timeout=_DEFAULT_TIMEOUT)
    finally:
        gw.stop()
        gw.close()

    assert slept_at[0] == 2500


# ---------------------------------------------------------------------------
# WP-RALF03: replay on SUB, subscription-filtered, and not a slow client
# ---------------------------------------------------------------------------


@pytest.fixture()
def seq_gateway(
    engine: tuple[CausalPublisher, str],
) -> Generator[tuple[RalfGateway, CausalPublisher, int], None, None]:
    pub, addr = engine
    (port,) = free_ports(1)
    gw, t = _start(_ralf_config(addr, port))
    try:
        _prime(gw, pub)
        yield gw, pub, port
    finally:
        gw.stop()
        t.join(timeout=_DEFAULT_TIMEOUT)


def _resume_hello(gw: RalfGateway, role: str, last_seq: int) -> str:
    return (
        f"HELLO|CLIENT=t|PROTO=RALF1|ROLE={role}|LASTSEQ={last_seq}"
        f"|EPOCH={gw._epoch}"
    )


def test_trades_between_welcome_and_sub_are_replayed_before_the_snap(
    seq_gateway: tuple[RalfGateway, CausalPublisher, int],
) -> None:
    """Review C1: the SNAP must not cover trades the client never got."""
    gw, pub, port = seq_gateway
    b = _latest(gw)
    for n in range(1, 12):
        _publish_trade(pub, n)
    _wait_latest(gw, b + 11)

    cli = _Client(port).start()
    cli.send(_resume_hello(gw, "CLEARING", b + 6))
    cli.wait("WELCOME")
    for n in range(12, 15):
        _publish_trade(pub, n)
    _wait_latest(gw, b + 14)
    cli.send("SUB|CH=CLEARING|SYM=*")
    snap = cli.wait("SNAP")[0]
    for n in range(15, 17):
        _publish_trade(pub, n)
    cli.wait("EXEC", 10)
    cli.close()

    assert int(snap.fields["SEQ"]) == b + 14
    kinds = [(f.msg_type, int(f.fields.get("SEQ", 0))) for f in cli.frames()]
    data = [k for k in kinds if k[0] in ("EXEC", "SNAP")]
    assert data == [
        *(("EXEC", b + i) for i in range(7, 15)),
        ("SNAP", b + 14),
        ("EXEC", b + 15),
        ("EXEC", b + 16),
    ]


def test_replay_is_subscription_filtered(
    seq_gateway: tuple[RalfGateway, CausalPublisher, int],
) -> None:
    gw, pub, port = seq_gateway
    b = _latest(gw, "DROP_COPY")
    for n in range(1, 7):
        _publish_trade(pub, n, "AAPL" if n % 2 else "MSFT")
    _wait_latest(gw, b + 6, "DROP_COPY")

    cli = _Client(port).start()
    cli.send(_resume_hello(gw, "DROP_COPY", b))
    cli.send("SUB|CH=DROP_COPY|SYM=AAPL")
    cli.wait("SNAP")
    time.sleep(0.2)
    cli.close()

    execs = cli.frames("EXEC")
    assert [f.fields["SYM"] for f in execs] == ["AAPL"] * 3
    assert [int(f.fields["SEQ"]) for f in execs] == [b + 1, b + 3, b + 5]


def test_each_channel_is_replayed_once_across_subs(
    seq_gateway: tuple[RalfGateway, CausalPublisher, int],
) -> None:
    gw, pub, port = seq_gateway
    b = {ch: _latest(gw, ch) for ch in ("CLEARING", "AUDIT")}
    for n in range(1, 4):
        _publish_trade(pub, n)
    _wait_latest(gw, b["AUDIT"] + 3, "AUDIT")

    cli = _Client(port).start()
    cli.send(_resume_hello(gw, "AUDIT", min(b.values())))
    cli.send("SUB|CH=CLEARING|SYM=*")
    cli.wait("SNAP", 1)
    cli.send("SUB|CH=CLEARING,AUDIT|SYM=*")
    cli.wait("SNAP", 2)
    cli.send("SUB|CH=CLEARING|SYM=AAPL")  # already wanted: nothing new
    cli.wait("SNAP", 3)
    time.sleep(0.2)
    cli.close()

    lines = [(f.fields["CH"], int(f.fields["SEQ"])) for f in cli.frames("EXEC")]
    assert len(lines) == len(set(lines))
    assert sorted(seq for ch, seq in lines if ch == "CLEARING")[-3:] == [
        b["CLEARING"] + i for i in (1, 2, 3)
    ]
    assert sorted(seq for ch, seq in lines if ch == "AUDIT")[-3:] == [
        b["AUDIT"] + i for i in (1, 2, 3)
    ]
    assert not [f for f in cli.frames("EXEC") if f.fields["CH"] == "DROP_COPY"]


def test_a_long_replay_to_a_late_reader_is_not_a_slow_client(
    engine: tuple[CausalPublisher, str],
) -> None:
    """Review C2: 30 000 journalled lines, 256 KiB receive buffer, the client
    starts reading 50 ms after its SUB."""
    pub, addr = engine
    (port,) = free_ports(1)
    gw, t = _start(_ralf_config(addr, port))  # max_client_queue 10 000
    try:
        _prime(gw, pub)
        b = _latest(gw)
        payload = dumps(_trade_payload(1))
        for _ in range(30_000):
            pub.send_multipart([b"trade.executed", payload])
        _wait_latest(gw, b + 30_000)

        cli = _Client(port, rcvbuf=256 * 1024)
        cli.send(_resume_hello(gw, "CLEARING", b))
        cli.send("SUB|CH=CLEARING|SYM=*")
        time.sleep(0.05)
        started = time.monotonic()
        cli.start()
        cli.wait("SNAP", timeout=20)
        took = time.monotonic() - started
        cli.close()
    finally:
        gw.stop()
        t.join(timeout=_DEFAULT_TIMEOUT)

    assert not cli.frames("ERR")
    assert _exec_seqs(cli) == list(range(b + 1, b + 30_001))
    assert took < 2.0


# ---------------------------------------------------------------------------
# WP-RALF04: poll() loop, EXIT on stop, half-close documented
# ---------------------------------------------------------------------------


def test_a_client_on_a_descriptor_above_1023_is_served(
    running_gateway: tuple[RalfGateway, zmq.Socket[bytes], int],
    caplog: pytest.LogCaptureFixture,
    descriptors_above_1023: None,
) -> None:
    _, _, port = running_gateway
    caplog.set_level(logging.WARNING, logger=gateway_mod.__name__)
    with socket.create_connection(("127.0.0.1", port), timeout=2) as cli:
        cli.sendall(b"HELLO|CLIENT=t|PROTO=RALF1|ROLE=CLEARING\n")
        assert parse_line(_recv_line(cli, timeout=2)).msg_type == "WELCOME"
        cli.sendall(b"PING\n")
        assert parse_line(_recv_line(cli, timeout=2)).msg_type == "PONG"
    assert not [r for r in caplog.records if "read" in r.getMessage()]


def test_stop_says_exit_shutdown_after_the_queued_lines(
    seq_gateway: tuple[RalfGateway, CausalPublisher, int],
) -> None:
    gw, pub, port = seq_gateway
    cli = _Client(port).start()
    cli.send("HELLO|CLIENT=t|PROTO=RALF1|ROLE=CLEARING")
    cli.send("SUB|CH=CLEARING|SYM=*")
    cli.wait("SNAP")
    b = _latest(gw)
    for n in range(1, 4):
        _publish_trade(pub, n)
    _wait_latest(gw, b + 3)
    gw.stop()
    cli.wait_eof()
    cli.close()

    frames = cli.frames()
    assert [f.msg_type for f in frames][-4:] == ["EXEC", "EXEC", "EXEC", "EXIT"]
    assert frames[-1].fields["REASON"] == "shutdown"
    assert frames[-1].fields["TS"].endswith("Z")
    assert gw._disconnects == {"shutdown": 1}


def test_a_client_that_stopped_reading_holds_the_stop_at_most_a_second(
    engine: tuple[CausalPublisher, str],
) -> None:
    pub, addr = engine
    (port,) = free_ports(1)
    gw, t = _start(_ralf_config(addr, port, max_client_queue=1_000_000))
    cli = _Client(port, rcvbuf=4096)  # never started: reads nothing
    try:
        _prime(gw, pub)
        cli.send("HELLO|CLIENT=t|PROTO=RALF1|ROLE=AUDIT")
        cli.send("SUB|CH=CLEARING,DROP_COPY,AUDIT|SYM=*")
        b = _latest(gw, "AUDIT")
        payload = dumps(_trade_payload(1))
        for _ in range(20_000):  # several MB: more than the socket buffers hold
            pub.send_multipart([b"trade.executed", payload])
        _wait_latest(gw, b + 20_000, "AUDIT")
        assert any(s.out_queue for s in list(gw._clients.values()))

        started = time.monotonic()
        gw.stop()
        t.join(timeout=_DEFAULT_TIMEOUT)
        took = time.monotonic() - started
    finally:
        gw.stop()
        cli.close()

    assert not t.is_alive()
    assert took < 1.5
    assert gw._disconnects.get("shutdown") == 1


def test_a_half_closed_reader_is_disconnected_as_peer_closed(
    running_gateway: tuple[RalfGateway, zmq.Socket[bytes], int],
) -> None:
    """Documented behaviour (review Q8): a half-close ends the session."""
    gw, _, port = running_gateway
    with socket.create_connection(("127.0.0.1", port), timeout=2) as cli:
        cli.sendall(
            b"HELLO|CLIENT=t|PROTO=RALF1|ROLE=CLEARING\nSUB|CH=CLEARING|SYM=*\n"
        )
        cli.shutdown(socket.SHUT_WR)
        cli.settimeout(_DEFAULT_TIMEOUT)
        data = bytearray()
        while chunk := cli.recv(65536):
            data.extend(chunk)

    types = [parse_line(ln).msg_type for ln in data.decode().splitlines()]
    assert types[:2] == ["WELCOME", "SNAP"]
    assert "EXEC" not in types
    assert gw._disconnects == {"peer_closed": 1}
