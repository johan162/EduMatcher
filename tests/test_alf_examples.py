from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import threading
import time
import platform
from collections.abc import Generator
from pathlib import Path

import pytest
import zmq

from edumatcher.alf_gwy.config import AlfGatewayConfig
from edumatcher.alf_gwy.gateway import AlfGateway
from edumatcher.models.message import decode, encode

EXAMPLE_DIR = Path("docs/examples/alf")


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


@pytest.fixture()
def running_alf_gateway() -> Generator[tuple[int, zmq.Socket[bytes]], None, None]:
    engine_pull_port = _free_port()
    engine_pub_port = _free_port()
    gateway_port = _free_port()

    engine_pull_addr = f"tcp://127.0.0.1:{engine_pull_port}"
    engine_pub_addr = f"tcp://127.0.0.1:{engine_pub_port}"

    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
    engine_pull: zmq.Socket[bytes] = ctx.socket(zmq.PULL)
    engine_pub: zmq.Socket[bytes] = ctx.socket(zmq.PUB)
    engine_pull.bind(engine_pull_addr)
    engine_pub.bind(engine_pub_addr)

    cfg = AlfGatewayConfig(
        name="alf-example-test",
        bind_address="127.0.0.1",
        port=gateway_port,
        engine_pull_addr=engine_pull_addr,
        engine_pub_addr=engine_pub_addr,
        heartbeat_interval_sec=1,
        handshake_timeout_sec=10,
        idle_timeout_sec=30,
    )

    gateway = AlfGateway(cfg)
    thread = threading.Thread(target=gateway.run, daemon=True)
    thread.start()
    _wait_for_listener("127.0.0.1", gateway_port)

    running = True

    def _engine_loop() -> None:
        while running:
            if not engine_pull.poll(timeout=100):
                continue
            topic, payload = decode(engine_pull.recv_multipart())
            if topic == "system.gateway_connect":
                gw_id = str(payload.get("gateway_id", "")).upper()
                # Allow SUB subscription propagation before publishing auth reply.
                time.sleep(0.1)
                engine_pub.send_multipart(
                    encode(
                        f"system.gateway_auth.{gw_id}",
                        {
                            "gateway_id": gw_id,
                            "accepted": True,
                            "reason": "",
                            "description": "alf examples test",
                        },
                    )
                )
            elif topic == "system.symbols_request":
                gw_id = str(payload.get("gateway_id", "")).upper()
                engine_pub.send_multipart(
                    encode(
                        f"system.symbols.{gw_id}",
                        {
                            "symbols": ["AAPL"],
                            "symbol_meta": {"AAPL": {"tick": "0.01"}},
                        },
                    )
                )

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
) -> None:
    if shutil.which("make") is None or shutil.which("cc") is None:
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
            print(
                "INFO: skipping C ALF example test because GNU readline is not available"
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
