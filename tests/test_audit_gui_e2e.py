"""End to end: the audit GUI in a real browser against the real API (AG6,
design §11 AU-0).

The chain as deployed, minus the matching engine: a real ``pm-api-gwy`` app
(``create_app``, served by uvicorn) reads the recorded audit world
(``tests/audit_gui_world.py``: the layering-like sequence, the halt, a
planted gap and a ``pm-sim-forensics`` report); the production build of
``web-apps/audit-gui`` is served by its own ``serve.ts``, which proxies
``/api`` to that gateway; headless Chrome (``tests/test_monitor_e2e.py``'s
``Page``) logs in, pins the collection and walks the AU-0 acceptance list:

- heatmap masks: the gap and the halt are listed (and hatched) with their
  reasons, and the depth canvas is drawn;
- each lifeline's end reason is the order's recorded one;
- clicking a lifeline opens the right story and raw lines;
- forensics SKIPPED and ERROR never render as PASS.

Needs ``web-apps/audit-gui``'s ``npm install`` and a Chrome; skips without
either (``-m e2e``, ``make test-e2e``).
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

from edumatcher.audit.rawlines import iso_ns
from tests import audit_gui_world as aw
from tests.audit_gui_world import World, build, make_audit_app
from tests.conftest import free_ports
from tests.test_monitor_e2e import CHROME, Page, until

pytestmark = pytest.mark.e2e

REPO = Path(__file__).resolve().parents[1]
GUI = REPO / "web-apps" / "audit-gui"
BODY = "document.body ? document.body.innerText : ''"


def _e2e_requested(request: pytest.FixtureRequest) -> bool:
    markexpr = str(request.config.getoption("markexpr"))
    return "e2e" in markexpr.replace("not e2e", "")


@pytest.fixture(scope="module")
def world(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> World:
    if not _e2e_requested(request):
        pytest.skip("end-to-end: run with -m e2e (make test-e2e)")
    return build(
        tmp_path_factory.mktemp("audit-world"), gap=True, forensics_report=True
    )


@pytest.fixture(scope="module")
def gateway(world: World) -> Iterator[str]:
    """The real API app over the recorded world, on a free port."""
    app = make_audit_app(world)
    (port,) = free_ports(1)
    # lifespan off: the app's state is the fixture's; its lifespan would
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


@pytest.fixture(scope="module")
def gui(gateway: str) -> Iterator[str]:
    """The production build, served by serve.ts with /api proxied to `gateway`."""
    tsx = GUI / "node_modules" / ".bin" / "tsx"
    if not tsx.exists():
        pytest.skip("web-apps/audit-gui has no node_modules (npm install)")
    built = subprocess.run(
        ["npm", "run", "build", "--workspace", "@edumatcher/audit-web"],
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
        until(up, "the audit GUI server to listen", 30)
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


def _contains(page: Page, text: str, what: str, timeout: float = 30.0) -> None:
    page.wait(f"({BODY}).includes({json.dumps(text)})", what, timeout)


def _login_and_pin(page: Page, gui: str) -> None:
    page.goto(gui + "/login")
    page.wait(
        f"""(() => {{
          const el = document.getElementById('api-key');
          if (!el) return false;
          const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
          set.call(el, {json.dumps(aw.ADMIN_KEY)});
          el.dispatchEvent(new Event('input', {{ bubbles: true }}));
          return true;
        }})()""",
        "the API key field",
    )
    page.wait(
        """(() => { const b = [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === 'Connect');
          if (!b || b.disabled) return false; b.click(); return true; })()""",
        "the Connect button",
    )
    page.wait("location.pathname === '/overview'", "the Overview")
    page.wait(
        """(() => { const s = document.getElementById('collection');
          if (!s || ![...s.options].some((o) => o.value === 'world')) return false;
          const set = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set;
          set.call(s, 'world'); s.dispatchEvent(new Event('change', { bubbles: true })); return true; })()""",
        "the collection picker",
    )
    _contains(page, "Historical snapshot", "the pinned snapshot")


#: The main grid of web-apps/audit-gui/.../chartOption.ts (left, right, top
#: margins and plot height in px) inside its 420 px canvas.
GRID_LEFT, GRID_RIGHT, GRID_TOP, GRID_HEIGHT = 70, 16, 28, 420 - 28 - 92


def _click_canvas(
    page: Page, gui: str, symbol: str, price_ticks: int, at: float
) -> None:
    """A real mouse click on the canvas, at `price_ticks` and fraction `at`
    of the window. The y axis spans the window's prices -2/+2 ticks, as the
    option builder sets it; the prices come from the same API reads."""
    key = json.dumps("Bearer " + aw.ADMIN_KEY)
    geo = page.js(f"""(async () => {{
          const sid = document.querySelector('[data-testid=snapshot-label] .font-mono').textContent;
          const get = async (u) => (await fetch(u, {{headers: {{Authorization: {key}}}}})).json();
          const h = await get(`/api/v1/audit/market/{symbol}/heatmap?snapshot_id=${{sid}}&bins=300`);
          const l = await get(`/api/v1/audit/market/{symbol}/lifelines?snapshot_id=${{sid}}`);
          const e = await get(`/api/v1/audit/events?snapshot_id=${{sid}}&topic=trade.executed&symbol={symbol}&limit=1000`);
          const prices = [...h.levels.map((v) => v.price_ticks),
            ...l.lifelines.flatMap((x) => x.segments.map((s) => s.price_ticks)).filter((p) => p !== null),
            ...e.events.map((x) => x.fields.price_ticks)];
          const host = document.querySelector('[role=img][aria-label^="{symbol}"]');
          const r = host.getBoundingClientRect();
          // The font-size setting zooms #root (CSS zoom): rects are zoomed px.
          return {{low: Math.min(...prices) - 2, high: Math.max(...prices) + 2, left: r.left, top: r.top,
                   width: r.width, zoom: r.width / host.clientWidth}};
        }})()""")
    zoom = geo["zoom"]
    plot = geo["width"] / zoom - GRID_LEFT - GRID_RIGHT
    x = geo["left"] + (GRID_LEFT + at * plot) * zoom
    price_y = (geo["high"] - price_ticks) / (geo["high"] - geo["low"]) * GRID_HEIGHT
    y = geo["top"] + (GRID_TOP + price_y) * zoom
    for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
        page._call(
            "Input.dispatchMouseEvent",
            {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1},
            page.session,
        )


def _brush_canvas(page: Page, start: float, end: float) -> None:
    """Drag across the main grid from fraction `start` to `end` of the window."""
    geo = page.js(
        """(() => { const host = document.querySelector('[role=img]');
          const r = host.getBoundingClientRect();
          return {left: r.left, top: r.top, width: r.width, zoom: r.width / host.clientWidth}; })()"""
    )
    zoom = geo["zoom"]
    plot = geo["width"] / zoom - GRID_LEFT - GRID_RIGHT
    y = geo["top"] + (GRID_TOP + GRID_HEIGHT / 2) * zoom

    def x(f: float) -> float:
        return float(geo["left"] + (GRID_LEFT + f * plot) * zoom)

    def mouse(kind: str, at: float) -> None:
        page._call(
            "Input.dispatchMouseEvent",
            {"type": kind, "x": at, "y": y, "button": "left", "clickCount": 1},
            page.session,
        )

    mouse("mousePressed", x(start))
    for i in range(1, 11):
        mouse("mouseMoved", x(start + (end - start) * i / 10))
    mouse("mouseReleased", x(end))


def iso_ms(world: World) -> tuple[float, float]:
    """The whole window the Market opens on: first record to just after the
    last, in ms (receipt clock), read naively from the trail."""
    lines = [
        ln for ln in world.audit_log.read_text().splitlines() if ln.startswith("[")
    ]
    first, last = (iso_ns(ln[1 : ln.index("]")]) for ln in (lines[0], lines[-1]))
    return first / 1e6, (last + 1) / 1e6


def _lifeline_rows(page: Page) -> list[str]:
    rows: list[str] = page.wait(
        """(() => { const l = document.querySelector('[role=listbox][aria-label="Order lifelines"]');
          const o = l ? [...l.querySelectorAll('[role=option]')].map((x) => x.textContent) : [];
          return o.length ? o : null; })()""",
        "the lifeline list",
    )
    return rows


def test_au0_market_journey(page: Page, gui: str, world: World) -> None:
    _login_and_pin(page, gui)
    # The banner: forensics SKIPPED and ERROR are their own states.
    _contains(page, "1 SKIPPED", "the forensics SKIPPED count")
    _contains(page, "1 ERROR", "the forensics ERROR count")
    _contains(page, "A check failed", "the unfoldable banner")
    _contains(page, "1 recorder gap", "the planted gap")

    # In-app navigation: a page load would be a fresh tab without the key.
    page.js(
        "history.pushState({}, '', '/market?symbol=AAA');"
        "dispatchEvent(new PopStateEvent('popstate'))"
    )
    page.wait("!!document.querySelector('canvas')", "the ECharts canvas", 30)
    _contains(page, "Records lost (gap)", "the gap mask")
    _contains(page, "Halt (ADMIN_SYMBOL)", "the halt mask")
    _contains(page, "book observations, median every 1.000 s", "the cadence")

    rows = _lifeline_rows(page)
    by_order = {
        name: next(r for r in rows if world.orders[name][:8] in r)
        for name in ("layer_1", "stop_bid", "gtc_bid", "smp_sell")
    }
    assert "owner cancel" in by_order["layer_1"]
    assert "expired" in by_order["stop_bid"]
    assert "still resting" in by_order["gtc_bid"]
    assert "system cancel: SELF_MATCH_PREVENTED" in by_order["smp_sell"]

    layer_1 = world.orders["layer_1"]
    page.wait(
        f"""(() => {{ const o = [...document.querySelectorAll('[role=option]')]
          .find((x) => x.textContent.includes({json.dumps(layer_1[:8])}));
          if (!o) return false; o.click(); return true; }})()""",
        "the layer_1 lifeline",
    )
    page.wait(
        f"new URLSearchParams(location.search).get('order') === {json.dumps(layer_1)}",
        "the drawer in the URL",
    )
    _contains(page, "TRADER02", "the order's story")
    page.wait(
        """(() => { const t = [...document.querySelectorAll('[role=tab]')].find((x) => x.textContent === 'Raw evidence');
          if (!t) return false; t.click(); return true; })()""",
        "the Raw evidence tab",
    )
    _contains(page, "order.cancelled.TRADER02", "the raw cancel line")
    _contains(page, "audit.log:", "the raw lines' source")

    # Back closes the drawer, Forward restores it.
    page.js("history.back()")
    page.wait("new URLSearchParams(location.search).get('tab') === 'story'", "Back")
    page.js("history.back()")
    page.wait("!document.querySelector('[role=dialog]')", "the drawer closed")
    page.js("history.forward()")
    page.wait("!!document.querySelector('[role=dialog]')", "the drawer restored")

    # The canvas itself: a real click on the GTC bid's bar (99.00, resting to
    # the end) opens its drawer.
    page.js(
        "history.pushState({}, '', '/market?symbol=AAA'); dispatchEvent(new PopStateEvent('popstate'))"
    )
    page.wait("!document.querySelector('[role=dialog]')", "the drawer closed")
    _click_canvas(page, gui, "AAA", 9900, 0.85)
    gtc = world.orders["gtc_bid"]
    page.wait(
        f"new URLSearchParams(location.search).get('order') === {json.dumps(gtc)}",
        "the GTC bid's drawer from a canvas click",
    )
    page.js("history.back()")
    page.wait("!document.querySelector('[role=dialog]')", "Back from the canvas click")

    # A brush lands where it was dragged: from 30% to 50% of the window.
    _brush_canvas(page, 0.3, 0.5)
    page.wait(
        "new URLSearchParams(location.search).has('from')", "the brushed interval"
    )
    got = page.js(
        "[...new URLSearchParams(location.search)].filter(([k]) => k === 'from' || k === 'to').map(([, v]) => Number(v) / 1e6)"
    )
    lo, hi = iso_ms(world)
    assert abs((got[0] - lo) / (hi - lo) - 0.3) < 0.01, (got, lo, hi)
    assert abs((got[1] - lo) / (hi - lo) - 0.5) < 0.01, (got, lo, hi)

    urls = page.js(
        "performance.getEntriesByType('resource').map((e) => e.name)"
        ".concat([location.href])"
    )
    assert urls and all(u.startswith(gui + "/") for u in urls), urls
