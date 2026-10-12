"""pm-ai-swarm: many AI traders, supervised.

The agents are split into K contiguous ID blocks; each block runs in one
worker process (one event loop, one ALF session per agent). A worker that
dies is restarted on its own, with back-off and a cap on restarts per hour;
the others keep trading. SIGTERM/SIGINT stop every worker, which closes all
ALF sessions.

Usage examples:
  poetry run pm-ai-swarm --count 20
  poetry run pm-ai-swarm --count 500 --workers 5 --budget 1000

Every bot id (PREFIX001, PREFIX002, ...) must be a participant in the deployed
engine config. With fewer bots than symbols each bot trades a slice of the
symbol list, so every symbol is traded.
"""

from __future__ import annotations

import argparse
import logging
import math
import multiprocessing
import os
import signal
import sys
import time
from collections import deque
from dataclasses import dataclass
from multiprocessing.context import SpawnProcess
from pathlib import Path
from types import FrameType
from typing import Any

from edumatcher.ai_trader.preset import Preset, builtin_presets
from edumatcher.ai_trader.swarm_config import (
    SwarmConfigError,
    SwarmFile,
    composition_counts,
    interleave,
    load_swarm_config,
    parse_presets_flag,
)
from edumatcher.ai_trader.transport import AlfTransport
from edumatcher.ai_trader.worker import AgentSpec, Worker
from edumatcher.alf_gwy.config import load_default_alf_gateway_config
from edumatcher.config import EDUMATCHER_ENGINE_HOST, ENGINE_CONFIG_FILE
from edumatcher.engine.config_loader import load_engine_config
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler

_CLIENT_NAME = "pm-ai-swarm"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"

log = logging.getLogger(__name__)


#: Bot ids carry a fixed three-digit suffix (AI001..AI999) so they sort in
#: numeric order and fit the 500-participant design limit.
MAX_BOT_INDEX = 999
#: Agents one worker process hosts by default (sets the default worker count).
AGENTS_PER_WORKER = 100
#: Worker restart back-off, and how many restarts an hour before giving up.
RESTART_BACKOFF_MIN = 1.0
RESTART_BACKOFF_MAX = 60.0
MAX_RESTARTS_PER_HOUR = 10
#: How long workers get to close their sessions after SIGTERM.
STOP_GRACE_SEC = 10.0
#: Built-in values of the settings a flag or the config file may give.
DEFAULTS: dict[str, object] = {
    "count": 10,
    "prefix": "AI",
    "start_index": 1,
    "symbols": "",
    "symbols_per_agent": 0,
    "seed_base": 1000,
    "duration": 0.0,
    "workers": 0,
    "budget": 0.0,
    "alf_host": EDUMATCHER_ENGINE_HOST,
    "alf_port": None,
    "log_level": None,
    "log_target": None,
    "log_file": None,
    "log_failover_timeout": None,
}


def build_gateway_ids(prefix: str, start_index: int, count: int) -> list[str]:
    last = start_index + count - 1
    if start_index < 1 or count < 1 or last > MAX_BOT_INDEX:
        raise ValueError(
            f"bot ids {prefix}{start_index:03d}..{prefix}{last:03d} are out of range; "
            f"indexes must lie in 1..{MAX_BOT_INDEX}"
        )
    return [f"{prefix}{i:03d}" for i in range(start_index, last + 1)]


def assign_symbols(
    gateway_ids: list[str], symbols: list[str], per_agent: int = 0
) -> dict[str, list[str]]:
    """Give each agent ``per_agent`` consecutive symbols so every symbol is traded.

    Agent i starts where agent i-1 stopped, wrapping around, so the first
    ``ceil(len(symbols) / per_agent)`` agents cover the whole list and the rest
    stack evenly on top. ``per_agent`` is raised to ``ceil(symbols / agents)``
    when it would leave symbols untraded (0 = exactly that).
    """
    if not symbols:
        raise ValueError("At least one symbol is required for swarm assignment")
    upper = [s.upper() for s in symbols]
    n = len(upper)
    k = min(n, max(per_agent, math.ceil(n / len(gateway_ids))))
    return {
        gw: [upper[(i * k + j) % n] for j in range(k)]
        for i, gw in enumerate(gateway_ids)
    }


def missing_participants(gateway_ids: list[str], config_path: Path) -> list[str]:
    """Bot ids the deployed engine config does not list as participants.

    The engine refuses to authenticate those, so the swarm checks up front
    instead of launching bots that all exit with "Gateway not configured".
    """
    allowed = load_engine_config(config_path).allowed_fix_gateways
    return [gw for gw in gateway_ids if gw not in allowed]


def select_symbols(
    deployed: list[str], include: list[str], exclude: list[str]
) -> list[str]:
    """The swarm's universe: ``include`` (default: every deployed symbol)
    minus ``exclude``. Symbols the exchange does not list are an error."""
    unknown = sorted(set(include + exclude) - set(deployed))
    if unknown:
        raise ValueError(f"symbol(s) not in the deployed config: {', '.join(unknown)}")
    chosen = include or sorted(deployed)
    return [sym for sym in chosen if sym not in set(exclude)]


def build_specs(
    gateway_ids: list[str],
    composition: dict[str, tuple[Preset, float]],
    symbols_by_gw: dict[str, list[str]],
    seed_base: int,
) -> list[AgentSpec]:
    """One agent per id; presets in exact proportion, evenly interleaved."""
    entries = list(composition.values())
    counts = composition_counts([w for _, w in entries], len(gateway_ids))
    order = interleave(counts)
    return [
        AgentSpec(gw, entries[order[i]][0], symbols_by_gw[gw], seed_base + i)
        for i, gw in enumerate(gateway_ids)
    ]


def default_worker_count(agents: int, cpus: int | None = None) -> int:
    """``min(cpu_count - 1, ceil(agents / 100))``, at least 1."""
    cpus = cpus or os.cpu_count() or 1
    return max(1, min(cpus - 1, math.ceil(agents / AGENTS_PER_WORKER)))


def split_blocks(specs: list[AgentSpec], workers: int) -> list[list[AgentSpec]]:
    """Contiguous ID blocks whose sizes differ by at most one."""
    workers = max(1, min(workers, len(specs)))
    size, extra = divmod(len(specs), workers)
    blocks: list[list[AgentSpec]] = []
    start = 0
    for i in range(workers):
        end = start + size + (1 if i < extra else 0)
        blocks.append(specs[start:end])
        start = end
    return blocks


@dataclass(frozen=True)
class WorkerJob:
    """Everything a worker process needs; pickled into it."""

    name: str
    specs: list[AgentSpec]
    alf_host: str
    alf_port: int
    budget: float | None
    log: dict[str, Any]


def run_worker(job: WorkerJob, duration: float) -> None:
    """Worker process entry point: one event loop for the job's agents."""
    _configure_logging(argparse.Namespace(**job.log), instance=job.name)
    transport = AlfTransport(job.alf_host, job.alf_port, seed=job.specs[0].seed)
    worker = Worker(
        job.specs, transport, budget_orders_per_sec=job.budget, name=job.name
    )
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    try:
        if not worker.start():
            sys.exit(1)
        worker.run(duration=duration)
    finally:
        worker.close()


class _Slot:
    def __init__(self, job: WorkerJob) -> None:
        self.job = job
        self.proc: SpawnProcess | None = None
        self.restarts: deque[float] = deque()
        self.backoff = RESTART_BACKOFF_MIN
        self.restart_at: float | None = None
        self.done = False
        self.gave_up = False


class Supervisor:
    """Runs one process per job and restarts the ones that die."""

    def __init__(self, jobs: list[WorkerJob], duration: float = 0.0) -> None:
        self.slots = [_Slot(job) for job in jobs]
        self.duration = duration
        self._ctx = multiprocessing.get_context("spawn")
        self._stopping = False
        self._start = 0.0

    def stop(self, _signum: int = 0, _frame: FrameType | None = None) -> None:
        self._stopping = True

    def _remaining(self, now: float) -> float:
        if self.duration <= 0:
            return 0.0
        return max(0.0, self.duration - (now - self._start))

    def _spawn(self, slot: _Slot, now: float) -> None:
        slot.proc = self._ctx.Process(
            target=run_worker,
            args=(slot.job, self._remaining(now)),
            name=slot.job.name,
        )
        slot.proc.start()
        slot.restart_at = None
        log.info(
            "[%s] worker started pid=%s agents=%d",
            slot.job.name,
            slot.proc.pid,
            len(slot.job.specs),
        )

    def _check(self, slot: _Slot, now: float) -> None:
        if slot.done:
            return
        if slot.restart_at is not None:
            if now >= slot.restart_at:
                self._spawn(slot, now)
            return
        proc = slot.proc
        if proc is None or proc.is_alive():
            return
        code = proc.exitcode
        if self.duration > 0 and (code == 0 or self._remaining(now) <= 0):
            slot.done = True  # ran its time
            return
        while slot.restarts and now - slot.restarts[0] > 3600:
            slot.restarts.popleft()
        if not slot.restarts:
            slot.backoff = RESTART_BACKOFF_MIN
        if len(slot.restarts) >= MAX_RESTARTS_PER_HOUR:
            log.error(
                "[%s] worker exited (code %s) and was restarted %d times in the "
                "last hour; giving up on its %d agents",
                slot.job.name,
                code,
                len(slot.restarts),
                len(slot.job.specs),
            )
            slot.done = slot.gave_up = True
            return
        slot.restarts.append(now)
        slot.restart_at = now + slot.backoff
        log.warning(
            "[%s] worker exited (code %s); restarting in %.0f s",
            slot.job.name,
            code,
            slot.backoff,
        )
        slot.backoff = min(RESTART_BACKOFF_MAX, slot.backoff * 2)

    def run(self) -> int:
        self._start = time.monotonic()
        for slot in self.slots:
            self._spawn(slot, self._start)
        try:
            while not self._stopping and not all(s.done for s in self.slots):
                now = time.monotonic()
                for slot in self.slots:
                    self._check(slot, now)
                time.sleep(0.2)
        finally:
            self._stop_all()
        return 1 if any(s.gave_up for s in self.slots) else 0

    def _stop_all(self) -> None:
        procs = [s.proc for s in self.slots if s.proc is not None and s.proc.is_alive()]
        for proc in procs:
            proc.terminate()
        deadline = time.monotonic() + STOP_GRACE_SEC
        for proc in procs:
            proc.join(max(0.0, deadline - time.monotonic()))
            if proc.is_alive():
                log.warning("[%s] worker did not stop; killing it", proc.name)
                proc.kill()
                proc.join()


def _configure_logging(args: argparse.Namespace, instance: str | None = None) -> int:
    log_level = getattr(args, "log_level", None)
    verbose = int(getattr(args, "verbose", 0) or 0)
    quiet = bool(getattr(args, "quiet", False))

    if log_level:
        level_name = str(log_level).upper()
        level = getattr(logging, level_name, logging.WARNING)
    elif verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    elif quiet:
        level = logging.WARNING
    else:
        level = logging.WARNING

    client_config = load_default_log_client_config()
    server_config = load_default_log_server_config()
    failover_timeout = getattr(args, "log_failover_timeout", None)
    handler = resolve_handler(
        log_target=getattr(args, "log_target", None),
        log_file=getattr(args, "log_file", None),
        client_name=_CLIENT_NAME,
        instance=instance,
        host=resolve_host_default(),
        port=server_config.port,
        connect_timeout_sec=client_config.connect_timeout_sec,
        failover_timeout_sec=(
            failover_timeout
            if failover_timeout is not None
            else client_config.failover_timeout_sec
        ),
        failover_dir=client_config.failover_dir,
    )
    logging.basicConfig(level=level, format=_LOG_FORMAT, handlers=[handler])
    return int(level)


def build_parser() -> argparse.ArgumentParser:
    """Overridable settings default to None, so an explicit flag can be told
    from an absent one; see ``resolve_settings``."""
    parser = argparse.ArgumentParser(description="EduMatcher AI trader swarm")
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-ai-swarm")
    parser.add_argument(
        "--swarm", type=Path, default=None, metavar="PATH", help="swarm.yaml file"
    )
    parser.add_argument("--count", type=int, help="Number of agents (default: 10)")
    parser.add_argument("--prefix", help="Gateway id prefix (default: AI)")
    parser.add_argument("--start-index", type=int, help="First id number (default: 1)")
    parser.add_argument(
        "--presets",
        default=None,
        help="Composition: 'a,b' (equal weights) or 'a:3,b:1'. Default: every built-in",
    )
    parser.add_argument(
        "--symbols",
        help="Comma-separated symbols (default: every deployed symbol)",
    )
    parser.add_argument(
        "--symbols-per-agent",
        type=int,
        help="Symbols each agent trades (default: just enough to cover them all)",
    )
    parser.add_argument(
        "--seed-base", type=int, help="Agent i gets seed-base + i (default: 1000)"
    )
    parser.add_argument(
        "--duration",
        type=float,
        help="Run duration in seconds; 0 (default) means run until stopped",
    )
    parser.add_argument(
        "--workers",
        type=int,
        help="Worker processes (default: min(cpus - 1, ceil(count / 100)))",
    )
    parser.add_argument(
        "--budget",
        type=float,
        help="Total order actions per second; 0 (default) = presets decide",
    )
    parser.add_argument(
        "--alf-host",
        help="Host of pm-alf-gwy (default: EDUMATCHER_ENGINE_HOST or 127.0.0.1)",
    )
    parser.add_argument(
        "--alf-port",
        type=int,
        help="Port of pm-alf-gwy (default: alf_gateway.port of the deployed config)",
    )
    parser.add_argument(
        "--log-level",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
        help="Logging level override (default: WARNING)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (-v: INFO, -vv: DEBUG); applies to the workers too",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Reduce output to warnings/errors; applies to the workers too",
    )
    parser.add_argument(
        "--log-target",
        choices=["server", "stdout", "file"],
        default=None,
        help=(
            "Where this process's own operational log records go: "
            "server (default, auto-detected pm-log-srv), stdout, or file"
        ),
    )
    parser.add_argument(
        "--log-file",
        default=None,
        metavar="PATH",
        help="Operational log file path — required when --log-target file",
    )
    parser.add_argument(
        "--log-failover-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Grace window before falling back to a local log file once "
            "pm-log-srv becomes unreachable (default: 30, from config)"
        ),
    )
    return parser


def resolve_settings(args: argparse.Namespace, file: SwarmFile | None) -> None:
    """Explicit flag, then the config file, then the built-in default."""
    for dest, default in DEFAULTS.items():
        if getattr(args, dest, None) is None:
            value = file.values.get(dest) if file is not None else None
            setattr(args, dest, default if value is None else value)


def main() -> None:
    args = build_parser().parse_args()
    try:
        file = load_swarm_config(args.swarm) if args.swarm is not None else None
        resolve_settings(args, file)
        if args.presets is not None:
            composition = parse_presets_flag(str(args.presets))
        elif file is not None and file.composition is not None:
            composition = file.composition
        else:
            composition = {
                name: (p, 1.0) for name, p in sorted(builtin_presets().items())
            }
    except SwarmConfigError as exc:
        raise SystemExit(f"pm-ai-swarm: {exc}") from exc
    _configure_logging(args)
    if args.count <= 0:
        log.error("invalid startup value: --count must be > 0 (got %s)", args.count)
        raise SystemExit("--count must be > 0")

    include = [s.strip().upper() for s in str(args.symbols).split(",") if s.strip()]
    exclude = file.exclude_symbols if file is not None else []
    try:
        symbols = select_symbols(
            sorted(load_engine_config(ENGINE_CONFIG_FILE).allowed_symbols),
            include,
            exclude,
        )
        gateway_ids = build_gateway_ids(
            str(args.prefix).upper(), int(args.start_index), int(args.count)
        )
    except ValueError as exc:
        raise SystemExit(f"pm-ai-swarm: {exc}") from exc
    if not symbols:
        log.error("no symbols available for swarm")
        raise SystemExit("No symbols available for swarm")
    missing = missing_participants(gateway_ids, ENGINE_CONFIG_FILE)
    if missing:
        log.error("swarm bot ids are not configured participants: %s", missing)
        raise SystemExit(
            f"{len(missing)} bot id(s) are not participants in "
            f"{ENGINE_CONFIG_FILE}: {', '.join(missing)}. Add them to "
            "`participants:` with role TRADER (pm-config-gen --participants "
            f"{missing[0]}:TRADER:CANCEL_ALL ...) and redeploy."
        )
    specs = build_specs(
        gateway_ids,
        composition,
        assign_symbols(gateway_ids, symbols, int(args.symbols_per_agent)),
        int(args.seed_base),
    )
    workers = int(args.workers) or default_worker_count(len(specs))
    blocks = split_blocks(specs, workers)
    budget = float(args.budget)
    log_args = {
        key: getattr(args, key, None)
        for key in (
            "log_level",
            "verbose",
            "quiet",
            "log_target",
            "log_file",
            "log_failover_timeout",
        )
    }
    port = args.alf_port or load_default_alf_gateway_config().port
    jobs = [
        WorkerJob(
            name=f"w{n + 1}-{block[0].gateway_id}-{block[-1].gateway_id}",
            specs=block,
            alf_host=str(args.alf_host),
            alf_port=port,
            budget=budget * len(block) / len(specs) if budget > 0 else None,
            log=log_args,
        )
        for n, block in enumerate(blocks)
    ]
    log.info(
        "swarm: %d agents on %d worker(s), %d symbols, composition %s",
        len(specs),
        len(jobs),
        len(symbols),
        ", ".join(f"{ref}:{w:g}" for ref, (_, w) in composition.items()),
    )
    supervisor = Supervisor(jobs, duration=float(args.duration))
    signal.signal(signal.SIGTERM, supervisor.stop)
    signal.signal(signal.SIGINT, supervisor.stop)
    raise SystemExit(supervisor.run())
