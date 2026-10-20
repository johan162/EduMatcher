"""The contract between the beaconing processes (Phase A) and pm-monitor (B).

pm-monitor interprets metrics by name and kind: which gauge of a gateway is
its client count, which counter its traffic, which engine counters are
requests. Nothing but this file ties those names to what each process
actually emits, so a renamed key in a gateway's ``_global_stats`` would
silently zero a dashboard figure. The producers are read from source (AST),
not run, so every process is covered without starting any of them.
"""

from __future__ import annotations

import ast
import re
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest

from edumatcher.engine.metrics import GATEWAY_COUNTERS
from edumatcher.monitor.activity import (
    GATEWAYS,
    REQUEST_COUNTERS,
    WATCHED_INCREASES,
)
from edumatcher.monitor.roster import BEACONING_PROCESSES

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "edumatcher"

#: Which package's source each beaconing process runs.
PACKAGE = {
    "pm-engine": "engine",
    "pm-alf-gwy": "alf_gwy",
    "pm-balf-gwy": "balf_gwy",
    "pm-md-gwy": "md_gateway",
    "pm-ralf-gwy": "ralf_gateway",
    "pm-dc-gwy": "dc_gateway",
    "pm-api-gwy": "api_gateway",
    "pm-log-srv": "log_srv",
    "pm-stats": "stats",
    "pm-audit": "audit",
    "pm-clearing": "clearing",
    "pm-scheduler": "scheduler",
    "pm-index": "index",
    "pm-market-sim": "market_sim",
    "pm-monitor": "monitor",
    "pm-mm-bot": "mm_bot",
    "pm-ai-swarm": "ai_trader",
}

COUNTER, GAUGE = "COUNTER", "GAUGE"


def _trees(package: str) -> Iterator[ast.AST]:
    for path in sorted((SRC / package).rglob("*.py")):
        yield ast.parse(path.read_text(encoding="utf-8"))


def _emitted(process: str) -> dict[str, str]:
    """Every metric name a process emits, with its kind."""
    out: dict[str, str] = {}
    for tree in _trees(PACKAGE[process]):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                fn, args = node.func.id, node.args
                if fn in ("counter", "gauge") and args:
                    if isinstance(args[0], ast.Constant) and isinstance(
                        args[0].value, str
                    ):
                        out[args[0].value] = COUNTER if fn == "counter" else GAUGE
                if fn == "client_gateway_samples" and isinstance(args[0], ast.Constant):
                    prefix = str(args[0].value)
                    out[f"{prefix}.clients"] = GAUGE
                    out[f"{prefix}.msgs_out"] = COUNTER
                    out[f"{prefix}.disconnects"] = COUNTER
                    given = {k.arg for k in node.keywords}
                    if "clients_max" in given:
                        out[f"{prefix}.clients_max"] = GAUGE
                    if "slow_clients" in given:
                        out[f"{prefix}.slow_clients"] = COUNTER
                    if "closing_clients" in given:
                        out[f"{prefix}.closing_clients"] = GAUGE
                if fn == "gateway_stats_samples":
                    out["gwy.clients_max"] = GAUGE
            # ALF/BALF: the keys of the _global_stats dict, exported as gwy.<key>
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                is_stats = any(
                    isinstance(t, ast.Attribute) and t.attr == "_global_stats"
                    for t in targets
                )
                if is_stats and isinstance(node.value, ast.Dict):
                    for key in node.value.keys:
                        if isinstance(key, ast.Constant):
                            kind = (
                                GAUGE if key.value == "connected_clients" else COUNTER
                            )
                            out[f"gwy.{key.value!s}"] = kind
    if process == "pm-engine":
        for name in GATEWAY_COUNTERS:  # counter(f"engine.{name}", ...)
            out[f"engine.{name}"] = COUNTER
    return out


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------


def _reporter_names() -> set[str]:
    """The process name every reporter in src/ is created with."""
    names: set[str] = set()
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for arg in re.findall(
            r"HealthReporter\.(?:start_)?from_compiled_config\((\w+|\"[^\"]+\")", text
        ):
            if arg.startswith('"'):
                names.add(arg.strip('"'))
            else:
                (value,) = re.findall(rf'^{arg} = "([^"]+)"', text, re.MULTILINE)
                names.add(value)
    return names


def test_every_beaconing_process_is_expected_by_the_roster() -> None:
    """A process the roster does not know reads as an unexpected extra; one
    it expects but that never beacons reads MISSING forever."""
    assert _reporter_names() == BEACONING_PROCESSES == set(PACKAGE)


def test_every_beacon_name_is_the_command_that_starts_it() -> None:
    """The roster maps a profile's command to a beacon by this name."""
    scripts = tomllib.loads((REPO / "pyproject.toml").read_text())["tool"]["poetry"][
        "scripts"
    ]
    for name in BEACONING_PROCESSES:
        assert name in scripts, name
        module = scripts[name].split(":")[0]
        assert module.split(".")[1] == PACKAGE[name], (name, module)


# ---------------------------------------------------------------------------
# names and kinds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("process", sorted(GATEWAYS))
def test_gateway_stats_read_what_the_gateway_emits(process: str) -> None:
    emitted = _emitted(process)
    spec = GATEWAYS[process]
    wanted = {spec.clients: GAUGE, spec.traffic: COUNTER}
    if spec.clients_max is not None:
        wanted[spec.clients_max] = GAUGE
    if spec.disconnects is not None:
        wanted[spec.disconnects] = COUNTER
    if spec.slow is not None:
        wanted[spec.slow] = COUNTER
    for name, kind in wanted.items():
        assert emitted.get(name) == kind, f"{process} does not emit {kind} {name}"


def test_watched_increases_are_counters_their_process_emits() -> None:
    owners = {
        "api.dropped_events": "pm-api-gwy",
        "stats.feed_gaps": "pm-stats",
        "monitor.store_errors": "pm-monitor",
    }
    assert set(WATCHED_INCREASES) == set(owners)
    for name, process in owners.items():
        assert _emitted(process).get(name) == COUNTER, name


def _engine_names_read_by_the_monitor() -> set[str]:
    names: set[str] = set(REQUEST_COUNTERS)
    for module in ("activity.py", "collector.py"):
        text = (SRC / "monitor" / module).read_text(encoding="utf-8")
        names.update(
            n
            for n in re.findall(r'"(engine\.[a-z0-9_]+)"', text)
            if not n.endswith("_")
        )
    return names


def test_every_engine_metric_the_monitor_reads_is_emitted() -> None:
    emitted = _emitted("pm-engine")
    missing = sorted(_engine_names_read_by_the_monitor() - set(emitted))
    assert not missing, f"pm-monitor reads engine metrics nobody emits: {missing}"


def test_engine_counters_the_monitor_differences_are_counters() -> None:
    emitted = _emitted("pm-engine")
    for name in (*REQUEST_COUNTERS, "engine.rejects", "engine.fills", "engine.trades",
                 "engine.traded_value", "engine.connects", "engine.disconnects",
                 "engine.heartbeat_timeouts"):  # fmt: skip
        assert emitted[name] == COUNTER, name
    for name in ("engine.participant_connected", "engine.resting_orders",
                 "engine.session_state", "engine.handle_us_p99",
                 "engine.book_heap_garbage_pct", "engine.book_heap_entries"):  # fmt: skip
        assert emitted[name] == GAUGE, name


def test_the_scanner_sees_what_it_should() -> None:
    """Guards the guard: an AST change that found nothing would pass above."""
    assert len(_emitted("pm-engine")) > 30
    assert "gwy.commands_received_total" in _emitted("pm-alf-gwy")
    assert "gwy.frames_received_total" in _emitted("pm-balf-gwy")
    assert "md.clients_max" in _emitted("pm-md-gwy")
    assert "gwy.slow_clients" in _emitted("pm-ralf-gwy")


# ---------------------------------------------------------------------------
# timing: constants on the two sides that only work together
# ---------------------------------------------------------------------------


def test_timing_constants_agree() -> None:
    from edumatcher.health import reporter
    from edumatcher.monitor import collector, state
    from edumatcher.monitor.config import MonitorConfig

    cfg = MonitorConfig()
    # a reporter's final beacon drains for FINAL_LINGER_MS after its stop; the
    # monitor must still be listening then (I88)
    assert reporter.FINAL_LINGER_MS / 1000 < collector.FINAL_GRACE_SEC
    # a full queued burst of every tracked source is read in one drain (I20)
    assert reporter.SNDHWM * state.MAX_SOURCES <= collector.DRAIN_BUDGET
    # a late loop is DEGRADED before it is HUNG, and a starting one gets longer
    assert state.LOOP_LAG_DEGRADED_MS < cfg.hung_after_sec * 1000
    assert cfg.hung_after_sec < state.STARTUP_GRACE_SEC
    # silence needs more than one missed beacon, so one late send is not SILENT
    assert cfg.silent_after_beacons >= 2
