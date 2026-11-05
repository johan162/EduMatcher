"""
Robustness and security tests for pm-alf-gwy (unit-level).

High priority:
  - Error threshold + sliding-window boundary

Medium priority:
  - Rate-limit exact boundary, token refill, bypass for control frames
  - Numeric field extremes: integer overflow, zero/negative QTY, inf/NaN prices
"""

from __future__ import annotations

from typing import Any

import errno
import json
import socket
import time

import pytest

from edumatcher.alf_gwy.config import AlfGatewayConfig
from edumatcher.alf_gwy.gateway import (
    _CLOSE_GRACE_SEC,
    _PROBE_ID_PREFIX,
    _SUB_RCVHWM,
    AlfGateway,
    ClientSession,
)
from edumatcher.alf_gwy.protocol import parse_alf_line

# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------


class _FakePush:
    def __init__(self) -> None:
        self.sent: list[list[bytes]] = []
        self.closed = False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        self.closed = True


class _FakeSub:
    def __init__(self) -> None:
        self.closed = False

    def setsockopt(self, op: int, value: bytes) -> None:
        pass

    def poll(self, timeout: int = 0) -> int:
        return 0

    def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gateway(monkeypatch: pytest.MonkeyPatch, **cfg_overrides: Any) -> AlfGateway:
    fake_push = _FakePush()
    fake_sub = _FakeSub()
    monkeypatch.setattr("edumatcher.alf_gwy.gateway.make_pusher", lambda _: fake_push)
    monkeypatch.setattr(
        "edumatcher.alf_gwy.gateway.make_subscriber", lambda _addr, *_t, **_kw: fake_sub
    )
    cfg = AlfGatewayConfig(
        bind_address="127.0.0.1",
        port=5565,
        gateway_roles=(("TRADER01", "TRADER"),),
        **cfg_overrides,
    )
    gw = AlfGateway(cfg)
    gw._push = fake_push
    gw._sub = fake_sub
    return gw


def _make_session() -> tuple[ClientSession, socket.socket]:
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    return ClientSession(sock=left, addr=("local", 0)), right


def _authed_session(
    gateway: AlfGateway,
    *,
    rate_tokens: float = 100.0,
) -> tuple[ClientSession, socket.socket]:
    """Return an authenticated session pre-registered with the gateway."""
    session, peer = _make_session()
    session.authenticated = True
    session.gateway_id = "TRADER01"
    session.role = "TRADER"
    session.rate_tokens = rate_tokens
    gateway._clients[session.sock.fileno()] = session
    gateway._active_gateway_sessions["TRADER01"] = session.sock.fileno()
    gateway._symbols_snapshot_loaded = True
    gateway._known_symbols.add("AAPL")
    return session, peer


def _err_codes(session: ClientSession) -> list[str]:
    """Return all ERR CODE values queued on the session."""
    codes: list[str] = []
    for raw in session.out_queue:
        try:
            frame = parse_alf_line(raw.decode("utf-8"))
            if frame.command == "ERR":
                codes.append(frame.fields.get("CODE", ""))
        except Exception:
            pass
    return codes


# ===========================================================================
# Error threshold and sliding window
# ===========================================================================


class TestErrorThresholdAndSlidingWindow:
    """_register_error accumulates, prunes by window, and disconnects at threshold."""

    def test_below_threshold_does_not_close(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """threshold - 1 errors leave the session open."""
        gw = _make_gateway(
            monkeypatch,
            max_errors_before_disconnect=3,
            error_window_sec=60,
        )
        session, peer = _make_session()
        for _ in range(2):
            gw._register_error(session, "BAD_MESSAGE", "bad", close_connection=False)
        assert session.closing is False
        assert len(session.error_times) == 2
        peer.close()

    def test_at_threshold_triggers_disconnect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exactly threshold errors → MAX_ERRORS sent and session marked closing."""
        gw = _make_gateway(
            monkeypatch,
            max_errors_before_disconnect=3,
            error_window_sec=60,
        )
        session, peer = _make_session()
        for _ in range(3):
            gw._register_error(session, "BAD_MESSAGE", "bad", close_connection=False)
        assert session.closing is True
        assert "MAX_ERRORS" in _err_codes(session)
        peer.close()

    def test_errors_outside_window_are_pruned(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Errors older than error_window_sec do not count toward the threshold."""
        _now = [1_000.0]
        monkeypatch.setattr(
            "edumatcher.alf_gwy.gateway.time.monotonic", lambda: _now[0]
        )
        gw = _make_gateway(
            monkeypatch,
            max_errors_before_disconnect=3,
            error_window_sec=10,
        )
        session, peer = _make_session()

        # 2 errors at t=1000 — below threshold
        for _ in range(2):
            gw._register_error(session, "BAD_MESSAGE", "bad", close_connection=False)
        assert session.closing is False

        # Advance past the error window (20s > 10s window)
        _now[0] = 1_020.0

        # 2 more errors at t=1020: the two old errors are pruned, only these 2 remain
        for _ in range(2):
            gw._register_error(session, "BAD_MESSAGE", "bad", close_connection=False)

        assert session.closing is False  # only 2 in window — below threshold 3
        assert len(session.error_times) == 2
        peer.close()

    def test_close_connection_true_disconnects_on_first_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """close_connection=True closes regardless of error count."""
        gw = _make_gateway(
            monkeypatch,
            max_errors_before_disconnect=50,
            error_window_sec=60,
        )
        session, peer = _make_session()
        gw._register_error(
            session, "AUTH_REQUIRED", "must send HELLO", close_connection=True
        )
        assert session.closing is True
        peer.close()

    def test_max_errors_code_is_last_queued_frame(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """MAX_ERRORS ERR frame must appear after the triggering error frame."""
        gw = _make_gateway(
            monkeypatch,
            max_errors_before_disconnect=2,
            error_window_sec=60,
        )
        session, peer = _make_session()
        for _ in range(2):
            gw._register_error(session, "BAD_MESSAGE", "bad", close_connection=False)
        codes = _err_codes(session)
        assert codes[-1] == "MAX_ERRORS"
        peer.close()


# ===========================================================================
# Rate-limit boundary and token refill
# ===========================================================================


class TestRateLimitBoundaryAndRefill:
    """_allow_command_now token-bucket boundary behaviour."""

    def test_tokens_exactly_at_limit_all_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """N tokens → exactly N commands accepted, N+1th rejected."""
        gw = _make_gateway(monkeypatch, max_commands_per_second=5)
        session, peer = _authed_session(gw, rate_tokens=5.0)
        # Pin rate_updated to now so elapsed ≈ 0 and no extra tokens are added.
        session.rate_updated = time.monotonic()

        results = [gw._allow_command_now(session) for _ in range(6)]
        assert all(results[:5])
        assert results[5] is False
        peer.close()

    def test_token_refill_after_elapsed_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Manually winding back rate_updated simulates token refill."""
        gw = _make_gateway(monkeypatch, max_commands_per_second=10)
        session, peer = _authed_session(gw, rate_tokens=1.0)
        session.rate_updated = time.monotonic()

        assert gw._allow_command_now(session) is True  # uses the 1 initial token
        assert gw._allow_command_now(session) is False  # exhausted

        # Simulate 0.15 s elapsed (≥ 1/rate = 0.1 s for rate=10/s)
        session.rate_updated -= 0.15
        assert gw._allow_command_now(session) is True
        peer.close()

    def test_ping_bypasses_rate_limiter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PING must be answered even when the token bucket is exhausted."""
        gw = _make_gateway(monkeypatch, max_commands_per_second=1)
        session, peer = _authed_session(gw, rate_tokens=0.0)
        session.rate_updated = time.monotonic()

        gw._handle_client_line(session, "PING")

        commands = [parse_alf_line(m.decode()).command for m in session.out_queue]
        assert "PONG" in commands
        peer.close()

    def test_exit_bypasses_rate_limiter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """EXIT must be honoured even when the token bucket is exhausted."""
        gw = _make_gateway(monkeypatch, max_commands_per_second=1)
        session, peer = _authed_session(gw, rate_tokens=0.0)
        session.rate_updated = time.monotonic()

        gw._handle_client_line(session, "EXIT")
        assert session.closing is True
        peer.close()

    def test_independent_sessions_have_independent_buckets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exhausting one session's tokens must not affect another session."""
        gw = _make_gateway(monkeypatch, max_commands_per_second=1)
        session1, peer1 = _authed_session(gw, rate_tokens=1.0)
        session1.rate_updated = time.monotonic()

        # Create a second session with a different gateway_id
        session2, peer2 = _make_session()
        session2.authenticated = True
        session2.gateway_id = "TRADER02"
        session2.role = "TRADER"
        session2.rate_tokens = 5.0
        session2.rate_updated = time.monotonic()

        assert gw._allow_command_now(session1) is True
        assert gw._allow_command_now(session1) is False  # session1 exhausted

        assert gw._allow_command_now(session2) is True  # session2 unaffected
        peer1.close()
        peer2.close()


# ===========================================================================
# Numeric field extremes
# ===========================================================================


class TestNumericFieldExtremes:
    """safe_int / safe_float edge cases surface as INVALID_VALUE, never crashes."""

    def _new_order(self, gw: AlfGateway, session: ClientSession, extra: str) -> None:
        gw._handle_client_line(session, f"NEW|SYM=AAPL|SIDE=BUY|{extra}")

    def test_quantity_integer_overflow_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        self._new_order(gw, session, "TYPE=LIMIT|QTY=9999999999|PRICE=100.0")
        assert "INVALID_VALUE" in _err_codes(session)
        peer.close()

    def test_quantity_zero_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        self._new_order(gw, session, "TYPE=LIMIT|QTY=0|PRICE=100.0")
        assert "INVALID_VALUE" in _err_codes(session)
        peer.close()

    def test_quantity_negative_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        self._new_order(gw, session, "TYPE=LIMIT|QTY=-5|PRICE=100.0")
        assert "INVALID_VALUE" in _err_codes(session)
        peer.close()

    def test_price_positive_inf_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        self._new_order(gw, session, "TYPE=LIMIT|QTY=10|PRICE=inf")
        assert "INVALID_VALUE" in _err_codes(session)
        peer.close()

    def test_price_negative_inf_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        self._new_order(gw, session, "TYPE=LIMIT|QTY=10|PRICE=-inf")
        assert "INVALID_VALUE" in _err_codes(session)
        peer.close()

    def test_price_nan_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        self._new_order(gw, session, "TYPE=LIMIT|QTY=10|PRICE=nan")
        assert "INVALID_VALUE" in _err_codes(session)
        peer.close()

    def test_price_string_overflow_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A price value with 500 '9' chars must raise INVALID_VALUE, not crash."""
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        self._new_order(gw, session, f"TYPE=LIMIT|QTY=10|PRICE={'9' * 500}")
        assert "INVALID_VALUE" in _err_codes(session)
        peer.close()

    def test_non_numeric_price_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        self._new_order(gw, session, "TYPE=LIMIT|QTY=10|PRICE=notanumber")
        assert "INVALID_VALUE" in _err_codes(session)
        peer.close()

    def test_non_numeric_quantity_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        self._new_order(gw, session, "TYPE=LIMIT|QTY=abc|PRICE=100.0")
        assert "INVALID_VALUE" in _err_codes(session)
        peer.close()


# ===========================================================================
# Engine-event containment and accept errors (review 2026-11-05 H1, M4)
# ===========================================================================


class _QueueSub(_FakeSub):
    """SUB stub that hands out queued multipart messages."""

    def __init__(self, *messages: tuple[str, Any]) -> None:
        super().__init__()
        self.queue = [[t.encode(), json.dumps(p).encode()] for t, p in messages]

    def poll(self, timeout: int = 0) -> int:
        return 1 if self.queue else 0

    def recv_multipart(self) -> list[bytes]:
        return self.queue.pop(0)


_GOOD_FILL = (
    "order.fill.TRADER01",
    {"order_id": "ok-1", "fill_qty": 5, "trade_ids": ["T1"]},
)


class TestEngineEventContainment:
    """A bad engine event is dropped; the loop and later events survive."""

    @pytest.mark.parametrize(
        "topic, payload",
        [
            ("order.triggered.TRADER01", {"order_id": "x", "symbol": "AAPL"}),
            ("order.fill.TRADER01", {"order_id": "x", "trade_ids": None}),
            ("system.symbols.TRADER01", {"symbols": None}),
            (f"system.gateways.{_PROBE_ID_PREFIX}1", {"gateways": None}),
            ("order.ack.TRADER01", ["not", "a", "dict"]),
        ],
    )
    def test_malformed_event_does_not_stop_the_loop(
        self, monkeypatch: pytest.MonkeyPatch, topic: str, payload: Any
    ) -> None:
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        gw._probes[f"{_PROBE_ID_PREFIX}1"] = 0.0
        gw._sub = _QueueSub((topic, payload), _GOOD_FILL)

        gw._poll_engine_events()

        lines = [parse_alf_line(raw.decode()) for raw in session.out_queue]
        assert any(
            f.command == "FILL" and f.fields["ORDER_ID"] == "OK-1" for f in lines
        )
        peer.close()

    def test_pipe_in_engine_text_is_delivered_blanked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        gw._sub = _QueueSub(
            ("order.ack.TRADER01", {"order_id": "x", "reason": "a|b"}),
            ("trade.executed", {"symbol": "A|B", "price": 1, "quantity": 1}),
        )

        gw._poll_engine_events()

        frames = [parse_alf_line(raw.decode()) for raw in session.out_queue]
        assert [f.command for f in frames] == ["ACK", "TRADE"]
        assert frames[0].fields["REASON"] == "A B"
        assert frames[1].fields["SYMBOL"] == "A B"
        peer.close()

    def test_malformed_drop_copy_event_is_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        session.dc_enabled = True
        gw._dc_sub = _QueueSub(
            ("drop_copy.event.TRADER01", ["not", "a", "dict"]),
            ("drop_copy.event.TRADER01", {"seq": 2, "order_id": "ok-2"}),
        )

        gw._poll_dc_events()

        frames = [parse_alf_line(raw.decode()) for raw in session.out_queue]
        assert [(f.command, f.fields["SEQ"]) for f in frames] == [("DC_FILL", "2")]
        peer.close()


class _FailingServer:
    def __init__(self, exc: OSError) -> None:
        self.exc = exc
        self.calls = 0

    def accept(self) -> tuple[socket.socket, tuple[str, int]]:
        self.calls += 1
        raise self.exc


class _BrokenConn:
    def __init__(self) -> None:
        self.closed = False

    def setblocking(self, flag: bool) -> None:
        raise OSError(errno.EINVAL, "already reset")

    def close(self) -> None:
        self.closed = True


class TestAcceptErrors:
    @pytest.mark.parametrize(
        "exc",
        [
            OSError(errno.EMFILE, "Too many open files"),
            ConnectionAbortedError(errno.ECONNABORTED, "aborted"),
        ],
    )
    def test_accept_error_is_not_fatal(
        self, monkeypatch: pytest.MonkeyPatch, exc: OSError
    ) -> None:
        gw = _make_gateway(monkeypatch)
        server = _FailingServer(exc)
        gw._server = server

        gw._accept_new_clients()

        assert server.calls == 1  # gave up for this tick, did not spin
        assert gw._clients == {}

    def test_connection_failing_setup_is_closed_and_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch)
        conn = _BrokenConn()

        class _Server:
            def __init__(self) -> None:
                self.pending = [conn]

            def accept(self) -> tuple[Any, tuple[str, int]]:
                if not self.pending:
                    raise BlockingIOError
                return self.pending.pop(), ("10.0.0.1", 1)

        gw._server = _Server()

        gw._accept_new_clients()

        assert conn.closed
        assert gw._clients == {}


# ===========================================================================
# Closing sessions and queue overflow (review 2026-11-05 H3, M1)
# ===========================================================================


def _fill_kernel_buffer(session: ClientSession) -> None:
    """Make the peer look like it stopped reading: no send() room left."""
    session.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    while True:
        try:
            session.sock.send(b"Z" * 4096)
        except BlockingIOError:
            return


class TestClosingSessionIsReaped:
    def test_non_reading_peer_is_disconnected_after_grace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch, idle_timeout_sec=1, heartbeat_interval_sec=1)
        session, peer = _authed_session(gw)
        _fill_kernel_buffer(session)
        session.last_activity -= 10

        gw._drop_idle_clients()  # IDLE_TIMEOUT queued, closing
        for _ in range(20):  # ticks within the grace period
            gw._send_heartbeats_if_due()
            gw._drop_idle_clients()
            gw._flush_client_writes(writable=set())

        assert session.closing
        assert _err_codes(session) == ["IDLE_TIMEOUT"]  # not one per tick
        assert not any(raw.startswith(b"HB|") for raw in session.out_queue)

        session.closing_since -= _CLOSE_GRACE_SEC + 1
        gw._drop_idle_clients()

        assert gw._clients == {}
        assert not gw._gateway_in_use("TRADER01")
        peer.close()

    def test_flushing_session_within_grace_is_left_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        gw._close_after_flush(session)
        first = session.closing_since
        gw._close_after_flush(session)  # a second reason does not restart it

        gw._drop_idle_clients()

        assert session.closing_since == first
        assert session.sock.fileno() in gw._clients
        peer.close()

    def test_nothing_is_queued_after_the_closing_line(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        gw._handle_client_line(session, "EXIT")
        gw._queue_line(session, "TRADE", {"SYMBOL": "AAPL"})

        assert list(session.out_queue) == []
        peer.close()


class TestSlowClientOverflow:
    def test_partly_sent_line_is_finished_before_the_err(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch, max_client_queue=3)
        session, peer = _authed_session(gw)
        # A trade print, sheddable, but half-sent: it must be finished.
        trade = b"TRADE|SYMBOL=AAPL|PRICE=1.00|QTY=100|SIDE=BUY\n"
        session.out_queue.extend([trade, b"TRADE|N=1\n", b"TRADE|N=2\n"])
        session.out_offset = 16  # 'TRADE|SYMBOL=AAP' already on the wire

        gw._queue_line(session, "HB", {"TS": "t"})  # overflows
        gw._flush_client_writes()

        wire = trade[:16] + peer.recv(65536)
        assert wire.split(b"\n") == [
            trade.rstrip(b"\n"),
            b"ERR|CODE=SLOW_CLIENT|DETAIL=Outbound queue full - disconnecting",
            b"",
        ]
        assert gw._clients == {}
        peer.close()

    def test_overflow_after_the_close_queues_nothing_more(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch, max_client_queue=2)
        session, peer = _authed_session(gw)
        for i in range(10):
            gw._queue_line(session, "TRADE", {"N": str(i)})

        assert list(session.out_queue) == [
            b"ERR|CODE=SLOW_CLIENT|DETAIL=Outbound queue full - disconnecting\n"
        ]
        assert gw._global_stats["slow_client_disconnects"] == 1
        peer.close()


# ===========================================================================
# Lost engine events (review 2026-11-05 H2)
# ===========================================================================


def _seq_sub(*events: tuple[str, int]) -> _QueueSub:
    """A SUB stub whose messages carry the publisher's per-topic sequence."""
    sub = _QueueSub()
    sub.queue = [
        [topic.encode(), json.dumps({"order_id": f"o{seq}"}).encode(), b"%d" % seq]
        for topic, seq in events
    ]
    return sub


def _lines(session: ClientSession) -> list[tuple[str, dict[str, str]]]:
    frames = [parse_alf_line(raw.decode()) for raw in session.out_queue]
    return [(f.command, f.fields) for f in frames]


class TestEventGapDetection:
    def test_gap_is_reported_before_the_event_that_revealed_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        gw._sub = _seq_sub(
            ("order.cancelled.TRADER01", 7),
            ("order.cancelled.TRADER01", 8),
            ("order.cancelled.TRADER01", 11),
        )

        gw._poll_engine_events()

        lines = _lines(session)
        assert [cmd for cmd, _ in lines] == [
            "CANCELLED",
            "CANCELLED",
            "ERR",
            "CANCELLED",
        ]
        assert lines[2][1]["CODE"] == "EVENTS_LOST"
        assert lines[2][1]["TOPIC"] == "ORDER.CANCELLED"
        assert lines[2][1]["COUNT"] == "2"
        assert "TAG" not in lines[2][1]
        assert gw._global_stats["events_lost"] == 2
        assert session.errors == 0  # not counted against the client
        peer.close()

    def test_topics_are_counted_separately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        gw._sub = _seq_sub(
            ("order.cancelled.TRADER01", 1),
            ("order.expired.TRADER01", 40),
            ("order.cancelled.OTHER", 5),
            ("order.cancelled.TRADER01", 2),
        )

        gw._poll_engine_events()

        assert gw._global_stats["events_lost"] == 0
        assert "ERR" not in [cmd for cmd, _ in _lines(session)]
        peer.close()

    def test_gap_while_logged_off_is_counted_but_not_misreported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch)
        gw._sub = _seq_sub(
            ("order.cancelled.TRADER01", 1),
            ("order.cancelled.TRADER01", 2),
        )
        gw._poll_engine_events()  # no session yet: tracked anyway
        session, peer = _authed_session(gw)
        gw._sub = _seq_sub(("order.cancelled.TRADER01", 3))

        gw._poll_engine_events()

        assert [cmd for cmd, _ in _lines(session)] == ["CANCELLED"]
        peer.close()

    def test_lower_sequence_is_an_engine_restart_not_a_gap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        gw._sub = _seq_sub(
            ("order.cancelled.TRADER01", 50),
            ("order.cancelled.TRADER01", 1),
            ("order.cancelled.TRADER01", 2),
        )

        gw._poll_engine_events()

        assert gw._global_stats["events_lost"] == 0
        peer.close()

    def test_restart_broadcast_resets_the_counters(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch)
        gw._topic_seq["order.cancelled.TRADER01"] = 3

        gw._handle_engine_restart()

        assert gw._topic_seq == {}

    def test_public_topics_are_not_sequence_checked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch)
        gw._sub = _seq_sub(("trade.executed", 1), ("trade.executed", 9))

        gw._poll_engine_events()

        assert gw._global_stats["events_lost"] == 0
        assert gw._topic_seq == {}


def test_both_subscribers_get_a_raised_receive_hwm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[int | None] = []

    def _record(_addr: str, *_topics: str, rcvhwm: int | None = None) -> _FakeSub:
        seen.append(rcvhwm)
        return _FakeSub()

    monkeypatch.setattr("edumatcher.alf_gwy.gateway.make_pusher", lambda _: _FakePush())
    monkeypatch.setattr("edumatcher.alf_gwy.gateway.make_subscriber", _record)
    AlfGateway(AlfGatewayConfig(bind_address="127.0.0.1", port=5565))

    assert seen == [_SUB_RCVHWM, _SUB_RCVHWM]
    assert _SUB_RCVHWM > 1000  # ZMQ's default, which this exists to raise


class TestSlowClientShedding:
    """Overflow sheds the public feed, not the client's own events (M2)."""

    def test_overflow_sheds_the_feed_and_keeps_the_clients_own_events(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch, max_client_queue=4)
        session, peer = _authed_session(gw)
        session.out_queue.extend(
            [
                b"TRADE|N=1\n",
                b"FILL|ORDER_ID=a\n",
                b"HB|TS=t\n",
                b"SESSION|STATE=OPEN\n",
            ]
        )

        gw._queue_line(session, "CANCELLED", {"ORDER_ID": "b"})  # overflows

        assert list(session.out_queue) == [
            b"FILL|ORDER_ID=a\n",
            b"SESSION|STATE=OPEN\n",
            b"CANCELLED|ORDER_ID=b\n",
            b"ERR|CODE=SLOW_CLIENT|DETAIL=Outbound queue full - disconnecting\n",
        ]
        assert session.closing
        peer.close()

    def test_overflowing_trade_print_is_itself_shed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch, max_client_queue=1)
        session, peer = _authed_session(gw)
        session.out_queue.append(b"FILL|ORDER_ID=a\n")

        gw._queue_line(session, "TRADE", {"SYMBOL": "AAPL"})

        assert list(session.out_queue) == [
            b"FILL|ORDER_ID=a\n",
            b"ERR|CODE=SLOW_CLIENT|DETAIL=Outbound queue full - disconnecting\n",
        ]
        peer.close()


# ===========================================================================
# Shutdown flush (review 2026-11-05 M3)
# ===========================================================================


class TestShutdownFlush:
    def test_queued_and_pending_events_reach_the_client_before_close(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        gw._queue_line(session, "FILL", {"ORDER_ID": "queued"})
        gw._sub = _QueueSub(  # published, not yet read
            ("order.cancelled.TRADER01", {"order_id": "pending"})
        )
        gw._dc_sub = _QueueSub()

        gw._flush_for_shutdown()

        received = peer.recv(65536).decode().splitlines()
        assert received == [
            "FILL|ORDER_ID=queued",
            "CANCELLED|ORDER_ID=pending",
            "ERR|CODE=GATEWAY_SHUTDOWN|DETAIL=Gateway shutting down",
        ]
        assert gw._clients == {}  # flushed sessions are closed
        peer.close()

    def test_a_peer_that_does_not_read_cannot_hold_up_the_stop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("edumatcher.alf_gwy.gateway._SHUTDOWN_FLUSH_SEC", 0.05)
        gw = _make_gateway(monkeypatch)
        gw._dc_sub = _QueueSub()
        session, peer = _authed_session(gw)
        _fill_kernel_buffer(session)
        gw._queue_line(session, "FILL", {"ORDER_ID": "stuck"})

        started = time.monotonic()
        gw._flush_for_shutdown()

        assert time.monotonic() - started < 1.0
        assert session.sock.fileno() in gw._clients  # left for close()
        gw.close()
        assert gw._clients == {}
        peer.close()


# ===========================================================================
# Other gateways' events are not decoded (review 2026-11-05 M5)
# ===========================================================================


class TestAbsentGatewayEventsSkipped:
    def _count_decodes(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        from edumatcher.models.message import decode as real

        decoded: list[str] = []

        def _counting(frames: list[bytes]) -> tuple[str, dict[str, Any]]:
            decoded.append(frames[0].decode())
            return real(frames)

        monkeypatch.setattr("edumatcher.alf_gwy.gateway.decode", _counting)
        return decoded

    def test_absent_gateways_private_events_are_not_decoded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch)
        session, peer = _authed_session(gw)
        decoded = self._count_decodes(monkeypatch)
        sub = _seq_sub(("order.fill.OTHER", 1), ("order.cancelled.TRADER01", 1))
        # Not even valid JSON: it would have been a decode warning before.
        sub.queue[0][1] = b"{not json"
        gw._sub = sub

        gw._poll_engine_events()

        assert decoded == ["order.cancelled.TRADER01"]
        assert [cmd for cmd, _ in _lines(session)] == ["CANCELLED"]
        peer.close()

    def test_skipped_events_still_keep_their_sequence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gw = _make_gateway(monkeypatch)
        gw._sub = _seq_sub(("order.fill.OTHER", 1), ("order.fill.OTHER", 4))

        gw._poll_engine_events()

        assert gw._topic_seq["order.fill.OTHER"] == 4
        assert gw._global_stats["events_lost"] == 2

    @pytest.mark.parametrize(
        "topic",
        [
            "system.gateway_auth.OTHER",  # routed to a pending, not active, session
            "system.symbols.OTHER",  # refreshes the shared symbol cache
            "system.position_snapshot.OTHER",  # routed by pending POS query
            "trade.executed",
        ],
    )
    def test_replies_and_public_events_are_still_decoded(
        self, monkeypatch: pytest.MonkeyPatch, topic: str
    ) -> None:
        gw = _make_gateway(monkeypatch)
        decoded = self._count_decodes(monkeypatch)
        gw._sub = _QueueSub((topic, {}))

        gw._poll_engine_events()

        assert decoded == [topic]
