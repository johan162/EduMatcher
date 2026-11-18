"""Tests for LALF-PS — the ZeroMQ log-distribution interface of pm-log-srv.

Covers the four behaviours the interface exists to provide (see
../docs/books/operator-guide/part-6-observe-and-recover/040-log-server.md): asynchronous notification, live streaming,
"last n minutes" backfill, and reaping a subscriber that has died.
"""

from __future__ import annotations

import socket
import sqlite3
import threading
import time
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest
import zmq

from edumatcher.log_srv.config import LogServerConfig
from edumatcher.log_srv.pubsub import (
    LogFilter,
    LogFilterError,
    LogPubSubHub,
    Subscription,
    register_sql_functions,
    row_to_dict,
)
from edumatcher.log_srv.server import LogServer
from edumatcher.log_srv.writer import LogEventRow
from edumatcher.logclient.protocol import PROTO_VERSION, build_header_line, iso_utc
from edumatcher.models.message import (
    decode,
    encode,
    make_log_backfill_request_msg,
    make_log_renew_msg,
    make_log_status_request_msg,
    make_log_subscribe_msg,
    make_log_unsubscribe_msg,
)
from edumatcher.models.generated.log import TOPIC_LOG_SUBSCRIBE
from tests.conftest import free_ports, opened

_HOST = "127.0.0.1"


class _PubSubHarness:
    """A running LogServer plus one LALF producer and one LALF-PS subscriber."""

    def __init__(self, tmp_path: Path, **overrides: Any) -> None:
        self.port, self.pub_port, self.pull_port = free_ports(3)
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
        tpl: str | None = None,
        module: str | None = "mod",
        line: str | None = "1",
    ) -> None:
        assert self.producer is not None
        self._seq += 1
        body = message.encode()
        fields = {
            "SEQ": str(self._seq),
            "TS": iso_utc(time.time()),
            "LEVEL": level,
            "LOGGER": logger,
        }
        if module is not None:
            fields["MODULE"] = module
        if line is not None:
            fields["LINE"] = line
        if tpl is not None:
            fields["TPL"] = tpl
        fields["LEN"] = str(len(body))
        self.producer.sendall(build_header_line("LOG", fields) + body)

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


def _row(**overrides: Any) -> dict[str, Any]:
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
        "tpl": None,
    }
    base.update(overrides)
    return row_to_dict(1, LogEventRow(**base))


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
    assert any("lalf_contains(message, ?)" in c for c in clauses)
    assert "pm-engine" in params and "boom" in params
    # Every placeholder must have exactly one bound parameter — the whole
    # point of building the clause this way rather than interpolating.
    assert sum(c.count("?") for c in clauses) == len(params)


@pytest.mark.parametrize(
    ("payload", "row"),
    [
        # LIKE would read "_" as a wildcard and ignore case.
        ({"loggers": ["edumatcher.log_srv"]}, {"logger": "edumatcher.logXsrv.server"}),
        ({"loggers": ["edumatcher.log_srv"]}, {"logger": "EDUMATCHER.LOG_SRV.server"}),
        ({"loggers": ["edumatcher.log_srv"]}, {"logger": "edumatcher.log_srv.server"}),
        # SQLite's LOWER folds ASCII only; LIKE's % and _ are wildcards.
        ({"contains": "ÅTERKÖP"}, {"message": "återköp avbrutet"}),
        ({"contains": "100%"}, {"message": "fill 100x done"}),
        ({"contains": "a_b"}, {"message": "aXb"}),
    ],
)
def test_backfill_sql_selects_exactly_what_the_live_filter_matches(
    payload: dict[str, Any], row: dict[str, Any]
) -> None:
    filt = LogFilter.from_payload(payload)
    live = _row(**row)
    conn = opened(sqlite3.connect(":memory:"))
    register_sql_functions(conn)
    conn.execute("CREATE TABLE log_events (logger TEXT, message TEXT)")
    conn.execute(
        "INSERT INTO log_events VALUES (?, ?)", (live["logger"], live["message"])
    )
    clauses, params = filt.sql_where()
    sql = "SELECT COUNT(*) FROM log_events WHERE " + " AND ".join(clauses)
    assert bool(conn.execute(sql, params).fetchone()[0]) is filt.matches(live)


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


def test_template_id_reaches_live_and_backfill_rows(harness: _PubSubHarness) -> None:
    harness.send(make_log_subscribe_msg("v1", "STREAM"))
    time.sleep(0.4)
    harness.drain(0.3)

    harness.emit("slow", level="WARNING", tpl="0123456789ab")
    harness.emit("fine")
    time.sleep(0.6)
    live = [r for t, p in harness.drain(0.8) if t == "log.event.v1" for r in p["rows"]]

    harness.send(make_log_backfill_request_msg("v1", minutes=10))
    time.sleep(0.5)
    history = [
        r for t, p in harness.drain(0.8) if t == "log.backfill.v1" for r in p["rows"]
    ]

    expected = [("slow", "0123456789ab"), ("fine", None)]
    assert [(r["message"], r["tpl"]) for r in live] == expected
    assert [(r["message"], r["tpl"]) for r in history] == expected


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
    # `levels` became a list of {level, count} records in Phase 5.2d: it was a
    # map keyed by level name, and the key was a value. The counts it reports
    # are unchanged.
    assert {each["level"] for n in notes for each in n["levels"]} == {"ERROR"}
    assert (
        sum(
            each["count"]
            for n in notes
            for each in n["levels"]
            if each["level"] == "ERROR"
        )
        == 3
    )
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


def test_backfill_and_live_stream_meet_without_overlap(
    harness: _PubSubHarness,
) -> None:
    for i in range(30):
        harness.emit(f"old-{i}")
    time.sleep(0.6)

    # Rows logged while the 10-chunk backfill is still running must arrive
    # once, on the live path — not a second time inside the backfill.
    harness.send(make_log_subscribe_msg("v1", "STREAM", backfill_minutes=10))
    for i in range(5):
        harness.emit(f"new-{i}")
    msgs = harness.drain(1.5)

    acks = [p for t, p in msgs if t == "log.subscribe_ack.v1"]
    chunks = [p for t, p in msgs if t == "log.backfill.v1"]
    live = [r for t, p in msgs if t == "log.event.v1" for r in p["rows"]]
    assert acks and chunks and chunks[-1]["done"] is True
    assert {c["request_id"] for c in chunks} == {acks[0]["backfill_request_id"]}
    backfilled = [r for c in chunks for r in c["rows"]]
    seqs = [r["seq"] for r in backfilled + live]
    assert len(seqs) == len(set(seqs)), "a row was delivered twice"
    assert sorted(r["message"] for r in backfilled + live) == sorted(
        [f"old-{i}" for i in range(30)] + [f"new-{i}" for i in range(5)]
    )


def test_a_superseded_backfill_is_still_terminated(harness: _PubSubHarness) -> None:
    harness.send(make_log_subscribe_msg("v1", "STREAM"))
    time.sleep(0.4)
    for i in range(30):
        harness.emit(f"old-{i}")
    time.sleep(0.6)
    harness.drain(0.5)

    harness.send(make_log_backfill_request_msg("v1", minutes=10))
    harness.send(make_log_backfill_request_msg("v1", minutes=10))
    chunks = [p for t, p in harness.drain(1.5) if t == "log.backfill.v1"]

    by_request: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        by_request.setdefault(chunk["request_id"], []).append(chunk)
    assert len(by_request) == 2
    assert all(c[-1]["done"] is True for c in by_request.values())


def test_inbox_overflow_is_reported_to_every_subscription(tmp_path: Path) -> None:
    hub = LogPubSubHub(
        pub_addr="tcp://127.0.0.1:1",
        pull_addr="tcp://127.0.0.1:2",
        db_path=tmp_path / "log.db",
        server_name="t",
    )
    sub = Subscription(
        sub_id="v1",
        mode="STREAM",
        filt=LogFilter(),
        lease_sec=30.0,
        notify_interval_sec=0.25,
        max_pending_rows=100,
        expires_at=time.monotonic() + 30,
    )
    hub._subs["v1"] = sub
    hub._inbox_dropped = 7
    hub._fan_out_new_rows()
    hub._fan_out_new_rows()
    assert sub.dropped_rows == 7


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
    # The client builder now rejects an invalid mode at construction, so this
    # sends one raw to exercise the server's own defence — a non-Python client
    # (the log-gui) can still put ``SIDEWAYS`` on the wire.
    harness.send(encode(TOPIC_LOG_SUBSCRIBE, {"sub_id": "v1", "mode": "SIDEWAYS"}))
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


# ---------------------------------------------------------------------------
# WP-LOG04: NULL columns go out as null; only what was sent is counted
# ---------------------------------------------------------------------------


def test_null_columns_reach_a_stream_subscriber_as_null(
    harness: _PubSubHarness,
) -> None:
    harness.send(make_log_subscribe_msg("v1", "STREAM"))
    time.sleep(0.4)
    harness.emit("bare", module=None, line=None)  # HELLO carried no INSTANCE
    rows = [r for p in harness.collect("log.event.v1", seconds=1.0) for r in p["rows"]]
    assert len(rows) == 1
    assert rows[0]["instance"] is None
    assert rows[0]["module"] is None
    assert rows[0]["line"] is None


def _emit_mixed(harness: _PubSubHarness) -> None:
    for i in range(300):
        harness.emit(f"row-{i}")
        if i % 100 == 50:
            harness.emit(f"noline-{i}", line=None, module=None)


def test_rows_with_null_line_do_not_lose_their_live_chunk(
    harness: _PubSubHarness,
) -> None:
    harness.send(make_log_subscribe_msg("v1", "STREAM"))
    time.sleep(0.4)
    _emit_mixed(harness)
    rows = [r for p in harness.collect("log.event.v1", seconds=2.5) for r in p["rows"]]
    assert len(rows) == 303


def test_a_backfill_over_null_columns_sends_what_it_counts(
    harness: _PubSubHarness,
) -> None:
    _emit_mixed(harness)
    time.sleep(1.0)
    harness.send(make_log_subscribe_msg("v1", "NOTIFY", backfill_minutes=5))
    chunks = harness.collect("log.backfill.v1", seconds=3.0)
    assert chunks and chunks[-1]["done"] is True
    assert sum(len(c["rows"]) for c in chunks) == 303
    assert chunks[-1]["total_sent"] == 303


class _CapturingHub:
    """A started hub whose publishes are decoded into a list, not sent."""

    def __init__(self, tmp_path: Path, **kwargs: Any) -> None:
        from edumatcher.log_srv.schema import open_db

        open_db(tmp_path / "log.db").close()
        pub_port, pull_port = free_ports(2)
        self.hub = LogPubSubHub(
            pub_addr=f"tcp://127.0.0.1:{pub_port}",
            pull_addr=f"tcp://127.0.0.1:{pull_port}",
            db_path=tmp_path / "log.db",
            server_name="t",
            **kwargs,
        )
        self.hub.start()
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.hub._publish = lambda frames: self.sent.append(decode(frames))

    def subscribe(self, sub_id: str, filt: LogFilter | None = None) -> Subscription:
        sub = Subscription(
            sub_id=sub_id,
            mode="STREAM",
            filt=filt or LogFilter(),
            lease_sec=30.0,
            notify_interval_sec=0.25,
            max_pending_rows=1000,
            expires_at=time.monotonic() + 30,
        )
        sub.last_stream_at = 0.0  # a partial chunk is due at once
        self.hub._subs[sub_id] = sub
        return sub

    def topics(self) -> list[str]:
        return [t for t, _ in self.sent]

    def close(self) -> None:
        self.hub._publish = lambda frames: None
        self.hub.stop()


def _persisted(seq: int, **overrides: Any) -> tuple[int, LogEventRow]:
    row = _row(**overrides)
    row.pop("seq")
    return seq, LogEventRow(**row)


def test_a_row_that_cannot_be_serialised_is_an_internal_error(tmp_path: Path) -> None:
    cap = _CapturingHub(tmp_path)
    try:
        sub = cap.subscribe("v1")
        expired = cap.subscribe("gone")
        expired.expires_at = 0.0
        cap.hub.on_batch_persisted(
            [_persisted(1), _persisted(2, logger="x" * 200), _persisted(3)]
        )
        cap.hub.poll()
        errors = [p for t, p in cap.sent if t == "log.error.v1"]
        assert errors and errors[0]["code"] == "INTERNAL"
        assert sub.sent_rows == 0
        assert sub.dropped_rows == 3
        assert not sub.pending_rows
        # The rest of the pass still ran: reaping and the server state.
        assert "log.lease_expired.gone" in cap.topics()
        assert "log.server_state" in cap.topics()
    finally:
        cap.close()


def test_a_backfill_chunk_that_cannot_be_serialised_ends_the_job(
    tmp_path: Path,
) -> None:
    from edumatcher.log_srv.pubsub import BackfillJob

    conn = sqlite3.connect(str(tmp_path / "log.db"))
    cap = _CapturingHub(tmp_path)
    try:
        for i, logger in enumerate(["ok", "x" * 200, "ok"], start=1):
            conn.execute(
                "INSERT INTO log_events (client_ts, server_ts, process, pid, host, "
                "session, level, logger, has_exception, truncated, message) "
                "VALUES (?, ?, 'p', 1, 'h', 's', 'INFO', ?, 0, 0, ?)",
                (iso_utc(time.time()), iso_utc(time.time()), logger, f"m{i}"),
            )
        conn.commit()
        sub = cap.subscribe("v1")
        cap.hub._backfills["v1"] = BackfillJob(
            sub_id="v1",
            request_id="r1",
            where_sql=" WHERE 1 = 1",
            params=[],
            max_seq=3,
            cursor_seq=0,
        )
        cap.hub.poll()
        errors = [p for t, p in cap.sent if t == "log.error.v1"]
        chunks = [p for t, p in cap.sent if t == "log.backfill.v1"]
        assert errors and errors[0]["code"] == "INTERNAL"
        assert len(chunks) == 1
        assert chunks[0]["rows"] == []
        assert chunks[0]["done"] is True and chunks[0]["truncated"] is True
        assert chunks[0]["total_sent"] == 0
        assert chunks[0]["last_seq"] == 0
        assert sub.sent_rows == 0
        assert not cap.hub._backfills
    finally:
        cap.close()
        conn.close()


def test_resubscribing_with_a_new_filter_counts_buffered_rows_and_ends_the_backfill(
    tmp_path: Path,
) -> None:
    from edumatcher.log_srv.pubsub import BackfillJob

    cap = _CapturingHub(tmp_path)
    try:
        sub = cap.subscribe("v1")
        sub.pending_rows = [_row(), _row()]
        cap.hub._backfills["v1"] = BackfillJob(
            sub_id="v1",
            request_id="r-old",
            where_sql=" WHERE 1 = 1",
            params=[],
            max_seq=10**6,
            cursor_seq=5,
            sent_rows=7,
        )
        cap.hub._handle_subscribe(
            "v1",
            {"mode": "STREAM", "filter": {"min_level": "ERROR"}},
            time.monotonic(),
        )
        new = cap.hub._subs["v1"]
        assert new.dropped_rows == 2
        assert not new.pending_rows
        ends = [
            p
            for t, p in cap.sent
            if t == "log.backfill.v1" and p["request_id"] == "r-old"
        ]
        assert ends and ends[0]["done"] is True and ends[0]["truncated"] is True
        assert "v1" not in cap.hub._backfills
    finally:
        cap.close()


def test_resubscribing_with_the_same_terms_keeps_buffered_rows(
    tmp_path: Path,
) -> None:
    cap = _CapturingHub(tmp_path)
    try:
        sub = cap.subscribe("v1")
        sub.pending_rows = [_row(), _row()]
        cap.hub._handle_subscribe("v1", {"mode": "STREAM"}, time.monotonic())
        new = cap.hub._subs["v1"]
        assert len(new.pending_rows) == 2
        assert new.dropped_rows == 0
    finally:
        cap.close()


# ---------------------------------------------------------------------------
# WP-LOG05: a slow subscriber can see every loss; the PUB queue is bounded
# ---------------------------------------------------------------------------


def _batch(first_seq: int, n: int) -> list[tuple[int, LogEventRow]]:
    return [_persisted(first_seq + i, message=f"m{first_seq + i}") for i in range(n)]


class _LiveHub:
    """A started hub publishing for real, with one registered STREAM sub."""

    def __init__(self, tmp_path: Path, **kwargs: Any) -> None:
        from edumatcher.log_srv.schema import open_db

        open_db(tmp_path / "log.db").close()
        self.pub_port, pull_port = free_ports(2)
        self.hub = LogPubSubHub(
            pub_addr=f"tcp://127.0.0.1:{self.pub_port}",
            pull_addr=f"tcp://127.0.0.1:{pull_port}",
            db_path=tmp_path / "log.db",
            server_name="t",
            **kwargs,
        )
        self.hub.start()
        self.ctx = zmq.Context()
        self.sub = self.ctx.socket(zmq.SUB)
        self.sub.setsockopt(zmq.RCVHWM, 100)
        self.sub.setsockopt(zmq.SUBSCRIBE, b"log.event.v1")
        self.sub.connect(f"tcp://127.0.0.1:{self.pub_port}")
        time.sleep(0.3)
        self.subscription = Subscription(
            sub_id="v1",
            mode="STREAM",
            filt=LogFilter(),
            lease_sec=300.0,
            notify_interval_sec=0.25,
            max_pending_rows=self.hub._max_pending_rows,
            expires_at=time.monotonic() + 300,
        )
        self.hub._subs["v1"] = self.subscription

    def drain(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        idle_since = time.monotonic()
        while time.monotonic() - idle_since < 0.5:
            try:
                out.append(decode(self.sub.recv_multipart(zmq.NOBLOCK))[1])
                idle_since = time.monotonic()
            except zmq.Again:
                time.sleep(0.01)
        return out

    def close(self) -> None:
        self.sub.close(linger=0)
        self.ctx.term()
        self.hub.stop()


def test_a_slow_subscriber_can_account_for_every_lost_row(tmp_path: Path) -> None:
    """C5: msg_no gaps plus `dropped` explain every row not received."""
    live = _LiveHub(tmp_path)
    try:
        committed = 200_000
        for first in range(1, committed + 1, 500):
            live.hub.on_batch_persisted(_batch(first, 500))
            live.hub.poll()
        while live.subscription.pending_rows:
            time.sleep(0.11)
            live.hub.poll()
        msgs = live.drain()
        # Messages lost at the tail show as a gap once the next one arrives.
        live.hub.on_batch_persisted(_batch(committed + 1, 500))
        live.hub.poll()
        committed += 500
        msgs += live.drain()
    finally:
        live.close()

    assert msgs
    msg_nos = [m["msg_no"] for m in msgs]
    assert msg_nos == sorted(msg_nos)
    lost_messages = 0
    for a, b in zip(msgs, msgs[1:]):
        missing = b["seq_from"] - a["seq_to"] - 1
        shed = b["dropped"] - a["dropped"]
        if b["msg_no"] == a["msg_no"] + 1:
            assert missing == shed, (a["msg_no"], b["msg_no"])
        else:
            lost_messages += b["msg_no"] - a["msg_no"] - 1
            assert missing > shed
    received = sum(m["row_count"] for m in msgs)
    assert received < committed
    assert lost_messages > 0


def test_a_fast_subscriber_sees_consecutive_msg_no_and_no_drops(
    tmp_path: Path,
) -> None:
    live = _LiveHub(tmp_path)
    try:
        for first in range(1, 2001, 100):
            live.hub.on_batch_persisted(_batch(first, 100))
            live.hub.poll()
            time.sleep(0.12)
            live.hub.poll()
        msgs = live.drain()
    finally:
        live.close()
    assert [m["msg_no"] for m in msgs] == list(range(1, len(msgs) + 1))
    assert sum(m["row_count"] for m in msgs) == 2000
    assert all(m["dropped"] == 0 for m in msgs)


def test_backfill_chunks_share_the_subscription_msg_no(harness: _PubSubHarness) -> None:
    for i in range(7):
        harness.emit(f"old-{i}")
    time.sleep(0.6)
    harness.send(make_log_subscribe_msg("v1", "STREAM", backfill_minutes=5))
    time.sleep(0.4)
    harness.emit("live-1")
    msgs = [
        p for t, p in harness.drain(1.5) if t in ("log.backfill.v1", "log.event.v1")
    ]
    assert [p["msg_no"] for p in msgs] == list(range(1, len(msgs) + 1))


def test_the_pub_queue_is_bounded_in_rows(tmp_path: Path) -> None:
    """P1: SNDHWM = max_pending_rows / backfill_chunk_rows, capped by pub_sndhwm."""
    live = _LiveHub(tmp_path, max_pending_rows=2000, backfill_chunk_rows=100)
    try:
        assert live.hub._pub is not None
        assert live.hub._pub.getsockopt(zmq.SNDHWM) == 20
    finally:
        live.close()
    capped = _LiveHub(tmp_path / "c", pub_sndhwm=5)
    try:
        assert capped.hub._pub is not None
        assert capped.hub._pub.getsockopt(zmq.SNDHWM) == 5
    finally:
        capped.close()


_RSS_CHILD = """
import gc, sys, time
from pathlib import Path
from edumatcher.log_srv.pubsub import LogFilter, LogPubSubHub, Subscription
from edumatcher.log_srv.schema import open_db
from edumatcher.log_srv.writer import LogEventRow

def rss_mb():
    status = Path("/proc/self/status")
    if status.exists():  # Linux: current RSS in kB
        for line in status.read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
        raise RuntimeError("no VmRSS")
    import subprocess, os  # macOS/BSD: no /proc; ask ps (RSS in kB)
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())],
                         capture_output=True, text=True, check=True).stdout
    return int(out.strip()) / 1024

db, pub_port, pull_port, rows_total = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
open_db(Path(db)).close()
hub = LogPubSubHub(pub_addr="tcp://127.0.0.1:" + pub_port,
                   pull_addr="tcp://127.0.0.1:" + pull_port,
                   db_path=Path(db), server_name="t")
hub.start()
print("ready", flush=True)
sys.stdin.readline()
hub._subs["v1"] = Subscription(sub_id="v1", mode="STREAM", filt=LogFilter(),
    lease_sec=999.0, notify_interval_sec=0.25,
    max_pending_rows=hub._max_pending_rows, expires_at=time.monotonic() + 999)
row = LogEventRow(client_ts="2026-11-10T10:00:00.000Z",
    server_ts="2026-11-10T10:00:00.001Z", process="pm-engine", instance=None,
    pid=1, host="h", session="abcd1234", level="INFO",
    logger="edumatcher.engine.book", module="book", line=10,
    has_exception=False, truncated=False, message="order accepted " + "x" * 60,
    tpl=None)
gc.collect()
base = rss_mb()
for first in range(1, rows_total + 1, 500):
    hub.on_batch_persisted([(first + i, row) for i in range(500)])
    hub.poll()
time.sleep(1.0)
gc.collect()
print(round(rss_mb() - base, 1), flush=True)
hub.stop()
"""


def test_a_wedged_subscriber_does_not_grow_the_server(tmp_path: Path) -> None:
    """P1: measured 2026-11-16, defaults, a SUB that never reads: +5 MB flat
    from 100 000 to 1 000 000 rows (before: +15 MB at 100 000, +163 MB at
    500 000). 300 000 rows here; the bound leaves room for allocator noise."""
    import subprocess
    import sys

    pub_port, pull_port = free_ports(2)
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _RSS_CHILD,
            str(tmp_path / "log.db"),
            str(pub_port),
            str(pull_port),
            "300000",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert child.stdin is not None and child.stdout is not None
    ctx = zmq.Context()
    sub = ctx.socket(zmq.SUB)
    try:
        assert child.stdout.readline().strip() == "ready"
        sub.setsockopt(zmq.RCVHWM, 100)
        sub.setsockopt(zmq.SUBSCRIBE, b"log.event.v1")
        sub.connect(f"tcp://127.0.0.1:{pub_port}")
        time.sleep(0.5)
        child.stdin.write("go\n")
        child.stdin.flush()
        growth_mb = float(child.stdout.readline())
        child.wait(timeout=60)
    finally:
        sub.close(linger=0)
        ctx.term()
        if child.poll() is None:
            child.kill()
    assert growth_mb < 30.0


def test_backfill_start_uses_the_client_ts_index(tmp_path: Path) -> None:
    """P2: the first-seq lookup must not walk the primary key from the oldest row."""
    cap = _CapturingHub(tmp_path)
    try:
        assert cap.hub._read_conn is not None
        statements: list[str] = []
        cap.hub._read_conn.set_trace_callback(statements.append)
        cap.hub._first_seq_at_or_after("2026-11-16T00:00:00.000Z")
        cap.hub._read_conn.set_trace_callback(None)
        (sql,) = [s for s in statements if "MIN(seq)" in s]
        plan = " | ".join(
            str(row[3])
            for row in cap.hub._read_conn.execute(f"EXPLAIN QUERY PLAN {sql}")
        )
    finally:
        cap.close()
    assert "idx_le_client_ts" in plan, plan


def _server_states(tmp_path: Path) -> list[dict[str, Any]]:
    h = _PubSubHarness(tmp_path, heartbeat_interval_sec=1)
    h.start()
    try:
        return [p for t, p in h.drain(1.5) if t == "log.server_state"]
    finally:
        h.stop()


def test_server_state_names_the_server_instance(tmp_path: Path) -> None:
    """For-Later L038, WP-FL13 (Q9): a subscriber recognises a restarted
    server by a random id that is new at every start (``last_seq`` continues
    across restarts, so it cannot tell)."""
    first = _server_states(tmp_path)
    second = _server_states(tmp_path)  # same log.db
    assert first and second
    ids_first = {p["instance_id"] for p in first}
    ids_second = {p["instance_id"] for p in second}
    assert len(ids_first) == 1 and len(ids_second) == 1
    assert ids_first != ids_second
    assert all(len(i) >= 16 for i in ids_first | ids_second)


def test_the_generated_server_state_requires_the_instance_id() -> None:
    from edumatcher.models.generated import log as gen_log

    assert "instance_id" in {f.name for f in fields(gen_log.LogServerState)}
