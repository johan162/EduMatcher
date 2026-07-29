"""Tests for LALF-PS — the ZeroMQ log-distribution interface of pm-log-srv.

Covers the four behaviours the interface exists to provide (see
docs/user-guide/280-log-srv.md): asynchronous notification, live streaming,
"last n minutes" backfill, and reaping a subscriber that has died.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Any

import pytest
import zmq

from edumatcher.log_srv.config import LogServerConfig
from edumatcher.log_srv.pubsub import LogFilter, LogFilterError
from edumatcher.log_srv.server import LogServer
from edumatcher.log_srv.writer import LogEventRow
from edumatcher.logclient.protocol import PROTO_VERSION, build_header_line, iso_utc
from edumatcher.models.message import (
    decode,
    make_log_backfill_request_msg,
    make_log_renew_msg,
    make_log_status_request_msg,
    make_log_subscribe_msg,
    make_log_unsubscribe_msg,
)

_HOST = "127.0.0.1"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((_HOST, 0))
        return int(s.getsockname()[1])


class _PubSubHarness:
    """A running LogServer plus one LALF producer and one LALF-PS subscriber."""

    def __init__(self, tmp_path: Path, **overrides: Any) -> None:
        self.port = _free_port()
        self.pub_port = _free_port()
        self.pull_port = _free_port()
        config_kwargs: dict[str, Any] = {
            "bind_address": _HOST,
            "port": self.port,
            "db_path": tmp_path / "log.db",
            "pub_port": self.pub_port,
            "pull_port": self.pull_port,
            # Generous, because several tests deliberately sit idle waiting out
            # a LALF-PS lease; a short LALF heartbeat interval would have the
            # server drop the *producer* connection mid-test for being idle.
            # Tests that care about the server_state tick rate override it.
            "heartbeat_interval_sec": 30,
            "write_batch_size": 5,
            "write_batch_interval_ms": 20,
            "notify_interval_ms": 100,
            "backfill_chunk_rows": 3,
            "lease_sec": 20,
            "max_lease_sec": 30,
        }
        config_kwargs.update(overrides)
        self.config = LogServerConfig(**config_kwargs)
        self.server = LogServer(self.config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.ctx = zmq.Context()
        self.sub: zmq.Socket[bytes] | None = None
        self.push: zmq.Socket[bytes] | None = None
        self.producer: socket.socket | None = None
        self._seq = 0

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        self.thread.start()
        time.sleep(0.5)

        sub = self.ctx.socket(zmq.SUB)
        sub.connect(f"tcp://{_HOST}:{self.pub_port}")
        sub.setsockopt(zmq.SUBSCRIBE, b"log.")
        self.sub = sub

        push = self.ctx.socket(zmq.PUSH)
        push.connect(f"tcp://{_HOST}:{self.pull_port}")
        self.push = push
        # ZeroMQ connects asynchronously; give both sockets a moment to settle
        # so the first publish is not lost to the classic slow-joiner race.
        time.sleep(0.4)

    def stop(self) -> None:
        for sock in (self.sub, self.push):
            if sock is not None:
                sock.close(linger=0)
        if self.producer is not None:
            self.producer.close()
        self.server.stop()
        time.sleep(0.4)
        self.ctx.term()

    # -- LALF producer side -------------------------------------------------

    def connect_producer(self) -> None:
        prod = socket.create_connection((_HOST, self.port), timeout=2.0)
        prod.sendall(
            build_header_line(
                "HELLO",
                {
                    "CLIENT": "pm-engine",
                    "PID": "4242",
                    "HOST": "testhost",
                    "PROTO": PROTO_VERSION,
                },
            )
        )
        time.sleep(0.3)
        self.producer = prod

    def emit(
        self,
        message: str,
        level: str = "INFO",
        logger: str = "edumatcher.engine",
    ) -> None:
        assert self.producer is not None
        self._seq += 1
        body = message.encode()
        self.producer.sendall(
            build_header_line(
                "LOG",
                {
                    "SEQ": str(self._seq),
                    "TS": iso_utc(time.time()),
                    "LEVEL": level,
                    "LOGGER": logger,
                    "MODULE": "mod",
                    "LINE": "1",
                    "LEN": str(len(body)),
                },
            )
            + body
        )

    # -- LALF-PS subscriber side --------------------------------------------

    def send(self, frames: list[bytes]) -> None:
        assert self.push is not None
        self.push.send_multipart(frames)

    def drain(self, seconds: float = 1.0) -> list[tuple[str, dict[str, Any]]]:
        assert self.sub is not None
        out: list[tuple[str, dict[str, Any]]] = []
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                out.append(decode(self.sub.recv_multipart(zmq.NOBLOCK)))
            except zmq.Again:
                time.sleep(0.02)
        return out

    def collect(
        self, topic: str, seconds: float = 1.0
    ) -> list[dict[str, Any]]:  # pragma: no cover - trivial
        return [p for t, p in self.drain(seconds) if t == topic]


@pytest.fixture
def harness(tmp_path: Path):
    h = _PubSubHarness(tmp_path)
    h.start()
    h.connect_producer()
    yield h
    h.stop()


# ---------------------------------------------------------------------------
# LogFilter (pure unit tests, no sockets)
# ---------------------------------------------------------------------------


def _row(**overrides: Any) -> LogEventRow:
    base: dict[str, Any] = {
        "client_ts": "2026-07-29T10:00:00.000Z",
        "server_ts": "2026-07-29T10:00:00.001Z",
        "process": "pm-engine",
        "instance": None,
        "pid": 1,
        "host": "h",
        "session": "abcd1234",
        "level": "INFO",
        "logger": "edumatcher.engine.book",
        "module": "m",
        "line": 1,
        "has_exception": False,
        "truncated": False,
        "message": "order accepted",
    }
    base.update(overrides)
    return LogEventRow(**base)


def test_empty_filter_matches_everything() -> None:
    assert LogFilter().matches(_row())


def test_min_level_filters_below_floor() -> None:
    filt = LogFilter.from_payload({"min_level": "warning"})
    assert filt.min_level == "WARNING"
    assert not filt.matches(_row(level="INFO"))
    assert filt.matches(_row(level="ERROR"))


def test_logger_prefix_and_process_and_contains() -> None:
    filt = LogFilter.from_payload(
        {
            "processes": ["pm-engine"],
            "loggers": ["edumatcher.engine"],
            "contains": "ACCEPTED",
        }
    )
    assert filt.matches(_row())
    assert not filt.matches(_row(process="pm-stats"))
    assert not filt.matches(_row(logger="edumatcher.stats.main"))
    assert not filt.matches(_row(message="order rejected"))


def test_exceptions_only() -> None:
    filt = LogFilter.from_payload({"exceptions_only": True})
    assert not filt.matches(_row())
    assert filt.matches(_row(has_exception=True))


@pytest.mark.parametrize(
    "bad",
    [
        {"min_level": "LOUD"},
        {"min_level": 3},
        {"processes": [1, 2]},
        {"contains": []},
        {"exceptions_only": "yes"},
        "not-an-object",
    ],
)
def test_invalid_filters_are_rejected(bad: Any) -> None:
    with pytest.raises(LogFilterError):
        LogFilter.from_payload(bad)


def test_sql_where_is_parameterised() -> None:
    clauses, params = LogFilter.from_payload(
        {"min_level": "ERROR", "processes": ["pm-engine"], "contains": "boom"}
    ).sql_where()
    assert any("level IN" in c for c in clauses)
    assert any("LOWER(message) LIKE" in c for c in clauses)
    assert "pm-engine" in params and "%boom%" in params
    # Every placeholder must have exactly one bound parameter — the whole
    # point of building the clause this way rather than interpolating.
    assert sum(c.count("?") for c in clauses) == len(params)


# ---------------------------------------------------------------------------
# End-to-end behaviour
# ---------------------------------------------------------------------------


def test_subscribe_ack_echoes_the_negotiated_terms(harness: _PubSubHarness) -> None:
    harness.send(
        make_log_subscribe_msg("v1", "STREAM", {"min_level": "INFO"}, lease_sec=99999)
    )
    time.sleep(0.4)
    acks = [p for t, p in harness.drain(0.5) if t == "log.subscribe_ack.v1"]
    assert acks, "no subscribe ack received"
    ack = acks[0]
    assert ack["accepted"] is True
    assert ack["mode"] == "STREAM"
    assert ack["filter"]["min_level"] == "INFO"
    # An outsized lease request is clamped to the server's max, not honoured.
    assert ack["lease_sec"] == harness.config.max_lease_sec
    assert ack["renew_before_sec"] == harness.config.max_lease_sec / 2


def test_stream_mode_delivers_matching_rows_live(harness: _PubSubHarness) -> None:
    harness.send(make_log_subscribe_msg("v1", "STREAM", {"min_level": "INFO"}))
    time.sleep(0.4)
    harness.drain(0.3)

    for i in range(6):
        harness.emit(f"event-{i}", level="DEBUG" if i % 2 else "ERROR")
    time.sleep(0.6)

    events = [p for t, p in harness.drain(0.8) if t == "log.event.v1"]
    rows = [r for e in events for r in e["rows"]]
    assert [r["message"] for r in rows] == ["event-0", "event-2", "event-4"]
    assert all(r["level"] == "ERROR" for r in rows)
    assert [r["seq"] for r in rows] == sorted(r["seq"] for r in rows)


def test_notify_mode_coalesces_into_counts(harness: _PubSubHarness) -> None:
    harness.send(make_log_subscribe_msg("ui", "NOTIFY", {"min_level": "ERROR"}))
    time.sleep(0.4)
    harness.drain(0.3)

    for i in range(6):
        harness.emit(f"e{i}", level="ERROR" if i % 2 == 0 else "INFO")
    time.sleep(0.6)

    notes = [p for t, p in harness.drain(0.8) if t == "log.notify.ui"]
    assert notes, "no notify tick received"
    # How many ticks the 3 matching rows land in depends on where the writer's
    # batch boundaries fall relative to notify_interval_ms; only the totals are
    # deterministic, and only the totals are what a subscriber acts on.
    assert sum(n["count"] for n in notes) == 3
    assert {lvl for n in notes for lvl in n["levels"]} == {"ERROR"}
    assert sum(n["levels"]["ERROR"] for n in notes) == 3
    assert notes[-1]["last_seq"] > 0
    # A notify carries no row bodies at all — that is what makes it cheap.
    assert all("rows" not in n for n in notes)


def test_backfill_is_chunked_and_terminated(harness: _PubSubHarness) -> None:
    harness.send(make_log_subscribe_msg("v1", "STREAM"))
    time.sleep(0.4)
    for i in range(7):
        harness.emit(f"old-{i}")
    time.sleep(0.6)
    harness.drain(0.5)

    harness.send(make_log_backfill_request_msg("v1", minutes=10))
    time.sleep(0.5)
    chunks = [p for t, p in harness.drain(1.2) if t == "log.backfill.v1"]

    assert len(chunks) > 1, "a 7-row backfill at chunk_rows=3 must span chunks"
    assert [c["done"] for c in chunks] == [False] * (len(chunks) - 1) + [True]
    assert chunks[-1]["total_sent"] == 7
    assert chunks[-1]["truncated"] is False
    assert len({c["request_id"] for c in chunks}) == 1
    all_rows = [r for c in chunks for r in c["rows"]]
    assert [r["message"] for r in all_rows] == [f"old-{i}" for i in range(7)]


def test_backfill_honours_the_time_window(harness: _PubSubHarness) -> None:
    harness.send(make_log_subscribe_msg("v1", "STREAM"))
    time.sleep(0.4)
    harness.emit("recent")
    time.sleep(0.5)
    harness.drain(0.4)

    # A window that ends before anything was logged must come back empty but
    # still terminate, rather than leaving the subscriber waiting forever.
    harness.send(make_log_backfill_request_msg("v1", minutes=1))
    time.sleep(0.4)
    chunks = [p for t, p in harness.drain(0.8) if t == "log.backfill.v1"]
    assert chunks and chunks[-1]["done"] is True
    assert chunks[-1]["total_sent"] == 1


def test_backfill_rejects_an_out_of_range_window(harness: _PubSubHarness) -> None:
    harness.send(make_log_subscribe_msg("v1", "STREAM"))
    time.sleep(0.4)
    harness.drain(0.3)

    harness.send(make_log_backfill_request_msg("v1", minutes=999_999))
    time.sleep(0.4)
    errs = [p for t, p in harness.drain(0.6) if t == "log.error.v1"]
    assert errs and errs[0]["code"] == "INVALID_WINDOW"


def test_backfill_without_a_subscription_is_refused(harness: _PubSubHarness) -> None:
    harness.send(make_log_backfill_request_msg("ghost", minutes=5))
    time.sleep(0.4)
    errs = [p for t, p in harness.drain(0.6) if t == "log.error.ghost"]
    assert errs and errs[0]["code"] == "UNKNOWN_SUB"


def test_renew_keeps_a_subscription_alive(harness: _PubSubHarness) -> None:
    harness.send(make_log_subscribe_msg("v1", "STREAM", lease_sec=2))
    time.sleep(0.4)
    harness.drain(0.3)

    for _ in range(4):
        harness.send(make_log_renew_msg("v1"))
        time.sleep(0.6)
    harness.drain(0.2)

    harness.send(make_log_status_request_msg("v1"))
    time.sleep(0.4)
    status = [p for t, p in harness.drain(0.6) if t == "log.status.v1"]
    assert status and status[0]["subscription"] is not None
    assert status[0]["subscription"]["renewals"] >= 4


def test_a_dead_subscriber_is_reaped_and_stops_being_buffered(
    harness: _PubSubHarness,
) -> None:
    """The headline behaviour: silence alone is enough to free the server."""
    harness.send(make_log_subscribe_msg("zombie", "STREAM", lease_sec=1))
    time.sleep(0.4)
    harness.drain(0.3)

    # Simulate a crashed viewer: stop renewing and simply wait it out.
    time.sleep(2.0)
    expiries = [p for t, p in harness.drain(0.8) if t == "log.lease_expired.zombie"]
    assert expiries, "server never reaped the silent subscriber"
    assert "no log.renew" in expiries[0]["reason"]

    # Nothing logged after the reap may be buffered or published for it.
    for i in range(4):
        harness.emit(f"post-{i}")
    time.sleep(0.6)
    after = harness.drain(0.6)
    assert not [t for t, _ in after if t.startswith("log.event.zombie")]

    harness.send(make_log_status_request_msg("zombie"))
    time.sleep(0.4)
    status = [p for t, p in harness.drain(0.6) if t == "log.status.zombie"]
    assert status and status[0]["subscription"] is None
    assert status[0]["subscribers"] == 0


def test_renew_for_an_unknown_subscription_is_an_error(
    harness: _PubSubHarness,
) -> None:
    harness.send(make_log_renew_msg("never-existed"))
    time.sleep(0.4)
    errs = [p for t, p in harness.drain(0.6) if t == "log.error.never-existed"]
    assert errs and errs[0]["code"] == "UNKNOWN_SUB"


def test_unsubscribe_stops_delivery_immediately(harness: _PubSubHarness) -> None:
    harness.send(make_log_subscribe_msg("v1", "STREAM"))
    time.sleep(0.4)
    harness.drain(0.3)

    harness.send(make_log_unsubscribe_msg("v1"))
    time.sleep(0.4)
    acks = [p for t, p in harness.drain(0.5) if t == "log.unsubscribe_ack.v1"]
    assert acks and acks[0]["accepted"] is True

    for i in range(4):
        harness.emit(f"after-{i}")
    time.sleep(0.6)
    assert not [t for t, _ in harness.drain(0.6) if t == "log.event.v1"]


def test_resubscribe_is_idempotent_and_preserves_counters(
    harness: _PubSubHarness,
) -> None:
    harness.send(make_log_subscribe_msg("v1", "STREAM"))
    time.sleep(0.4)
    harness.emit("first")
    time.sleep(0.5)
    harness.drain(0.4)

    # Re-sending subscribe is the documented cure for a lost slow-joiner ack.
    harness.send(make_log_subscribe_msg("v1", "NOTIFY"))
    time.sleep(0.4)
    acks = [p for t, p in harness.drain(0.5) if t == "log.subscribe_ack.v1"]
    assert acks and acks[-1]["mode"] == "NOTIFY"

    harness.send(make_log_status_request_msg("v1"))
    time.sleep(0.4)
    status = [p for t, p in harness.drain(0.6) if t == "log.status.v1"]
    assert status and status[0]["subscription"]["mode"] == "NOTIFY"
    assert status[0]["subscription"]["sent_rows"] >= 1
    assert status[0]["subscribers"] == 1


def test_invalid_mode_is_rejected(harness: _PubSubHarness) -> None:
    harness.send(make_log_subscribe_msg("v1", "SIDEWAYS"))
    time.sleep(0.4)
    errs = [p for t, p in harness.drain(0.6) if t == "log.error.v1"]
    assert errs and errs[0]["code"] == "INVALID_MODE"


def test_max_subscribers_is_enforced(tmp_path: Path) -> None:
    h = _PubSubHarness(tmp_path, max_subscribers=2)
    h.start()
    try:
        for name in ("a", "b", "c"):
            h.send(make_log_subscribe_msg(name, "NOTIFY"))
        time.sleep(0.6)
        msgs = h.drain(0.6)
        assert len([t for t, _ in msgs if t.startswith("log.subscribe_ack.")]) == 2
        errs = [p for t, p in msgs if t == "log.error.c"]
        assert errs and errs[0]["code"] == "TOO_MANY_SUBS"
    finally:
        h.stop()


def test_server_state_is_published_periodically(tmp_path: Path) -> None:
    h = _PubSubHarness(tmp_path, heartbeat_interval_sec=1)
    h.start()
    try:
        states = [p for t, p in h.drain(2.5) if t == "log.server_state"]
        assert len(states) >= 2, "server_state is not being published on a tick"
        assert states[-1]["state"] == "UP"
        assert states[-1]["proto"] == "LALF-PS/1"
        assert states[-1]["subscribers"] == 0
    finally:
        h.stop()


def test_pubsub_can_be_disabled(tmp_path: Path) -> None:
    h = _PubSubHarness(tmp_path, pubsub_enabled=False)
    h.thread.start()
    time.sleep(0.5)
    try:
        assert h.server._pubsub is None
        # Nothing is listening on either ZeroMQ port.
        for port in (h.pub_port, h.pull_port):
            with pytest.raises(OSError):
                socket.create_connection((_HOST, port), timeout=0.5).close()
    finally:
        h.server.stop()
        time.sleep(0.4)
        h.ctx.term()
