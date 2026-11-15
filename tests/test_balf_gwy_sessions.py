"""pm-balf-gwy session behaviour against a real engine (BALF review 2026-11).

Every test runs a real ``Engine`` and a real ``BalfGateway`` joined by
``tests/balf_harness.py``; what the client receives is decided by payloads
the engine really published.
"""

from __future__ import annotations

import socket
import time
from collections import deque
from collections.abc import Generator
from typing import Any

import pytest
import zmq

from edumatcher.balf_gwy import codec as C
from edumatcher.balf_gwy.config import BalfGatewayConfig
from edumatcher.balf_gwy.gateway import BalfGateway, ClientSession
from edumatcher.engine.config_loader import SymbolConfig
from edumatcher.engine.order_limits import OrderLimitsConfig
from edumatcher.models.generated.order import parse_execution_report_balf
from edumatcher.models.generated.system import TOPIC_STARTUP_RECOVERY
from edumatcher.models.message import decode, encode
from edumatcher.models.order import OrderType, Side
from tests.balf_harness import (
    BalfBridge,
    amend_ack,
    amend_frame,
    cancel_ack,
    cancel_frame,
    heartbeat_frame,
    logon_frame,
    new_order_frame,
    of_type,
    order_ack,
    read_wire,
    take,
)
from tests.engine_harness import connect, order_payload


@pytest.fixture()
def bridge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> Generator[BalfBridge, None, None]:
    b = BalfBridge(monkeypatch, tmp_path)
    yield b
    b.close()


def _make(monkeypatch: pytest.MonkeyPatch, tmp_path: Any, **cfg: Any) -> BalfBridge:
    return BalfBridge(monkeypatch, tmp_path, config=BalfGatewayConfig(**cfg))


# ===========================================================================
# WP-BALF01 — a resting order stays the client's after a reconnect (H1)
# ===========================================================================


def _rest_sell(b: BalfBridge, gw_id: str = "GW01") -> tuple[Any, int]:
    """Log ``gw_id`` on and rest SELL 100 AAPL @ 100.00; return (session, id)."""
    s = b.logon(gw_id)
    b.send(s, new_order_frame(11, side=C.SIDE_SELL, price=100.0))
    ack = order_ack(of_type(take(s), C.MSG_ORDER_ACK)[0])
    assert ack["accepted"] == 1
    return s, ack["order_id"]


class TestOrdersOutliveTheSession:
    def test_fill_of_an_earlier_sessions_order_reaches_the_new_session(
        self, bridge: BalfBridge
    ) -> None:
        s1, oid = _rest_sell(bridge)
        bridge.logout(s1)
        s1b = bridge.logon("GW01")
        buyer = bridge.logon("GW02")
        bridge.send(buyer, new_order_frame(21, side=C.SIDE_BUY, price=100.0))

        reports = of_type(take(s1b), C.MSG_EXECUTION_REPORT)
        assert len(reports) == 1
        er = parse_execution_report_balf(reports[0])
        assert (er.order_id, er.client_order_id, er.status) == (oid, 11, "FILLED")

    def test_new_session_can_cancel_an_earlier_sessions_order(
        self, bridge: BalfBridge
    ) -> None:
        s1, oid = _rest_sell(bridge)
        bridge.logout(s1)
        s1b = bridge.logon("GW01")
        bridge.send(s1b, cancel_frame(99, oid))

        acks = [cancel_ack(f) for f in of_type(take(s1b), C.MSG_CANCEL_ACK)]
        assert acks == [
            {"client_order_id": 99, "order_id": oid, "accepted": 1, "cancel_reason": 0}
        ]
        assert not bridge.engine.books["AAPL"].resting_orders()

    def test_evicting_session_receives_the_evicted_sessions_fills(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        b = _make(monkeypatch, tmp_path, duplicate_session_policy="EVICT_OLD")
        try:
            _s1, oid = _rest_sell(b)
            s1b = b.logon("GW01", name="second")
            buyer = b.logon("GW02")
            b.send(buyer, new_order_frame(21, side=C.SIDE_BUY, price=100.0))
            reports = of_type(take(s1b), C.MSG_EXECUTION_REPORT)
            assert [parse_execution_report_balf(r).order_id for r in reports] == [oid]
        finally:
            b.close()

    def test_order_ids_are_not_reused_by_a_later_session(
        self, bridge: BalfBridge
    ) -> None:
        s1, first = _rest_sell(bridge)
        bridge.logout(s1)
        s1b = bridge.logon("GW01")
        bridge.send(s1b, new_order_frame(12, side=C.SIDE_SELL, price=101.0))
        second = order_ack(of_type(take(s1b), C.MSG_ORDER_ACK)[0])["order_id"]
        assert (first, second) == (1, 2)

    def test_orders_stay_reachable_across_an_engine_restart(
        self, bridge: BalfBridge
    ) -> None:
        # A restarted engine restores GTC orders under their original engine
        # ids, so the gateway keeps the map: a cancel of the old BALF id is
        # forwarded with the original engine id, not refused locally.
        s1, oid = _rest_sell(bridge)
        engine_id = bridge.published("order.ack.GW01")[0]["order_id"]
        # The engine side of a restart: it no longer holds GW01's session
        # (CANCEL_QUOTES_ONLY leaves the order resting, as a restored GTC
        # order would be).
        bridge.engine._dispatch_pull_message(
            "system.gateway_disconnect", {"gateway_id": "GW01", "reason": "restart"}
        )
        bridge.gw._dispatch_engine_event(TOPIC_STARTUP_RECOVERY, {})
        bridge.gw._flush_client_writes()
        bridge.push.sent.clear()
        bridge.push.queue.clear()

        s1b = bridge.logon("GW01")
        s1b.in_buffer.extend(cancel_frame(99, oid))
        bridge.gw._drain_frames(s1b)

        cancels = [p for t, p in map(decode, bridge.push.sent) if t == "order.cancel"]
        assert [c["order_id"] for c in cancels] == [engine_id]


# ===========================================================================
# WP-BALF02 — a logon is never lost (C3, C9, C14)
# ===========================================================================


def _connect_until_symbols_wait(b: BalfBridge, gw_id: str) -> Any:
    """LOGON, deliver the engine's auth reply, hold back the symbols reply."""
    s = b.connect(gw_id)
    s.in_buffer.extend(logon_frame(gw_id))
    b.gw._drain_frames(s)
    topic, payload = decode(b.push.queue.popleft())
    assert topic == "system.gateway_connect"
    b.engine._dispatch_pull_message(topic, payload)
    for frames in b.pub.sent[b._pub_idx :]:
        b.gw._dispatch_engine_event(*decode(frames))
    b._pub_idx = len(b.pub.sent)
    assert s.symbols_pending and not s.authenticated
    b.push.queue.clear()  # the symbols request never reaches the engine
    return s


class TestLogonIsNeverLost:
    def test_repeated_logon_while_symbols_pending_keeps_the_session(
        self, bridge: BalfBridge
    ) -> None:
        s = _connect_until_symbols_wait(bridge, "GW01")
        bridge.push.sent.clear()
        s.in_buffer.extend(logon_frame("GW01"))
        bridge.gw._drain_frames(s)

        acks = of_type(take(s), C.MSG_LOGON_ACK)
        assert len(acks) == 1 and acks[0][24] == 0
        assert b"LOGON_ALREADY_PENDING" in acks[0]
        assert not s.closing and s.symbols_pending
        sent = [decode(f)[0] for f in bridge.push.sent]
        assert "system.gateway_disconnect" not in sent
        assert "system.gateway_connect" not in sent

    def test_gateway_id_with_a_dot_is_refused_at_once(self, bridge: BalfBridge) -> None:
        s = bridge.connect("dotted")
        s.in_buffer.extend(logon_frame("GW.01"))
        bridge.gw._drain_frames(s)

        acks = of_type(take(s), C.MSG_LOGON_ACK)
        assert len(acks) == 1 and acks[0][24] == 0
        assert b"gateway_id invalid" in acks[0]
        assert [decode(f)[0] for f in bridge.push.sent] == []


class _AsyncSub:
    """A SUB whose runtime SUBSCRIBEs take effect one poll later.

    That is the ZMQ race in its worst case: the subscription travels on the
    SUB's TCP connection and the PUB applies it asynchronously, so a reply
    published before it lands is filtered out. Prefixes given at
    construction are in force from the start, as after the gateway's
    start-up settle.
    """

    def __init__(self, *topics: str) -> None:
        self.closed = False
        self.active = set(topics)
        self.pending: set[str] = set()
        self.queue: deque[list[bytes]] = deque()

    def setsockopt(self, op: int, value: Any) -> None:
        if op == zmq.SUBSCRIBE:
            self.pending.add(value.decode())
        elif op == zmq.UNSUBSCRIBE:
            self.active.discard(value.decode())

    def publish(self, frames: list[bytes]) -> None:
        topic = frames[0].decode()
        if any(topic.startswith(p) for p in self.active):
            self.queue.append(frames)

    def poll(self, timeout: int = 0) -> int:
        _ = timeout
        self.active |= self.pending
        self.pending.clear()
        return 1 if self.queue else 0

    def recv_multipart(self) -> list[bytes]:
        return self.queue.popleft()

    def close(self) -> None:
        self.closed = True


def test_auth_reply_published_at_once_still_completes_the_logon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An engine that answers gateway_connect immediately (review C3)."""
    subs: list[_AsyncSub] = []

    class _Engine:
        closed = False

        def send_multipart(self, frames: list[bytes]) -> None:
            topic, payload = decode(frames)
            gw_id = payload.get("gateway_id", "")
            if topic == "system.gateway_connect":
                subs[0].publish(
                    encode(
                        f"system.gateway_auth.{gw_id}",
                        {"gateway_id": gw_id, "accepted": True, "reason": ""},
                    )
                )
            elif topic == "system.symbols_request":
                subs[0].publish(
                    encode(
                        f"system.symbols.{gw_id}",
                        {"symbols": [{"symbol": "AAPL", "tick_decimals": 2}]},
                    )
                )

        def close(self) -> None:
            self.closed = True

    def _make_sub(_addr: str, *topics: str, **_kw: Any) -> _AsyncSub:
        subs.append(_AsyncSub(*topics))
        return subs[0]

    monkeypatch.setattr("edumatcher.balf_gwy.gateway.make_pusher", lambda _a: _Engine())
    monkeypatch.setattr("edumatcher.balf_gwy.gateway.make_subscriber", _make_sub)
    gw = BalfGateway(BalfGatewayConfig())
    left, right = socket.socketpair()
    try:
        session = ClientSession(sock=left, addr=("race", 1))
        session.rate_tokens = 100.0
        gw._clients[left.fileno()] = session
        session.in_buffer.extend(logon_frame("GW01"))
        gw._drain_frames(session)
        for _ in range(3):
            gw._poll_engine_events()
        acks = of_type(take(session), C.MSG_LOGON_ACK)
        assert len(acks) == 1 and acks[0][24] == 1
    finally:
        left.close()
        right.close()


# ===========================================================================
# WP-BALF03 — engine events are not dropped silently, nor at shutdown (C5, C6)
# ===========================================================================


def _sequenced(topic: str, payload: dict[str, Any], seq: int) -> list[bytes]:
    """An engine frame as SequencedPublisher sends it: topic, payload, then
    ``seq|eseq|`` (no envelope)."""
    return [*encode(topic, payload), b"%d|1|" % seq]


def test_sub_socket_has_a_deep_receive_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    def _make_sub(_addr: str, *_topics: str, **kw: Any) -> Any:
        seen.update(kw)
        return _AsyncSub()

    monkeypatch.setattr("edumatcher.balf_gwy.gateway.make_pusher", lambda _a: None)
    monkeypatch.setattr("edumatcher.balf_gwy.gateway.make_subscriber", _make_sub)
    BalfGateway(BalfGatewayConfig())
    assert seen.get("rcvhwm") == 200_000


class TestLostEngineEvents:
    def test_a_sequence_gap_is_counted_logged_and_ends_the_session(
        self, bridge: BalfBridge, caplog: pytest.LogCaptureFixture
    ) -> None:
        s = bridge.logon("GW01")
        before = bridge.gw._global_stats["events_lost"]
        for seq in (3, 5):
            bridge.sub.queue.append(
                _sequenced("order.fill.GW01", {"order_id": "x"}, seq)
            )
        with caplog.at_level("WARNING", logger="edumatcher.balf_gwy.gateway"):
            bridge.gw._poll_engine_events()

        assert bridge.gw._global_stats["events_lost"] - before == 1
        assert any("order.fill.GW01" in r.getMessage() for r in caplog.records)
        assert [mt for mt, _ in take(s)] == [C.MSG_LOGOUT]
        assert s.closing

    def test_first_sight_and_an_engine_restart_are_not_gaps(
        self, bridge: BalfBridge
    ) -> None:
        s = bridge.logon("GW01")
        for seq in (7, 8, 2):  # first sight at 7; 2 = the engine restarted
            bridge.sub.queue.append(
                _sequenced("order.fill.GW01", {"order_id": "x"}, seq)
            )
        bridge.gw._poll_engine_events()
        assert bridge.gw._global_stats["events_lost"] == 0
        assert take(s) == [] and not s.closing


def test_stop_delivers_what_is_queued_and_waiting_then_logout(
    bridge: BalfBridge,
) -> None:
    s, oid = _rest_sell(bridge)
    bridge.gw._queue_frame(s, C.build_heartbeat(s.next_seq()))
    # GW02 trades against the order inside the engine; the fill for GW01 is
    # left waiting on the gateway's SUB socket, unread, as at a SIGTERM.
    connect(bridge.engine, "GW02")
    bridge.engine._dispatch_pull_message(
        "order.new",
        order_payload(Side.BUY, OrderType.LIMIT, 100, "GW02", price=100.0),
    )
    for frames in bridge.pub.sent[bridge._pub_idx :]:
        if decode(frames)[0] == "order.fill.GW01":
            bridge.sub.queue.append(frames)
    bridge._pub_idx = len(bridge.pub.sent)
    peer = bridge.peer_of[id(s)]

    bridge.gw._flush_for_shutdown()
    bridge.gw.close()

    wire = read_wire(peer)
    assert [mt for mt, _ in wire] == [
        C.MSG_HEARTBEAT,
        C.MSG_EXECUTION_REPORT,
        C.MSG_LOGOUT,
    ]
    assert parse_execution_report_balf(wire[1][1]).order_id == oid


# ===========================================================================
# WP-BALF04 — a closing session always ends (C4, C15)
# ===========================================================================


def _stuff_until_blocked(b: BalfBridge, s: Any) -> None:
    """Fill the kernel send buffer of a client that never reads."""
    s.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    for _ in range(3000):
        b.gw._queue_frame(s, C.build_heartbeat(s.next_seq()))
    b.gw._flush_client_writes()
    assert s.out_queue, "precondition: the peer's buffer is full"


class TestClosingSessionsEnd:
    def test_logout_releases_the_id_and_the_session_ends_after_the_grace(
        self, bridge: BalfBridge, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "edumatcher.balf_gwy.gateway._CLOSE_GRACE_SEC", 0.05, raising=False
        )
        s = bridge.logon("GW01")
        _stuff_until_blocked(bridge, s)
        bridge.send(s, C.build_header(C.MSG_LOGOUT, 2))

        # The ID is free at once: the engine was told on LOGOUT.
        again = bridge.logon("GW01", name="again")
        assert again.authenticated

        time.sleep(0.1)
        bridge.gw._flush_client_writes()
        bridge.gw._drop_stale_clients()
        assert s not in bridge.gw._clients.values()

    def test_a_permanent_send_error_disconnects_on_that_pass(
        self, bridge: BalfBridge
    ) -> None:
        s = bridge.logon("GW01")

        class _Broken(socket.socket):
            def send(self, *_a: Any, **_k: Any) -> int:
                raise BrokenPipeError(32, "Broken pipe")

        fd = s.sock.fileno()
        s.sock = _Broken(fileno=s.sock.detach())
        bridge.gw._queue_frame(s, C.build_heartbeat(s.next_seq()))
        bridge.gw._flush_client_writes()
        assert fd not in bridge.gw._clients

    def test_slow_client_close_never_cuts_a_frame(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        b = _make(monkeypatch, tmp_path, max_client_queue=200)
        try:
            s = b.logon("GW01")
            peer = b.peer_of[id(s)]
            frame = C.build_logon_ack("GW01", accepted=True)  # 92 bytes
            # The state the bug needs: the head frame is 40 bytes sent when
            # the queue overflows.
            s.sock.send(frame[:40])
            s.out_queue.append(frame)
            s.out_offset = 40
            for _ in range(200):  # overflow: SLOW_CLIENT
                b.gw._queue_frame(s, frame)
            for _ in range(5):  # what the loop would queue afterwards
                b.gw._queue_frame(s, C.build_heartbeat(s.next_seq()))
            for _ in range(10):
                b.gw._flush_client_writes()

            assert s not in b.gw._clients.values()
            got = bytearray()
            peer.setblocking(False)
            while True:
                try:
                    chunk = peer.recv(65536)
                except BlockingIOError:
                    break
                if not chunk:
                    break
                got.extend(chunk)
            assert len(got) == len(frame), "the stream ends inside a frame"
        finally:
            b.close()


# ===========================================================================
# WP-BALF05 — every request gets an answer (C2, C11)
# ===========================================================================


def _empty_bucket(s: Any) -> None:
    s.rate_tokens = 0.0
    s.rate_updated = time.monotonic()


class TestEveryRequestIsAnswered:
    def test_rate_limited_orders_are_refused_not_dropped(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        b = _make(monkeypatch, tmp_path, max_messages_per_second=5)
        try:
            s = b.logon("GW01")  # the LOGON took one of the five tokens
            for i in range(1, 11):
                b.send(
                    s,
                    new_order_frame(i, side=C.SIDE_BUY, price=90.0 + i, seq_no=i),
                )
            acks = [order_ack(f) for f in of_type(take(s), C.MSG_ORDER_ACK)]
            assert [a["client_order_id"] for a in acks] == list(range(1, 11))
            limited = [a for a in acks if a["reject_code"] == 0x0D]
            assert len(limited) == 6
            assert all(a["accepted"] == 0 for a in limited)
            assert {a["reason"] for a in limited} == {"RATE_LIMITED"}
            assert s.errors == 0 and not s.closing
        finally:
            b.close()

    def test_rate_limited_cancel_amend_and_heartbeat(self, bridge: BalfBridge) -> None:
        s, oid = _rest_sell(bridge)
        _empty_bucket(s)
        bridge.send(s, cancel_frame(31, oid, seq_no=2))
        _empty_bucket(s)
        bridge.send(s, amend_frame(32, oid, new_quantity=50, flags=0x02, seq_no=3))
        _empty_bucket(s)
        bridge.send(s, heartbeat_frame(4))
        frames = take(s)
        assert [mt for mt, _ in frames] == [C.MSG_CANCEL_ACK, C.MSG_AMEND_ACK]
        assert cancel_ack(frames[0][1])["accepted"] == 0
        assert cancel_ack(frames[0][1])["order_id"] == oid
        assert amend_ack(frames[1][1])["accepted"] == 0
        assert amend_ack(frames[1][1])["client_order_id"] == 32

    def test_logout_is_honoured_with_an_empty_bucket(self, bridge: BalfBridge) -> None:
        s = bridge.logon("GW01")
        _empty_bucket(s)
        bridge.send(s, C.build_header(C.MSG_LOGOUT, 1))
        assert s.closing

    def test_amend_with_a_zero_flagged_field_is_refused_whole(
        self, bridge: BalfBridge
    ) -> None:
        s, oid = _rest_sell(bridge)
        bridge.push.sent.clear()
        bridge.send(s, amend_frame(33, oid, new_price=0.0, new_quantity=50, flags=0x03))
        acks = [amend_ack(f) for f in of_type(take(s), C.MSG_AMEND_ACK)]
        assert [a["accepted"] for a in acks] == [0]
        assert "order.amend" not in [decode(f)[0] for f in bridge.push.sent]


# ===========================================================================
# WP-BALF06 — timestamps, reject codes, cancel reasons, metrics
# ===========================================================================


class TestFiguresTheClientCanUse:
    def test_execution_reports_carry_the_engines_fill_time(
        self, bridge: BalfBridge
    ) -> None:
        seller, _ = _rest_sell(bridge)
        buyer = bridge.logon("GW02")
        bridge.send(buyer, new_order_frame(21, side=C.SIDE_BUY, price=100.0))
        engine_ts = {p["order_id"]: p["ts_ns"] for p in bridge.published("order.fill.")}
        assert all(engine_ts.values())
        for s in (seller, buyer):
            (frame,) = of_type(take(s), C.MSG_EXECUTION_REPORT)
            er = parse_execution_report_balf(frame)
            assert er.timestamp_ns in engine_ts.values()
        assert len(set(engine_ts.values())) == 1  # one match, one clock read

    def test_order_ack_carries_the_engines_ack_time(self, bridge: BalfBridge) -> None:
        s = bridge.logon("GW01")
        bridge.send(s, new_order_frame(11, side=C.SIDE_SELL, price=100.0))
        (engine_ack,) = bridge.published("order.ack.GW01")
        ack = order_ack(of_type(take(s), C.MSG_ORDER_ACK)[0])
        assert ack["timestamp_ns"] == engine_ack["ts_ns"]

    def test_invalid_price_is_classified_as_invalid_field(
        self, bridge: BalfBridge
    ) -> None:
        s = bridge.logon("GW01")
        bridge.send(s, new_order_frame(11, side=C.SIDE_BUY, price=-100.0))
        (engine_ack,) = bridge.published("order.ack.GW01")
        assert engine_ack["reject_code"] == "PRICE_OUT_OF_RANGE"
        assert order_ack(of_type(take(s), C.MSG_ORDER_ACK)[0])["reject_code"] == 0x0C

    def test_risk_limit_refusal_has_its_own_code(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        b = BalfBridge(
            monkeypatch,
            tmp_path,
            symbol_configs={
                "AAPL": SymbolConfig(
                    name="AAPL", order_limits=OrderLimitsConfig(max_order_qty=50)
                )
            },
        )
        try:
            s = b.logon("GW01")
            b.send(s, new_order_frame(11, side=C.SIDE_BUY, price=100.0, qty=100))
            (engine_ack,) = b.published("order.ack.GW01")
            assert engine_ack["reject_code"] == "MAX_ORDER_QTY"
            ack = order_ack(of_type(take(s), C.MSG_ORDER_ACK)[0])
            assert ack["reject_code"] == 0x0E
        finally:
            b.close()

    def test_a_self_match_cancel_says_so(self, bridge: BalfBridge) -> None:
        s, oid = _rest_sell(bridge)
        bridge.send(
            s, new_order_frame(12, side=C.SIDE_BUY, price=100.0, smp=0x02)
        )  # CANCEL_RESTING
        acks = [cancel_ack(f) for f in of_type(take(s), C.MSG_CANCEL_ACK)]
        assert acks == [
            {"client_order_id": 11, "order_id": oid, "accepted": 1, "cancel_reason": 1}
        ]

    def test_an_expiry_says_so(self, bridge: BalfBridge) -> None:
        s, oid = _rest_sell(bridge)
        engine_id = bridge.published("order.ack.GW01")[0]["order_id"]
        bridge.gw._dispatch_engine_event(
            "order.expired.GW01",
            {
                "gateway_id": "GW01",
                "order_id": engine_id,
                "reason": "Trading day ended",
            },
        )
        acks = [cancel_ack(f) for f in of_type(take(s), C.MSG_CANCEL_ACK)]
        assert [a["cancel_reason"] for a in acks] == [254]

    def test_frames_are_counted_once(self, bridge: BalfBridge) -> None:
        s = bridge.logon("GW01")
        stats = bridge.gw._global_stats
        fwd, rej = stats["frames_forwarded_total"], stats["frames_rejected_total"]
        bridge.send(s, new_order_frame(11, side=C.SIDE_SELL, price=100.0))
        assert stats["frames_forwarded_total"] - fwd == 1
        bridge.send(s, new_order_frame(12, side=C.SIDE_SELL, price=100.001))
        assert stats["frames_rejected_total"] - rej == 1


# ===========================================================================
# WP-BALF08 — inbound sequence numbers are checked (C10)
# ===========================================================================


def _seq(frame: bytes, seq_no: int) -> bytes:
    return frame[:4] + seq_no.to_bytes(4, "little") + frame[8:]


class TestInboundSequence:
    def test_a_gap_is_a_protocol_error(
        self, bridge: BalfBridge, caplog: pytest.LogCaptureFixture
    ) -> None:
        s = bridge.logon("GW01")
        before = bridge.gw._global_stats["protocol_errors_total"]
        bridge.send(
            s, new_order_frame(11, side=C.SIDE_SELL, price=100.0, seq_no=1), raw=True
        )
        with caplog.at_level("WARNING", logger="edumatcher.balf_gwy.gateway"):
            bridge.send(s, heartbeat_frame(3), raw=True)
        assert s not in bridge.gw._clients.values()
        assert bridge.gw._global_stats["protocol_errors_total"] - before == 1
        text = " ".join(r.getMessage() for r in caplog.records)
        assert "expected 2" in text and "got 3" in text

    def test_a_repeat_is_a_protocol_error(self, bridge: BalfBridge) -> None:
        s = bridge.logon("GW01")
        bridge.send(s, heartbeat_frame(1), raw=True)
        bridge.send(s, heartbeat_frame(1), raw=True)
        assert s not in bridge.gw._clients.values()

    def test_consecutive_numbers_and_seq_zero_logon_are_accepted(
        self, bridge: BalfBridge
    ) -> None:
        s = bridge.logon("GW01")  # LOGON carries seq 0
        for n in (1, 2, 3):
            bridge.send(s, heartbeat_frame(n), raw=True)
        assert s in bridge.gw._clients.values() and not s.closing
        assert [mt for mt, _ in take(s)] == [C.MSG_HEARTBEAT_ACK] * 3

    def test_the_number_wraps_to_one(self, bridge: BalfBridge) -> None:
        s = bridge.logon("GW01")
        s.inbound_seq = 0xFFFFFFFE
        bridge.send(s, heartbeat_frame(0xFFFFFFFF), raw=True)
        bridge.send(s, heartbeat_frame(1), raw=True)
        assert s in bridge.gw._clients.values() and not s.closing
