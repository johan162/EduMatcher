"""pm-opctl - start, stop, and monitor named EduMatcher process profiles.

EduMatcher runs as a set of cooperating ``pm-*`` processes connected by a
ZeroMQ message bus. This module is the operator front end for that stack: it
launches a named group of those processes, tracks them, reports their health,
and shuts them down again.

Profiles
--------
A *profile* is a named list of processes to run together. Three profiles are
built in:

``micro``
    Centralized logging plus the matching engine only.
``mini``
    A trading-capable subset: logging, stats, engine, scheduler, market data,
    the desk API gateway, and the ALF/post-trade/drop-copy gateways.
``default``
    The full nominal exchange stack, including audit, clearing, both API
    gateway instances, and the BALF gateway.

The built-ins are used as-is when no configuration file exists. Running
``init`` writes them to ``<DATA_DIR>/emo-config.yaml`` so they can be edited.
Once that file exists its profiles replace the built-ins entirely; a missing
``default`` profile is backfilled from the built-in nominal stack.

Each process entry supports:

``name`` (required)
    Unique identifier used for the PID and log file names.
``command`` (required)
    A YAML list of argv tokens, or a shell-like string that is split with
    ``shlex``. The command is executed directly, never through a shell.
``healthcheck`` (optional)
    A command that exits ``0`` when the process is responsive.
``tcp`` (optional)
    A ``"host:port"`` address to probe with a plain TCP connect.

Health checking
---------------
There is no general way to prove an arbitrary process is not internally hung,
so health is reported at three levels of confidence:

* ``dead`` - no live PID could be found for the entry.
* ``not responding`` - the PID is alive but its ``healthcheck`` failed or its
  ``tcp`` address refused or timed out.
* ``running`` - the PID is alive and any configured check passed.

``healthcheck`` takes precedence over ``tcp`` because it exercises the
application itself. The ``tcp`` probe is far cheaper but weaker: libzmq's I/O
thread accepts connections independently of the application's own message
loop, so a successful connect proves the process is alive and bound to its
port, not that it is still processing messages.

Process tracking
----------------
Started processes are detached into their own session and recorded as
``<DATA_DIR>/emo/<name>.pid``, with combined stdout/stderr appended to
``<DATA_DIR>/emo/<name>.log``. The active profile name is remembered in
``<DATA_DIR>/emo/active-profile``.

Because a process restarted outside this tool gets a new PID, a stale PID file
is not treated as final. ``pgrep`` is used to look for a live process whose
command line matches the profile entry, and any match is re-adopted and
written back to the PID file. Matching ignores ``argv[0]`` and compares the
remaining arguments, since a console script appears in ``ps`` as
``python /path/to/pm-engine --verbose`` rather than ``pm-engine --verbose``.

Commands
--------
``start [profile]``
    Start a profile (``default`` when omitted), skipping entries already
    running.
``list``
    Print a status table for the active profile, including each process's
    uptime as ``HH:MM`` and resident memory in MiB, and offer to restart any
    dead entries. Use ``-y`` to restart without asking or ``--no-restart`` to
    suppress the offer; the prompt is skipped automatically when stdin is not
    a terminal.
``health [-q]``
    Same checks as ``list``, but exits ``0`` only when every process is
    running. ``-q`` suppresses output for use in monitoring scripts.
``stop``
    Send ``SIGTERM`` only to processes recorded in the PID directory.
``kill``
    Emergency stop: ``pkill -15 -f -i -l pm-``, which signals every process
    whose command line contains ``pm-``, including ones this tool did not
    start.
``init``
    Write the built-in profiles to ``<DATA_DIR>/emo-config.yaml``, refusing to
    overwrite an existing file.
``show``
    Print the resolved data directory.

All paths resolve through :func:`edumatcher.config.resolve_data_path`, so the
tool and the processes it launches agree on ``EDUMATCHER_DATA_DIR``.
"""

from __future__ import annotations

import argparse
import os
import shlex
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from edumatcher.config import DATA_DIR, resolve_data_path

CONFIG_NAME = "emo-config.yaml"
RUNTIME_DIR_NAME = "emo"
ACTIVE_PROFILE_FILE = "active-profile"
HEALTHCHECK_TIMEOUT_SEC = 2.0
TCP_CHECK_TIMEOUT_SEC = 0.3
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"

DEFAULT_PROCESSES: list[dict[str, Any]] = [
    {"name": "log", "command": ["pm-log-srv"], "tcp": "127.0.0.1:5600"},
    {"name": "audit", "command": ["pm-audit", "--verbose"]},
    {
        "name": "stats",
        "command": ["pm-stats", "--verbose"],
        "healthcheck": ["pm-stats-cli", "health", "-q"],
    },
    {"name": "clearing", "command": ["pm-clearing", "--verbose"]},
    {"name": "engine", "command": ["pm-engine", "--verbose"], "tcp": "127.0.0.1:5555"},
    {"name": "scheduler", "command": ["pm-scheduler", "--daily", "--verbose"]},
    {
        "name": "market-data-gwy",
        "command": ["pm-md-gwy", "--verbose"],
        "tcp": "127.0.0.1:5570",
    },
    {
        "name": "post-trade-gwy",
        "command": ["pm-ralf-gwy", "--verbose"],
        "tcp": "127.0.0.1:5580",
    },
    {
        "name": "drop-copy-gwy",
        "command": ["pm-dc-gwy", "--verbose"],
        "tcp": "127.0.0.1:5590",
    },
    {
        "name": "api-desk-gwy",
        "command": ["pm-api-gwy", "--verbose", "--instance", "desk"],
        "tcp": "127.0.0.1:8080",
    },
    {
        "name": "api-dashboards-gwy",
        "command": ["pm-api-gwy", "--verbose", "--instance", "dashboards"],
        "tcp": "127.0.0.1:8081",
    },
    {
        "name": "alf-gwy",
        "command": ["pm-alf-gwy", "--verbose"],
        "tcp": "127.0.0.1:5565",
    },
    {
        "name": "balf-gwy",
        "command": ["pm-balf-gwy", "--verbose"],
        "tcp": "127.0.0.1:5560",
    },
]

MICRO_PROCESSES: list[dict[str, Any]] = [
    {"name": "log", "command": ["pm-log-srv"], "tcp": "127.0.0.1:5600"},
    {"name": "engine", "command": ["pm-engine", "--verbose"], "tcp": "127.0.0.1:5555"},
]

MINI_PROCESSES: list[dict[str, Any]] = [
    {"name": "log", "command": ["pm-log-srv"], "tcp": "127.0.0.1:5600"},
    {
        "name": "stats",
        "command": ["pm-stats", "--verbose"],
        "healthcheck": ["pm-stats-cli", "health", "-q"],
    },
    {"name": "engine", "command": ["pm-engine", "--verbose"], "tcp": "127.0.0.1:5555"},
    {"name": "scheduler", "command": ["pm-scheduler", "--daily", "--verbose"]},
    {
        "name": "market-data-gwy",
        "command": ["pm-md-gwy", "--verbose"],
        "tcp": "127.0.0.1:5570",
    },
    {
        "name": "api-desk-gwy",
        "command": ["pm-api-gwy", "--verbose", "--instance", "desk"],
        "tcp": "127.0.0.1:8080",
    },
    {
        "name": "alf-gwy",
        "command": ["pm-alf-gwy", "--verbose"],
        "tcp": "127.0.0.1:5565",
    },
    {
        "name": "post-trade-gwy",
        "command": ["pm-ralf-gwy", "--verbose"],
        "tcp": "127.0.0.1:5580",
    },
    {
        "name": "drop-copy-gwy",
        "command": ["pm-dc-gwy", "--verbose"],
        "tcp": "127.0.0.1:5590",
    },
]


# {"name": "trader", "command": ["pm-alf-console", "--id", "TRADER01", "--verbose"]},

BUILTIN_PROFILES = {
    "default": DEFAULT_PROCESSES,
    "micro": MICRO_PROCESSES,
    "mini": MINI_PROCESSES,
}


def runtime_dir() -> Path:
    return resolve_data_path(RUNTIME_DIR_NAME)


def config_path() -> Path:
    return resolve_data_path(CONFIG_NAME)


def pid_path(name: str) -> Path:
    return resolve_data_path(f"{RUNTIME_DIR_NAME}/{name}.pid")


def log_path(name: str) -> Path:
    return resolve_data_path(f"{RUNTIME_DIR_NAME}/{name}.log")


def active_profile_path() -> Path:
    return resolve_data_path(f"{RUNTIME_DIR_NAME}/{ACTIVE_PROFILE_FILE}")


def load_profiles() -> dict[str, list[dict[str, Any]]]:
    path = config_path()
    if not path.exists():
        return {name: list(processes) for name, processes in BUILTIN_PROFILES.items()}

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw is None:
        return {"default": list(DEFAULT_PROCESSES)}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a mapping of profile names")

    profiles: dict[str, list[dict[str, Any]]] = {}
    for profile_name, profile_raw in raw.items():
        if not isinstance(profile_name, str) or not profile_name.strip():
            raise ValueError("profile names must be non-empty strings")
        process_raw = (
            profile_raw.get("processes")
            if isinstance(profile_raw, dict)
            else profile_raw
        )
        if not isinstance(process_raw, list):
            raise ValueError(f"profile {profile_name!r}.processes must be a list")
        profiles[profile_name] = validate_processes(profile_name, process_raw)

    if "default" not in profiles:
        profiles["default"] = list(DEFAULT_PROCESSES)
    return profiles


def create_config() -> int:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        profile_name: {"processes": processes}
        for profile_name, processes in BUILTIN_PROFILES.items()
    }
    text = yaml.safe_dump(document, sort_keys=False, allow_unicode=False)
    try:
        with path.open("x", encoding="utf-8") as output:
            output.write(text)
    except FileExistsError:
        print(f"Refusing to overwrite existing configuration: {path}", file=sys.stderr)
        return 1
    print(f"Created pm-opctl configuration: {path}")
    print("Profiles: " + ", ".join(document))
    return 0


def validate_processes(
    profile_name: str, process_raw: list[Any]
) -> list[dict[str, Any]]:
    processes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(process_raw):
        if not isinstance(item, dict):
            raise ValueError(
                f"profile {profile_name!r} process {index} must be a mapping"
            )
        name = item.get("name")
        command = item.get("command")
        healthcheck = item.get("healthcheck")
        tcp = item.get("tcp")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"profile {profile_name!r} process {index} needs a name")
        if name in seen:
            raise ValueError(f"profile {profile_name!r} repeats process name {name!r}")
        if isinstance(command, str):
            command = shlex.split(command)
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(part, str) and part for part in command)
        ):
            raise ValueError(
                f"profile {profile_name!r} process {name!r} needs a command list or string"
            )
        if isinstance(healthcheck, str):
            healthcheck = shlex.split(healthcheck)
        if healthcheck is not None and (
            not isinstance(healthcheck, list)
            or not healthcheck
            or not all(isinstance(part, str) and part for part in healthcheck)
        ):
            raise ValueError(
                f"profile {profile_name!r} process {name!r} healthcheck must be a command list or string"
            )
        if tcp is not None:
            if not isinstance(tcp, str) or ":" not in tcp:
                raise ValueError(
                    f"profile {profile_name!r} process {name!r} tcp must be host:port"
                )
            _, _, port_text = tcp.rpartition(":")
            if not port_text.isdigit():
                raise ValueError(
                    f"profile {profile_name!r} process {name!r} tcp port must be numeric"
                )
        seen.add(name)
        process = {"name": name, "command": command}
        if healthcheck is not None:
            process["healthcheck"] = healthcheck
        if tcp is not None:
            process["tcp"] = tcp
        processes.append(process)
    return processes


def read_pid(name: str) -> int | None:
    try:
        pid = int(pid_path(name).read_text(encoding="ascii").strip())
    except (FileNotFoundError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        pid_path(name).unlink(missing_ok=True)
        return None
    except PermissionError:
        return pid
    return pid


def pgrep_pids(program: str) -> list[int]:
    try:
        result = subprocess.run(
            ["pgrep", "-f", program],
            capture_output=True,
            text=True,
            timeout=HEALTHCHECK_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [int(line) for line in result.stdout.split() if line.isdigit()]


def command_line(pid: int) -> str:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            timeout=HEALTHCHECK_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip()


def matches_command(cmdline: str, command: list[str]) -> bool:
    """Match ignoring argv[0]; console scripts run as `python /path/pm-foo ...`."""
    try:
        tokens = shlex.split(cmdline)
    except ValueError:
        tokens = cmdline.split()
    program = os.path.basename(command[0])
    for index, token in enumerate(tokens):
        if os.path.basename(token) == program:
            return tokens[index + 1 :] == list(command[1:])
    return False


def discover_pid(process: dict[str, Any], claimed: set[int]) -> int | None:
    """Find a running process matching this entry's command line."""
    command = process["command"]
    own_pid = os.getpid()
    for pid in pgrep_pids(os.path.basename(command[0])):
        if pid == own_pid or pid in claimed:
            continue
        if matches_command(command_line(pid), command):
            return pid
    return None


def resolve_pid(process: dict[str, Any], claimed: set[int]) -> tuple[int | None, bool]:
    """Return the live PID for a process, re-adopting it if it was restarted."""
    name = process["name"]
    pid = read_pid(name)
    if pid is not None:
        claimed.add(pid)
        return pid, False
    pid = discover_pid(process, claimed)
    if pid is None:
        return None, False
    claimed.add(pid)
    runtime_dir().mkdir(parents=True, exist_ok=True)
    pid_path(name).write_text(f"{pid}\n", encoding="ascii")
    return pid, True


def spawn_process(process: dict[str, Any]) -> int | None:
    """Launch one profile process and record its PID."""
    name = process["name"]
    command = process["command"]
    runtime_dir().mkdir(parents=True, exist_ok=True)
    output = log_path(name).open("ab")
    try:
        child = subprocess.Popen(
            command,
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as exc:
        print(f"  failed to start {name}: {exc}", file=sys.stderr)
        return None
    finally:
        output.close()
    pid_path(name).write_text(f"{child.pid}\n", encoding="ascii")
    return child.pid


def write_active_profile(profile_name: str) -> None:
    active_profile_path().write_text(f"{profile_name}\n", encoding="utf-8")


def read_active_profile() -> str | None:
    try:
        profile_name = active_profile_path().read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return profile_name or None


def check_tcp(address: str) -> tuple[str, str]:
    """Cheapest liveness probe for a ZMQ-bus process: connect, don't speak.

    A successful connect only proves the transport accepted it — libzmq's I/O
    thread accepts sockets independently of the application thread, so this
    does not prove the process's own message loop is unstuck. It is still the
    cheapest signal available without a protocol-specific client.
    """
    host, _, port_text = address.rpartition(":")
    try:
        with socket.create_connection(
            (host, int(port_text)), timeout=TCP_CHECK_TIMEOUT_SEC
        ):
            pass
    except OSError as exc:
        return "not responding", f"tcp connect to {address} failed: {exc}"
    return "running", f"tcp connect to {address} ok"


def check_health(process: dict[str, Any], pid: int | None) -> tuple[str, str]:
    if pid is None:
        return "dead", "process is not running"
    healthcheck = process.get("healthcheck")
    if healthcheck is not None:
        try:
            result = subprocess.run(
                healthcheck,
                env=os.environ.copy(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=HEALTHCHECK_TIMEOUT_SEC,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return "not responding", str(exc)
        if result.returncode == 0:
            return "running", "healthcheck passed"
        return "not responding", f"healthcheck exit {result.returncode}"
    tcp = process.get("tcp")
    if tcp is not None:
        return check_tcp(tcp)
    return "running", "no healthcheck or tcp check configured"


def status_mark(status: str) -> str:
    if status == "running":
        return f"{GREEN}✅{RESET}"
    if status == "dead":
        return f"{RED}❌{RESET}"
    return f"{YELLOW}⚠️{RESET}"


def parse_etime(text: str) -> float | None:
    """Parse the portable ps elapsed-time format ``[[dd-]hh:]mm:ss`` to minutes."""
    days, _, clock = text.strip().rpartition("-")
    parts = clock.split(":")
    if not all(part.isdigit() for part in parts) or not 2 <= len(parts) <= 3:
        return None
    values = [int(part) for part in parts]
    seconds = values.pop()
    minutes = values.pop()
    hours = values.pop() if values else 0
    total = seconds + minutes * 60 + hours * 3600
    if days:
        if not days.isdigit():
            return None
        total += int(days) * 86400
    return total / 60


def process_stats(pid: int) -> tuple[float | None, float | None]:
    """Return (uptime minutes, resident memory MiB) for a running process."""
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "etime=,rss="],
            capture_output=True,
            text=True,
            timeout=HEALTHCHECK_TIMEOUT_SEC,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, None
    fields = result.stdout.split()
    if len(fields) != 2:
        return None, None
    etime, rss = fields
    return parse_etime(etime), int(rss) / 1024 if rss.isdigit() else None


def format_uptime(minutes: float | None) -> str:
    if minutes is None:
        return "-"
    total = int(minutes)
    return f"{total // 60:02d}:{total % 60:02d}"


def list_profile(restart: str = "ask") -> int:
    profile_name = read_active_profile()
    if profile_name is None:
        print("No pm-opctl profile is recorded as started.")
        return 1
    profiles = load_profiles()
    processes = profiles.get(profile_name)
    if processes is None:
        print(f"Active profile {profile_name!r} is no longer defined.", file=sys.stderr)
        return 1

    print(f"pm-opctl profile: {profile_name}")
    print(f"data directory: {DATA_DIR}")
    header = (
        f"{'':1} {'Process':<20} {'PID':>7} {'Uptime':>8} "
        f"{'RSS(MB)':>8}  {'Status':<15} Details"
    )
    print(header)
    print("-" * 94)
    claimed: set[int] = set()
    dead: list[dict[str, Any]] = []
    for process in processes:
        name = process["name"]
        pid, adopted = resolve_pid(process, claimed)
        state, detail = check_health(process, pid)
        if adopted:
            detail = f"{detail} (re-adopted restarted process)"
        if state == "dead":
            dead.append(process)
        uptime, rss = process_stats(pid) if pid is not None else (None, None)
        uptime_text = format_uptime(uptime)
        rss_text = f"{rss:.1f}" if rss is not None else "-"
        print(
            f"{status_mark(state)} {name:<20} {str(pid or '-'):>7} "
            f"{uptime_text:>8} {rss_text:>8}  {state:<15} {detail}"
        )

    if dead and restart != "never":
        restart_dead(dead, assume_yes=restart == "always")
    return 0


def restart_dead(dead: list[dict[str, Any]], assume_yes: bool) -> None:
    names = ", ".join(process["name"] for process in dead)
    if not assume_yes:
        if not sys.stdin.isatty():
            return
        answer = input(f"\nRestart {len(dead)} dead process(es) ({names})? [y/N] ")
        if answer.strip().lower() not in {"y", "yes"}:
            return
    print(f"Restarting: {names}")
    for process in dead:
        pid = spawn_process(process)
        if pid is not None:
            command = " ".join(process["command"])
            print(f"  started {process['name']} (pid {pid}): {command}")


def health_profile(quiet: bool) -> int:
    """Like list_profile, but exits non-zero unless every process is running."""
    profile_name = read_active_profile()
    if profile_name is None:
        if not quiet:
            print("No pm-opctl profile is recorded as started.", file=sys.stderr)
        return 1
    profiles = load_profiles()
    processes = profiles.get(profile_name)
    if processes is None:
        if not quiet:
            print(
                f"Active profile {profile_name!r} is no longer defined.",
                file=sys.stderr,
            )
        return 1

    healthy = True
    claimed: set[int] = set()
    for process in processes:
        name = process["name"]
        pid, _ = resolve_pid(process, claimed)
        state, detail = check_health(process, pid)
        if state != "running":
            healthy = False
        if not quiet:
            print(f"{status_mark(state)} {name:<20} {state:<15} {detail}")
    if not quiet:
        print(f"health: {'OK' if healthy else 'FAIL'}")
    return 0 if healthy else 1


def start_profile(profile_name: str) -> int:
    profiles = load_profiles()
    if profile_name not in profiles:
        available = ", ".join(sorted(profiles))
        print(
            f"Unknown configuration {profile_name!r}; available: {available}",
            file=sys.stderr,
        )
        return 2

    runtime_dir().mkdir(parents=True, exist_ok=True)
    processes = profiles[profile_name]
    write_active_profile(profile_name)
    print(f"Starting pm-opctl configuration {profile_name!r} from {config_path()}")
    print(f"Data directory: {DATA_DIR}")
    claimed: set[int] = set()
    for process in processes:
        name = process["name"]
        existing, _ = resolve_pid(process, claimed)
        if existing is not None:
            print(f"  already running {name} (pid {existing})")
            continue
        pid = spawn_process(process)
        if pid is None:
            return 1
        print(f"  started {name} (pid {pid}): {' '.join(process['command'])}")
    return 0


def stop_profile() -> int:
    runtime = runtime_dir()
    pid_files = sorted(runtime.glob("*.pid"))
    if not pid_files:
        print("No pm-opctl-managed processes are running.")
        active_profile_path().unlink(missing_ok=True)
        return 0

    for path in pid_files:
        name = path.stem
        pid = read_pid(name)
        if pid is None:
            path.unlink(missing_ok=True)
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"  stopped {name} (pid {pid})")
        except ProcessLookupError:
            pass
        path.unlink(missing_ok=True)
    time.sleep(0.2)
    active_profile_path().unlink(missing_ok=True)
    return 0


def kill_all_processes() -> int:
    """Send SIGTERM to every process whose full command line contains pm-."""
    print("Sending signal 15 to all matching EduMatcher processes...")
    result = subprocess.run(
        ["pkill", "-15", "-f", "-i", "-l", "pm-"],
        check=False,
    )
    runtime = runtime_dir()
    for path in runtime.glob("*.pid"):
        path.unlink(missing_ok=True)
    active_profile_path().unlink(missing_ok=True)
    if result.returncode == 0:
        return 0
    if result.returncode == 1:
        print("No matching EduMatcher processes were found.")
        return 0
    print(f"pkill failed with exit code {result.returncode}", file=sys.stderr)
    return result.returncode


def show_data_dir() -> int:
    print(DATA_DIR)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pm-opctl-cli", description="Manage EduMatcher operational process control"
    )
    from edumatcher.cli_version import add_version_argument
    
    add_version_argument(parser, "pm-opctl-cli")
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    start = subparsers.add_parser("start", help="start a named process profile")
    start.add_argument("config_name", nargs="?", default="default")
    subparsers.add_parser(
        "init", help="create the built-in process profile configuration"
    )
    subparsers.add_parser("stop", help="stop processes started by pm-opctl")
    subparsers.add_parser(
        "kill",
        help="send SIGTERM to every process whose command line contains pm-",
    )
    listing = subparsers.add_parser(
        "list", help="list status for the active process profile"
    )
    restart_group = listing.add_mutually_exclusive_group()
    restart_group.add_argument(
        "-y",
        "--restart",
        dest="restart",
        action="store_const",
        const="always",
        help="restart dead processes without asking",
    )
    restart_group.add_argument(
        "--no-restart",
        dest="restart",
        action="store_const",
        const="never",
        help="never offer to restart dead processes",
    )
    listing.set_defaults(restart="ask")
    health = subparsers.add_parser(
        "health", help="check health of every process in the active profile"
    )
    health.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="print nothing; exit 0 when all processes are running, 1 otherwise",
    )
    subparsers.add_parser("show", help="print the current data directory path")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "init":
            return create_config()
        if args.command == "start":
            return start_profile(args.config_name or "default")
        if args.command == "stop":
            return stop_profile()
        if args.command == "kill":
            return kill_all_processes()
        if args.command == "list":
            return list_profile(args.restart)
        if args.command == "health":
            return health_profile(args.quiet)
        if args.command == "show":
            return show_data_dir()
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"pm-opctl: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
