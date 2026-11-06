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
from edumatcher.audit.writer import AuditFile
from tests.conftest import free_ports

pytestmark = pytest.mark.e2e


def _wait(what: str, done: Callable[[], bool], timeout: float = 30.0) -> None:
    end = time.monotonic() + timeout
    while not done():
        if time.monotonic() > end:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(0.05)


def _wait_for_subscriptions(
    publisher: zmq.Socket[bytes], expected: set[bytes], timeout: float = 5.0
) -> None:
    """Wait for XPUB to observe the expected topic-subscription frames."""
    deadline = time.monotonic() + timeout
    observed: set[bytes] = set()
    while not expected.issubset(observed):
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not publisher.poll(int(remaining * 1000)):
            raise AssertionError(
                f"publisher did not observe subscriptions: {expected - observed}"
            )
        event = publisher.recv()
        if event[:1] == b"\x01":
            observed.add(event)


@pytest.fixture()
def exchange(
    tmp_path: Path,
) -> Iterator[
    tuple[
        AuditProcess,
        zmq.Socket[bytes],
        zmq.Socket[bytes],
        list,
        threading.Thread,
    ]
]:
    pub_port, health_port = free_ports(2)
    pub_addr = f"tcp://127.0.0.1:{pub_port}"
    ctx = zmq.Context()
    pub = ctx.socket(zmq.XPUB)
    pub.setsockopt(zmq.XPUB_VERBOSER, 1)
    pub.bind(pub_addr)
    observer = ctx.socket(zmq.SUB)
    observer.setsockopt(zmq.SUBSCRIBE, b"order.")
    observer.connect(pub_addr)
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
            True,
            buffer_size=100,
            flush_interval=10.0,
            session_tz=timezone.utc,
        )
    proc._now = lambda: clock[0]
    thread = threading.Thread(target=proc._receive, daemon=True)
    thread.start()
    _wait_for_subscriptions(pub, {b"\x01", b"\x01order."})
    try:
        yield proc, pub, observer, clock, thread
    finally:
        proc._eod_seen = True  # or the stop drains _DRAIN_SEC for system.eod
        proc._running = False
        thread.join(timeout=5)
        if proc._flush_timer is not None:
            proc._flush_timer.cancel()
        proc._flush_buffer()
        if not proc._file._fh.closed:
            proc._file.close()
        child = proc._archiver
        if child is not None:
            child.wait(timeout=30)
        proc.sub.close()
        proc.health_rep.close()
        observer.close()
        pub.close()
        ctx.term()


def _publish(pub: zmq.Socket[bytes], day: str, count: int) -> None:
    for n in range(count):
        payload = {"order_id": f"{day}-{n}", "symbol": "AAPL", "gateway_id": "GW01"}
        pub.send_multipart([b"order.new", json.dumps(payload).encode()])


def _audit_order_ids(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        json.loads(line[line.index("{") :])["order_id"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.startswith("[") and '"order_id"' in line
    ]


def test_a_day_closes_at_midnight_is_archived_and_replays_from_the_archive(
    exchange: tuple[
        AuditProcess,
        zmq.Socket[bytes],
        zmq.Socket[bytes],
        list,
        threading.Thread,
    ],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    proc, pub, _observer, clock, _thread = exchange
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


def test_events_after_subscription_are_recorded_once_within_flush_interval(
    exchange: tuple[
        AuditProcess,
        zmq.Socket[bytes],
        zmq.Socket[bytes],
        list,
        threading.Thread,
    ],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    proc, pub, observer, _clock, thread = exchange
    expected = [f"ready-{n}" for n in range(13)]
    published: list[tuple[str, float]] = []
    terminal = ""
    started = time.monotonic()

    for n, order_id in enumerate(expected):
        deadline = started + n * 3.0
        time.sleep(max(0.0, deadline - time.monotonic()))
        pub.send_multipart(
            [
                b"order.new",
                json.dumps(
                    {"order_id": order_id, "symbol": "AAPL", "gateway_id": "GW01"}
                ).encode(),
            ]
        )
        published.append((order_id, time.monotonic()))

        assert observer.poll(1000), f"raw subscriber missed {order_id}"
        frames = observer.recv_multipart()
        assert json.loads(frames[1])["order_id"] == order_id
        _wait(
            f"pm-audit to receive {order_id}",
            lambda: proc._records == n + 1,
            timeout=2.0,
        )

        now = time.monotonic()
        overdue = [
            event_id
            for event_id, sent_at in published
            if now - sent_at > proc.flush_interval + 2.0
        ]
        recorded = _audit_order_ids(tmp_path / "audit.log")
        terminal += capsys.readouterr().out
        assert all(event_id in recorded for event_id in overdue)
        assert all(
            terminal.count(f'"order_id": "{event_id}"') == 1 for event_id in overdue
        )

    _wait(
        "all audit lines to be flushed",
        lambda: all(
            _audit_order_ids(tmp_path / "audit.log").count(event_id) == 1
            for event_id in expected
        ),
        timeout=proc.flush_interval + 2.0,
    )
    terminal += capsys.readouterr().out
    assert _audit_order_ids(tmp_path / "audit.log") == expected
    assert all(
        terminal.count(f'"order_id": "{event_id}"') == 1 for event_id in expected
    )

    proc._running = False
    proc._eod_seen = True
    thread.join(timeout=5)
    if proc._flush_timer is not None:
        proc._flush_timer.cancel()
    proc._flush_buffer()
    proc._file.close()
    reopened = AuditFile(tmp_path / "audit.log", 10_000_000, timezone.utc)
    reopened.close()
    assert _audit_order_ids(tmp_path / "audit.log") == expected


def test_publication_before_audit_subscription_is_not_replayed(
    tmp_path: Path,
) -> None:
    pub_port, health_port = free_ports(2)
    pub_addr = f"tcp://127.0.0.1:{pub_port}"
    ctx = zmq.Context()
    pub = ctx.socket(zmq.XPUB)
    pub.setsockopt(zmq.XPUB_VERBOSER, 1)
    pub.bind(pub_addr)
    proc: AuditProcess | None = None
    thread: threading.Thread | None = None
    try:
        pub.send_multipart(
            [
                b"order.new",
                json.dumps(
                    {
                        "order_id": "before-audit-subscription",
                        "symbol": "AAPL",
                        "gateway_id": "GW01",
                    }
                ).encode(),
            ]
        )

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
        thread = threading.Thread(target=proc._receive, daemon=True)
        thread.start()
        _wait_for_subscriptions(pub, {b"\x01"})

        pub.send_multipart(
            [
                b"order.new",
                json.dumps(
                    {
                        "order_id": "after-audit-subscription",
                        "symbol": "AAPL",
                        "gateway_id": "GW01",
                    }
                ).encode(),
            ]
        )
        _wait("pm-audit to receive the subscribed event", lambda: proc._records == 1)
        assert _audit_order_ids(tmp_path / "audit.log") == ["after-audit-subscription"]
    finally:
        if proc is not None:
            proc._eod_seen = True
            proc._running = False
            if thread is not None:
                thread.join(timeout=5)
            if proc._flush_timer is not None:
                proc._flush_timer.cancel()
            proc._flush_buffer()
            if not proc._file._fh.closed:
                proc._file.close()
            proc.sub.close()
            proc.health_rep.close()
        pub.close()
        ctx.term()
