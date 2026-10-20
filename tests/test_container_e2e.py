"""End to end on the container stack (WP-E3): ``deployment/docker``'s
``make up-all`` -- the exchange image, pm-monitor inside it, and the
dashboard in its own container -- driven the way an operator would.

``tests/test_monitor_e2e.py`` proves the chain on locally spawned processes;
this proves it where it is deployed: across the compose network, through the
read-only data mount, with the images built from this checkout. The six
scenarios of the design's WP-E3, in order on one stack:

* E3.6 reachability -- pm-monitor listens on 0.0.0.0 inside the exchange
  container, and the dashboard container reaches it (checked from inside);
* E3.1 the happy path -- a market maker and two AI traders trade; every
  process is HEALTHY, rates are non-zero, and today's trades match
  ``pm-stats-cli``;
* E3.2 SIGSTOP/SIGCONT of pm-clearing -- SILENT and back, in the events and
  on the dashboard;
* E3.5 pm-monitor stopped and restarted -- DOWN with the banner, then
  today's totals continue and the event numbers carry on;
* E3.4 the engine SIGKILLed -- DEAD, the exchange DOWN on the dashboard, and
  ``pm-opctl-cli list --restart`` brings it back with the RESTARTED badge;
* E3.3 no false HUNG -- while the traders run (``E3_SOAK_MIN`` minutes, 30 by
  default, as the design asks) and through every scenario above, no process
  is ever reported HUNG.

Run with ``make test-container`` (marker ``container``, deselected by
default), which builds the images first. The stack uses the fixed container
names and host ports, so the module skips when an EduMatcher stack is
already up or ``deployment/docker/data`` holds an exchange: it never touches
your own state. It empties ``data/`` afterwards only if it found it empty.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

from tests.test_monitor_e2e import BANNER, CHROME, PILL, Page, until

pytestmark = pytest.mark.container

REPO = Path(__file__).resolve().parents[1]
DOCKER = REPO / "deployment" / "docker"
DATA = DOCKER / "data"
ENGINE = os.environ.get("CONTAINER_ENGINE") or next(
    (e for e in ("podman", "docker") if shutil.which(e)), None
)
BACKEND = "edumatcher"
DASH_CONTAINER = "edumatcher-dash-gui"
DASH = "http://127.0.0.1:8095"
#: The container's hostname, the host part of every process key.
HOST = "edumatcher"
SOAK_SEC = float(os.environ.get("E3_SOAK_MIN", "30")) * 60
#: interval 2 s x silent_after 3 (design: within silent_after x interval + 1 s),
#: plus pm-monitor's 1 Hz snapshot and the bridge's hop.
SILENT_WITHIN = 10.0


#: The test's own make calls must not inherit the flags of a make that ran
#: pytest (``make -n`` would turn ``up-all`` into a dry run).
CLEAN_ENV = {
    k: v for k, v in os.environ.items() if k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")
}


def run(*args: str, timeout: float = 600, check: bool = True) -> str:
    done = subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=CLEAN_ENV,
    )
    if check and done.returncode != 0:
        raise AssertionError(
            f"{' '.join(args)} exited {done.returncode}:\n{done.stdout}{done.stderr}"
        )
    return done.stdout


def inside(*args: str, container: str = BACKEND, check: bool = True) -> str:
    assert ENGINE is not None
    return run(ENGINE, "exec", container, *args, check=check)


def program(command: str) -> str:
    """A ``pgrep -f``/``pkill -f`` pattern for the profile process
    ``command`` -- and not ``<command>-cli``, which pm-opctl runs as a
    health check. Run inside the container, where nothing of the test's own
    can match; pgrep never matches itself."""
    return f"/opt/edumatcher/.venv/bin/{command}( |$)"


def pid_of(command: str) -> int:
    (pid,) = inside("pgrep", "-f", program(command)).split()
    return int(pid)


def get(path: str) -> Any:
    with urllib.request.urlopen(f"{DASH}{path}", timeout=5) as r:
        return json.load(r)


def make(*targets: str, timeout: float = 600) -> str:
    return run("make", "-s", "-C", str(DOCKER), *targets, timeout=timeout)


# ---------------------------------------------------------------------------
# the stack
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def stack() -> Iterator[None]:
    if ENGINE is None:
        pytest.skip("neither podman nor docker is installed")
    names = run(ENGINE, "ps", "-a", "--format", "{{.Names}}").split()
    if any(n == "edumatcher" or n.startswith("edumatcher-") for n in names):
        pytest.skip(f"an EduMatcher stack is already there: {sorted(names)}")
    data_was_empty = not DATA.exists() or not any(DATA.iterdir())
    if not data_was_empty:
        pytest.skip(f"{DATA} holds an exchange; this test does not touch it")
    env_existed = (DOCKER / ".env").exists()
    try:
        make("up-all")
        until(
            lambda: _status().get("monitor") == "UP",
            "the dashboard bridge to see pm-monitor",
            120,
        )
        yield
    finally:
        run("make", "-s", "-C", str(DOCKER), "down-all", check=False, timeout=300)
        if data_was_empty and DATA.exists():
            # Files the container wrote belong to its users; remove them from inside one.
            run(
                ENGINE,
                "run",
                "--rm",
                "--entrypoint",
                "sh",
                "-v",
                f"{DATA}:/data:z",
                "edumatcher:local",
                "-c",
                "rm -rf /data/* /data/.[!.]*",
                check=False,
            )
        if not env_existed:
            (DOCKER / ".env").unlink(missing_ok=True)


def _status() -> dict[str, Any]:
    try:
        result: dict[str, Any] = get("/api/bridge/status")
        return result
    except OSError:
        return {}


class Feed:
    """The dashboard's own WebSocket, as the operator's browser receives it.

    A 30-minute soak brings some 2000 snapshots of tens of kilobytes each,
    so only the latest is kept, with a count and every HUNG process seen in
    any of them; every other frame (events, ``monitor_state``) is kept.
    """

    def __init__(self, ws: ClientConnection) -> None:
        self.ws = ws
        self.snapshot: dict[str, Any] | None = None
        self.snapshots = 0
        self.hung: list[tuple[str, str]] = []
        self.frames: list[dict[str, Any]] = []
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            for message in self.ws:
                frame = json.loads(message)
                if frame["type"] != "snapshot":
                    self.frames.append(frame)
                    continue
                data = frame["data"]
                self.hung += [
                    (data["ts"], p["key"])
                    for p in data["processes"]
                    if p["state"] == "HUNG"
                ]
                self.snapshot = data
                self.snapshots += 1
        except ConnectionClosed:
            pass

    def mark(self) -> int:
        return len(self.frames)

    def wait(
        self,
        match: Callable[[dict[str, Any]], bool],
        what: str,
        timeout: float = 20.0,
        since: int = 0,
    ) -> dict[str, Any]:
        return until(
            lambda: next((f for f in self.frames[since:] if match(f)), None),
            what,
            timeout,
        )

    def events(self, since: int = 0) -> list[dict[str, Any]]:
        return [f["data"] for f in self.frames[since:] if f["type"] == "event"]

    def latest(self) -> dict[str, Any]:
        assert self.snapshot is not None, "no snapshot yet"
        return self.snapshot

    def until_snapshot(
        self, check: Callable[[dict[str, Any]], bool], what: str, timeout: float = 30
    ) -> dict[str, Any]:
        def seen() -> object:
            s = self.latest()
            return {
                "status": s["exchange"]["status"],
                "not healthy": {
                    p["key"]: p["state"]
                    for p in s["processes"]
                    if p["state"] != "HEALTHY"
                },
            }

        return until(
            lambda: (lambda s: s if check(s) else None)(self.latest()),
            what,
            timeout,
            seen=seen,
        )


@pytest.fixture(scope="module")
def feed(stack: None) -> Iterator[Feed]:
    with connect("ws://127.0.0.1:8095/ws", max_size=None) as ws:
        f = Feed(ws)
        until(lambda: f.snapshot, "the first snapshot", 30)
        yield f


@pytest.fixture(scope="module")
def page(
    stack: None, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Page | None]:
    if CHROME is None:
        yield None
        return
    p = Page(CHROME, tmp_path_factory.mktemp("chrome"))
    try:
        p.goto(f"{DASH}/")
        yield p
    finally:
        p.close()


def proc(snapshot: dict[str, Any], process: str) -> dict[str, Any]:
    (p,) = [
        p
        for p in snapshot["processes"]
        if p["process"] == process and p["instance"] is None
    ]
    return p


# ---------------------------------------------------------------------------
# E3.6 -- reachability
# ---------------------------------------------------------------------------


def test_e3_6_pm_monitor_is_reachable_from_the_dashboard_container(stack: None) -> None:
    listening = json.loads(
        inside(
            "python3",
            "-c",
            "import json, psutil; print(json.dumps(sorted({(c.laddr.ip, c.laddr.port) "
            "for c in psutil.net_connections('tcp') if c.status == 'LISTEN'})))",
        )
    )
    assert ["0.0.0.0", 5610] in listening and ["0.0.0.0", 5611] in listening, listening
    # From inside the dashboard container, not the host: the bridge's own view.
    status = json.loads(
        inside(
            "node",
            "-e",
            "fetch('http://127.0.0.1:8095/api/bridge/status').then(r => r.json())"
            ".then(j => console.log(JSON.stringify(j)))",
            container=DASH_CONTAINER,
        )
    )
    assert status["monitor"] == "UP" and status["monitorConnected"], status
    assert status["source"] == "edumatcher:5611"
    assert status["metricsDb"]["ok"], status["metricsDb"]
    assert get("/api/thresholds")["source"] == "artifact"


# ---------------------------------------------------------------------------
# E3.1 + E3.3 -- trading, all healthy, figures agree; the soak
# ---------------------------------------------------------------------------

BOTS = (
    (
        "pm-mm-bot",
        "--gateway-id",
        "MM01",
        "--all-symbols",
        "--strategy",
        "passive",
        "--gap",
        "0.20",
        "--qty",
        "200",
    ),
    ("pm-ai-trader", "--id", "TRADER01", "--preset", "market-taker", "--duration", "0"),
    ("pm-ai-trader", "--id", "TRADER02", "--preset", "noise-retail", "--duration", "0"),
)


def all_healthy(s: dict[str, Any]) -> bool:
    """Every exchange process HEALTHY, and so the exchange OPERATIONAL -- or
    DEGRADED by a breach that is no process's: with the bots trading, the
    reject ratio counts a market maker's cancels that race its fills
    (ORDER_NOT_FOUND, I123) and can pass its 10 % band."""
    return s["exchange"]["status"] in ("OPERATIONAL", "DEGRADED") and all(
        p["state"] == "HEALTHY" for p in s["processes"] if p["group"] == "EXCHANGE"
    )


def operational(s: dict[str, Any]) -> bool:
    return all_healthy(s) and s["exchange"]["status"] == "OPERATIONAL"


def test_e3_1_a_trading_exchange_is_healthy_and_its_figures_agree(
    feed: Feed, page: Page | None
) -> None:
    feed.until_snapshot(operational, "a quiet exchange OPERATIONAL", 60)
    assert ENGINE is not None
    for bot in BOTS:
        run(ENGINE, "exec", "-d", BACKEND, *bot)
    try:
        until(
            lambda: feed.latest()["trading"]["trades"]["today"] >= 5,
            "the bots to trade",
            180,
        )
        until(
            lambda: feed.latest()["trading"]["orders"]["per_sec_now"] > 0,
            "a non-zero order rate",
            60,
        )
        if page is not None:
            page.wait(
                f"{PILL}?.textContent.includes({json.dumps(feed.latest()['exchange']['status'])})",
                "the exchange status on the pill",
            )

        # E3.3's soak: the traders keep every loop busy; a missed tick()
        # would show as HUNG (checked at the end, over the whole module).
        end = time.monotonic() + SOAK_SEC
        while time.monotonic() < end:
            time.sleep(5)
            assert feed.latest()["exchange"]["status"] in (
                "OPERATIONAL",
                "DEGRADED",
            ), feed.latest()["exchange"]
    finally:
        # Stopped whatever happened, or the later scenarios would see trading.
        for name in ("pm-ai-trader", "pm-mm-bot"):
            inside("pkill", "-f", program(name), check=False)

    # Within a minute of the trading stopping, pm-monitor and pm-stats agree.
    date = feed.latest()["exchange"]["trading_date"]
    counted: list[tuple[int, int]] = []

    def agree() -> bool:
        engine = feed.latest()["trading"]["trades"]["today"]
        recorded = len(
            json.loads(
                inside(
                    "pm-stats-cli",
                    "--format",
                    "json",
                    "trades",
                    "--date",
                    date,
                    "--limit",
                    "1000000",
                )
            )
        )
        counted.append((engine, recorded))
        return engine > 0 and engine == recorded

    until(
        agree,
        "pm-monitor's trades today to equal pm-stats-cli's",
        60,
        seen=lambda: counted[-3:],
    )


# ---------------------------------------------------------------------------
# E3.2 -- SILENT and back
# ---------------------------------------------------------------------------


def test_e3_2_a_stopped_process_goes_silent_and_comes_back(
    feed: Feed, page: Page | None
) -> None:
    key = f"pm-clearing@{HOST}"

    def status(f: dict[str, Any], ending: str) -> bool:
        return (
            f["type"] == "event"
            and f["data"]["kind"] == "PROCESS_STATUS"
            and f["data"]["subject"] == key
            and f["data"]["detail"].endswith(ending)
        )

    mark = feed.mark()
    stopped = time.monotonic()
    inside("pkill", "-STOP", "-f", program("pm-clearing"))
    try:
        feed.wait(
            lambda f: status(f, "SILENT"),
            "pm-clearing's SILENT event",
            SILENT_WITHIN,
            since=mark,
        )
        took = time.monotonic() - stopped
        feed.until_snapshot(
            lambda s: proc(s, "pm-clearing")["state"] == "SILENT",
            "SILENT in the snapshot",
            5,
        )
        if page is not None:
            page.wait(
                f"document.querySelector('table[aria-label=Processes] [data-row=\"{key}\"]')?.textContent.includes('SILENT')",
                "SILENT on the dashboard",
            )
    finally:
        inside("pkill", "-CONT", "-f", program("pm-clearing"))
    feed.wait(
        lambda f: status(f, "HEALTHY"), "pm-clearing's HEALTHY event", 20, since=mark
    )
    feed.until_snapshot(all_healthy, "pm-clearing HEALTHY, every process HEALTHY")
    print(f"pm-clearing SILENT {took:.1f} s after SIGSTOP")


# ---------------------------------------------------------------------------
# E3.5 -- a pm-monitor restart keeps today's totals
# ---------------------------------------------------------------------------


def test_e3_5_a_pm_monitor_restart_keeps_todays_totals(
    feed: Feed, page: Page | None
) -> None:
    before = feed.latest()["trading"]
    last_seq = max((e["seq"] for e in feed.events()), default=0)
    mark = feed.mark()
    inside("kill", "-TERM", str(pid_of("pm-monitor")))
    down = feed.wait(
        lambda f: f["type"] == "monitor_state" and f["monitor"] == "DOWN",
        "monitor_state DOWN",
        15,
        since=mark,
    )
    if page is not None:
        page.wait(
            f"{BANNER}?.textContent.includes('pm-monitor down')",
            "the pm-monitor down banner",
        )
    inside("pm-opctl-cli", "list", "--restart")
    feed.wait(
        lambda f: f["type"] == "monitor_state" and f["monitor"] == "UP",
        "monitor_state UP",
        60,
        since=feed.frames.index(down) + 1,
    )
    counted = feed.snapshots
    until(lambda: feed.snapshots > counted + 1, "snapshots from the new pm-monitor", 30)
    after = feed.latest()
    assert after["trading"]["trades"]["today"] == before["trades"]["today"]
    assert after["trading"]["orders"]["today"] == before["orders"]["today"]
    feed.until_snapshot(
        lambda s: proc(s, "pm-monitor")["state"] == "HEALTHY", "pm-monitor HEALTHY"
    )
    if page is not None:
        page.wait(f"!{BANNER}", "the banner gone")
    new = [e["seq"] for e in feed.events(since=mark)]
    assert all(seq > last_seq for seq in new), (last_seq, new)


# ---------------------------------------------------------------------------
# E3.4 -- the engine killed, then restarted
# ---------------------------------------------------------------------------


def test_e3_4_a_killed_engine_is_dead_and_comes_back_restarted(
    feed: Feed, page: Page | None
) -> None:
    key = f"pm-engine@{HOST}"
    mark = feed.mark()
    inside("kill", "-KILL", str(pid_of("pm-engine")))
    feed.until_snapshot(
        lambda s: proc(s, "pm-engine")["state"] == "DEAD"
        and s["exchange"]["status"] == "DOWN",
        "the engine DEAD and the exchange DOWN",
        SILENT_WITHIN + 10,
    )
    feed.wait(
        lambda f: f["type"] == "event"
        and f["data"]["kind"] == "PROCESS_STATUS"
        and f["data"]["subject"] == key
        and f["data"]["severity"] == "CRIT",
        "a CRIT event for the engine",
        since=mark,
    )
    if page is not None:
        page.wait(
            f"{PILL}?.textContent.includes('DOWN')", "the DOWN pill on the dashboard"
        )
    inside("pm-opctl-cli", "list", "--restart")
    feed.until_snapshot(
        lambda s: all_healthy(s) and proc(s, "pm-engine")["restarted_recently"],
        "the engine HEALTHY again, marked restarted",
        90,
    )
    if page is not None:
        page.wait(
            f"document.querySelector('table[aria-label=Processes] [data-row=\"{key}\"]')?.textContent.includes('RESTARTED')",
            "the RESTARTED badge",
        )


# ---------------------------------------------------------------------------
# E3.3 -- no false HUNG, ever
# ---------------------------------------------------------------------------


def test_e3_3_no_process_was_ever_hung(feed: Feed) -> None:
    """Through the soak and every scenario above -- a SIGSTOP is SILENT, a
    SIGKILL DEAD -- nothing was ever reported HUNG."""
    hung_events = [
        (e["ts"], e["subject"]) for e in feed.events() if e["detail"].endswith("HUNG")
    ]
    assert feed.hung == [] and hung_events == []
    assert feed.snapshots >= SOAK_SEC * 0.9, feed.snapshots
