"""WP-API09: the REST examples run against a real exchange, so they cannot rot.

Each script in ``docs/examples/REST/python`` is run as a reader would run it
-- ``python3 <script> --url ... --key ...`` from its own directory -- against
the bundled ``mini`` exchange (``s10-basic`` keys). A script exits non-zero
when what it demonstrates does not hold.

End-to-end: runs only with ``-m e2e`` (``make test-e2e``).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.e2e_exchange import Exchange, running_exchange

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals"),
]

EXAMPLES = Path(__file__).resolve().parents[1] / "docs" / "examples" / "REST" / "python"
URL = "http://127.0.0.1:8080"
#: s10-basic's API desk keys.
TRADER = "key-trader01-610wpl"
ADMIN = "key-ops01-iy9y1f"


@pytest.fixture(scope="module")
def exchange(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Exchange]:
    with running_exchange(request, tmp_path_factory) as ex:
        deadline = time.monotonic() + 60
        while True:
            try:
                with urllib.request.urlopen(f"{URL}/api/v1/healthz", timeout=2) as r:
                    if json.loads(r.read()).get("ok"):
                        break
            except OSError:
                pass
            assert time.monotonic() < deadline, "the API gateway never became healthy"
            time.sleep(0.5)
        yield ex


def run(script: str, key: str, *args: str) -> str:
    done = subprocess.run(
        [sys.executable, script, "--url", URL, "--key", key, *args],
        cwd=EXAMPLES,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert done.returncode == 0, f"{script}:\n{done.stdout}\n{done.stderr}"
    return done.stdout


def test_order_lifecycle(exchange: Exchange) -> None:
    # s10-basic seeds AAPL at bid 22.78 / ask 22.98: 22.70 rests.
    out = run("order_lifecycle.py", TRADER, "--symbol", "AAPL", "--price", "22.70")
    assert "same order, no duplicate" in out
    assert "reject_code=TICK_VIOLATION" in out


def test_private_stream(exchange: Exchange) -> None:
    out = run("private_stream.py", TRADER, "--symbol", "AAPL", "--price", "22.70")
    assert "snapshot:" in out and "done:" in out


def test_market_data(exchange: Exchange) -> None:
    out = run("market_data.py", TRADER, "--symbol", "AAPL", "--trade")
    assert "trade AAPL" in out and "done:" in out


def test_history_pages(exchange: Exchange) -> None:
    out = run("history_pages.py", TRADER, "--limit", "2")
    assert "trades today" in out or "no history yet" in out


def test_admin_halt_and_reopen(exchange: Exchange) -> None:
    out = run("admin_halt_reopen.py", ADMIN, "--symbol", "MSFT")
    assert "1. halted MSFT" in out and "4. " in out


def test_market_order_script(exchange: Exchange) -> None:
    out = run(
        "submit_market_order.py", TRADER, "--side", "SELL", "--symbol", "AAPL",
        "--qty", "1", "--wait-ack",
    )  # fmt: skip
    assert "order_id" in out
