"""End to end: the clearing GUI in a real browser against the real API.

The chain as deployed, minus the matching engine: a real ``pm-api-gwy`` app
(``create_app``, served by uvicorn) reads ``clearing.db`` and ``eod.db``
recorded by the real ``pm-clearing`` and ``pm-eod`` code
(``tests/clearing_api_fixture.py``); the production build of
``web-apps/clearing-gui`` is served by its own ``serve.ts``, which proxies
``/api`` to that gateway; and headless Chrome, driven over the DevTools
protocol (``tests/test_monitor_e2e.py``'s ``Page``), logs in with each role's
key and walks its journey. The engine is the fixture's fake, which answers
key checks, roles, the ADMIN gateway roster and the per-requester symbol
settings -- everything the clearing routes ask it.

Needs ``web-apps/clearing-gui``'s ``npm install`` and a Chrome; skips without
either. Binds only free ports, but builds the web app, so it runs with the
other end-to-end tests (``-m e2e``, ``make test-e2e``).
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from edumatcher.api_gateway.routers import clearing as clearing_router
from tests.clearing_api_fixture import (
    ADMIN_KEY,
    MM_KEY,
    SILENT_HEALTH_ADDR,
    TRADER_KEY,
    build_venue,
    make_clearing_app,
)
from tests.conftest import free_ports
from tests.test_monitor_e2e import CHROME, Page, until

pytestmark = pytest.mark.e2e

REPO = Path(__file__).resolve().parents[1]
GUI = REPO / "web-apps" / "clearing-gui"


def _e2e_requested(request: pytest.FixtureRequest) -> bool:
    markexpr = str(request.config.getoption("markexpr"))
    return "e2e" in markexpr.replace("not e2e", "")


@pytest.fixture(scope="module")
def gateway(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[str]:
    """The real API app over the seeded venue, on a free port."""
    if not _e2e_requested(request):
        pytest.skip("end-to-end: run with -m e2e (make test-e2e)")
    venue = build_venue(tmp_path_factory.mktemp("venue"))
    app = make_clearing_app(venue)
    # Never ping a pm-clearing that may be running on this machine.
    saved = clearing_router._HEALTH_ADDR
    clearing_router._HEALTH_ADDR = SILENT_HEALTH_ADDR
    (port,) = free_ports(1)
    # lifespan off: the app's state is the fixture's, and its lifespan would
    # replace it with a real engine client.
    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=port, lifespan="off", log_level="warning"
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        until(lambda: server.started, "the API gateway to listen", 20)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        clearing_router._HEALTH_ADDR = saved


@pytest.fixture(scope="module")
def gui(gateway: str) -> Iterator[str]:
    """The production build, served by serve.ts with /api proxied to `gateway`."""
    tsx = GUI / "node_modules" / ".bin" / "tsx"
    if not tsx.exists():
        pytest.skip("web-apps/clearing-gui has no node_modules (npm install)")
    built = subprocess.run(
        ["npm", "run", "build", "--workspace", "@edumatcher/clearing-web"],
        cwd=GUI,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert built.returncode == 0, f"web build failed: {built.stdout}{built.stderr}"
    (port,) = free_ports(1)
    env = {
        **os.environ,
        "HOST": "127.0.0.1",
        "PORT": str(port),
        "API_PROXY_TARGET": gateway,
        "STATIC_DIR": str(GUI / "apps" / "web" / "dist"),
    }
    proc = subprocess.Popen(
        [str(tsx), "apps/serve/serve.ts"],
        cwd=GUI,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"

    def up() -> bool:
        try:
            with urllib.request.urlopen(url + "/", timeout=2) as r:
                return bool(r.status == 200)
        except OSError:
            return False

    try:
        until(up, "the clearing GUI server to listen", 30)
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="module")
def page(gui: str, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Page]:
    if CHROME is None:
        pytest.skip("no Chrome to drive")
    p = Page(CHROME, tmp_path_factory.mktemp("chrome"))
    try:
        yield p
    finally:
        p.close()


# ---------------------------------------------------------------------------
# Driving the page: React inputs need the native setter plus an input event.
# ---------------------------------------------------------------------------

BODY = "document.body ? document.body.innerText : ''"


def _contains(page: Page, text: str, what: str, timeout: float = 20.0) -> None:
    page.wait(f"({BODY}).includes({json.dumps(text)})", what, timeout)


def _path(page: Page, path: str) -> None:
    page.wait(f"location.pathname === {json.dumps(path)}", f"the route {path}")


def _fill(page: Page, label: str, value: str) -> None:
    page.wait(
        f"""(() => {{
          const l = [...document.querySelectorAll('label')]
            .find((x) => x.textContent.trim() === {json.dumps(label)});
          const el = l && document.getElementById(l.htmlFor);
          if (!el) return false;
          const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
          set.call(el, {json.dumps(value)});
          el.dispatchEvent(new Event('input', {{ bubbles: true }}));
          return true;
        }})()""",
        f"the {label} field",
    )


def _click(page: Page, text: str) -> None:
    page.wait(
        f"""(() => {{
          const el = [...document.querySelectorAll('button, a')]
            .find((x) => x.textContent.trim() === {json.dumps(text)});
          if (!el || el.disabled) return false;
          el.click();
          return true;
        }})()""",
        f"a {text!r} control",
    )


def _login(page: Page, gui: str, key: str) -> None:
    # A load is a fresh tab: the key is held in memory only.
    page.goto(gui + "/login")
    _fill(page, "API key", key)
    _click(page, "Connect")


def _table_text(page: Page, caption: str) -> str:
    text: str = page.wait(
        f"""(() => {{
          const t = [...document.querySelectorAll('table')]
            .find((x) => x.caption && x.caption.textContent === {json.dumps(caption)});
          return t ? t.innerText : '';
        }})()""",
        f"the table {caption!r}",
    )
    return text


def _same_origin_only(page: Page, gui: str) -> None:
    """Every request the page made went to its own origin: the GUI never
    learns another service's address."""
    urls = page.js(
        "performance.getEntriesByType('resource').map((e) => e.name)"
        ".concat([location.href])"
    )
    assert urls and all(u.startswith(gui + "/") for u in urls), urls


# ---------------------------------------------------------------------------
# Journeys
# ---------------------------------------------------------------------------


def test_admin_journey(page: Page, gui: str) -> None:
    _login(page, gui, ADMIN_KEY)
    _path(page, "/overview")
    _contains(page, "Feed gap on 2026-11-03", "the GAP alarm")
    _contains(page, "2 trades missing between ids 3 and 6", "the GAP interval")
    _contains(page, "Database: readable", "database health")
    _contains(page, "pm-clearing process: not answering", "process liveness")
    participants = _table_text(page, "Participants")
    assert "TRADER01" in participants and "MM01" in participants

    _click(page, "TRADER01")
    _path(page, "/participants/TRADER01")
    positions = _table_text(page, "TRADER01 positions")
    assert "EURUSD" in positions and "1.0862" in positions  # its own 4 decimals

    _click(page, "Reconciliation")
    _path(page, "/reconciliation")
    _fill(page, "From", "2026-11-02")
    _fill(page, "To", "2026-11-03")
    _click(page, "Run")
    _contains(page, "No discrepancy in the queried retained data.", "the result")
    _contains(page, "Compared 2026-11-02 to 2026-11-03", "the compared window")

    _click(page, "EOD Settlement")
    _path(page, "/eod")
    _contains(page, "EXCHANGE (rounding residual account)", "the rounding row")
    _same_origin_only(page, gui)


def test_trader_journey(page: Page, gui: str) -> None:
    _login(page, gui, TRADER_KEY)
    _path(page, "/me/positions")
    positions = _table_text(page, "My positions")
    assert "AAPL" in positions and "EURUSD" in positions and "MM01" not in positions

    _click(page, "My Trades")
    _contains(page, "Raw trades are kept from 2026-11-02", "the retention window")
    trades = _table_text(page, "My retained trades")
    assert "CLOSING_AUCTION" in trades
    assert "MM01" not in trades  # the counterparty is never shown

    _click(page, "EOD Settlement")
    _contains(page, "10,098.79", "the derived balance")

    # A typed ADMIN URL is turned away by the router (and the API would 403).
    page.js(
        "history.pushState({}, '', '/overview');"
        "dispatchEvent(new PopStateEvent('popstate'))"
    )
    _path(page, "/me/positions")
    _same_origin_only(page, gui)


def test_market_maker_journey(page: Page, gui: str) -> None:
    _login(page, gui, MM_KEY)
    _path(page, "/me/positions")
    _click(page, "My Quote Obligations")
    settings = _table_text(page, "Quote obligation settings")
    assert "Enforced" in settings and "5 ticks (0.0005)" in settings
    assert "1,000" in settings
    _contains(page, "not a measure of how you quoted", "the configuration caveat")


def test_unknown_key_is_refused(page: Page, gui: str) -> None:
    _login(page, gui, "no-such-key")
    _contains(page, "Invalid API key.", "the login error")
    _path(page, "/login")
