"""Shared building blocks for the recorders' liveness checks.

pm-stats, pm-audit and pm-clearing each bind a bare REP socket that answers a
ping from its own receive loop, and each has a ``*-cli health`` command that
combines three signals: the process exists (pgrep), the loop answers (ZMQ
ping), and -- under ``--extended`` -- its data file is sound. This module
holds the parts that are identical across the three; what "sound" means for
each data file stays with its own CLI.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

import zmq

T = TypeVar("T")

PING_TIMEOUT_MS = 1000


def find_process_pids(program: str) -> list[int]:
    """Find running `program` processes, excluding this process.

    The pattern matches `program` as a whole command-line word, so
    ``pm-stats`` does not match ``pm-stats-cli``. `program` is used in a
    pgrep extended regex as-is; the pm-* names contain nothing that needs
    escaping.
    """
    pattern = rf"(^|/){program}([[:space:]]|$)"
    result = subprocess.run(
        ["pgrep", "-f", pattern],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise OSError(f"pgrep failed with exit code {result.returncode}")
    pids: list[int] = []
    for line in result.stdout.splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid != os.getpid():
            pids.append(pid)
    return sorted(set(pids))


def ping_health_endpoint(
    addr: str, timeout_ms: int = PING_TIMEOUT_MS
) -> tuple[bool, str]:
    """Ping a recorder's health REP socket at `addr` and confirm it replies.

    Unlike pgrep or a data-file check, this is the only signal that actually
    exercises the running process's receive loop: a reply proves the process
    is not just alive but pumping messages.
    """
    ctx: zmq.Context[Any] = zmq.Context.instance()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.LINGER, 0)
    sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sock.setsockopt(zmq.SNDTIMEO, timeout_ms)
    try:
        sock.connect(addr)
        sock.send(b"ping")
        reply = sock.recv()
        return True, f"replied at {reply.decode(errors='replace')}"
    except zmq.Again:
        return False, f"no reply within {timeout_ms}ms"
    except zmq.ZMQError as exc:
        return False, f"ZMQ ping failed: {exc}"
    finally:
        sock.close(0)


def answer_health_ping(sock: zmq.Socket[bytes], log: logging.Logger) -> None:
    """Answer one health ping on a REP socket with the current UTC time.

    REP sockets must reply before another recv is allowed, so this always
    drains and answers exactly one request per poll, regardless of what the
    request actually contains.
    """
    try:
        sock.recv()
        sock.send(datetime.now(tz=timezone.utc).isoformat().encode())
    except zmq.ZMQError as exc:
        log.warning("failed to answer health ping: %s", exc)


def run_with_timeout(fn: Callable[[], T], timeout_sec: float) -> T:
    """Run `fn` off-thread and return its result, or raise `TimeoutError`.

    The worker is a daemon thread rather than a `ThreadPoolExecutor`: the
    latter's atexit hook joins every worker before the interpreter exits,
    which would make a timed-out check block process exit for however long it
    actually takes regardless of the timeout reported here. A daemon thread is
    simply abandoned when the CLI exits. An exception raised by `fn` is
    re-raised in the caller.
    """
    outcome: list[T] = []
    failure: list[BaseException] = []

    def _run() -> None:
        try:
            outcome.append(fn())
        except BaseException as exc:  # re-raised in the caller below
            failure.append(exc)

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout_sec)
    if worker.is_alive():
        raise TimeoutError(f"did not finish within {timeout_sec:.0f}s")
    if failure:
        raise failure[0]
    return outcome[0]


def format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{value:.1f}TB"  # pragma: no cover - no data file gets here
