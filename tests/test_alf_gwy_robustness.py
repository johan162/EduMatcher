"""
Robustness and security tests for pm-alf-gwy (unit-level).

High priority:
  - Error threshold + sliding-window boundary

Medium priority:
  - Rate-limit exact boundary, token refill, bypass for control frames
  - Numeric field extremes: integer overflow, zero/negative QTY, inf/NaN prices
"""

from __future__ import annotations

import socket
import time

import pytest

from edumatcher.alf_gwy.config import AlfGatewayConfig
from edumatcher.alf_gwy.gateway import AlfGateway, ClientSession
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


def _make_gateway(
    monkeypatch: pytest.MonkeyPatch, **cfg_overrides: object
) -> AlfGateway:
    fake_push = _FakePush()
    fake_sub = _FakeSub()
    monkeypatch.setattr("edumatcher.alf_gwy.gateway.make_pusher", lambda _: fake_push)
    monkeypatch.setattr(
        "edumatcher.alf_gwy.gateway.make_subscriber", lambda _addr, *_t: fake_sub
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
