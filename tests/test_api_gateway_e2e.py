"""End to end: pm-api-gwy between real processes (API gateway review 2026-11).

The defects these pin only show between processes: a WebSocket handler that
kept a stopped gateway alive (H2), and a private snapshot that forgot every
order and position over a gateway restart (H1). Each test starts its own
``mini`` exchange, because each one stops or restarts part of it.

End-to-end: runs only with ``-m e2e`` (``make test-e2e``).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import signal
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

import pytest
from websockets.sync.client import connect

from tests.e2e_exchange import BIN, Exchange, port_taken, running_exchange

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals"),
]

URL = "http://127.0.0.1:8080"
WS_URL = "ws://127.0.0.1:8080"
#: s10-basic's API desk keys.
TRADER01 = "key-trader01-610wpl"
TRADER02 = "key-trader02-hosap4"
#: MM01 keeps its orders when its gateway disconnects (CANCEL_QUOTES_ONLY).
MM01 = "key-mm01-yongbq"


def _wait_healthy(deadline_sec: float = 60.0) -> None:
    deadline = time.monotonic() + deadline_sec
    while True:
        try:
            with urllib.request.urlopen(f"{URL}/api/v1/healthz", timeout=2) as r:
                if json.loads(r.read()).get("ok"):
                    return
        except OSError:
            pass
        assert time.monotonic() < deadline, "the API gateway never became healthy"
        time.sleep(0.5)


@pytest.fixture
def exchange(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Exchange]:
    with running_exchange(request, tmp_path_factory) as ex:
        _wait_healthy()
        yield ex


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_stop_after_a_closed_private_socket(exchange: Exchange) -> None:
    """H2: a client-closed /ws/private socket no longer holds the process."""
    desk = exchange.pid("api-desk-gwy")
    with connect(f"{WS_URL}/api/v1/ws/private", open_timeout=10) as socket:
        socket.send(json.dumps({"api_key": TRADER02}))
        types = [json.loads(socket.recv(timeout=10))["type"] for _ in range(2)]
    assert types == ["authenticated", "orders.snapshot"]

    started = time.monotonic()
    done = subprocess.run(
        [str(BIN / "pm-opctl-cli"), "stop"],
        env=exchange.env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    while (_alive(desk) or port_taken(8080)) and time.monotonic() - started < 15:
        time.sleep(0.2)

    assert done.returncode == 0, done.stdout + done.stderr
    assert not _alive(desk), "pm-api-gwy still running after stop"
    assert not port_taken(8080)


def _call(method: str, path: str, key: str, body: Any = None) -> Any:
    request = urllib.request.Request(
        f"{URL}{path}",
        data=None if body is None else json.dumps(body).encode(),
        method=method,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as reply:
            return json.loads(reply.read())
    except urllib.error.HTTPError as exc:
        raise AssertionError(f"{method} {path}: {exc.code} {exc.read()!r}") from exc


def _order(key: str, side: str, qty: int, price: float, tif: str) -> Any:
    body = {
        "symbol": "AAPL",
        "side": side,
        "order_type": "LIMIT",
        "tif": tif,
        "quantity": qty,
        "price": price,
    }
    return _call("POST", "/api/v1/orders?wait=ack", key, body)


def _private_snapshot(key: str) -> dict[str, Any]:
    with connect(f"{WS_URL}/api/v1/ws/private", open_timeout=10) as socket:
        socket.send(json.dumps({"api_key": key}))
        frames = [json.loads(socket.recv(timeout=10)) for _ in range(2)]
    assert [f["type"] for f in frames] == ["authenticated", "orders.snapshot"]
    return frames[1]


def test_snapshot_after_a_gateway_restart(exchange: Exchange) -> None:
    """H1: after a desk restart the snapshot still has MM01's resting order
    and position, which the engine holds."""
    assert _order(TRADER01, "SELL", 10, 22.70, "DAY")["accepted"]
    assert _order(MM01, "BUY", 10, 22.70, "DAY")["accepted"]
    resting = _order(MM01, "BUY", 5, 20.00, "GTC")
    assert resting["accepted"]
    deadline = time.monotonic() + 10
    while _call("GET", "/api/v1/positions", MM01)["count"] == 0:
        assert time.monotonic() < deadline, "MM01's buy never filled"
        time.sleep(0.2)

    desk = exchange.pid("api-desk-gwy")
    os.kill(desk, signal.SIGTERM)
    deadline = time.monotonic() + 15
    while _alive(desk) or port_taken(8080):
        assert time.monotonic() < deadline, "the desk gateway did not stop"
        time.sleep(0.2)
    log = (exchange.data_dir / "emo" / "api-desk-gwy-restarted.log").open("ab")
    with log:
        restarted = subprocess.Popen(
            [str(BIN / "pm-api-gwy"), "--instance", "desk"],
            env=exchange.env,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    # Recorded where pm-opctl-cli keeps it, so the fixture's stop ends it.
    (exchange.data_dir / "emo" / "api-desk-gwy.pid").write_text(
        f"{restarted.pid}\n", encoding="ascii"
    )
    _wait_healthy()

    snapshot = _private_snapshot(MM01)

    orders = {o["order_id"]: o for o in snapshot["data"]["orders"]}
    assert resting["order_id"] in orders
    assert orders[resting["order_id"]]["remaining_qty"] == 5
    assert snapshot["data"]["positions"] == {"AAPL": 10}
