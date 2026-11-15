"""Gateway-local refusals reach the audit trail without being able to flood it (A3)."""

from __future__ import annotations

from typing import Any

import pytest
import zmq

from edumatcher.messaging.reject_report import RejectReporter
from edumatcher.models.message import decode


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def make(clock: Clock) -> tuple[RejectReporter, list[list[bytes]]]:
    sent: list[list[bytes]] = []
    return RejectReporter("ALF", sent.append, clock=clock), sent


def payload(frames: list[bytes]) -> dict[str, Any]:
    topic, body = decode(frames)
    assert topic == "system.gateway_reject"
    return body


class TestReport:
    def test_a_refusal_becomes_one_message(self) -> None:
        reporter, sent = make(Clock())
        reporter.report("RATE_LIMITED", "GW01", "10.0.0.5:4411", "Too many commands")
        assert len(sent) == 1
        body = payload(sent[0])
        assert body["source"] == "ALF"
        assert body["gateway_id"] == "GW01"
        assert body["peer"] == "10.0.0.5:4411"
        assert body["reject_code"] == "RATE_LIMITED"
        assert body["count"] == 1
        assert body["ts_ns"] > 0

    def test_a_repeat_inside_the_interval_is_folded_into_the_next_record(self) -> None:
        clock = Clock()
        reporter, sent = make(clock)
        for _ in range(5):
            reporter.report("RATE_LIMITED", "GW01", "p:1", "x")
        assert len(sent) == 1
        clock.now += 1.5
        reporter.report("RATE_LIMITED", "GW01", "p:1", "x")
        assert len(sent) == 2
        assert payload(sent[1])["count"] == 5  # itself plus four folded in

    def test_peer_and_code_are_throttled_separately(self) -> None:
        reporter, sent = make(Clock())
        reporter.report("RATE_LIMITED", "GW01", "p:1", "x")
        reporter.report("RATE_LIMITED", "GW02", "q:1", "x")
        reporter.report("AUTH_FAILED", "GW01", "p:1", "x")
        assert len(sent) == 3

    def test_new_connections_from_one_host_are_folded_together(self) -> None:
        """A REST client opens a connection per request, each from another
        source port: keyed by host:port, every refusal was its own record."""
        clock = Clock()
        reporter, sent = make(clock)
        for port in range(4000, 4010):
            reporter.report("AUTH_REQUIRED", "", f"10.0.0.5:{port}", "x")
        assert len(sent) == 1
        clock.now += 1.5
        reporter.report("AUTH_REQUIRED", "", "10.0.0.5:4999", "x")
        assert len(sent) == 2
        body = payload(sent[1])
        assert body["count"] == 10
        assert body["peer"] == "10.0.0.5:4999"

    def test_an_ipv6_peer_is_keyed_by_its_address(self) -> None:
        reporter, sent = make(Clock())
        reporter.report("AUTH_REQUIRED", "", "::1:4000", "x")
        reporter.report("AUTH_REQUIRED", "", "::1:4001", "x")
        reporter.report("AUTH_REQUIRED", "", "::2:4000", "x")
        assert len(sent) == 2

    def test_long_fields_are_clipped_not_rejected(self) -> None:
        reporter, sent = make(Clock())
        reporter.report("AUTH_FAILED", "G" * 80, "p" * 200, "r" * 900)
        body = payload(sent[0])
        assert (len(body["gateway_id"]), len(body["peer"]), len(body["reason"])) == (
            32,
            64,
            256,
        )

    def test_a_send_failure_never_escapes(self) -> None:
        def boom(_frames: list[bytes]) -> None:
            raise RuntimeError("engine is gone")

        RejectReporter("REST", boom).report("ROLE_DENIED", "GW01", "p:1", "x")

    def test_the_throttle_table_stays_bounded(self) -> None:
        reporter, sent = make(Clock())
        for n in range(10_000):
            reporter.report("AUTH_FAILED", "", f"h{n}:1", "x")
        assert len(sent) == 10_000
        assert reporter.tracked <= 4096

    def test_an_unreportable_code_is_ignored(self) -> None:
        reporter, sent = make(Clock())
        reporter.report("INVALID_VALUE", "GW01", "p:1", "x")
        assert sent == []


class TestCountsAreNeverDropped:
    """Messaging review 2026-11, C1 and C2: the records' ``count`` values add
    up to the refusals the gateway made, except the documented tail of a
    burst nobody follows up."""

    @staticmethod
    def total(sent: list[list[bytes]]) -> int:
        return sum(payload(f)["count"] for f in sent)

    def test_a_full_table_sends_what_it_folded_before_forgetting_it(self) -> None:
        clock = Clock()
        reporter, sent = make(clock)
        for _ in range(50):
            reporter.report("AUTH_FAILED", "", "10.0.0.1:1000", "bad key")
        for n in range(4096):
            reporter.report(
                "AUTH_FAILED", "", f"10.1.{n // 256}.{n % 256}:1", "bad key"
            )
        clock.now += 5
        reporter.report("AUTH_FAILED", "", "10.0.0.1:1001", "bad key")
        assert self.total(sent) == 50 + 4096 + 1
        assert reporter.tracked <= 4096

    def test_a_flushed_record_names_the_last_refusal_it_folded(self) -> None:
        reporter, sent = make(Clock())
        reporter.report("RATE_LIMITED", "GW01", "10.0.0.1:1", "first")
        reporter.report("RATE_LIMITED", "GW01", "10.0.0.1:2", "second")
        for n in range(4096):
            reporter.report("AUTH_FAILED", "", f"h{n}:1", "x")
        flushed = [b for b in map(payload, sent) if b["reason"] == "second"]
        assert [(b["peer"], b["count"]) for b in flushed] == [("10.0.0.1:2", 1)]

    def test_refusals_made_while_the_engine_is_away_are_counted_later(self) -> None:
        clock = Clock()
        sent: list[list[bytes]] = []
        attempts = [0]
        up = [False]

        def send(frames: list[bytes]) -> None:
            attempts[0] += 1
            if not up[0]:
                raise zmq.Again()
            sent.append(frames)

        reporter = RejectReporter("ALF", send, clock=clock)
        start = clock.now
        for k in range(10):  # 10 s of 100 refusals a second
            for j in range(100):
                clock.now = start + k + j / 100
                reporter.report("RATE_LIMITED", "GW1", "10.0.0.2:5", "rate")
        up[0] = True
        clock.now = start + 10.5
        reporter.report("RATE_LIMITED", "GW1", "10.0.0.2:5", "rate")
        assert self.total(sent) == 1001
        # Failed sends are throttled like successful ones: one try a second.
        assert attempts[0] <= 12

    def test_a_flush_with_the_engine_away_warns_once(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def send(_frames: list[bytes]) -> None:
            raise zmq.Again()

        reporter = RejectReporter("REST", send, clock=Clock())
        for n in range(4096):
            reporter.report("AUTH_FAILED", "", f"h{n}:1", "x")
            reporter.report("AUTH_FAILED", "", f"h{n}:2", "x")
        caplog.clear()
        reporter.report("AUTH_FAILED", "", "new:1", "x")
        flush = [r for r in caplog.records if "folded refusals" in r.getMessage()]
        assert len(flush) == 1 and "8192" in flush[0].getMessage()
        assert reporter.tracked == 1
