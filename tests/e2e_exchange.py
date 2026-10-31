"""Start the bundled ``mini`` exchange for end-to-end tests.

Shared by the e2e modules (tests/test_monitor_e2e.py, tests/test_examples_e2e.py):
``pm-opctl-cli`` starts the ``mini`` profile with the bundled ``s10-basic``
config in a scratch data directory. It binds the exchange's fixed ports, so it
runs only with ``-m e2e`` (``make test-e2e``), serially, and skips when a port
is taken.

Not a test module (no test_ prefix) -- pytest will not collect it.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

BIN = Path(sys.executable).parent
#: Every fixed port the mini profile binds (engine, stats health, gateways,
#: log server, pm-monitor, API desk).
PORTS = (
    5555,
    5556,
    5557,
    5561,
    5565,
    5570,
    5580,
    5590,
    5600,
    5601,
    5602,
    5610,
    5611,
    8080,
)


def port_taken(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # As the processes bind: a previous run's TIME_WAIT is no listener.
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
        except OSError:
            return True
    return False


@dataclass
class Exchange:
    data_dir: Path
    env: dict[str, str]
    session_tz: str

    def cli(self, *args: str, timeout: float = 90.0) -> str:
        done = subprocess.run(
            [str(BIN / args[0]), *args[1:]],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        assert done.returncode == 0, f"{' '.join(args)}: {done.stdout}{done.stderr}"
        return done.stdout

    def pid(self, name: str) -> int:
        """The PID pm-opctl-cli recorded for a profile entry."""
        return int((self.data_dir / "emo" / f"{name}.pid").read_text().strip())

    @property
    def today(self) -> str:
        return datetime.now(ZoneInfo(self.session_tz)).date().isoformat()

    def metrics_db(self, sql: str, *args: Any) -> list[tuple[Any, ...]]:
        conn = sqlite3.connect(f"file:{self.data_dir / 'metrics.db'}?mode=ro", uri=True)
        try:
            return conn.execute(sql, args).fetchall()
        finally:
            conn.close()


@contextmanager
def running_exchange(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Generator[Exchange, None, None]:
    """The ``mini`` exchange, started for the calling module and stopped after."""
    # Some Makefile targets pass their own -m, which replaces the default
    # "not e2e": run only when e2e is asked for by name.
    if "e2e" not in str(request.config.getoption("markexpr")).replace("not e2e", ""):
        pytest.skip("end-to-end: run with -m e2e (make test-e2e)")
    if int(os.environ.get("PYTEST_XDIST_WORKER_COUNT", "1")) > 1:
        pytest.skip("one exchange per machine: run serially (make test-e2e)")
    taken = [p for p in PORTS if port_taken(p)]
    if taken:
        pytest.skip(f"exchange ports in use (another exchange running?): {taken}")
    data_dir = tmp_path_factory.mktemp("e2e") / "data"
    data_dir.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("EDUMATCHER_")}
    env["EDUMATCHER_DATA_DIR"] = str(data_dir)
    ex = Exchange(data_dir, env, "")
    ex.cli("pm-config-deploy", "--example", "s10-basic")
    compiled = json.loads((data_dir / "ref_data" / "engine_config.json").read_text())
    ex.session_tz = compiled["engine"]["locale"]["session_timezone"]
    try:
        ex.cli("pm-opctl-cli", "start", "mini")
        yield ex
    finally:
        subprocess.run(
            [str(BIN / "pm-opctl-cli"), "stop"],
            env=env,
            capture_output=True,
            timeout=60,
        )
        # `stop` returns before every process has released its ports (pm-monitor
        # is the slowest); the next e2e module would otherwise find them taken
        # and skip. Wait, so modules can run back to back.
        deadline = time.monotonic() + 30
        while any(port_taken(p) for p in PORTS) and time.monotonic() < deadline:
            time.sleep(0.5)
