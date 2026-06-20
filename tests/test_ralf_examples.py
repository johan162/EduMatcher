from __future__ import annotations

import importlib.util
import errno
import os
from pathlib import Path
import pty
import select
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Generator
from types import ModuleType
from typing import Protocol, cast

import pytest
import zmq

from edumatcher.models.message import dumps
from edumatcher.ralf_gateway.config import RalfGatewayConfig
from edumatcher.ralf_gateway.gateway import RalfGateway

EXAMPLE_DIR = Path("docs-design/examples/ralf")


class _LineReader(Protocol):
    def recv_line(self) -> str: ...


class _RalfMessage(Protocol):
    msg_type: str
    fields: dict[str, str]


class _ParserModule(Protocol):
    def parse_ralf_line(self, line: str) -> _RalfMessage: ...


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_listener(host: str, port: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError(f"gateway did not start listening on {host}:{port}")


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _read_pty_output(
    fd: int,
    predicate: Callable[[str], bool],
    timeout: float,
    proc: subprocess.Popen[bytes] | None = None,
) -> str:
    output = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            break
        remaining = max(0.0, deadline - time.monotonic())
        ready, _, _ = select.select([fd], [], [], min(0.2, remaining))
        if not ready:
            continue
        try:
            raw = os.read(fd, 4096)
        except OSError as exc:
            # On Linux PTYs, reading after child exit can raise EIO instead of EOF.
            if exc.errno == errno.EIO:
                break
            raise
        if not raw:
            break
        chunk = raw.decode("utf-8", errors="replace")
        output += chunk
        if predicate(output):
            return output
    if proc is not None and proc.poll() is not None:
        raise AssertionError(
            f"subscriber exited rc={proc.returncode} before expected output; output was:\n{output}"
        )
    raise AssertionError(output)


def _recv_exec(
    reader: _LineReader,
    parser_module: _ParserModule,
    timeout: float = 2.0,
) -> _RalfMessage:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = parser_module.parse_ralf_line(reader.recv_line())
        if msg.msg_type == "EXEC":
            return msg
    raise AssertionError("did not receive EXEC event")


def _send_trade_executed(pub: zmq.Socket[bytes], exec_id: str) -> None:
    pub.send_multipart(
        [
            b"trade.executed",
            dumps(
                {
                    "id": exec_id,
                    "symbol": "AAPL",
                    "buy_order_id": "B1",
                    "sell_order_id": "S1",
                    "buy_gateway_id": "GW1",
                    "sell_gateway_id": "GW2",
                    "price": 150.25,
                    "quantity": 100,
                    "aggressor_side": "BUY",
                    "timestamp": time.time(),
                }
            ),
        ]
    )


@pytest.fixture()
def running_gateway() -> Generator[tuple[zmq.Socket[bytes], int], None, None]:
    engine_port = _free_port()
    gateway_port = _free_port()
    engine_addr = f"tcp://127.0.0.1:{engine_port}"

    cfg = RalfGatewayConfig(
        name="ralf-example-test",
        bind_address="127.0.0.1",
        port=gateway_port,
        engine_pub_addr=engine_addr,
        replay_retention_sec=60,
        heartbeat_interval_sec=60,
        idle_timeout_sec=30,
        max_client_queue=1000,
    )

    gateway = RalfGateway(cfg)
    thread = threading.Thread(target=gateway.run, daemon=True)
    thread.start()
    _wait_for_listener("127.0.0.1", gateway_port)

    ctx = zmq.Context.instance()
    pub = ctx.socket(zmq.PUB)
    pub.bind(engine_addr)
    time.sleep(0.15)

    try:
        yield pub, gateway_port
    finally:
        gateway.stop()
        thread.join(timeout=2)
        pub.close()
        sys.modules.pop("ralf_parser", None)
        sys.modules.pop("ralf_subscriber_example", None)


def test_ralf_example_files_exist() -> None:
    expected = {
        "ralf_parser.py",
        "ralf_subscriber.py",
        "ralf_parser.h",
        "ralf_parser.c",
        "ralf_subscriber.c",
        "Makefile",
        "README.md",
    }
    found = {p.name for p in EXAMPLE_DIR.iterdir()}
    assert expected.issubset(found)


def test_python_example_subscribes_and_parses_gateway_exec(
    running_gateway: tuple[zmq.Socket[bytes], int],
) -> None:
    pub, gateway_port = running_gateway
    parser_module = cast(
        _ParserModule, _load_module("ralf_parser", EXAMPLE_DIR / "ralf_parser.py")
    )
    subscriber_module = _load_module(
        "ralf_subscriber_example", EXAMPLE_DIR / "ralf_subscriber.py"
    )

    with socket.create_connection(("127.0.0.1", gateway_port), timeout=2) as sock:
        reader = subscriber_module.LineReader(sock)
        subscriber_module.send_line(
            sock,
            "HELLO",
            {
                "CLIENT": "py-example",
                "PROTO": "RALF1",
                "ROLE": "CLEARING",
                "LASTSEQ": "0",
            },
        )
        welcome = parser_module.parse_ralf_line(reader.recv_line())
        assert welcome.msg_type == "WELCOME"
        assert welcome.fields["ROLE"] == "CLEARING"

        subscriber_module.subscribe_channels(
            sock,
            "CLEARING",
            ["CLEARING", "DROP_COPY", "AUDIT"],
            "*",
        )
        snap_types = [
            parser_module.parse_ralf_line(reader.recv_line()).msg_type for _ in range(3)
        ]
        assert snap_types == ["SNAP", "SNAP", "SNAP"]

        _send_trade_executed(pub, "EX-PY-1")

        exec_msg = _recv_exec(reader, parser_module)
        assert exec_msg.fields["EXEC_ID"] == "EX-PY-1"
        assert exec_msg.fields["SYM"] == "AAPL"


def test_c_example_builds_and_receives_gateway_exec(
    running_gateway: tuple[zmq.Socket[bytes], int],
) -> None:
    if shutil.which("make") is None or shutil.which("cc") is None:
        pytest.skip("make and cc are required for the C RALF example test")

    pub, gateway_port = running_gateway
    subprocess.run(
        ["make", "clean"],
        cwd=EXAMPLE_DIR,
        check=True,
    )
    subprocess.run(
        ["make"],
        cwd=EXAMPLE_DIR,
        check=True,
    )

    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        ["./ralf_subscriber", "127.0.0.1", str(gateway_port), "CLEARING"],
        cwd=EXAMPLE_DIR,
        stdin=subprocess.DEVNULL,
        stdout=slave_fd,
        stderr=slave_fd,
    )
    os.close(slave_fd)

    try:
        startup_output = _read_pty_output(
            master_fd,
            lambda text: "WELCOME type=WELCOME" in text
            and "Subscribed as CLEARING" in text,
            timeout=10.0,
            proc=proc,
        )
        assert "WELCOME type=WELCOME" in startup_output
        assert "Subscribed as CLEARING" in startup_output

        event_output = ""
        for _ in range(20):
            _send_trade_executed(pub, "EX-C-1")
            try:
                event_output += _read_pty_output(
                    master_fd,
                    lambda text: "MSG type=EXEC CH=CLEARING" in text
                    and "SYM=AAPL" in text,
                    timeout=0.6,
                    proc=proc,
                )
                break
            except AssertionError as exc:
                event_output += str(exc)
                time.sleep(0.05)

        assert "MSG type=EXEC CH=CLEARING" in event_output
        assert "SYM=AAPL" in event_output
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        os.close(master_fd)
