from __future__ import annotations

import errno
import importlib.util
import os
import pty
import select
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Generator
from pathlib import Path
from types import ModuleType
from typing import Protocol, cast

import pytest
import zmq

from edumatcher.dc_gateway.config import DcGatewayConfig
from edumatcher.dc_gateway.gateway import DcGateway
from edumatcher.engine.drop_copy import DropCopyPublisher
from tests.conftest import free_ports, wait_for_listener

EXAMPLE_DIR = Path("docs/examples/dc")


class _LineReader(Protocol):
    def recv_line(self) -> str: ...


class _DcMessage(Protocol):
    msg_type: str
    fields: dict[str, str]


class _ParserModule(Protocol):
    def parse_dc_line(self, line: str) -> _DcMessage: ...


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def example_subscriber_module() -> Generator[ModuleType, None, None]:
    _load_module("dc_parser", EXAMPLE_DIR / "dc_parser.py")
    module = _load_module("dc_subscriber_example", EXAMPLE_DIR / "dc_subscriber.py")
    try:
        yield module
    finally:
        sys.modules.pop("dc_parser", None)
        sys.modules.pop("dc_subscriber_example", None)


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
        output += raw.decode("utf-8", errors="replace")
        if predicate(output):
            return output
    if proc is not None and proc.poll() is not None:
        raise AssertionError(
            f"subscriber exited rc={proc.returncode} before expected output; output was:\n{output}"
        )
    raise AssertionError(output)


def _publish_fill(
    pub: DropCopyPublisher, order_id: str, qty: int, price: float
) -> None:
    pub.publish_fill(
        "TRADER01",
        order_id=order_id,
        trade_ids=["000001-000000001"],
        symbol="AAPL",
        fill_qty=qty,
        fill_price=price,
        liquidity_flag="MAKER",
    )


@pytest.fixture()
def running_gateway() -> Generator[tuple[DropCopyPublisher, int], None, None]:
    dc_pub_port, gateway_port = free_ports(2)
    dc_pub_addr = f"tcp://127.0.0.1:{dc_pub_port}"
    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
    pub = DropCopyPublisher(ctx, addr=dc_pub_addr)

    cfg = DcGatewayConfig(
        name="dc-example-test",
        bind_address="127.0.0.1",
        port=gateway_port,
        drop_copy_pub_addr=dc_pub_addr,
        heartbeat_interval_sec=60,
        idle_timeout_sec=30,
        max_client_queue=1000,
    )
    gateway = DcGateway(cfg)
    thread = threading.Thread(target=gateway.run, daemon=True)
    thread.start()
    wait_for_listener("127.0.0.1", gateway_port)

    try:
        yield pub, gateway_port
    finally:
        gateway.stop()
        thread.join(timeout=2)
        pub.close()
        sys.modules.pop("dc_parser", None)
        sys.modules.pop("dc_subscriber_example", None)


def test_dc_example_files_exist() -> None:
    expected = {
        "dc_parser.py",
        "dc_subscriber.py",
        "dc_parser.h",
        "dc_parser.c",
        "dc_subscriber.c",
        "Makefile",
        "README.md",
    }
    found = {p.name for p in EXAMPLE_DIR.iterdir()}
    assert expected.issubset(found)


def test_python_example_handshakes_and_parses_gateway_fill(
    running_gateway: tuple[DropCopyPublisher, int],
) -> None:
    pub, gateway_port = running_gateway
    parser_module = cast(
        _ParserModule, _load_module("dc_parser", EXAMPLE_DIR / "dc_parser.py")
    )
    subscriber_module = _load_module(
        "dc_subscriber_example", EXAMPLE_DIR / "dc_subscriber.py"
    )

    with socket.create_connection(("127.0.0.1", gateway_port), timeout=2) as sock:
        reader: _LineReader = subscriber_module.LineReader(sock)
        subscriber_module.send_line(
            sock, "HELLO", {"CLIENT": "py-example", "PROTO": "DC1", "ID": "TRADER01"}
        )
        welcome = parser_module.parse_dc_line(reader.recv_line())
        assert welcome.msg_type == "WELCOME"
        assert welcome.fields["ID"] == "TRADER01"

        # PUB/SUB startup can drop early messages until subscriptions propagate.
        # Send a short burst so at least one DC_FILL lands deterministically.
        time.sleep(0.2)
        for _ in range(10):
            _publish_fill(pub, "ord-py-1", 100, 150.25)
            time.sleep(0.02)

        fill = parser_module.parse_dc_line(reader.recv_line())
        assert fill.msg_type == "DC_FILL"
        assert fill.fields["ORDER_ID"] == "ord-py-1"
        assert fill.fields["SYMBOL"] == "AAPL"


def test_python_example_tallies_qty_vwap_and_liquidity(
    example_subscriber_module: ModuleType,
) -> None:
    tracker = example_subscriber_module.FillTracker()
    tracker.observe(
        {"SYMBOL": "AAPL", "FILL_QTY": "100", "FILL_PRICE": "10", "LIQUIDITY": "MAKER"}
    )
    tracker.observe(
        {"SYMBOL": "AAPL", "FILL_QTY": "300", "FILL_PRICE": "20", "LIQUIDITY": "TAKER"}
    )
    tracker.observe({"SYMBOL": "AAPL", "FILL_QTY": "x", "FILL_PRICE": "20"})

    tally = tracker.tally_for("AAPL")
    assert tally.fills == 2
    assert tally.total_qty == 400
    assert tally.vwap == pytest.approx(17.5)
    assert (tally.maker_qty, tally.taker_qty) == (100, 300)


def test_python_example_reports_backwards_seq_but_not_gaps(
    example_subscriber_module: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """SEQ is engine-wide, so a per-ID session sees gaps routinely; only a
    SEQ that goes backwards (engine restart) is worth reporting."""
    tracker = example_subscriber_module.SequenceTracker()
    tracker.observe("5")
    tracker.observe("42")
    assert "SEQ went backwards" not in capsys.readouterr().err
    tracker.observe("1")
    assert "SEQ went backwards: 1 after 42" in capsys.readouterr().err
    tracker.observe("2")
    assert capsys.readouterr().err == ""


def test_python_example_exits_when_the_handshake_is_refused(
    running_gateway: tuple[DropCopyPublisher, int],
) -> None:
    """An empty ID gets ERR|CODE=AUTH_REQUIRED in reply to HELLO and the
    session is closed; the example must exit instead of waiting for fills."""
    _pub, gateway_port = running_gateway
    proc = subprocess.run(
        [sys.executable, "dc_subscriber.py", "--port", str(gateway_port), "--id", ""],
        cwd=EXAMPLE_DIR,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 1
    assert "handshake refused: ERR AUTH_REQUIRED" in proc.stderr
    assert "Receiving fills" not in proc.stdout


def test_c_example_builds_receives_fills_and_prints_summary_on_sigint(
    running_gateway: tuple[DropCopyPublisher, int],
) -> None:
    if shutil.which("make") is None or shutil.which("cc") is None:
        pytest.skip("make and cc are required for the C DC example test")

    pub, gateway_port = running_gateway
    subprocess.run(["make", "clean"], cwd=EXAMPLE_DIR, check=True)
    subprocess.run(["make"], cwd=EXAMPLE_DIR, check=True)

    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        ["./dc_subscriber", "127.0.0.1", str(gateway_port), "TRADER01"],
        cwd=EXAMPLE_DIR,
        stdin=subprocess.DEVNULL,
        stdout=slave_fd,
        stderr=slave_fd,
    )
    os.close(slave_fd)

    try:
        _read_pty_output(
            master_fd,
            lambda text: "Receiving fills for ID=TRADER01" in text,
            timeout=10.0,
            proc=proc,
        )
        time.sleep(0.2)  # let the gateway's ZMQ SUBSCRIBE reach the publisher

        # handle_message()'s DC_FILL format is
        # "FILL  %-8s %6s @ %10s %-5s order=%s seq=%s  [...]" (dc_subscriber.c).
        _publish_fill(pub, "ord-c-1", 100, 150.25)
        _read_pty_output(
            master_fd,
            lambda text: "FILL  AAPL" in text and "order=ord-c-1" in text,
            timeout=5.0,
            proc=proc,
        )

        proc.send_signal(signal.SIGINT)
        summary = _read_pty_output(
            master_fd,
            lambda text: "AAPL     1 fill(s), 100 qty, VWAP 150.2500" in text,
            timeout=5.0,
            proc=None,
        )
        assert "Fill summary: 1 fill(s)" in summary
        assert proc.wait(timeout=5) == 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
        os.close(master_fd)
