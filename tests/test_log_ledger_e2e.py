"""The log ledger on a real exchange, from the log call to the log-GUI drawer.

The ``mini`` exchange runs real processes logging through the real log
client into a real pm-log-srv. Every WARNING+ row they log must carry a
``tpl``, that ``tpl`` must be the key the call-site scanner derives from the
source (so ``pm-log-cli ledger check`` and the rows agree), and
``pm-log-cli explain`` must read it. The log-GUI bridge must load the same
ledger through ``pm-log-cli ledger export``, and its Explorer drawer must
explain a real WARNING row (docs-design/EduMatcher-Log-Ledger.md). The
browser part needs ``web-apps/log-gui``'s ``npm install`` and Chrome.

End-to-end: runs only with ``-m e2e`` (``make test-e2e``).
"""

from __future__ import annotations

import json
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from edumatcher.log_ledger import load_ledger
from edumatcher.log_ledger.scan import scan_package
from edumatcher.logclient.protocol import template_id
from tests.conftest import free_ports
from tests.e2e_exchange import BIN, Exchange, running_exchange
from tests.test_monitor_e2e import CHROME, Page, until

LOG_GUI = Path(__file__).resolve().parents[1] / "web-apps" / "log-gui"

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals"),
]


@pytest.fixture(scope="module")
def exchange(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Exchange]:
    with running_exchange(request, tmp_path_factory) as ex:
        yield ex


def _rows(exchange: Exchange, where: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(f"file:{exchange.data_dir / 'log.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [
            dict(r)
            for r in conn.execute(
                f"SELECT seq, level, logger, tpl, message FROM log_events WHERE {where}"
            )
        ]
    finally:
        conn.close()


@pytest.fixture(scope="module")
def warnings(exchange: Exchange) -> list[dict[str, Any]]:
    """WARNING+ rows, first the one this provokes: ``mini`` starts cleanly,
    so a line longer than CALF allows is sent to pm-md-gwy, which drops the
    client with a WARNING."""
    compiled = json.loads(
        (exchange.data_dir / "ref_data" / "engine_config.json").read_text()
    )
    port = compiled["market_data_gateway"]["port"]

    def send_oversized_line() -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
                sock.sendall(b"x" * 8192)
        except OSError:
            return False  # pm-md-gwy is not listening yet
        return True

    until(send_oversized_line, "pm-md-gwy to accept a connection", 30)
    provoked = "inbound line exceeds"
    deadline = time.monotonic() + 30
    while True:
        rows = _rows(exchange, "level IN ('WARNING', 'ERROR', 'CRITICAL')")
        if any(provoked in r["message"] for r in rows) or time.monotonic() > deadline:
            break
        time.sleep(0.5)
    rows.sort(key=lambda r: provoked not in r["message"])
    assert rows and provoked in rows[0]["message"], rows
    return rows


def test_warning_rows_carry_the_scanned_call_site_key(
    exchange: Exchange, warnings: list[dict[str, Any]]
) -> None:
    scanned = {
        template_id(s.logger, s.template)
        for s in scan_package()
        if s.logger is not None and s.template is not None
    }
    assert all(r["tpl"] in scanned for r in warnings), warnings
    assert not _rows(exchange, "level IN ('DEBUG', 'INFO') AND tpl IS NOT NULL")


def test_explain_reads_a_real_row(
    exchange: Exchange, warnings: list[dict[str, Any]]
) -> None:
    row = warnings[0]
    entry = load_ledger().get(row["tpl"])

    out = exchange.cli("pm-log-cli", "explain", str(row["seq"]))
    assert row["message"].splitlines()[0] in out
    if entry is None:
        assert f"No ledger entry for this message (tpl={row['tpl']})." in out
    else:
        assert "Explanation:" in out

    explained = json.loads(
        exchange.cli("pm-log-cli", "--format", "json", "explain", str(row["seq"]))
    )
    assert explained["tpl"] == row["tpl"]
    assert (explained["explain"] is None) == (entry is None)


# ---------------------------------------------------------------------------
# the log-GUI bridge and its Explorer drawer
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def log_gui(exchange: Exchange) -> Iterator[str]:
    """The log-GUI bridge on the exchange's log.db, serving the built web app."""
    tsx = LOG_GUI / "node_modules" / ".bin" / "tsx"
    if not tsx.exists():
        pytest.skip("web-apps/log-gui has no node_modules (npm install)")
    built = subprocess.run(
        ["npm", "run", "build", "--workspace", "@edumatcher/log-web"],
        cwd=LOG_GUI,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert built.returncode == 0, f"web build failed: {built.stdout}{built.stderr}"
    (port,) = free_ports(1)
    env = {
        **exchange.env,
        "HOST": "127.0.0.1",
        "PORT": str(port),
        "LOG_DB_PATH": str(exchange.data_dir / "log.db"),
        "ACK_STORE_PATH": str(exchange.data_dir / "log-ui-acks.db"),
        "STATIC_DIR": str(LOG_GUI / "apps" / "web" / "dist"),
        "LOG_CLI_COMMAND": str(BIN / "pm-log-cli"),
    }
    proc = subprocess.Popen(
        [str(tsx), "src/server.ts"],
        cwd=LOG_GUI / "apps" / "bridge",
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"

    def up() -> bool:
        try:
            with urllib.request.urlopen(f"{url}/api/healthz", timeout=2):
                return True
        except OSError:
            return False

    try:
        until(up, "the log-GUI bridge to listen", 30)
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_the_bridge_serves_the_shipped_ledger(log_gui: str) -> None:
    with urllib.request.urlopen(f"{log_gui}/api/ledger", timeout=20) as r:
        served = json.load(r)
    assert served["available"] is True
    assert {
        tpl: (e["logger"], e["template"], e["explanation"], e["actions"])
        for tpl, e in served["entries"].items()
    } == {
        tpl: (e.logger, e.template, e.explanation, list(e.actions))
        for tpl, e in load_ledger().items()
    }


def _click(element: str) -> str:
    """JS that clicks ``element`` once it exists; truthy only when it did."""
    return f"(() => {{ const el = {element}; if (!el) return false; el.click(); return true; }})()"


def test_the_explorer_drawer_explains_a_real_warning(
    log_gui: str,
    warnings: list[dict[str, Any]],
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    if CHROME is None:
        pytest.skip("no Chrome to drive")
    row = warnings[0]
    entry = load_ledger().get(row["tpl"])
    first_line = row["message"].splitlines()[0]
    no_entry = f"No ledger entry for this message (tpl={row['tpl']})."
    page = Page(CHROME, tmp_path_factory.mktemp("chrome"))
    try:
        page.goto(f"{log_gui}/logs?minLevel=WARNING")
        # LIVE shows only rows that arrive from now on; history has the
        # warnings logged while the exchange started.
        page.wait(
            _click(
                "[...document.querySelectorAll('button')]"
                ".find(b => b.textContent.includes('LIVE'))"
            ),
            "the LIVE/history toggle",
        )
        page.wait(
            _click(
                "[...document.querySelectorAll('div.cursor-pointer')]"
                f".find(d => d.textContent.includes({json.dumps(first_line)}))"
            ),
            "the warning row in history",
        )
        if entry is None:
            page.wait(
                f"document.body.innerText.includes({json.dumps(no_entry)})",
                "the drawer's no-entry line",
            )
        else:
            explanation = page.wait(
                "document.querySelector('section[aria-label=Explanation]')?.innerText",
                "the drawer's Explanation panel",
            )
            assert entry.explanation in explanation
            actions = page.js(
                "document.querySelectorAll("
                "'section[aria-label=\"Suggested actions\"] li').length"
            )
            assert actions == len(entry.actions)
    finally:
        page.close()
