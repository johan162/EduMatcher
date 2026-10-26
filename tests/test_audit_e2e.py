"""End to end: pm-audit across a (faked) midnight, then the archive is replayed.

A real ``AuditProcess`` listens on a real ZeroMQ PUB/SUB pair; only its clock
is faked, since a test cannot wait for midnight.  The day close, the real
``pm-audit-cli archive --pending`` child process it starts, and the readers
that follow are all the production code.  Run with ``-m e2e``.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import zmq

from edumatcher.audit.cli import main as cli_main
from edumatcher.audit.main import AuditProcess
from edumatcher.audit.replay.cli import main as replay_main
from tests.conftest import free_ports

pytestmark = pytest.mark.e2e


def _wait(what: str, done: Callable[[], bool], timeout: float = 30.0) -> None:
    end = time.monotonic() + timeout
    while not done():
        if time.monotonic() > end:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(0.05)


@pytest.fixture()
def exchange(tmp_path: Path) -> Iterator[tuple[AuditProcess, zmq.Socket[bytes], list]]:
    pub_port, health_port = free_ports(2)
    pub_addr = f"tcp://127.0.0.1:{pub_port}"
    ctx = zmq.Context()
    pub = ctx.socket(zmq.PUB)
    pub.bind(pub_addr)
    day = (datetime.now(timezone.utc) - timedelta(days=2)).date()
    clock = [datetime.combine(day, dtime(12, 0), tzinfo=timezone.utc)]
    with (
        patch("edumatcher.audit.main.ENGINE_PUB_ADDR", pub_addr),
        patch(
            "edumatcher.audit.main.AUDIT_HEALTH_BIND_ADDR",
            f"tcp://127.0.0.1:{health_port}",
        ),
    ):
        proc = AuditProcess(
            tmp_path / "audit.log",
            False,
            buffer_size=1,
            flush_interval=0.2,
            session_tz=timezone.utc,
        )
    proc._now = lambda: clock[0]
    thread = threading.Thread(target=proc._receive, daemon=True)
    thread.start()
    time.sleep(1.0)  # let the subscription join the publisher
    try:
        yield proc, pub, clock
    finally:
        proc._running = False
        thread.join(timeout=5)
        proc._flush_buffer()
        proc._file.close()
        child = proc._archiver
        if child is not None:
            child.wait(timeout=30)
        proc.sub.close()
        proc.health_rep.close()
        pub.close()
        ctx.term()


def _publish(pub: zmq.Socket[bytes], day: str, count: int) -> None:
    for n in range(count):
        payload = {"order_id": f"{day}-{n}", "symbol": "AAPL", "gateway_id": "GW01"}
        pub.send_multipart([b"order.new", json.dumps(payload).encode()])


def test_a_day_closes_at_midnight_is_archived_and_replays_from_the_archive(
    exchange: tuple[AuditProcess, zmq.Socket[bytes], list],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    proc, pub, clock = exchange
    day = clock[0].date().isoformat()
    next_day = (clock[0].date() + timedelta(days=1)).isoformat()

    _publish(pub, day, 5)
    _wait("the first day's records", lambda: proc._records == 5)

    clock[0] = datetime.combine(
        clock[0].date() + timedelta(days=1), dtime(0, 0, 30), tzinfo=timezone.utc
    )
    _publish(pub, next_day, 3)
    _wait("the second day's records", lambda: proc._records == 8)

    archive = tmp_path / "audit" / f"audit-{day}.log.zst"
    _wait("the archive", lambda: archive.exists())
    _wait("the parts to go", lambda: not list((tmp_path / "audit").glob("*.log")))

    def reaped() -> bool:
        proc._service_archiver()
        return proc._archives == 1

    _wait("the archiver to be counted", reaped)
    assert proc._archive_errors == 0

    def events(*extra: str) -> list[str]:
        monkeypatch.setattr(
            "sys.argv",
            [
                "pm-audit-cli",
                "--log-file",
                str(tmp_path / "audit.log"),
                "--format",
                "json",
                "events",
                "--limit",
                "100",
                *extra,
            ],
        )
        capsys.readouterr()
        cli_main()
        return sorted(r["order_id"] for r in json.loads(capsys.readouterr().out))

    assert events("--date", day) == [f"{day}-{n}" for n in range(5)]
    assert events() == [f"{next_day}-{n}" for n in range(3)]

    capsys.readouterr()
    assert (
        replay_main(
            [
                "--log-file",
                str(tmp_path / "audit.log"),
                "--no-index",
                "--date",
                day,
                "episodes",
            ]
        )
        == 0
    )
    # One episode per record of that day, none from the day after.
    assert capsys.readouterr().out.count("orphan") == 5
