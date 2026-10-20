"""End to end: the operator dashboard's whole chain on a real exchange.

Phases A-C as an operator sees them (design §18, E3 in local form).
``pm-opctl-cli`` starts the ``mini`` profile with the bundled ``s10-basic``
config in a scratch data directory: a real pm-engine, gateways and services,
each beaconing (phase A) to a real pm-monitor (B), whose snapshot, events and
``metrics.db`` the real dashboard bridge (C) serves to a WebSocket client.
Participants trade over ALF, and every figure is checked against what they
did -- not against a unit's idea of it. Then the failure states the dashboard
exists for: SILENT, a pm-monitor restart that keeps today's totals, and a
killed engine (DEAD, exchange DOWN) restarted by ``pm-opctl-cli``.

The tests run in file order on one exchange: each builds on the one before
and the destructive ones come last. The processes bind the exchange's fixed
ports (5555...), so the module runs only with ``-m e2e`` (``make test-e2e``),
serially, and skips when a port is taken -- by a developer's own exchange,
for instance. The bridge part needs ``web-apps/dash-gui``'s ``npm install``;
it builds the web app and serves it as the container does. With Chrome
installed, a headless page (driven over the DevTools protocol, no extra
dependency) checks what the operator actually sees: the top bar from the
live exchange, the time range, the theme, and the banner when pm-monitor
goes away (WP-D1).
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

import pytest
import zmq
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

from edumatcher.alf_client import protocol as alf
from edumatcher.alf_client.connection import AlfConnection, State
from edumatcher.emo.cli import MINI_PROCESSES
from tests.conftest import free_ports

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals"),
]

REPO = Path(__file__).resolve().parents[1]
DASH = REPO / "web-apps" / "dash-gui"
CHROME = next(
    (c for c in ("google-chrome", "chromium", "chromium-browser") if shutil.which(c)),
    None,
)
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
MONITOR_PUB = "tcp://127.0.0.1:5611"
ALF_PORT = 5565
#: s10-basic: MM01's seeded ask on AAPL, 1000 at 22.98.
ASK = 2298
#: interval 2 s x silent_after 3, plus pm-monitor's 1 Hz and some slack.
SILENT_WITHIN = 15.0

T = TypeVar("T")


def until(
    check: Callable[[], T | None],
    what: str,
    timeout: float = 20.0,
    seen: Callable[[], object] | None = None,
) -> T:
    """The first truthy result of ``check`` within ``timeout`` seconds;
    ``seen`` describes what there was instead, for the failure message."""
    deadline = time.monotonic() + timeout
    while True:
        result = check()
        if result:
            return result
        if time.monotonic() > deadline:
            extra = f"; seen: {seen()}" if seen is not None else ""
            raise AssertionError(
                f"timed out after {timeout:.0f} s waiting for {what}{extra}"
            )
        time.sleep(0.1)


def _port_taken(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # As the processes bind: a previous run's TIME_WAIT is no listener.
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("0.0.0.0", port))
        except OSError:
            return True
    return False


# ---------------------------------------------------------------------------
# the exchange
# ---------------------------------------------------------------------------


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


def _identity(entry: dict[str, Any]) -> tuple[str, str | None]:
    command: list[str] = entry["command"]
    instance = (
        command[command.index("--instance") + 1] if "--instance" in command else None
    )
    return command[0], instance


EXPECTED = {_identity(e) for e in MINI_PROCESSES}


@pytest.fixture(scope="module")
def exchange(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Exchange]:
    # Some Makefile targets pass their own -m, which replaces the default
    # "not e2e": run only when e2e is asked for by name.
    if "e2e" not in str(request.config.getoption("markexpr")).replace("not e2e", ""):
        pytest.skip("end-to-end: run with -m e2e (make test-e2e)")
    if int(os.environ.get("PYTEST_XDIST_WORKER_COUNT", "1")) > 1:
        pytest.skip("one exchange per machine: run serially (make test-e2e)")
    taken = [p for p in PORTS if _port_taken(p)]
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


# ---------------------------------------------------------------------------
# pm-monitor's feed, as any subscriber sees it
# ---------------------------------------------------------------------------


class Feed:
    """Every ``health.snapshot`` and ``health.event`` pm-monitor publishes."""

    def __init__(self) -> None:
        self.snapshots: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        sub: zmq.Socket[bytes] = zmq.Context.instance().socket(zmq.SUB)
        sub.setsockopt(zmq.LINGER, 0)
        sub.connect(MONITOR_PUB)
        sub.subscribe(b"health.")
        try:
            while not self._stop.is_set():
                if not sub.poll(100):
                    continue
                frames = sub.recv_multipart()
                data = json.loads(frames[1])
                if frames[0] == b"health.snapshot":
                    self.snapshots.append(data)
                else:
                    self.events.append(data)
        finally:
            sub.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    @property
    def latest(self) -> dict[str, Any] | None:
        return self.snapshots[-1] if self.snapshots else None

    def wait(
        self,
        check: Callable[[dict[str, Any]], T | None],
        what: str,
        timeout: float = 20.0,
    ) -> T:
        def on_latest() -> T | None:
            s = self.latest
            return check(s) if s is not None else None

        return until(on_latest, what, timeout)

    def event(
        self, kind: str, subject: str, after: int = -1, detail: str = ""
    ) -> dict[str, Any] | None:
        return next(
            (
                e
                for e in self.events
                if e["seq"] > after
                and e["kind"] == kind
                and e["subject"] == subject
                and detail in e["detail"]
            ),
            None,
        )

    def wait_event(
        self,
        kind: str,
        subject: str,
        after: int = -1,
        detail: str = "",
        timeout: float = 20.0,
    ) -> dict[str, Any]:
        return until(
            lambda: self.event(kind, subject, after, detail),
            f"{kind} {subject} {detail}".rstrip(),
            timeout,
            seen=lambda: [
                (e["seq"], e["kind"], e["subject"], e["detail"])
                for e in self.events
                if e["seq"] > after
            ][-12:],
        )


@pytest.fixture(scope="module")
def feed(exchange: Exchange) -> Iterator[Feed]:
    f = Feed()
    yield f
    f.close()


def process(s: dict[str, Any], name: str) -> dict[str, Any]:
    return next(p for p in s["processes"] if p["process"] == name)


def participant(s: dict[str, Any], pid: str) -> dict[str, Any]:
    zero = {
        "connected": False,
        "fills_today": 0,
        "resting_orders": 0,
        "orders": {"today": 0},
    }
    return next((p for p in s["participants"] if p["id"] == pid), zero)


def gateway(s: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(g for g in s["gateways"] if g["kind"] == kind)


def book(s: dict[str, Any], symbol: str) -> dict[str, Any]:
    return next(b for b in s["books"] if b["symbol"] == symbol)


# ---------------------------------------------------------------------------
# a participant over ALF
# ---------------------------------------------------------------------------


class Trader:
    def __init__(self, gateway_id: str) -> None:
        self.conn = AlfConnection("127.0.0.1", ALF_PORT, gateway_id, client="e2e")
        self.acks = 0
        self.fills = 0
        self.conn.open(time.time())
        until(self._ready, f"{gateway_id} logged in over ALF", 10)

    def _ready(self) -> bool:
        self.pump()
        return self.conn.state == State.READY

    def pump(self) -> None:
        for m in self.conn.read():
            if m.msg_type == "ACK" and m.flag("ACCEPTED"):
                self.acks += 1
            elif m.msg_type == "FILL":
                self.fills += 1
        self.conn.tick(time.time())

    def buy(self, symbol: str, price_ticks: int, qty: int = 10, tag: str = "") -> None:
        line = alf.new_order(
            tag=tag or f"E2E{self.acks}",
            symbol=symbol,
            side="BUY",
            order_type="LIMIT",
            tif="DAY",
            qty=qty,
            tick_decimals=2,
            price_ticks=price_ticks,
        )
        assert self.conn.send(line, time.time())
        self.conn.flush()

    def wait(self, acks: int, fills: int) -> None:
        def done() -> bool:
            self.pump()
            return self.acks >= acks and self.fills >= fills

        until(done, f"{acks} acks and {fills} fills", 10)

    def close(self) -> None:
        self.conn.close()


# ---------------------------------------------------------------------------
# the dashboard bridge and a browser tab
# ---------------------------------------------------------------------------


@dataclass
class Bridge:
    port: int
    proc: subprocess.Popen[bytes]

    def get(self, path: str) -> Any:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}{path}", timeout=5
        ) as r:
            return json.load(r)


@pytest.fixture(scope="module")
def bridge(exchange: Exchange) -> Iterator[Bridge]:
    tsx = DASH / "node_modules" / ".bin" / "tsx"
    if not tsx.exists():
        pytest.skip("web-apps/dash-gui has no node_modules (npm install)")
    built = subprocess.run(
        ["npm", "run", "build", "--workspace", "@edumatcher/dash-web"],
        cwd=DASH,
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
        "MONITOR_HOST": "127.0.0.1",
        "METRICS_DB_PATH": str(exchange.data_dir / "metrics.db"),
        "LOG_SRV_ENABLED": "false",
        "LOG_FAILOVER_DIR": str(exchange.data_dir / "logs"),
        "STATIC_DIR": str(DASH / "apps" / "web" / "dist"),
        "CONFIG_ARTIFACT_PATH": str(
            exchange.data_dir / "ref_data" / "engine_config.json"
        ),
    }
    proc = subprocess.Popen(
        [str(tsx), "--disable-warning=ExperimentalWarning", "src/main.ts"],
        cwd=DASH / "apps" / "bridge",
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    b = Bridge(port, proc)

    def up() -> bool:
        try:
            return bool(b.get("/api/bridge/status")["monitor"] == "UP")
        except OSError:
            return False

    try:
        until(up, "the bridge to listen and receive pm-monitor's snapshots", 30)
        yield b
    finally:
        proc.terminate()
        proc.wait(timeout=10)


class Tab:
    """A browser tab on the bridge's /ws: every frame it receives."""

    def __init__(self, ws: ClientConnection) -> None:
        self.ws = ws
        self.frames: list[dict[str, Any]] = []
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            for message in self.ws:
                self.frames.append(json.loads(message))
        except ConnectionClosed:
            pass

    def wait(
        self, match: Callable[[dict[str, Any]], bool], what: str, timeout: float = 20.0
    ) -> dict[str, Any]:
        return until(
            lambda: next((f for f in self.frames if match(f)), None), what, timeout
        )

    def mark(self) -> int:
        return len(self.frames)

    def since(self, mark: int) -> list[dict[str, Any]]:
        return self.frames[mark:]


@pytest.fixture(scope="module")
def tab(bridge: Bridge) -> Iterator[Tab]:
    with connect(f"ws://127.0.0.1:{bridge.port}/ws", max_size=None) as ws:
        yield Tab(ws)


class Page:
    """A headless Chrome tab, driven over the DevTools protocol."""

    def __init__(self, chrome: str, profile: Path) -> None:
        self.proc = subprocess.Popen(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--no-default-browser-check",
                "--window-size=1600,900",
                "--remote-debugging-port=0",
                f"--user-data-dir={profile}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        active = profile / "DevToolsActivePort"
        until(
            lambda: active.exists() and len(active.read_text().splitlines()) >= 2,
            "Chrome's DevTools port",
            20,
        )
        port, path = active.read_text().splitlines()[:2]
        self._stack = ExitStack()
        self.ws = self._stack.enter_context(
            connect(f"ws://127.0.0.1:{port}{path}", max_size=None)
        )
        self._id = 0
        target = self._call("Target.createTarget", {"url": "about:blank"})["targetId"]
        attached = self._call(
            "Target.attachToTarget", {"targetId": target, "flatten": True}
        )
        self.session: str = attached["sessionId"]

    def _call(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        session: str | None = None,
    ) -> dict[str, Any]:
        self._id += 1
        message: dict[str, Any] = {
            "id": self._id,
            "method": method,
            "params": params or {},
        }
        if session:
            message["sessionId"] = session
        self.ws.send(json.dumps(message))
        while True:
            reply = json.loads(self.ws.recv(timeout=30))
            if reply.get("id") == self._id:
                assert "error" not in reply, f"{method}: {reply['error']}"
                result: dict[str, Any] = reply["result"]
                return result

    def goto(self, url: str) -> None:
        self._call("Page.navigate", {"url": url}, self.session)

    def js(self, expression: str) -> Any:
        result = self._call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            self.session,
        )
        assert (
            "exceptionDetails" not in result
        ), f"{expression}: {result['exceptionDetails']}"
        return result["result"].get("value")

    def wait(self, expression: str, what: str, timeout: float = 20.0) -> Any:
        return until(
            lambda: self.js(expression), what, timeout, seen=lambda: self.js(BODY_TEXT)
        )

    def close(self) -> None:
        self._stack.close()
        self.proc.terminate()
        self.proc.wait(timeout=10)


#: What the page says, for a failure message.
BODY_TEXT = "document.body ? document.body.innerText.slice(0, 400) : ''"
PILL = "document.querySelector('[role=status][aria-label^=\"Exchange status\"]')"
BANNER = "document.querySelector('[role=alert]')"
MAIN_STALE = "document.querySelector('main')?.dataset.stale"


@pytest.fixture(scope="module")
def page(
    bridge: Bridge, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Page | None]:
    """The dashboard in a browser; None without Chrome (the browser checks skip)."""
    if CHROME is None:
        yield None
        return
    p = Page(CHROME, tmp_path_factory.mktemp("chrome"))
    try:
        yield p
    finally:
        p.close()


def session_clock(ts: str, tz: str) -> str:
    """``HH:MM:SS`` of an ISO UTC instant in the session timezone, as lib/time.ts shows it."""
    moment = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    return moment.astimezone(ZoneInfo(tz)).strftime("%H:%M:%S")


def latest_snapshot(t: Tab) -> dict[str, Any] | None:
    return next(
        (f["data"] for f in reversed(t.frames) if f["type"] == "snapshot"), None
    )


# ---------------------------------------------------------------------------
# the scenario
# ---------------------------------------------------------------------------


def test_every_process_of_the_profile_beacons_and_is_healthy(
    exchange: Exchange, feed: Feed
) -> None:
    """Phase A+B: every started process is judged from its own beacons."""

    def all_healthy(s: dict[str, Any]) -> dict[str, Any] | None:
        seen = {(p["process"], p["instance"]): p for p in s["processes"]}
        ok = all(
            k in seen and seen[k]["state"] == "HEALTHY" and not seen[k]["starting"]
            for k in EXPECTED
        )
        return s if ok and s["exchange"]["status"] == "OPERATIONAL" else None

    s = feed.wait(
        all_healthy, "every mini process HEALTHY and the exchange OPERATIONAL", 45
    )
    by_name = {e["name"]: _identity(e) for e in MINI_PROCESSES}
    for name, (proc, instance) in by_name.items():
        record = next(
            p
            for p in s["processes"]
            if (p["process"], p["instance"]) == (proc, instance)
        )
        assert record["pid"] == exchange.pid(name), name
        assert record["rss_bytes"] > 0 and record["threads"] > 0, name
    assert s["exchange"]["session_state"] == "CONTINUOUS"
    assert s["exchange"]["session_timezone"] == exchange.session_tz
    assert s["exchange"]["trading_date"] == exchange.today
    assert s["host"]["mem_total_bytes"] > 0
    files = {f["name"]: f["size_bytes"] for f in s["host"]["files"]}
    assert files.get("metrics.db", 0) > 0
    # 1 Hz, numbered
    seqs = [x["seq"] for x in feed.snapshots[-5:]]
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))


def test_a_traders_activity_reaches_every_figure(
    exchange: Exchange, feed: Feed
) -> None:
    """Five crossing orders and one resting one, seen in the snapshot, the
    events and metrics.db exactly as they were sent."""
    base = feed.latest
    assert base is not None
    first_seq = max((e["seq"] for e in feed.events), default=0)
    base_orders = base["trading"]["orders"]["today"]
    base_trades = base["trading"]["trades"]["today"]
    base_value = base["trading"]["traded_value_today"]
    base_book = book(base, "AAPL")["trades_today"]
    base_alf = gateway(base, "ALF")["clients"]

    trader = Trader("TRADER01")
    try:
        feed.wait_event("CONNECT", "TRADER01", first_seq)
        feed.wait(
            lambda s: participant(s, "TRADER01")["connected"]
            and gateway(s, "ALF")["clients"] == base_alf + 1,
            "TRADER01 connected, one more ALF client",
        )
        for i in range(5):
            trader.buy("AAPL", ASK, tag=f"X{i}")
        trader.buy("AAPL", ASK - 300, tag="REST")
        trader.wait(acks=6, fills=5)

        s = feed.wait(
            lambda s: (
                s
                if s["trading"]["orders"]["today"] == base_orders + 6
                and s["trading"]["trades"]["today"] == base_trades + 5
                else None
            ),
            "6 orders and 5 trades in the snapshot",
        )
        assert s["trading"]["traded_value_today"] == pytest.approx(
            base_value + 5 * 10 * 22.98
        )
        assert s["trading"]["reject_pct_5m"] == 0.0
        assert s["trading"]["handle_p99_us"] > 0
        p = participant(s, "TRADER01")
        assert (p["orders"]["today"], p["fills_today"], p["resting_orders"]) == (
            6,
            5,
            1,
        )
        assert book(s, "AAPL")["trades_today"] == base_book + 5
    finally:
        trader.close()

    # CANCEL_ALL on disconnect: the resting order goes with the session.
    s = feed.wait(
        lambda s: (
            s
            if not participant(s, "TRADER01")["connected"]
            and participant(s, "TRADER01")["resting_orders"] == 0
            and gateway(s, "ALF")["clients"] == base_alf
            else None
        ),
        "TRADER01 gone, its resting order cancelled",
    )
    assert participant(s, "TRADER01")["fills_today"] == 5
    feed.wait_event("DISCONNECT", "TRADER01", first_seq)

    # History: the day's total per gateway, and the events under their wire seq.
    rows = until(
        lambda: exchange.metrics_db(
            "SELECT total FROM daily_totals WHERE name = 'engine.orders_in' "
            "AND label = 'TRADER01' AND date = ?",
            exchange.today,
        ),
        "TRADER01's orders in metrics.db daily_totals",
    )
    assert rows == [(6.0,)]
    live = {(e["seq"], e["kind"]) for e in feed.events if e["subject"] == "TRADER01"}
    stored = set(
        exchange.metrics_db("SELECT seq, kind FROM events WHERE subject = 'TRADER01'")
    )
    assert live == stored and {k for _, k in live} == {"CONNECT", "DISCONNECT"}


def test_the_dashboard_bridge_shows_the_exchange_live_and_in_history(
    exchange: Exchange, feed: Feed, bridge: Bridge, tab: Tab
) -> None:
    """Phase C: what a browser tab gets is pm-monitor's, live and from metrics.db."""
    hello = tab.wait(lambda f: f["type"] == "hello", "hello")
    assert hello["monitor"] == "UP" and hello["sessionTz"] == exchange.session_tz
    snap = until(lambda: latest_snapshot(tab), "a snapshot frame")
    assert {(p["process"], p["instance"]) for p in snap["processes"]} >= EXPECTED

    # The threshold rules pm-monitor judges by, from the deployed artifact (I113).
    thresholds = bridge.get("/api/thresholds")
    assert thresholds["source"] == "artifact"
    deployed = json.loads(
        (exchange.data_dir / "ref_data" / "engine_config.json").read_text()
    )
    for rule, band in deployed["monitor"]["thresholds"].items():
        assert thresholds["rules"][rule] == {
            "warn": band["warn"],
            "crit": band["crit"],
            "invert": rule == "disk_free_pct",
            "configurable": True,
        }, rule
    assert thresholds["rules"]["loop_age_ms"]["configurable"] is False

    status = bridge.get("/api/bridge/status")
    assert status["monitor"] == "UP" and status["monitorConnected"]
    assert status["metricsDb"]["ok"] and status["sessionTz"] == exchange.session_tz

    mark = tab.mark()
    trader = Trader("TRADER02")
    try:
        for i in range(3):
            trader.buy("AAPL", ASK, tag=f"Y{i}")
        trader.wait(acks=3, fills=3)
        tab.wait(
            lambda f: f["type"] == "event"
            and f["data"]["kind"] == "CONNECT"
            and f["data"]["subject"] == "TRADER02",
            "TRADER02's CONNECT event on the tab",
        )
        tab.wait(
            lambda f: f["type"] == "snapshot"
            and participant(f["data"], "TRADER02")["fills_today"] == 3,
            "TRADER02's 3 fills in a snapshot on the tab",
        )
    finally:
        trader.close()
    assert all(f["type"] in {"snapshot", "event"} for f in tab.since(mark))

    # REST history, as the charts will read it.
    daily = until(
        lambda: [
            d
            for d in bridge.get("/api/daily?name=engine.orders_in&label=TRADER02")[
                "days"
            ]
            if d["date"] == exchange.today and d["total"] == 3
        ],
        "TRADER02's 3 orders in /api/daily",
    )
    assert daily
    engine = process(feed.latest or {}, "pm-engine")
    series = f"/api/series?name=engine.orders_in&label=TRADER01&source={engine['key']}&range=15m"
    counter = until(
        lambda: [pt for pt in bridge.get(series)["points"] if pt[1] == 6],
        "TRADER01's counter at 6 in /api/series (raw, every 10 s)",
        seen=lambda: {k: v for k, v in bridge.get(series).items() if k != "points"}
        | {"last": bridge.get(series)["points"][-3:]},
    )
    assert counter
    rss = bridge.get(f"/api/series?name=proc.rss_bytes&source={engine['key']}&range=5m")
    assert rss["resolution"] == "raw" and rss["points"]
    assert rss["points"][-1][1] == pytest.approx(engine["rss_bytes"], rel=0.5)
    events = bridge.get("/api/events?range=1h&kind=CONNECT,DISCONNECT")["events"]
    by_subject = {(e["seq"], e["kind"], e["subject"]) for e in events}
    live = {
        (e["seq"], e["kind"], e["subject"])
        for e in feed.events
        if e["kind"] in {"CONNECT", "DISCONNECT"}
    }
    assert live <= by_subject
    first = min(e["seq"] for e in events)
    caught_up = bridge.get(f"/api/events?after_seq={first}")["events"]
    assert [e["seq"] for e in caught_up] == sorted(e["seq"] for e in caught_up)
    assert all(e["seq"] > first for e in caught_up)


def test_the_dashboard_page_shows_the_live_exchange_in_a_browser(
    exchange: Exchange, bridge: Bridge, page: Page | None
) -> None:
    """WP-D1 as the operator sees it: the built page from the bridge, live."""
    if page is None:
        pytest.skip("no Chrome to drive")
    page.goto(f"http://127.0.0.1:{bridge.port}/?from=now-6h")
    pill = page.wait(
        f"{PILL}?.getAttribute('aria-label') === 'Exchange status OPERATIONAL' && {PILL}.textContent",
        "the live exchange status pill",
    )
    assert pill == "●OPERATIONAL"
    badge = page.js("document.querySelector('[data-testid=session-badge]').textContent")
    assert badge == f"CONTINUOUS · {exchange.today}"
    header = page.js("document.querySelector('header').innerText")
    assert "LIVE" in header and "pm-dash" in header
    assert page.js(f"{BANNER}") is None and page.js(MAIN_STALE) == "false"
    picker = "document.querySelector('[aria-label^=\"Time range:\"]')"
    assert page.js(f"{picker}.getAttribute('aria-label')") == "Time range: Last 6 hours"

    # The theme swaps the palette, not just a class.
    assert (
        page.js("getComputedStyle(document.body).backgroundColor") == "rgb(10, 12, 16)"
    )
    page.js("document.querySelector('[aria-label=\"Theme: dark\"]').click()")
    page.wait("!document.documentElement.classList.contains('dark')", "the light theme")
    assert (
        page.js("getComputedStyle(document.body).backgroundColor")
        == "rgb(255, 255, 255)"
    )
    page.js("document.querySelector('[aria-label=\"Theme: light\"]').click()")
    page.wait(
        "document.documentElement.classList.contains('dark')", "the dark theme again"
    )

    # A range chosen in the picker lands in the URL.
    page.js(f"{picker}.click()")
    page.js(
        "[...document.querySelectorAll('[role=option]')]"
        ".find(o => o.textContent === 'Last 24 hours').click()"
    )
    page.wait("location.search === '?from=now-24h'", "?from=now-24h in the URL")
    assert (
        page.js(f"{picker}.getAttribute('aria-label')") == "Time range: Last 24 hours"
    )


#: Every widget whose content reaches past its own box or its container,
#: and a page that scrolls sideways. HealthTable alone may scroll inside
#: itself: that is how a wide table stays in a narrow panel.
OVERFLOW = """JSON.stringify([...document.querySelectorAll('[data-widget]')].flatMap(el => {
  const r = el.getBoundingClientRect(), host = el.parentElement.getBoundingClientRect(), bad = [];
  const name = el.dataset.widget + ' ' + (el.getAttribute('aria-label') || '');
  if (el.dataset.widget !== 'health-table' && el.scrollWidth > el.clientWidth + 1) bad.push('spills: ' + name);
  if (r.right > host.right + 1 || r.left < host.left - 1) bad.push('outside its panel: ' + name);
  return bad;
}).concat(document.documentElement.scrollWidth > innerWidth ? ['the page scrolls sideways'] : []))"""


def test_every_widget_renders_in_both_themes_in_a_browser(
    bridge: Bridge, page: Page | None
) -> None:
    """WP-D2's done-when, in a real browser: the /widgets gallery (synthetic
    data, and a row of edge cases: long labels, no values, NaN, negatives,
    empty data, twelve series, narrow columns) draws every widget at its
    real size, in each theme's own colours, and nothing overflows -- at a
    desktop width and a narrow one. jsdom can show none of this."""
    if page is None:
        pytest.skip("no Chrome to drive")
    for width in (1600, 900):
        page._call(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": 1200, "deviceScaleFactor": 1, "mobile": False},
            page.session,
        )
        page.goto(f"http://127.0.0.1:{bridge.port}/widgets")
        page.wait(
            "document.querySelectorAll('[role=meter]').length === 7", "the gauges"
        )
        page.wait(
            "document.querySelectorAll('.recharts-surface').length === 7",
            "all seven charts",
        )
        # The responsive charts measured their panels: none is zero-sized.
        widths = page.js(
            "[...document.querySelectorAll('.recharts-surface')]"
            ".map(s => s.getBoundingClientRect().width)"
        )
        assert min(widths) > 150, (width, widths)
        assert page.js("document.body.innerHTML.includes('NaN')") is False
        ok_band = "getComputedStyle(document.querySelector('[data-band=OK]')).stroke"
        for theme, ok in (("dark", "rgb(38, 208, 124)"), ("light", "rgb(6, 118, 71)")):
            page.js(
                f"document.documentElement.classList.toggle('dark', {str(theme == 'dark').lower()})"
            )
            assert page.js(ok_band) == ok, theme
            line = page.js(
                "getComputedStyle(document.querySelector('.recharts-line-curve')).stroke"
            )
            assert line.startswith("rgb("), (theme, line)  # var(--series-1) resolved
            assert json.loads(page.js(OVERFLOW)) == [], (width, theme)
    page._call("Emulation.clearDeviceMetricsOverride", {}, page.session)
    page.js("document.documentElement.classList.add('dark')")
    # Back to the dashboard: the scenarios after this one watch it.
    page.goto(f"http://127.0.0.1:{bridge.port}/")
    page.wait(f"{PILL}?.textContent === '●OPERATIONAL'", "the dashboard again")


def test_a_stopped_process_goes_silent_and_comes_back(
    exchange: Exchange, feed: Feed, tab: Tab
) -> None:
    """SIGSTOP: no beacons, PID alive -> SILENT, the exchange IMPAIRED; SIGCONT heals it."""
    pid = exchange.pid("stats")
    key = process(feed.latest or {}, "pm-stats")["key"]
    after = max((e["seq"] for e in feed.events), default=0)
    os.kill(pid, signal.SIGSTOP)
    try:
        feed.wait(
            lambda s: process(s, "pm-stats")["state"] == "SILENT"
            and s["exchange"]["status"] == "IMPAIRED",
            "pm-stats SILENT and the exchange IMPAIRED",
            SILENT_WITHIN,
        )
        event = feed.wait_event("PROCESS_STATUS", key, after, "HEALTHY -> SILENT")
        assert event["severity"] == "CRIT"
    finally:
        os.kill(pid, signal.SIGCONT)
    feed.wait(
        lambda s: process(s, "pm-stats")["state"] == "HEALTHY"
        and s["exchange"]["status"] == "OPERATIONAL",
        "pm-stats HEALTHY again",
    )
    feed.wait_event("PROCESS_STATUS", key, after, "SILENT -> HEALTHY")
    # Nothing in between: standing still is SILENT, not a hung or slow loop (I108).
    assert [
        (e["kind"], e["detail"])
        for e in feed.events
        if e["seq"] > after and e["subject"] == key
    ] == [
        ("PROCESS_STATUS", "HEALTHY -> SILENT"),
        ("PROCESS_STATUS", "SILENT -> HEALTHY"),
    ]
    tab.wait(
        lambda f: f["type"] == "event"
        and f["data"]["subject"] == key
        and "-> SILENT" in f["data"]["detail"],
        "the SILENT event on the tab",
    )


def test_a_pm_monitor_restart_keeps_todays_totals_and_its_event_numbers(
    exchange: Exchange, feed: Feed, bridge: Bridge, tab: Tab, page: Page | None
) -> None:
    """The bridge shows DOWN, then UP; today's figures continue (design §9.4).
    In the browser: the banner with the time the data froze, panels dimmed."""
    before = feed.latest
    assert before is not None
    orders, trades = (
        before["trading"]["orders"]["today"],
        before["trading"]["trades"]["today"],
    )
    last_seq = max(e["seq"] for e in feed.events)
    mark = tab.mark()
    os.kill(exchange.pid("monitor"), signal.SIGTERM)
    tab.wait(
        lambda f: f in tab.since(mark)
        and f == {"type": "monitor_state", "monitor": "DOWN"},
        "monitor_state DOWN on the tab",
    )
    assert bridge.get("/api/bridge/status")["monitor"] == "DOWN"
    restarted_at = len(feed.snapshots)
    if page is not None:
        frozen = session_clock(feed.snapshots[-1]["ts"], exchange.session_tz)
        banner = page.wait(f"{BANNER}?.textContent", "the banner in the browser")
        assert banner == f"pm-monitor down — data frozen at {frozen}"
        assert page.js(MAIN_STALE) == "true"
        assert page.js(f"{PILL}.textContent") == "●OPERATIONAL"  # frozen, not gone

    exchange.cli("pm-opctl-cli", "list", "--restart")
    tab.wait(
        lambda f: f in tab.since(mark)
        and f == {"type": "monitor_state", "monitor": "UP"},
        "monitor_state UP on the tab",
        30,
    )
    # Counted from the restart: the old pm-monitor's last snapshot would pass
    # any test on its own seq, and the feed may reconnect after the bridge.
    until(
        lambda: len(feed.snapshots) >= restarted_at + 3,
        "a few snapshots from the new pm-monitor",
        30,
    )
    if page is not None:
        page.wait(f"{BANNER} === null && {MAIN_STALE} === 'false'", "the banner gone")
    after = feed.snapshots[restarted_at:]
    assert after, "no snapshot after the restart"
    assert all(s["trading"]["orders"]["today"] == orders for s in after)
    assert all(s["trading"]["trades"]["today"] == trades for s in after)

    trader = Trader("TRADER01")
    trader.close()
    event = feed.wait_event("CONNECT", "TRADER01", last_seq)
    assert event["seq"] > last_seq  # numbering continues from metrics.db (I107)


def test_a_killed_engine_is_dead_the_exchange_down_and_a_restart_shows(
    exchange: Exchange, feed: Feed, tab: Tab
) -> None:
    """kill -9 the engine: DEAD, exchange DOWN, a CRIT event on the tab; then
    pm-opctl-cli restarts it and the dashboard shows the restart."""
    old_pid = exchange.pid("engine")
    key = process(feed.latest or {}, "pm-engine")["key"]
    after = max(e["seq"] for e in feed.events)
    os.kill(old_pid, signal.SIGKILL)
    feed.wait(
        lambda s: process(s, "pm-engine")["state"] == "DEAD"
        and s["exchange"]["status"] == "DOWN",
        "pm-engine DEAD and the exchange DOWN",
        SILENT_WITHIN,
    )
    tab.wait(
        lambda f: f["type"] == "event"
        and f["data"]["subject"] == key
        and f["data"]["seq"] > after
        and f["data"]["detail"].endswith("-> DEAD")
        and f["data"]["severity"] == "CRIT",
        "the engine's DEAD event on the tab",
    )

    exchange.cli("pm-opctl-cli", "list", "--restart")
    s = feed.wait(
        lambda s: (
            s
            if process(s, "pm-engine")["state"] == "HEALTHY"
            and process(s, "pm-engine")["pid"] != old_pid
            and s["exchange"]["status"] == "OPERATIONAL"
            else None
        ),
        "a new pm-engine HEALTHY and the exchange OPERATIONAL",
        45,
    )
    assert process(s, "pm-engine")["restarted_recently"]
    assert process(s, "pm-engine")["pid"] == exchange.pid("engine")
