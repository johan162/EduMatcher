"""The host sampler (WP-B3.3, design §8.1)."""

from __future__ import annotations

from pathlib import Path

from edumatcher.config import DATA_DIR
from edumatcher.models.generated.health import HostStats
from edumatcher.monitor.host import (
    HostSampler,
    default_files,
    disk_free_pct,
    file_size,
    mem_used_pct,
)


def test_sizes_equal_the_files_in_the_data_dir(tmp_path: Path) -> None:
    (tmp_path / "stats.db").write_bytes(b"x" * 1000)
    (tmp_path / "stats.db-wal").write_bytes(b"x" * 24)
    (tmp_path / "audit.log").write_bytes(b"x" * 7)
    sampler = HostSampler(
        {
            "stats.db": tmp_path / "stats.db",
            "audit": tmp_path / "audit.log",
            "clearing.db": tmp_path / "clearing.db",  # missing
        },
        disk_path=tmp_path,
    )
    host = sampler.sample()
    assert host["files"] == [
        {"name": "stats.db", "size_bytes": 1024},
        {"name": "audit", "size_bytes": 7},
        {"name": "clearing.db", "size_bytes": 0},
    ]


def test_file_size_of_a_missing_file_is_zero(tmp_path: Path) -> None:
    assert file_size(tmp_path / "nope") == 0


def test_a_sample_is_valid_host_stats(tmp_path: Path) -> None:
    host = HostSampler({}, disk_path=tmp_path).sample()
    HostStats.from_dict(host).validate()
    assert host["mem_total_bytes"] > 0
    assert host["disk_total_bytes"] > 0
    assert len(host["cpu_per_core"]) >= 1
    assert 0.0 <= mem_used_pct(host) <= 100.0
    free = disk_free_pct(host)
    assert free is not None and 0.0 <= free <= 100.0


def test_an_unreadable_disk_path_reports_zero(tmp_path: Path) -> None:
    host = HostSampler({}, disk_path=tmp_path / "does-not-exist").sample()
    assert (host["disk_free_bytes"], host["disk_total_bytes"]) == (0, 0)
    assert disk_free_pct(host) is None


def test_default_files_live_in_the_data_dir() -> None:
    files = default_files()
    assert set(files) == {"log.db", "stats.db", "audit", "clearing.db", "gtc"}
    assert all(path.is_relative_to(DATA_DIR) for path in files.values())
    assert default_files(Path("/elsewhere/log.db"))["log.db"] == Path(
        "/elsewhere/log.db"
    )
