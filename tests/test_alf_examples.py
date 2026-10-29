from __future__ import annotations

import shutil
import socket
import os
import select
import subprocess
import sys
import threading
import time
import platform
import re
from types import SimpleNamespace
from importlib import import_module
from collections.abc import Generator, Callable
from pathlib import Path

import pytest
import zmq

from edumatcher.alf_gwy.config import AlfGatewayConfig
from edumatcher.alf_gwy.gateway import AlfGateway
from edumatcher.engine.drop_copy import DropCopyPublisher
from edumatcher.models.message import decode
from tests.conftest import wait_for_listener, free_ports
from tests.engine_harness import make_engine

EXAMPLE_DIR = Path("docs/examples/alf")


def test_python_example_position_reversal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(EXAMPLE_DIR / "python"))
    AlfClient = import_module("alf_client").AlfClient

    client = AlfClient(SimpleNamespace(gateway_id="TRADER01", known_symbols=[]))
    client._update_position("AAPL", "BUY", 10, 100.0)
    client._update_position("AAPL", "SELL", 15, 110.0)
    assert client._positions["AAPL"] == {
        "net_qty": -5,
        "avg_cost": 110.0,
        "realized_pnl": 100.0,
    }
    client._update_position("AAPL", "BUY", 6, 105.0)
    assert client._positions["AAPL"] == {
        "net_qty": 1,
        "avg_cost": 105.0,
        "realized_pnl": 125.0,
    }


@pytest.mark.parametrize("partial_reply", [False, True])
def test_python_example_handshake_timeout(
    partial_reply: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(EXAMPLE_DIR / "python"))
    AlfSession = import_module("alf_parser").AlfSession

    client, peer = socket.socketpair()
    peer.settimeout(1)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: client)

    def close_peer() -> None:
        try:
            peer.recv(4096)
            for _ in range(30):
                if partial_reply:
                    try:
                        peer.sendall(b"W")
                    except BrokenPipeError, ConnectionResetError:
                        break
                time.sleep(0.01)
        finally:
            peer.close()

    thread = threading.Thread(target=close_peer)
    thread.start()
    try:
        with pytest.raises(TimeoutError):
            AlfSession.connect("unused", 5565, "TRADER01", timeout=0.05)
        assert client.fileno() == -1
    finally:
        client.close()
        thread.join(timeout=2)


def test_python_example_parser_and_framing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(EXAMPLE_DIR / "python"))
    parser = import_module("alf_parser")
    AlfParseError = parser.AlfParseError
    AlfSession = parser.AlfSession
    build_alf_line = parser.build_alf_line
    parse_alf_line = parser.parse_alf_line

    msg = parse_alf_line(" ack |order_id=FIRST|ORDER_ID=abc123|REASON=Mixed case ")
    assert msg.msg_type == "ACK"
    assert msg.fields == {"ORDER_ID": "abc123", "REASON": "Mixed case"}
    assert build_alf_line("new", {"TAG": "one\r\ntwo"}) == "NEW|TAG=one  two\n"
    with pytest.raises(AlfParseError):
        build_alf_line("NEW", {"TAG": "bad|value"})

    client, peer = socket.socketpair()
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: client)
    peer.sendall(
        b"HB|TS=now\nWELCOME|PROTO=ALF1|GW=alf-test|ID=TRADER01|HBINT=1|IDLE=3\n"
        b"SYMBOLS|COUNT=1\nSYMBOL|SYM=AAPL|TICK=0.01\nEND|TYPE=SYMBOLS\n"
    )
    try:
        session = AlfSession.connect("unused", 5565, "TRADER01")
        assert session.sock.gettimeout() is None
        assert session.recv_msg().msg_type == "SYMBOLS"
        assert session.recv_msg().fields["SYM"] == "AAPL"
        assert session.recv_msg().fields["TYPE"] == "SYMBOLS"
        with pytest.raises(AlfParseError):
            session.send_raw("PING\nEXIT")
        peer.sendall(b"FILL|ORDER_")
        peer.sendall(b"ID=abc123|SYMBOL=AAPL\n")
        assert session.recv_msg().fields["ORDER_ID"] == "abc123"
        session.close()
    finally:
        client.close()
        peer.close()


@pytest.mark.parametrize(
    "reply",
    [
        b"ERR|CODE=AUTH_FAILED|DETAIL=not configured\n",
        b"WELCOME|PROTO=ALF2|GW=gwy|ID=TRADER01|HBINT=1|IDLE=3\n",
        b"WELCOME|PROTO=ALF1|GW=gwy|ID=OTHER|HBINT=1|IDLE=3\n",
    ],
)
def test_python_example_refuses_invalid_handshake(
    reply: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(EXAMPLE_DIR / "python"))
    AlfSession = import_module("alf_parser").AlfSession

    client, peer = socket.socketpair()
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: client)
    peer.sendall(reply)
    try:
        with pytest.raises(RuntimeError):
            AlfSession.connect("unused", 5565, "TRADER01")
        assert client.fileno() == -1
    finally:
        client.close()
        peer.close()


def test_c_example_behavior(tmp_path: Path, c_example_binary: Path) -> None:
    binary = tmp_path / "alf_checks"
    readline_flags = ["-lreadline"]
    if sys.platform == "darwin" and shutil.which("brew"):
        prefix = subprocess.run(
            ["brew", "--prefix", "readline"], text=True, capture_output=True
        )
        if prefix.returncode == 0:
            root = prefix.stdout.strip()
            readline_flags = [f"-I{root}/include", f"-L{root}/lib", "-lreadline"]
    subprocess.run(
        [
            "cc",
            "-std=gnu11",
            "-Wall",
            "-Wextra",
            "-o",
            str(binary),
            "tests/alf_example_checks.c",
            str(EXAMPLE_DIR / "c" / "alf_parser.c"),
            *readline_flags,
        ],
        check=True,
    )
    subprocess.run([str(binary)], check=True, timeout=5)


@pytest.fixture()
def c_example_binary(tmp_path: Path) -> Path:
    if shutil.which("make") is None or shutil.which("cc") is None:
        pytest.skip("make and cc are required")
    for name in ("Makefile", "alf_client.c", "alf_parser.c", "alf_parser.h"):
        shutil.copy2(EXAMPLE_DIR / "c" / name, tmp_path / name)
    build = subprocess.run(["make"], cwd=tmp_path, text=True, capture_output=True)
    if build.returncode != 0:
        output = build.stdout + build.stderr
        if any(
            marker in output
            for marker in (
                "readline/readline.h",
                "readline/history.h",
                "cannot find -lreadline",
                "library not found for -lreadline",
            )
        ):
            pytest.skip("GNU readline development headers/libs are required")
        pytest.fail(output)
    return tmp_path / "alf_client"


@pytest.mark.parametrize("language", ["python", "c"])
def test_example_client_trades_with_engine(
    language: str,
    running_alf_gateway: tuple[int, zmq.Socket[bytes]],
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(EXAMPLE_DIR / "python"))
    AlfSession = import_module("alf_parser").AlfSession

    port, _ = running_alf_gateway
    command = (
        [sys.executable, "-u", str(EXAMPLE_DIR / "python" / "alf_client.py")]
        if language == "python"
        else [str(request.getfixturevalue("c_example_binary")), "--no-color"]
    )
    proc = subprocess.Popen(
        [*command, "--port", str(port), "--id", "MM01", "--debug"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ, "HOME": str(tmp_path)},
    )
    assert proc.stdin is not None and proc.stdout is not None
    stdout = proc.stdout
    output = ""

    def wait_for(predicate: Callable[[str], bool]) -> str:
        nonlocal output
        deadline = time.monotonic() + 5
        while not predicate(output):
            remaining = deadline - time.monotonic()
            assert remaining > 0, output
            ready, _, _ = select.select([stdout], [], [], remaining)
            assert ready, output
            chunk = os.read(stdout.fileno(), 65536)
            assert chunk, output
            output += chunk.decode("utf-8")
        result, output = output, ""
        return result

    def send(line: str) -> None:
        assert proc.stdin is not None
        proc.stdin.write((line + "\n").encode())
        proc.stdin.flush()

    def peer_until(kind: str) -> dict[str, str]:
        assert peer is not None
        for _ in range(100):
            msg = peer.recv_msg()
            if msg.msg_type == kind:
                return msg.fields
        raise AssertionError(f"peer did not receive {kind}")

    peer = None
    try:
        wait_for(lambda text: "Gateway MM01 connected." in text and "SESSION" in text)
        peer = AlfSession.connect("127.0.0.1", port, "TRADER02")
        peer.sock.settimeout(5)

        send("NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=10|PRICE=100|TAG=test-buy")
        ack = wait_for(lambda text: "order accepted" in text)
        order_id = re.search(r"ACK\s+([0-9a-f]{32})", ack)
        assert order_id is not None, ack
        oid = order_id.group(1)
        send(f"AMEND|ID={oid}|PRICE=101|RTAG=amend-test")
        amended = wait_for(lambda text: "AMENDED" in text)
        assert "rtag=AMEND-TEST" in amended

        peer.send_raw("NEW|SYM=AAPL|SIDE=SELL|TYPE=LIMIT|QTY=15|PRICE=101")
        peer_until("FILL")
        filled = wait_for(lambda text: "FILL" in text and "[FILLED]" in text)
        assert "liquidity=MAKER" in filled

        # The peer buys its five remaining asks and leaves fifteen bids.
        peer.send_raw("NEW|SYM=AAPL|SIDE=BUY|TYPE=LIMIT|QTY=20|PRICE=110")
        peer_until("ACK")

        send("NEW|SYM=AAPL|SIDE=SELL|TYPE=MARKET|QTY=15")
        wait_for(lambda text: "FILL" in text and "[FILLED]" in text)
        send("POS")
        position = wait_for(
            lambda text: "Positions" in text
            and re.search(r"AAPL\s+(?:SHORT\s+)?-5", text) is not None
        )
        assert "110.00" in position, position

        send("NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=1|PRICE=20")
        ack = wait_for(lambda text: "order accepted" in text)
        match = re.search(r"ACK\s+([0-9a-f]{32})", ack)
        assert match is not None, ack
        send(f"CANCEL|ID={match.group(1)}|RTAG=cancel-test")
        cancelled = wait_for(lambda text: "CANCELLED" in text)
        assert "rtag=CANCEL-TEST" in cancelled
        send("STATUS")
        status = wait_for(lambda text: "Open orders:" in text)
        assert re.search(r"Open orders:\s+0", status), status
        send("POS|GW=MM01")
        wait_for(lambda text: "Position" in text and "AAPL" in text)
        send("ORDERS")
        wait_for(lambda text: "Orders" in text and "STATUS" in text)
        send("DC|STATE=ON")
        wait_for(lambda text: "DC ACK" in text and "ON" in text)

        send("NEW|SYM=MSFT|SIDE=BUY|TYPE=STOP|QTY=1|STOP=30|TAG=stop-test")
        wait_for(lambda text: "order accepted" in text)
        peer.send_raw("NEW|SYM=MSFT|SIDE=SELL|TYPE=LIMIT|QTY=2|PRICE=30")
        peer_until("ACK")
        peer.send_raw("NEW|SYM=MSFT|SIDE=BUY|TYPE=LIMIT|QTY=1|PRICE=30")
        peer_until("FILL")
        triggered = wait_for(
            lambda text: "TRIGGERED" in text
            and "[FILLED]" in text
            and "DC FILL" in text
        )
        assert triggered.index("TRIGGERED") < triggered.index("[FILLED]"), triggered
        assert "tag=STOP-TEST" in triggered
        send("POS")
        stop_position = wait_for(
            lambda text: "Positions" in text
            and re.search(r"MSFT\s+(?:LONG\s+)?1\s+30.00", text) is not None
        )
        assert re.search(r"MSFT\s+(?:LONG\s+)?1\s+30.00", stop_position), stop_position
        send("DC|STATE=OFF")
        wait_for(lambda text: "DC ACK" in text and "OFF" in text)

        send(
            "NEW|TYPE=OCO|OCO_ID=pair-test|SYM=MSFT|QTY=1|TIF=DAY"
            "|LEG1_SIDE=BUY|LEG1_TYPE=LIMIT|LEG1_PRICE=10"
            "|LEG2_SIDE=SELL|LEG2_TYPE=LIMIT|LEG2_PRICE=40"
        )
        wait_for(lambda text: "OCO ACK" in text and "PAIR-TEST" in text)
        send("CANCEL|OCO_ID=pair-test")
        wait_for(lambda text: text.count("CANCELLED") >= 2)

        send(
            "NEW|TYPE=COMBO|COMBO_ID=combo-test|COMBO_TYPE=AON|TIF=DAY|LEG_COUNT=2"
            "|LEG0.SYM=AAPL|LEG0.SIDE=BUY|LEG0.QTY=1|LEG0.PRICE=10"
            "|LEG1.SYM=MSFT|LEG1.SIDE=SELL|LEG1.QTY=1|LEG1.PRICE=40"
        )
        wait_for(lambda text: "COMBO ACK" in text and "COMBO-TEST" in text)
        send("CANCEL|COMBO_ID=combo-test")
        wait_for(lambda text: "COMBO CANCELLED" in text)
        send("QUOTE|SYM=MSFT|BID=25|ASK=35|BID_QTY=10|ASK_QTY=10|QUOTE_ID=quote-test")
        wait_for(lambda text: "QUOTE ACK" in text and "QUOTE-TEST" in text)
        send("QBOOT|SYM=MSFT")
        wait_for(lambda text: "Quote Bootstrap" in text and "QUOTE-TEST" in text)
        send("QLEGS|SYM=MSFT|SHOW=ALL")
        wait_for(lambda text: "Quote legs" in text and "QUOTE-TEST" in text)
        send("QUOTE_CANCEL|SYM=MSFT")
        wait_for(lambda text: "QUOTE CANCELLED" in text)
        send("KILL")
        wait_for(lambda text: "KILL ACK" in text)
        for order_fields in (
            "SIDE=BUY|TYPE=STOP_LIMIT|QTY=1|STOP=40|PRICE=41",
            "SIDE=SELL|TYPE=TRAILING_STOP|QTY=1|TRAIL=5",
            "SIDE=BUY|TYPE=ICEBERG|QTY=2|PRICE=10|VISIBLE=1",
        ):
            send(f"NEW|SYM=MSFT|{order_fields}")
            ack = wait_for(lambda text: "order accepted" in text)
            order_id = re.search(r"ACK\s+([0-9a-f]{32})", ack)
            assert order_id is not None, ack
            send(f"CANCEL|ID={order_id.group(1)}")
            wait_for(lambda text: "CANCELLED" in text)
        send("NEW|SYM=MSFT|SIDE=BUY|TYPE=IOC|QTY=1|PRICE=10")
        wait_for(lambda text: "order accepted" in text)
        peer.send_raw("NEW|SYM=MSFT|SIDE=SELL|TYPE=LIMIT|QTY=2|PRICE=35")
        peer_until("ACK")
        send("NEW|SYM=MSFT|SIDE=BUY|TYPE=FOK|QTY=2|PRICE=35")
        wait_for(lambda text: "FILL" in text and "[FILLED]" in text)
        send("NEW|SYM=UNKNOWN|SIDE=BUY|TYPE=LIMIT|QTY=1|PRICE=1|TAG=bad-symbol")
        rejected = wait_for(lambda text: "UNKNOWN_SYMBOL" in text)
        assert "tag=BAD-SYMBOL" in rejected
        wait_for(lambda text: text.count("keepalive PING sent") >= 4)
        send("PING")
        wait_for(lambda text: "PONG" in text)
        send("EXIT")
        proc.wait(timeout=5)
        assert proc.returncode == 0
    finally:
        if peer is not None:
            peer.close()
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
        proc.stdin.close()
        proc.stdout.close()


@pytest.fixture()
def running_alf_gateway(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[tuple[int, zmq.Socket[bytes]], None, None]:
    engine, publications = make_engine(
        monkeypatch,
        tmp_path,
        symbols=("AAPL", "MSFT"),
        gateways=("TRADER01", "TRADER02", "MM01"),
        mm_gateways=("MM01",),
    )
    for symbol in ("AAPL", "MSFT"):
        engine._book(symbol)
    engine_pull_port, engine_pub_port, gateway_port, dc_port = free_ports(4)

    engine_pull_addr = f"tcp://127.0.0.1:{engine_pull_port}"
    engine_pub_addr = f"tcp://127.0.0.1:{engine_pub_port}"

    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
    engine_pull: zmq.Socket[bytes] = ctx.socket(zmq.PULL)
    engine_pub: zmq.Socket[bytes] = ctx.socket(zmq.PUB)
    engine_pull.bind(engine_pull_addr)
    engine_pub.bind(engine_pub_addr)
    dc_addr = f"tcp://127.0.0.1:{dc_port}"
    engine._drop_copy = DropCopyPublisher(ctx, addr=dc_addr)

    cfg = AlfGatewayConfig(
        name="alf-example-test",
        bind_address="127.0.0.1",
        port=gateway_port,
        engine_pull_addr=engine_pull_addr,
        engine_pub_addr=engine_pub_addr,
        heartbeat_interval_sec=1,
        handshake_timeout_sec=10,
        idle_timeout_sec=3,
        drop_copy_pub_addr=dc_addr,
        gateway_roles=(("MM01", "MARKET_MAKER"),),
    )

    gateway = AlfGateway(cfg)
    thread = threading.Thread(target=gateway.run, daemon=True)
    thread.start()
    wait_for_listener("127.0.0.1", gateway_port)

    running = True
    errors: list[Exception] = []

    def _engine_loop() -> None:
        try:
            while running:
                if not engine_pull.poll(timeout=100):
                    continue
                topic, payload = decode(engine_pull.recv_multipart())
                if topic == "system.gateway_connect":
                    # The gateway subscribes to auth replies during HELLO.
                    time.sleep(0.1)
                start = len(publications.sent)
                engine._dispatch_pull_message(topic, payload)
                for frames in publications.sent[start:]:
                    engine_pub.send_multipart(frames)
        except Exception as exc:
            errors.append(exc)

    engine_thread = threading.Thread(target=_engine_loop, daemon=True)
    engine_thread.start()

    try:
        yield gateway_port, engine_pull
    finally:
        running = False
        gateway.stop()
        thread.join(timeout=2)
        engine_thread.join(timeout=2)
        engine_pull.close()
        engine_pub.close()
        engine._drop_copy.close()
        assert not errors, errors


def test_alf_example_files_exist() -> None:
    expected = {
        "README.md",
        "python/alf_parser.py",
        "python/alf_client.py",
        "c/alf_parser.h",
        "c/alf_parser.c",
        "c/alf_client.c",
        "c/Makefile",
    }
    found = {
        str(p.relative_to(EXAMPLE_DIR)).replace("\\", "/")
        for p in EXAMPLE_DIR.rglob("*")
        if p.is_file()
    }
    assert expected.issubset(found)


def test_python_example_client_connects_and_exits(
    running_alf_gateway: tuple[int, zmq.Socket[bytes]],
) -> None:
    gateway_port, _ = running_alf_gateway
    script = EXAMPLE_DIR / "python" / "alf_client.py"

    proc = subprocess.run(
        [
            sys.executable,
            script.name,
            "--host",
            "127.0.0.1",
            "--port",
            str(gateway_port),
            "--id",
            "TRADER01",
            "--client",
            "py-example-test",
        ],
        cwd=str(script.parent),
        input="EXIT\n",
        text=True,
        capture_output=True,
        timeout=10,
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    assert proc.returncode == 0, combined
    assert "Gateway TRADER01 connected." in combined


def test_c_example_client_builds_connects_and_exits(
    running_alf_gateway: tuple[int, zmq.Socket[bytes]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _emit_info(*lines: str) -> None:
        with capsys.disabled():
            for line in lines:
                print(line, file=sys.stderr, flush=True)

    if shutil.which("make") is None or shutil.which("cc") is None:
        _emit_info("INFO: skipping C ALF example test because make or cc is missing")
        pytest.skip("make and cc are required for the C ALF example test")

    gateway_port, _ = running_alf_gateway
    c_dir = EXAMPLE_DIR / "c"
    cc_path = shutil.which("cc") or "<missing>"
    make_path = shutil.which("make") or "<missing>"

    print(f"INFO: ALF C example build directory: {c_dir}")
    print(f"INFO: platform={platform.platform()}")
    print(f"INFO: sys.platform={sys.platform}")
    print(f"INFO: make={make_path}")
    print(f"INFO: cc={cc_path}")

    cc_version = subprocess.run(
        [cc_path, "--version"],
        text=True,
        capture_output=True,
    )
    print("INFO: cc --version stdout:")
    print((cc_version.stdout or "<empty>").strip())
    if cc_version.stderr:
        print("INFO: cc --version stderr:")
        print(cc_version.stderr.strip())

    uname = subprocess.run(
        ["uname", "-a"],
        text=True,
        capture_output=True,
    )
    print("INFO: uname -a:")
    print((uname.stdout or "<empty>").strip())

    subprocess.run(["make", "clean"], cwd=c_dir, check=True)
    build = subprocess.run(
        ["make"],
        cwd=c_dir,
        text=True,
        capture_output=True,
    )
    if build.returncode != 0:
        combined = (build.stdout or "") + "\n" + (build.stderr or "")
        print(f"INFO: make failed in {c_dir}")
        if build.stdout:
            print("INFO: make stdout:")
            print(build.stdout)
        if build.stderr:
            print("INFO: make stderr:")
            print(build.stderr)
        if (
            "readline/readline.h" in combined
            or "readline/history.h" in combined
            or "cannot find -lreadline" in combined
            or "ld: cannot find -lreadline" in combined
            or "library not found for -lreadline" in combined
        ):
            _emit_info(
                f"INFO: make failed in {c_dir}",
                "INFO: make stdout:",
                (build.stdout or "<empty>").rstrip(),
                "INFO: make stderr:",
                (build.stderr or "<empty>").rstrip(),
                "INFO: skipping C ALF example test because GNU readline is not available",
            )
            pytest.skip(
                "GNU readline development headers/libs are required for the C ALF example test"
            )
        pytest.fail(
            f"make failed in {c_dir} with exit code {build.returncode}\n"
            f"stdout:\n{build.stdout or '<empty>'}\n"
            f"stderr:\n{build.stderr or '<empty>'}"
        )

    proc = subprocess.run(
        [
            "./alf_client",
            "--host",
            "127.0.0.1",
            "--port",
            str(gateway_port),
            "--id",
            "TRADER01",
            "--client",
            "c-example-test",
            "--no-color",
        ],
        cwd=c_dir,
        input="EXIT\n",
        text=True,
        capture_output=True,
        timeout=10,
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    assert proc.returncode == 0, combined
    assert "Gateway TRADER01 connected." in combined


def test_python_example_client_displays_new_ack_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script_dir = EXAMPLE_DIR / "python"
    monkeypatch.syspath_prepend(str(script_dir))
    AlfClient = import_module("alf_client").AlfClient
    parse_alf_line = import_module("alf_parser").parse_alf_line

    client = AlfClient(SimpleNamespace(gateway_id="TRADER01", known_symbols=[]))
    lines: list[str] = []
    monkeypatch.setattr(client, "_pr", lines.append)
    monkeypatch.setattr(client, "_ts", lambda: "09:30:00.000")

    for raw in [
        "ERR|CODE=SYMBOL_NOT_CONFIGURED|REJECT_CODE=UNKNOWN_SYMBOL|TAG=BAD-TAG|DETAIL=Unknown symbol",
        "ACK|ORDER_ID=ORD1|ACCEPTED=FALSE|REJECT_CODE=ORDER_NOT_FOUND|TAG=ORDER-001|RTAG=REQ-001|REASON=missing",
        "ACK|ORDER_ID=ORD1|ACCEPTED=TRUE|TAG=ORDER-001|SYMBOL=AAPL|SIDE=BUY|TYPE=LIMIT",
        "FILL|ORDER_ID=ORD1|FILL_QTY=1|FILL_PRICE=100|REMAINING=0|STATUS=FILLED|TAG=ORDER-001",
        "AMENDED|ORDER_ID=ORD1|PRICE=101|QTY=2|REMAINING=2|PRIORITY_RESET=TRUE|TAG=ORDER-001|RTAG=REQ-002",
        "CANCELLED|ORDER_ID=ORD1|TAG=ORDER-001|RTAG=REQ-003",
        "EXPIRED|ORDER_ID=ORD1|TAG=ORDER-001",
    ]:
        client._handle(parse_alf_line(raw))

    joined = "\n".join(lines)
    assert "reject_code=UNKNOWN_SYMBOL" in joined
    assert "code=ORDER_NOT_FOUND" in joined
    assert "tag=ORDER-001" in joined
    assert "rtag=REQ-003" in joined


def test_c_example_client_handles_new_ack_metadata_in_source() -> None:
    source = (EXAMPLE_DIR / "c" / "alf_client.c").read_text(encoding="utf-8")

    assert 'alf_get_field(msg, "REJECT_CODE")' in source
    assert 'alf_get_field(msg, "TAG")' in source
    assert 'alf_get_field(msg, "RTAG")' in source
    assert '"TAG="' in source
    assert '"RTAG="' in source
