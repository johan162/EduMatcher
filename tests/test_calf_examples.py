"""docs/examples/calf/calf_subscriber.py against the gateway's session rules:
a refused HELLO, a gateway EXIT and which ERR codes end the session."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import threading
from collections.abc import Generator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from edumatcher.md_gateway.config import MarketDataGatewayConfig
from edumatcher.md_gateway.gateway import MarketDataGateway
from tests.conftest import free_ports, wait_for_listener

EXAMPLE_DIR = Path("docs/examples/calf")


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"failed to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def example() -> Generator[ModuleType, None, None]:
    _load_module("calf_parser", EXAMPLE_DIR / "calf_parser.py")
    module = _load_module("calf_subscriber_example", EXAMPLE_DIR / "calf_subscriber.py")
    try:
        yield module
    finally:
        sys.modules.pop("calf_parser", None)
        sys.modules.pop("calf_subscriber_example", None)


def _handle(example: ModuleType, msg_type: str, fields: dict[str, str]) -> None:
    example._handle_message(
        example.CalfMessage(msg_type, fields),
        {},
        example.SequenceTracker(sock=None),
        example.ReferenceData(),
        set(),
    )


def test_a_gateway_exit_ends_the_example(example: ModuleType) -> None:
    with pytest.raises(SystemExit, match="idle_timeout"):
        _handle(example, "EXIT", {"REASON": "idle_timeout", "TS": "x"})


@pytest.mark.parametrize("code", ["AUTH_REQUIRED", "SLOW_CLIENT"])
def test_terminal_errors_end_the_example(example: ModuleType, code: str) -> None:
    with pytest.raises(SystemExit, match=code):
        _handle(example, "ERR", {"CODE": code, "DETAIL": "x"})


def test_a_bad_message_leaves_the_session_open(example: ModuleType) -> None:
    """BAD_MESSAGE is terminal only for an oversized line, which this
    example never sends; a bad RESUME, say, keeps the session."""
    _handle(example, "ERR", {"CODE": "BAD_MESSAGE", "DETAIL": "LASTSEQ must be > 0"})


@pytest.fixture()
def running_gateway() -> Generator[int, None, None]:
    port, engine_pub, engine_pull, index_pub = free_ports(4)
    gateway = MarketDataGateway(
        MarketDataGatewayConfig(
            bind_address="127.0.0.1",
            port=port,
            engine_pub_addr=f"tcp://127.0.0.1:{engine_pub}",
            engine_pull_addr=f"tcp://127.0.0.1:{engine_pull}",
            index_pub_addr=f"tcp://127.0.0.1:{index_pub}",
        )
    )
    thread = threading.Thread(target=gateway.run, daemon=True)
    thread.start()
    wait_for_listener("127.0.0.1", port)
    try:
        yield port
    finally:
        gateway.stop()
        thread.join(timeout=2)


def test_the_example_exits_when_the_handshake_is_refused(running_gateway: int) -> None:
    """CLIENT over 32 characters is refused with ERR|CODE=AUTH_REQUIRED."""
    proc: Any = subprocess.run(
        [
            sys.executable,
            "calf_subscriber.py",
            "--port",
            str(running_gateway),
            "--client",
            "X" * 40,
        ],
        cwd=EXAMPLE_DIR,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 1
    assert "handshake refused: ERR AUTH_REQUIRED" in proc.stderr
    assert "Subscribed" not in proc.stdout
