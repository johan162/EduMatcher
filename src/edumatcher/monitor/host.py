"""The host pm-monitor runs on: CPU, load, memory, disk and data files (§8.1).

In the container deployment this is the whole exchange; across hosts the
per-process figures in each beacon stay correct and this describes
pm-monitor's own machine.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

import psutil

from edumatcher.config import (
    AUDIT_LOG_FILE,
    CLEARING_DB_FILE,
    DATA_DIR,
    GTC_ORDERS_FILE,
    LOG_DB_FILE,
    METRICS_DB_FILE,
    STATS_DB_FILE,
)

#: SQLite companions whose bytes are part of a database's footprint.
SQLITE_SUFFIXES = ("-wal", "-shm")


def default_files(log_db: Path | None = None) -> dict[str, Path]:
    """The data files the dashboard shows, by logical name (``FileSize.name``).

    ``log_db`` is the log server's configured ``db_path`` when there is one.
    """
    return {
        "metrics.db": METRICS_DB_FILE,
        "log.db": LOG_DB_FILE if log_db is None else log_db,
        "stats.db": STATS_DB_FILE,
        "audit": AUDIT_LOG_FILE,
        "clearing.db": CLEARING_DB_FILE,
        "gtc": GTC_ORDERS_FILE,
    }


def file_size(path: Path) -> int:
    """Bytes on disk, including a SQLite database's ``-wal``/``-shm``; 0 if absent."""
    total = 0
    for candidate in (path, *(Path(f"{path}{s}") for s in SQLITE_SUFFIXES)):
        try:
            total += os.stat(candidate).st_size
        except OSError:
            continue
    return total


class HostSource(Protocol):
    """What the collector needs from a host sampler (tests pass a fixed one)."""

    def sample(self) -> dict[str, Any]: ...


class HostSampler:
    """Reads ``HostStats``; CPU figures are since the previous :meth:`sample`."""

    def __init__(
        self, files: dict[str, Path] | None = None, disk_path: Path = DATA_DIR
    ) -> None:
        self.files = default_files() if files is None else files
        self.disk_path = disk_path
        # The first cpu_percent(None) call returns 0.0 by definition.
        psutil.cpu_percent(None)
        psutil.cpu_percent(None, percpu=True)

    def sample(self) -> dict[str, Any]:
        cpu = psutil.cpu_percent(None)
        per_core = psutil.cpu_percent(None, percpu=True)
        load1, load5, load15 = psutil.getloadavg()
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()
        try:
            disk = psutil.disk_usage(str(self.disk_path))
            disk_free, disk_total = disk.free, disk.total
        except OSError:
            disk_free = disk_total = 0
        return {
            "cpu_pct": float(cpu),
            "cpu_per_core": [float(c) for c in per_core],
            "load1": float(load1),
            "load5": float(load5),
            "load15": float(load15),
            "mem_total_bytes": int(vm.total),
            "mem_used_bytes": int(vm.total - vm.available),
            "mem_available_bytes": int(vm.available),
            "swap_used_bytes": int(swap.used),
            "disk_free_bytes": int(disk_free),
            "disk_total_bytes": int(disk_total),
            "files": [
                {"name": name, "size_bytes": file_size(path)}
                for name, path in self.files.items()
            ],
        }


def mem_used_pct(host: dict[str, Any]) -> float:
    total = host["mem_total_bytes"]
    return 0.0 if total <= 0 else 100.0 * host["mem_used_bytes"] / total


def disk_free_pct(host: dict[str, Any]) -> float | None:
    total = host["disk_total_bytes"]
    return None if total <= 0 else 100.0 * host["disk_free_bytes"] / total
