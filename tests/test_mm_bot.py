"""Tests for mm_bot — QuotePricer unit tests and MMBot integration tests."""

from __future__ import annotations

import time
from typing import Any

import pytest

from edumatcher.mm_bot.bot import BotState, MMBot
from edumatcher.mm_bot.pricer import QuotePricer
from edumatcher.models.message import decode as msg_decode, encode

# ========================================================================
# Unit Tests — QuotePricer
# ========================================================================


class TestQuotePricerConstruction:
    """Validate parameter validation at construction time."""

    def test_gap_validation_too_small(self) -> None:
        """gap < 2 × tick_size raises ValueError."""
        with pytest.raises(ValueError, match="gap.*must be at least"):
            QuotePricer(tick_size=0.01, gap=0.01, drift_ticks=3)

    def test_gap_validation_exactly_two_ticks(self) -> None:
        """gap == 2 × tick_size is valid."""
        p = QuotePricer(tick_size=0.01, gap=0.02, drift_ticks=3)
        assert p is not None

    def test_tick_size_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="tick_size must be positive"):
            QuotePricer(tick_size=0.0, gap=0.10, drift_ticks=3)

    def test_tick_size_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="tick_size must be positive"):
            QuotePricer(tick_size=-0.01, gap=0.10, drift_ticks=3)

    def test_drift_ticks_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="drift_ticks must be >= 1"):
            QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=0)


class TestQuotePricerMid:
    """Test mid-price tracking."""

    def test_mid_from_book(self) -> None:
        """update_mid(bid, ask) uses average when both sides present."""
        p = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        p.update_mid(149.95, 150.05)
        assert p.mid_price == pytest.approx(150.00)

    def test_mid_from_ask_only(self) -> None:
        """Falls back to ask when no bid."""
        p = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        p.update_mid(None, 150.05)
        assert p.mid_price == pytest.approx(150.05)

    def test_mid_from_bid_only(self) -> None:
        """Falls back to bid when no ask."""
        p = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        p.update_mid(149.95, None)
        assert p.mid_price == pytest.approx(149.95)

    def test_mid_no_data_keeps_previous(self) -> None:
        """No book data keeps previous mid."""
        p = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        p.set_mid(100.0)
        p.update_mid(None, None)
        assert p.mid_price == pytest.approx(100.0)

    def test_mid_initially_none(self) -> None:
        """Mid is None before any update."""
        p = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        assert p.mid_price is None

    def test_set_mid(self) -> None:
        """set_mid sets mid directly."""
        p = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        p.set_mid(99.50)
        assert p.mid_price == pytest.approx(99.50)


class TestQuotePricerPrices:
    """Test quote price computation."""

    def test_prices_symmetric(self) -> None:
        """bid = mid − gap/2, ask = mid + gap/2, both tick-aligned."""
        p = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        p.set_mid(150.00)
        bid, ask = p.compute_prices()
        assert bid == pytest.approx(149.95)
        assert ask == pytest.approx(150.05)

    def test_prices_symmetric_wider_gap(self) -> None:
        """Verify with gap=0.20."""
        p = QuotePricer(tick_size=0.01, gap=0.20, drift_ticks=3)
        p.set_mid(100.00)
        bid, ask = p.compute_prices()
        assert bid == pytest.approx(99.90)
        assert ask == pytest.approx(100.10)

    def test_prices_minimum_spread(self) -> None:
        """Rounding never produces bid >= ask; always at least 2 ticks apart."""
        # Use a case where mid is exactly on a tick boundary with minimal gap
        p = QuotePricer(tick_size=0.01, gap=0.02, drift_ticks=3)
        p.set_mid(100.00)
        bid, ask = p.compute_prices()
        assert ask - bid >= 2 * 0.01
        assert bid < ask

    def test_prices_minimum_spread_odd_mid(self) -> None:
        """Even with an odd mid, spread is at least 2 ticks."""
        p = QuotePricer(tick_size=0.01, gap=0.02, drift_ticks=3)
        p.set_mid(100.005)  # between ticks
        bid, ask = p.compute_prices()
        assert ask - bid >= 2 * 0.01 - 1e-9
        assert bid < ask

    def test_prices_tick_aligned(self) -> None:
        """Results are aligned to tick_size."""
        p = QuotePricer(tick_size=0.05, gap=0.20, drift_ticks=3)
        p.set_mid(100.00)
        bid, ask = p.compute_prices()
        # Check divisibility with tolerance for floating point
        assert abs(round(bid / 0.05) * 0.05 - bid) < 1e-9
        assert abs(round(ask / 0.05) * 0.05 - ask) < 1e-9

    def test_prices_no_mid_raises(self) -> None:
        """compute_prices without mid raises RuntimeError."""
        p = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        with pytest.raises(RuntimeError, match="No mid-price"):
            p.compute_prices()

    def test_prices_large_tick(self) -> None:
        """Works with tick_size=1.0."""
        p = QuotePricer(tick_size=1.0, gap=4.0, drift_ticks=2)
        p.set_mid(50.0)
        bid, ask = p.compute_prices()
        assert bid == pytest.approx(48.0)
        assert ask == pytest.approx(52.0)
        assert ask - bid >= 2 * 1.0


class TestQuotePricerDrift:
    """Test drift detection."""

    def test_drift_detected(self) -> None:
        """has_drifted() returns True when mid moves by > drift_ticks ticks."""
        p = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        p.set_mid(150.04)  # moved 4 ticks from 150.00
        assert p.has_drifted(150.00) is True

    def test_drift_not_detected(self) -> None:
        """Returns False when mid moves within threshold."""
        p = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        p.set_mid(150.02)  # moved 2 ticks from 150.00
        assert p.has_drifted(150.00) is False

    def test_drift_exactly_at_threshold(self) -> None:
        """Exactly at threshold (not exceeded) returns False."""
        p = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        p.set_mid(150.02)  # moved exactly 2 ticks (within threshold of 3)
        assert p.has_drifted(150.00) is False

    def test_drift_just_over_threshold(self) -> None:
        """Just over threshold (3 ticks + epsilon) returns True."""
        p = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        p.set_mid(150.031)  # moved 3.1 ticks — exceeds 3
        assert p.has_drifted(150.00) is True

    def test_drift_negative_direction(self) -> None:
        """Drift detection works in both directions."""
        p = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        p.set_mid(149.96)  # moved 4 ticks down
        assert p.has_drifted(150.00) is True

    def test_drift_no_mid_returns_false(self) -> None:
        """No mid-price means no drift."""
        p = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        assert p.has_drifted(150.00) is False


class TestBootstrapRangeValidation:
    """Test bootstrap range parameter validation."""

    def test_bootstrap_random_range_validation_only_min(self) -> None:
        """Only initial_min without initial_max raises ValueError."""
        with pytest.raises(ValueError, match="Both.*must be provided together"):
            QuotePricer.validate_bootstrap_range(95.0, None)

    def test_bootstrap_random_range_validation_only_max(self) -> None:
        """Only initial_max without initial_min raises ValueError."""
        with pytest.raises(ValueError, match="Both.*must be provided together"):
            QuotePricer.validate_bootstrap_range(None, 105.0)

    def test_bootstrap_random_range_validation_min_equals_max(self) -> None:
        """min == max raises ValueError."""
        with pytest.raises(ValueError, match="must be less than"):
            QuotePricer.validate_bootstrap_range(100.0, 100.0)

    def test_bootstrap_random_range_validation_min_greater_max(self) -> None:
        """min > max raises ValueError."""
        with pytest.raises(ValueError, match="must be less than"):
            QuotePricer.validate_bootstrap_range(110.0, 100.0)

    def test_bootstrap_random_range_validation_valid(self) -> None:
        """Valid range does not raise."""
        QuotePricer.validate_bootstrap_range(95.0, 105.0)

    def test_bootstrap_random_range_validation_both_none(self) -> None:
        """Both None is valid (no bootstrap range configured)."""
        QuotePricer.validate_bootstrap_range(None, None)


class TestQuotePricerDecimals:
    """Test price decimals derivation from tick_size."""

    def test_decimals_from_tick_001(self) -> None:
        p = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        assert p._price_decimals == 2

    def test_decimals_from_tick_0001(self) -> None:
        p = QuotePricer(tick_size=0.001, gap=0.01, drift_ticks=3)
        assert p._price_decimals == 3

    def test_decimals_from_tick_005(self) -> None:
        p = QuotePricer(tick_size=0.05, gap=0.20, drift_ticks=3)
        assert p._price_decimals == 2

    def test_decimals_from_tick_1(self) -> None:
        p = QuotePricer(tick_size=1.0, gap=4.0, drift_ticks=2)
        assert p._price_decimals == 0


# ========================================================================
# Tests — main.py argument parsing and validation
# ========================================================================


class TestMainParsing:
    """Test CLI argument parsing and validation in main.py."""

    def test_main_minimal_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Minimal args produce correct gateway_id and launch bot.run()."""
        from edumatcher.mm_bot import main as mm_main

        bot_instances: list[object] = []

        class FakeBot:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs
                bot_instances.append(self)
                self._running = True

            def run(self) -> int:
                return 0

            def shutdown(self) -> None:
                pass

        monkeypatch.setattr("edumatcher.mm_bot.bot.MMBot", FakeBot)
        with pytest.raises(SystemExit) as exc_info:
            mm_main.main(["--symbol", "AAPL"])
        assert exc_info.value.code == 0
        assert len(bot_instances) == 1
        bot = bot_instances[0]
        assert bot.kwargs["gateway_id"] == "MM_AAPL_01"  # type: ignore[attr-defined]
        assert bot.kwargs["symbol"] == "AAPL"  # type: ignore[attr-defined]
        assert bot.kwargs["gap"] == 0.10  # type: ignore[attr-defined]
        assert bot.kwargs["qty"] == 500  # type: ignore[attr-defined]

    def test_main_custom_suffix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--id-suffix changes gateway_id."""
        from edumatcher.mm_bot import main as mm_main

        bot_instances: list[object] = []

        class FakeBot:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs
                bot_instances.append(self)
                self._running = True

            def run(self) -> int:
                return 0

            def shutdown(self) -> None:
                pass

        monkeypatch.setattr("edumatcher.mm_bot.bot.MMBot", FakeBot)
        with pytest.raises(SystemExit):
            mm_main.main(["--symbol", "MSFT", "--id-suffix", "03"])
        bot = bot_instances[0]
        assert bot.kwargs["gateway_id"] == "MM_MSFT_03"  # type: ignore[attr-defined]

    def test_main_invalid_bootstrap_range(self) -> None:
        """Only initial_min without max raises SystemExit via ValueError."""
        from edumatcher.mm_bot import main as mm_main

        with pytest.raises((SystemExit, ValueError)):
            mm_main.main(["--symbol", "AAPL", "--initial_min", "95.0"])

    def test_main_negative_session_timeout(self) -> None:
        """Negative --startup-session-timeout-sec exits with error."""
        from edumatcher.mm_bot import main as mm_main

        with pytest.raises(SystemExit) as exc_info:
            mm_main.main(["--symbol", "AAPL", "--startup-session-timeout-sec", "-1"])
        assert exc_info.value.code == 1

    def test_main_negative_bootstrap_timeout(self) -> None:
        """Negative --bootstrap-timeout-sec exits with error."""
        from edumatcher.mm_bot import main as mm_main

        with pytest.raises(SystemExit) as exc_info:
            mm_main.main(["--symbol", "AAPL", "--bootstrap-timeout-sec", "-1"])
        assert exc_info.value.code == 1

    def test_main_negative_qlegs_interval(self) -> None:
        """Negative --qlegs-reconcile-interval-sec exits with error."""
        from edumatcher.mm_bot import main as mm_main

        with pytest.raises(SystemExit) as exc_info:
            mm_main.main(["--symbol", "AAPL", "--qlegs-reconcile-interval-sec", "-1"])
        assert exc_info.value.code == 1


# ========================================================================
# Tests — MMBot integration tests (Phase 2-5)
# ========================================================================


class _FakeSock:
    """Mock ZMQ socket for testing."""

    def __init__(self) -> None:
        self.sent: list[list[bytes]] = []
        self.closed = False
        self.recv_queue: list[list[bytes]] = []
        self._subscriptions: list[str] = []

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def recv_multipart(self) -> list[bytes]:
        if self.recv_queue:
            return self.recv_queue.pop(0)
        return [b"", b"{}"]

    def close(self) -> None:
        self.closed = True

    def setsockopt(self, opt: int, val: bytes) -> None:
        self._subscriptions.append(val.decode())

    def connect(self, addr: str) -> None:
        pass


class _FakePoller:
    """Mock ZMQ Poller that returns events from queue.

    After the queue is exhausted, sets bot._running = False after max_empty polls.
    """

    def __init__(self, sub_sock: _FakeSock, bot: MMBot | None = None) -> None:
        self._sub_sock = sub_sock
        self._bot = bot
        self._empty_count = 0
        self._max_empty = 2  # stop after 2 empty polls

    def register(self, _sock: object, _event: object) -> None:
        pass

    def poll(self, timeout: int = 0) -> list[tuple[object, int]]:
        if self._sub_sock.recv_queue:
            self._empty_count = 0
            return [(self._sub_sock, 1)]
        self._empty_count += 1
        if self._bot and self._empty_count >= self._max_empty:
            self._bot._running = False
        return []


def _make_bot(
    monkeypatch: pytest.MonkeyPatch,
    *,
    initial_min: float | None = None,
    initial_max: float | None = None,
    gap_was_explicit: bool = True,
    verbose: bool = False,
    startup_session_timeout_sec: float = 0.1,
    bootstrap_timeout_sec: float = 0.1,
) -> tuple[MMBot, _FakeSock, _FakeSock]:
    """Create a bot with mocked sockets."""
    import edumatcher.mm_bot.bot as bot_mod

    push = _FakeSock()
    sub = _FakeSock()

    monkeypatch.setattr(bot_mod, "make_pusher", lambda _addr: push)
    monkeypatch.setattr(bot_mod, "make_subscriber", lambda _addr, *_topics: sub)

    # Use a container so the poller can reference the bot after creation
    bot_ref: list[MMBot | None] = [None]

    def _make_poller() -> _FakePoller:
        return _FakePoller(sub, bot_ref[0])

    monkeypatch.setattr("edumatcher.mm_bot.bot.zmq.Poller", _make_poller)

    bot = MMBot(
        gateway_id="MM_AAPL_01",
        symbol="AAPL",
        gap=0.10,
        gap_was_explicit=gap_was_explicit,
        qty=500,
        drift_ticks=3,
        reissue_delay_ms=200,
        tif="DAY",
        heartbeat_interval_sec=5.0,
        startup_session_timeout_sec=startup_session_timeout_sec,
        bootstrap_timeout_sec=bootstrap_timeout_sec,
        cancel_timeout_sec=1.0,
        shutdown_timeout_sec=0.1,
        qlegs_reconcile_interval_sec=15.0,
        initial_min=initial_min,
        initial_max=initial_max,
        engine_pull="tcp://127.0.0.1:5555",
        engine_pub="tcp://127.0.0.1:5556",
        verbose=verbose,
    )
    bot_ref[0] = bot
    return bot, push, sub


def _auth_msg(accepted: bool = True) -> list[bytes]:
    return encode("system.gateway_auth.MM_AAPL_01", {"accepted": accepted})


def _symbols_msg(symbols: list[str] | None = None) -> list[bytes]:
    return encode(
        "system.symbols.MM_AAPL_01",
        {"symbols": symbols or ["AAPL", "MSFT"]},
    )


def _session_msg(state: str = "CONTINUOUS") -> list[bytes]:
    return encode("session.state", {"state": state})


def _boot_msg(quotes: list[dict[str, Any]] | None = None) -> list[bytes]:
    return encode(
        "system.quote_bootstrap.MM_AAPL_01",
        {"quotes": quotes or []},
    )


def _qlegs_msg(legs: list[dict[str, Any]] | None = None) -> list[bytes]:
    return encode("system.quote_legs.MM_AAPL_01", {"legs": legs or []})


def _book_msg(
    best_bid: float | None = None, best_ask: float | None = None
) -> list[bytes]:
    bids = [{"price": best_bid}] if best_bid is not None else []
    asks = [{"price": best_ask}] if best_ask is not None else []
    return encode("book.AAPL", {"bids": bids, "asks": asks})


def _setup_full_startup(sub: _FakeSock, session: str = "CONTINUOUS") -> None:
    """Queue messages for a successful startup sequence."""
    sub.recv_queue.extend(
        [
            _auth_msg(),
            _symbols_msg(),
            _boot_msg(),
            _qlegs_msg(),
            _session_msg(session),
        ]
    )


class TestMMBotStartup:
    """Integration tests for bot startup sequence."""

    def test_startup_sends_gateway_connect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On run(), the first PUSH message is system.gateway_connect."""
        bot, push, sub = _make_bot(monkeypatch, initial_min=95.0, initial_max=105.0)
        _setup_full_startup(sub)
        # Stop bot after startup
        bot._running = False  # will be set True in run(), but _run_loop exits
        # We need to let the bot start and then stop
        sub.recv_queue.append(_book_msg(149.95, 150.05))

        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None
        )
        bot.run()

        # First sent message should be gateway_connect
        assert len(push.sent) >= 1

        topic, payload = msg_decode(push.sent[0])
        assert topic == "system.gateway_connect"
        assert payload["gateway_id"] == "MM_AAPL_01"

    def test_auth_failure_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bot exits cleanly if gateway_auth.accepted = false."""
        bot, push, sub = _make_bot(monkeypatch)
        sub.recv_queue.append(_auth_msg(accepted=False))

        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None
        )
        rc = bot.run()
        assert rc == 1

    def test_qboot_request_sent_on_startup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bot sends QBOOT request after auth+symbols."""
        bot, push, sub = _make_bot(monkeypatch, initial_min=95.0, initial_max=105.0)
        _setup_full_startup(sub)

        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None
        )
        bot.run()

        topics_sent = [msg_decode(m)[0] for m in push.sent]
        assert "system.quote_bootstrap_request" in topics_sent

    def test_qlegs_request_sent_after_qboot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bot sends QLEGS request after QBOOT."""
        bot, push, sub = _make_bot(monkeypatch, initial_min=95.0, initial_max=105.0)
        _setup_full_startup(sub)

        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None
        )
        bot.run()

        topics_sent = [msg_decode(m)[0] for m in push.sent]
        assert "system.quote_legs_request" in topics_sent
        # QLEGS after QBOOT
        boot_idx = topics_sent.index("system.quote_bootstrap_request")
        legs_idx = topics_sent.index("system.quote_legs_request")
        assert legs_idx > boot_idx

    def test_adopt_existing_active_quote_from_bootstrap(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bootstrap reply with active quote causes adoption (no duplicate QUOTE)."""
        bot, push, sub = _make_bot(monkeypatch)
        active_quote = {
            "symbol": "AAPL",
            "state": "ACTIVE",
            "quote_id": "q-existing",
            "bid_order_id": "bid-001",
            "ask_order_id": "ask-001",
            "bid_price": 149.95,
            "ask_price": 150.05,
        }
        sub.recv_queue.extend(
            [
                _auth_msg(),
                _symbols_msg(),
                _boot_msg([active_quote]),
                _qlegs_msg(
                    [{"quote_id": "q-existing", "order_id": "bid-001", "side": "BUY"}]
                ),
                _session_msg("CONTINUOUS"),
            ]
        )

        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None
        )
        bot.run()

        topics_sent = [msg_decode(m)[0] for m in push.sent]
        # Should NOT send quote.new since we adopted
        assert "quote.new" not in topics_sent
        assert bot._quote_id == "q-existing"

    def test_startup_qboot_timeout_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Missing QBOOT reply past timeout falls back to random range."""
        bot, push, sub = _make_bot(
            monkeypatch,
            initial_min=95.0,
            initial_max=105.0,
            bootstrap_timeout_sec=0.01,
        )
        # No QBOOT reply — just auth, symbols, (skip boot), qlegs, session
        sub.recv_queue.extend(
            [
                _auth_msg(),
                _symbols_msg(),
                # No boot reply here — will time out
                _qlegs_msg(),
                _session_msg("CONTINUOUS"),
            ]
        )

        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None
        )
        bot.run()

        # Bot should have started and used random range

        topics_sent = [msg_decode(m)[0] for m in push.sent]
        assert "quote.new" in topics_sent

    def test_startup_fails_without_bootstrap_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No reference and no range configured → clean startup failure."""
        bot, push, sub = _make_bot(monkeypatch)  # no initial_min/max
        sub.recv_queue.extend(
            [
                _auth_msg(),
                _symbols_msg(),
                _boot_msg(),  # empty
                _qlegs_msg(),
                _session_msg("CONTINUOUS"),
            ]
        )

        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None
        )
        rc = bot.run()
        assert rc == 1

    def test_startup_fails_without_session_snapshot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No session.state before timeout → clean startup failure."""
        bot, push, sub = _make_bot(
            monkeypatch,
            initial_min=95.0,
            initial_max=105.0,
            startup_session_timeout_sec=0.01,
        )
        sub.recv_queue.extend(
            [
                _auth_msg(),
                _symbols_msg(),
                _boot_msg(),
                _qlegs_msg(),
                # No session.state message
            ]
        )

        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None
        )
        rc = bot.run()
        assert rc == 1

    def test_gap_defaulted_from_mm_obligation_when_not_explicit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without explicit --gap, bot defaults to half mm_max_spread_ticks*tick_size."""
        bot, push, sub = _make_bot(
            monkeypatch,
            initial_min=95.0,
            initial_max=105.0,
            gap_was_explicit=False,
        )
        sub.recv_queue.extend(
            [
                _auth_msg(),
                encode(
                    "system.symbols.MM_AAPL_01",
                    {
                        "symbols": ["AAPL", "MSFT"],
                        "symbol_meta": {
                            "AAPL": {"tick_size": 0.01, "mm_max_spread_ticks": 8}
                        },
                    },
                ),
                _boot_msg(),
                _qlegs_msg(),
                _session_msg("CONTINUOUS"),
            ]
        )

        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None
        )
        bot.run()

        assert bot.gap == pytest.approx(0.04)

    def test_startup_fails_when_explicit_gap_exceeds_obligation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Explicit gap wider than mm_max_spread_ticks*tick_size fails fast."""
        bot, push, sub = _make_bot(
            monkeypatch,
            initial_min=95.0,
            initial_max=105.0,
            gap_was_explicit=True,
        )
        bot.gap = 0.20
        sub.recv_queue.extend(
            [
                _auth_msg(),
                encode(
                    "system.symbols.MM_AAPL_01",
                    {
                        "symbols": ["AAPL", "MSFT"],
                        "symbol_meta": {
                            "AAPL": {"tick_size": 0.01, "mm_max_spread_ticks": 10}
                        },
                    },
                ),
            ]
        )

        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None
        )
        rc = bot.run()
        assert rc == 1


class TestMMBotQuoting:
    """Integration tests for quoting lifecycle."""

    def _start_bot(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        initial_min: float = 95.0,
        initial_max: float = 105.0,
    ) -> tuple[MMBot, _FakeSock, _FakeSock]:
        """Helper: create a bot and run startup, returning started bot."""
        bot, push, sub = _make_bot(
            monkeypatch, initial_min=initial_min, initial_max=initial_max
        )
        _setup_full_startup(sub)

        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None
        )
        # Don't actually run the event loop — just do startup
        bot._setup_sockets = lambda: None
        bot._push_sock = push
        bot._sub_sock = sub
        bot._close_sockets = lambda: None

        # Manually run startup steps
        assert bot._authenticate(timeout_sec=0.1)
        bot._request_symbols(timeout_sec=0.1)

        bot._pricer = QuotePricer(
            tick_size=0.01, gap=bot.gap, drift_ticks=bot.drift_ticks
        )
        bot._request_bootstrap()
        bot._request_qlegs()
        bot._session_state = "CONTINUOUS"
        bot._resolve_bootstrap_reference(None)
        bot._state = BotState.QUOTING
        bot._running = True

        return bot, push, sub

    def test_quote_issued_after_book_update(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bot sends QUOTE after receiving book data in CONTINUOUS."""
        bot, push, sub = _make_bot(monkeypatch, initial_min=95.0, initial_max=105.0)
        _setup_full_startup(sub)
        # Add book update so mid is set before quote
        sub.recv_queue.insert(4, _book_msg(149.95, 150.05))

        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None
        )
        bot.run()

        topics_sent = [msg_decode(m)[0] for m in push.sent]
        assert "quote.new" in topics_sent

    def test_bootstrap_from_random_range(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Empty book/trade + random range → bot samples and quotes."""
        bot, push, sub = _make_bot(monkeypatch, initial_min=95.0, initial_max=105.0)
        _setup_full_startup(sub)

        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None
        )
        bot.run()

        topics_sent = [msg_decode(m)[0] for m in push.sent]
        assert "quote.new" in topics_sent

    def test_reissue_after_fill(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """order.fill → timer fires → cancel then quote.new replace sent."""
        bot, push, sub = self._start_bot(monkeypatch)
        bot._quote_id = "q-001"
        bot._bid_order_id = "bid-001"
        bot._ask_order_id = "ask-001"
        bot._quoted_at_mid = 100.0
        assert bot._pricer is not None
        bot._pricer.set_mid(100.0)

        # Simulate fill
        fill_payload: dict[str, Any] = {
            "order_id": "ask-001",
            "fill_qty": 100,
            "fill_price": 100.05,
            "remaining_qty": 400,
        }
        bot._handle_order_fill(fill_payload)
        assert bot._reissue_at is not None

        # Simulate timer firing
        bot._reissue_at = 0  # force immediate
        push.sent.clear()
        bot._tick()

        assert len(push.sent) >= 1
        topic0, _ = msg_decode(push.sent[-1])
        assert topic0 == "quote.cancel"

        bot._reissue_at = 0  # force cancel-timeout path
        bot._tick()
        topic1, _ = msg_decode(push.sent[-1])
        assert topic1 == "quote.new"

    def test_reissue_batches_rapid_fills(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Three fills in rapid succession produce exactly one reissue."""
        bot, push, sub = self._start_bot(monkeypatch)
        bot._quote_id = "q-001"
        bot._bid_order_id = "bid-001"
        bot._ask_order_id = "ask-001"
        bot._quoted_at_mid = 100.0
        assert bot._pricer is not None
        bot._pricer.set_mid(100.0)

        # Three rapid fills
        for i in range(3):
            bot._handle_order_fill(
                {
                    "order_id": "ask-001",
                    "fill_qty": 50,
                    "fill_price": 100.05,
                    "remaining_qty": 350 - i * 50,
                }
            )

        # Only one reissue_at should be set (the last one)
        assert bot._reissue_at is not None

        # Fire first tick -> cancel
        bot._reissue_at = 0
        push.sent.clear()
        bot._tick()

        cancel_sends = [m for m in push.sent if msg_decode(m)[0] == "quote.cancel"]
        assert len(cancel_sends) == 1

        # Fire second tick -> forced replacement
        bot._reissue_at = 0
        bot._tick()

        quote_sends = [m for m in push.sent if msg_decode(m)[0] == "quote.new"]
        assert len(quote_sends) == 1

    def test_fill_before_ack_buffering(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """order.fill received before quote.ack is buffered and processed on ack."""
        bot, push, sub = self._start_bot(monkeypatch)
        bot._quote_id = None
        bot._bid_order_id = None
        bot._ask_order_id = None
        assert bot._pricer is not None
        bot._pricer.set_mid(100.0)

        # Fill arrives before ack
        bot._handle_order_fill(
            {
                "order_id": "ask-001",
                "fill_qty": 100,
                "fill_price": 100.05,
                "remaining_qty": 400,
            }
        )
        assert len(bot._pending_fills) == 1
        assert bot._reissue_at is None

        # Now ack arrives
        bot._handle_quote_ack(
            {
                "accepted": True,
                "quote_id": "q-001",
                "bid_order_id": "bid-001",
                "ask_order_id": "ask-001",
            }
        )
        # Fill should have been processed
        assert len(bot._pending_fills) == 0
        assert bot._reissue_at is not None

    def test_drift_triggers_reprice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mid moves 4 ticks → quote.new replace at new mid."""
        bot, push, sub = self._start_bot(monkeypatch)
        bot._quote_id = "q-001"
        bot._bid_order_id = "bid-001"
        bot._ask_order_id = "ask-001"
        bot._quoted_at_mid = 100.0
        assert bot._pricer is not None
        bot._pricer.set_mid(100.0)
        bot._state = BotState.QUOTING

        push.sent.clear()
        # Book update with 4-tick drift
        book_payload: dict[str, Any] = {
            "bids": [{"price": 100.03}],
            "asks": [{"price": 100.05}],
        }
        bot._dispatch("book.AAPL", book_payload)

        # Reprice path now sends cancel first.
        cancel_sends = [m for m in push.sent if msg_decode(m)[0] == "quote.cancel"]
        assert len(cancel_sends) == 1

        # Simulate cancel-timeout fallback and replacement quote.
        bot._reissue_at = 0
        bot._tick()
        quote_sends = [m for m in push.sent if msg_decode(m)[0] == "quote.new"]
        assert len(quote_sends) == 1
        assert bot._state in (BotState.REISSUING, BotState.REPRICING)


class TestMMBotSessionHandling:
    """Tests for session state and circuit breaker handling."""

    def _started_bot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[MMBot, _FakeSock, _FakeSock]:
        bot, push, sub = _make_bot(monkeypatch, initial_min=95.0, initial_max=105.0)

        bot._push_sock = push
        bot._sub_sock = sub
        bot._running = True
        bot._session_state = "CONTINUOUS"
        bot._state = BotState.QUOTING
        bot._quote_id = "q-001"
        bot._bid_order_id = "bid-001"
        bot._ask_order_id = "ask-001"

        bot._pricer = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        assert bot._pricer is not None
        bot._pricer.set_mid(100.0)
        bot._quoted_at_mid = 100.0
        return bot, push, sub

    def test_no_quote_in_auction(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bot in QUOTING receives session=OPENING_AUCTION → CANCEL, no reissue."""
        bot, push, sub = self._started_bot(monkeypatch)
        push.sent.clear()

        bot._handle_session_state({"state": "OPENING_AUCTION"})

        assert bot._state == BotState.PAUSED
        cancel_sends = [m for m in push.sent if msg_decode(m)[0] == "quote.cancel"]
        assert len(cancel_sends) == 1
        quote_sends = [m for m in push.sent if msg_decode(m)[0] == "quote.new"]
        assert len(quote_sends) == 0

    def test_resume_from_pause(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """session.state=CONTINUOUS from PAUSED → bot re-enters quoting path."""
        bot, push, sub = self._started_bot(monkeypatch)
        bot._state = BotState.PAUSED
        bot._quote_id = None

        bot._handle_session_state({"state": "CONTINUOUS"})

        assert bot._state == BotState.WAITING_FOR_SESSION
        assert bot._reissue_at is not None  # scheduled reissue

    def test_halt_cancels_quote(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """circuit_breaker.halt.AAPL → CANCEL, state=PAUSED."""
        bot, push, sub = self._started_bot(monkeypatch)
        push.sent.clear()

        bot._handle_circuit_breaker_halt()

        assert bot._state == BotState.PAUSED
        cancel_sends = [m for m in push.sent if msg_decode(m)[0] == "quote.cancel"]
        assert len(cancel_sends) == 1

    def test_resume_after_halt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """circuit_breaker.resume.AAPL → state=WAITING_FOR_SESSION."""
        bot, push, sub = self._started_bot(monkeypatch)
        bot._state = BotState.PAUSED

        bot._handle_circuit_breaker_resume()

        assert bot._state == BotState.WAITING_FOR_SESSION

    def test_graceful_shutdown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """bot.shutdown() → sets _running=False; _do_shutdown sends CANCEL."""
        bot, push, sub = self._started_bot(monkeypatch)
        push.sent.clear()

        # Add a quote.status reply for shutdown
        sub.recv_queue.append(
            encode("quote.status.MM_AAPL_01", {"status": "CANCELLED"})
        )
        bot._do_shutdown()

        cancel_sends = [m for m in push.sent if msg_decode(m)[0] == "quote.cancel"]
        assert len(cancel_sends) == 1

    def test_gap_obligation_check(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Bot validates gap at pricer construction (gap < 2*tick fails)."""
        # This is handled by QuotePricer construction validation
        with pytest.raises(ValueError, match="gap.*must be at least"):
            QuotePricer(tick_size=0.01, gap=0.01, drift_ticks=3)


class TestMMBotQlegsReconciliation:
    """Tests for QLEGS reconciliation logic."""

    def test_qlegs_mismatch_triggers_safe_reconcile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Divergence between local and QLEGS triggers reissue."""
        bot, push, sub = _make_bot(monkeypatch, initial_min=95.0, initial_max=105.0)

        bot._push_sock = push
        bot._sub_sock = sub
        bot._running = True
        bot._state = BotState.QUOTING
        bot._quote_id = "q-001"
        bot._bid_order_id = "bid-001"
        bot._ask_order_id = "ask-001"

        bot._pricer = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        assert bot._pricer is not None
        bot._pricer.set_mid(100.0)

        # QLEGS response with a different quote_id
        bot._reconcile_qlegs(
            {"legs": [{"quote_id": "q-OTHER", "order_id": "x", "side": "BUY"}]}
        )

        # Should have cleared local state and scheduled reissue
        assert bot._quote_id is None
        assert bot._reissue_at is not None

    def test_qlegs_order_id_divergence_triggers_reconcile(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """QLEGS legs with same quote_id but different leg IDs must reissue."""
        bot, push, sub = _make_bot(monkeypatch, initial_min=95.0, initial_max=105.0)

        bot._push_sock = push
        bot._sub_sock = sub
        bot._running = True
        bot._state = BotState.QUOTING
        bot._quote_id = "q-001"
        bot._bid_order_id = "bid-001"
        bot._ask_order_id = "ask-001"

        bot._pricer = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        assert bot._pricer is not None
        bot._pricer.set_mid(100.0)

        bot._reconcile_qlegs(
            {
                "legs": [
                    {"quote_id": "q-001", "order_id": "bid-OTHER", "side": "BUY"},
                    {"quote_id": "q-001", "order_id": "ask-OTHER", "side": "SELL"},
                ]
            }
        )

        assert bot._quote_id is None
        assert bot._reissue_at is not None


# ========================================================================
# Additional coverage tests
# ========================================================================


class TestMMBotDispatch:
    """Tests for dispatch and event handler coverage."""

    def _ready_bot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[MMBot, _FakeSock, _FakeSock]:
        bot, push, sub = _make_bot(monkeypatch, initial_min=95.0, initial_max=105.0)
        bot._push_sock = push
        bot._sub_sock = sub
        bot._running = True
        bot._session_state = "CONTINUOUS"
        bot._state = BotState.QUOTING
        bot._quote_id = "q-001"
        bot._bid_order_id = "bid-001"
        bot._ask_order_id = "ask-001"
        bot._pricer = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        assert bot._pricer is not None
        bot._pricer.set_mid(100.0)
        bot._quoted_at_mid = 100.0
        return bot, push, sub

    def test_dispatch_trade_executed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Dispatch trade.executed updates mid when no book data."""
        bot, push, sub = self._ready_bot(monkeypatch)
        assert bot._pricer is not None
        bot._pricer._mid_price = None  # reset mid

        bot._dispatch("trade.executed", {"symbol": "AAPL", "price": 99.50})
        assert bot._pricer.mid_price == pytest.approx(99.50)

    def test_dispatch_trade_wrong_symbol_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """trade.executed for different symbol is ignored."""
        bot, push, sub = self._ready_bot(monkeypatch)
        assert bot._pricer is not None
        bot._pricer._mid_price = None

        bot._dispatch("trade.executed", {"symbol": "MSFT", "price": 50.0})
        assert bot._pricer.mid_price is None

    def test_dispatch_order_cancelled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """order.cancelled for our leg is handled."""
        bot, push, sub = self._ready_bot(monkeypatch)
        bot._dispatch(
            "order.cancelled.MM_AAPL_01",
            {"order_id": "bid-001"},
        )
        # Just verify no crash

    def test_dispatch_quote_status_cancelled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """quote.status CANCELLED triggers reissue."""
        bot, push, sub = self._ready_bot(monkeypatch)
        bot._dispatch(
            "quote.status.MM_AAPL_01",
            {"status": "CANCELLED"},
        )
        assert bot._reissue_at is not None
        assert bot._quote_id is None

    def test_dispatch_quote_ack_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """quote.ack with accepted=false schedules retry."""
        bot, push, sub = self._ready_bot(monkeypatch)
        bot._dispatch(
            "quote.ack.MM_AAPL_01",
            {"accepted": False, "reason": "invalid symbol"},
        )
        assert bot._reissue_at is not None

    def test_dispatch_circuit_breaker_halt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dispatch circuit_breaker.halt.AAPL."""
        bot, push, sub = self._ready_bot(monkeypatch)
        push.sent.clear()
        bot._dispatch("circuit_breaker.halt.AAPL", {})
        assert bot._state == BotState.PAUSED

    def test_dispatch_circuit_breaker_resume(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dispatch circuit_breaker.resume.AAPL."""
        bot, push, sub = self._ready_bot(monkeypatch)
        bot._state = BotState.PAUSED
        bot._dispatch("circuit_breaker.resume.AAPL", {})
        assert bot._state == BotState.WAITING_FOR_SESSION

    def test_dispatch_session_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Dispatch session.state to CLOSED triggers PAUSED."""
        bot, push, sub = self._ready_bot(monkeypatch)
        push.sent.clear()
        bot._dispatch("session.state", {"state": "CLOSED"})
        assert bot._state == BotState.PAUSED

    def test_bootstrap_inactive_quote_as_reference(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Inactive quote from QBOOT provides reference price."""
        bot, push, sub = _make_bot(monkeypatch)
        bot._pricer = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        boot = {
            "quotes": [
                {
                    "symbol": "AAPL",
                    "state": "INACTIVE",
                    "bid_price": 99.00,
                    "ask_price": 101.00,
                }
            ]
        }
        result = bot._resolve_bootstrap_reference(boot)
        assert result is True
        assert bot._pricer is not None
        assert bot._pricer.mid_price == pytest.approx(100.0)

    def test_verbose_logging(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verbose mode logs debug messages."""
        bot, push, sub = _make_bot(
            monkeypatch, verbose=True, initial_min=95.0, initial_max=105.0
        )
        _setup_full_startup(sub)
        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None
        )
        bot.run()
        # Just verify no crash with verbose=True

    def test_tick_heartbeat_reissue(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Heartbeat triggers reissue when quote_id is None."""
        bot, push, sub = self._ready_bot(monkeypatch)
        bot._quote_id = None  # lost quote
        bot._last_heartbeat = 0.0  # force heartbeat check
        push.sent.clear()

        bot._tick()

        # Should have issued a new quote
        topics = [msg_decode(m)[0] for m in push.sent]
        assert "quote.new" in topics

    def test_tick_heartbeat_recovers_stuck_reissuing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A dropped quote.ack must not strand the bot in REISSUING forever."""
        bot, push, sub = self._ready_bot(monkeypatch)
        # Simulate having sent a quote whose ack was lost.
        bot._state = BotState.REISSUING
        bot._quote_id = None
        bot._reissue_at = None  # no pending reissue timer
        bot._last_heartbeat = 0.0  # force heartbeat check
        push.sent.clear()

        bot._tick()

        topics = [msg_decode(m)[0] for m in push.sent]
        assert "quote.new" in topics

    def test_tick_heartbeat_skips_when_reissue_pending(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Heartbeat must not fight a reissue that is already scheduled."""
        bot, push, sub = self._ready_bot(monkeypatch)
        bot._state = BotState.REISSUING
        bot._quote_id = None
        bot._reissue_at = time.monotonic() + 100.0  # pending, not yet due
        bot._last_heartbeat = 0.0
        push.sent.clear()

        bot._tick()

        topics = [msg_decode(m)[0] for m in push.sent]
        assert "quote.new" not in topics

    def test_qlegs_reconcile_no_legs_but_quote_exists(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """QLEGS returns no legs but bot thinks it has a quote → reissue."""
        bot, push, sub = self._ready_bot(monkeypatch)

        # Empty QLEGS response while we still believe we hold a quote
        bot._reconcile_qlegs({"legs": []})

        assert bot._quote_id is None
        assert bot._reissue_at is not None

    def test_fill_for_unrelated_order_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fill for an order not in our quote is ignored."""
        bot, push, sub = self._ready_bot(monkeypatch)
        bot._handle_order_fill(
            {"order_id": "unrelated-999", "fill_qty": 100, "fill_price": 100.0}
        )
        assert bot._reissue_at is None  # no reissue scheduled

    def test_session_transition_from_paused_to_continuous(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PAUSED → CONTINUOUS triggers reissue."""
        bot, push, sub = self._ready_bot(monkeypatch)
        bot._state = BotState.PAUSED
        bot._quote_id = None
        bot._handle_session_state({"state": "CONTINUOUS"})
        assert bot._state == BotState.WAITING_FOR_SESSION
        assert bot._reissue_at is not None


# ========================================================================
# Bug-fix regression tests and additional coverage
# ========================================================================


class TestFillDuringCancelInFlight:
    """Bug fix: fill must not overwrite the cancel-confirmation timeout."""

    def _ready_bot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[MMBot, _FakeSock, _FakeSock]:
        bot, push, sub = _make_bot(monkeypatch, initial_min=95.0, initial_max=105.0)
        bot._push_sock = push
        bot._sub_sock = sub
        bot._running = True
        bot._session_state = "CONTINUOUS"
        bot._state = BotState.REPRICING
        bot._quote_id = "q-001"
        bot._bid_order_id = "bid-001"
        bot._ask_order_id = "ask-001"
        bot._awaiting_cancel_for_reissue = True
        bot._pricer = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        assert bot._pricer is not None
        bot._pricer.set_mid(100.0)
        return bot, push, sub

    def test_fill_while_cancel_in_flight_does_not_overwrite_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fill arriving while _awaiting_cancel_for_reissue=True must not reset the
        cancel-confirmation timer, which would leave the bot stuck in REPRICING."""
        bot, push, sub = self._ready_bot(monkeypatch)
        bot._reissue_at = time.monotonic() + 1.0  # cancel timeout at T+1s
        original_reissue_at = bot._reissue_at

        bot._handle_order_fill(
            {"order_id": "ask-001", "fill_qty": 100, "fill_price": 100.05}
        )

        # Timer must NOT be shortened by the fill
        assert bot._reissue_at == pytest.approx(original_reissue_at, abs=1e-3)

    def test_fill_without_cancel_in_flight_sets_timer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Normal fill (no cancel in flight) still arms the reissue timer."""
        bot, push, sub = self._ready_bot(monkeypatch)
        bot._awaiting_cancel_for_reissue = False
        bot._reissue_at = None

        bot._handle_order_fill(
            {"order_id": "ask-001", "fill_qty": 100, "fill_price": 100.05}
        )

        assert bot._reissue_at is not None


class TestQuoteStatusOrphanedCancelled:
    """Bug fix: stale CANCELLED after INACTIVE already handled must be ignored."""

    def _reissuing_bot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[MMBot, _FakeSock, _FakeSock]:
        """Bot that has already processed INACTIVE — quote cleared, in REISSUING."""
        bot, push, sub = _make_bot(monkeypatch, initial_min=95.0, initial_max=105.0)
        bot._push_sock = push
        bot._sub_sock = sub
        bot._running = True
        bot._session_state = "CONTINUOUS"
        bot._state = BotState.REISSUING
        bot._quote_id = None  # already cleared by INACTIVE handler
        bot._bid_order_id = None
        bot._ask_order_id = None
        bot._awaiting_cancel_for_reissue = False
        bot._pricer = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        assert bot._pricer is not None
        bot._pricer.set_mid(100.0)
        return bot, push, sub

    def test_orphaned_cancelled_does_not_schedule_second_reissue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CANCELLED arriving after INACTIVE already cleared quote state must be
        ignored — prevents a duplicate quote.new."""
        bot, push, sub = self._reissuing_bot(monkeypatch)
        bot._reissue_at = None  # no timer already running

        bot._handle_quote_status({"status": "CANCELLED"})

        # Must NOT schedule a reissue — there is no tracked quote to cancel
        assert bot._reissue_at is None

    def test_inactive_bid_filled_schedules_reissue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """INACTIVE_BID_FILLED always schedules reissue regardless of quote_id."""
        bot, push, sub = self._reissuing_bot(monkeypatch)
        # Reset to QUOTING with active quote to simulate real INACTIVE scenario
        bot._state = BotState.QUOTING
        bot._quote_id = "q-active"
        bot._reissue_at = None

        bot._handle_quote_status({"status": "INACTIVE_BID_FILLED"})

        assert bot._reissue_at is not None
        assert bot._quote_id is None  # cleared

    def test_inactive_ask_filled_schedules_reissue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """INACTIVE_ASK_FILLED always schedules reissue."""
        bot, push, sub = self._reissuing_bot(monkeypatch)
        bot._state = BotState.QUOTING
        bot._quote_id = "q-active"
        bot._reissue_at = None

        bot._handle_quote_status({"status": "INACTIVE_ASK_FILLED"})

        assert bot._reissue_at is not None
        assert bot._quote_id is None

    def test_cancelled_with_quote_id_schedules_reissue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CANCELLED when we still track a quote schedules immediate reissue."""
        bot, push, sub = self._reissuing_bot(monkeypatch)
        bot._state = BotState.QUOTING
        bot._quote_id = "q-tracked"
        bot._reissue_at = None

        bot._handle_quote_status({"status": "CANCELLED"})

        assert bot._reissue_at is not None
        assert bot._quote_id is None

    def test_cancelled_while_awaiting_cancel_ack_schedules_reissue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """CANCELLED when awaiting cancel confirmation (cancel-then-reissue path)."""
        bot, push, sub = self._reissuing_bot(monkeypatch)
        bot._state = BotState.REPRICING
        bot._quote_id = None  # cleared by cancel timeout path
        bot._awaiting_cancel_for_reissue = True
        bot._reissue_at = None

        bot._handle_quote_status({"status": "CANCELLED"})

        assert bot._reissue_at is not None
        assert bot._awaiting_cancel_for_reissue is False

    def test_quote_status_paused_state_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Any status received while PAUSED is silently ignored."""
        bot, push, sub = self._reissuing_bot(monkeypatch)
        bot._state = BotState.PAUSED
        bot._quote_id = "q-active"

        bot._handle_quote_status({"status": "CANCELLED"})

        assert bot._reissue_at is None
        assert bot._quote_id == "q-active"  # not cleared

    def test_unknown_status_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Unknown status string is silently ignored."""
        bot, push, sub = self._reissuing_bot(monkeypatch)
        bot._state = BotState.QUOTING
        bot._quote_id = "q-active"

        bot._handle_quote_status({"status": "SOME_FUTURE_STATUS"})

        assert bot._reissue_at is None
        assert bot._quote_id == "q-active"


class TestRunLoopInvalidGap:
    """Bug fix: QuotePricer ValueError must be caught and return exit code 1."""

    def test_gap_smaller_than_two_ticks_after_meta_load_exits_cleanly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """tick_size loaded from engine makes gap < 2*tick_size → clean exit, not crash."""
        bot, push, sub = _make_bot(monkeypatch)
        # Inject a large tick_size that makes default gap invalid
        bot.gap = 0.10
        bot._tick_size = 0.20  # 2*tick_size = 0.40 > gap=0.10

        sub.recv_queue.extend(
            [
                _auth_msg(),
                _symbols_msg(),
                _boot_msg(),
                _qlegs_msg(),
                _session_msg("CONTINUOUS"),
            ]
        )
        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None
        )
        rc = bot.run()
        assert rc == 1


class TestHandleBookMissingPrice:
    """Bug fix: _handle_book must not raise KeyError on malformed level."""

    def test_book_level_without_price_key_treated_as_no_side(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Level dict missing 'price' key → treated as no best bid/ask for that side."""
        bot, push, sub = _make_bot(monkeypatch, initial_min=95.0, initial_max=105.0)
        bot._pricer = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        bot._pricer.set_mid(100.0)

        # Malformed book: bid level has no 'price', ask level is normal
        bot._handle_book({"bids": [{"qty": 500}], "asks": [{"price": 100.10}]})

        # ask-only mid should be 100.10
        assert bot._pricer is not None
        assert bot._pricer.mid_price == pytest.approx(100.10)

    def test_empty_book_keeps_previous_mid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty bids and asks list keeps the previous mid unchanged."""
        bot, push, sub = _make_bot(monkeypatch, initial_min=95.0, initial_max=105.0)
        bot._pricer = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        bot._pricer.set_mid(99.0)

        bot._handle_book({"bids": [], "asks": []})

        assert bot._pricer is not None
        assert bot._pricer.mid_price == pytest.approx(99.0)


class TestMainValidation:
    """Additional coverage for main.py validation paths."""

    def test_negative_reissue_delay_exits(self) -> None:
        """--reissue-delay-ms negative exits with error."""
        from edumatcher.mm_bot import main as mm_main

        with pytest.raises(SystemExit) as exc_info:
            mm_main.main(["--symbol", "AAPL", "--reissue-delay-ms", "-1"])
        assert exc_info.value.code == 1

    def test_negative_cancel_timeout_exits(self) -> None:
        """--cancel-timeout-sec negative exits with error."""
        from edumatcher.mm_bot import main as mm_main

        with pytest.raises(SystemExit) as exc_info:
            mm_main.main(["--symbol", "AAPL", "--cancel-timeout-sec", "-1"])
        assert exc_info.value.code == 1

    def test_symbol_not_in_list_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Symbol not in the engine symbol list exits with rc=1."""
        bot, push, sub = _make_bot(monkeypatch, initial_min=95.0, initial_max=105.0)
        sub.recv_queue.extend(
            [
                _auth_msg(),
                encode("system.symbols.MM_AAPL_01", {"symbols": ["MSFT", "TSLA"]}),
            ]
        )
        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None
        )
        rc = bot.run()
        assert rc == 1

    def test_main_keyboard_interrupt_calls_shutdown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """KeyboardInterrupt during bot.run() calls bot.shutdown() and exits 0."""
        from edumatcher.mm_bot import main as mm_main

        class FakeBotInterrupt:
            def __init__(self, **kwargs: object) -> None:
                self.shutdown_called = False

            def run(self) -> int:
                raise KeyboardInterrupt

            def shutdown(self) -> None:
                self.shutdown_called = True

        bot_ref: list[FakeBotInterrupt] = []

        def _make_fake(**kwargs: object) -> FakeBotInterrupt:
            b = FakeBotInterrupt(**kwargs)
            bot_ref.append(b)
            return b

        monkeypatch.setattr("edumatcher.mm_bot.bot.MMBot", _make_fake)

        with pytest.raises(SystemExit) as exc_info:
            mm_main.main(["--symbol", "AAPL"])
        assert exc_info.value.code == 0
        assert bot_ref[0].shutdown_called


class TestAdditionalBotPaths:
    """Cover remaining uncovered paths for the 88% target."""

    def _ready_bot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[MMBot, _FakeSock, _FakeSock]:
        bot, push, sub = _make_bot(monkeypatch, initial_min=95.0, initial_max=105.0)
        bot._push_sock = push
        bot._sub_sock = sub
        bot._running = True
        bot._session_state = "CONTINUOUS"
        bot._state = BotState.QUOTING
        bot._quote_id = "q-001"
        bot._bid_order_id = "bid-001"
        bot._ask_order_id = "ask-001"
        bot._pricer = QuotePricer(tick_size=0.01, gap=0.10, drift_ticks=3)
        assert bot._pricer is not None
        bot._pricer.set_mid(100.0)
        bot._quoted_at_mid = 100.0
        return bot, push, sub

    def test_cancel_and_reissue_guard_when_awaiting(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_cancel_and_reissue returns early when already awaiting cancel."""
        bot, push, sub = self._ready_bot(monkeypatch)
        bot._awaiting_cancel_for_reissue = True
        push.sent.clear()

        bot._cancel_and_reissue()

        # No additional cancel should be sent
        assert len(push.sent) == 0

    def test_tick_forces_replacement_on_cancel_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cancel timeout in REPRICING with existing quote_id forces replacement."""
        bot, push, sub = self._ready_bot(monkeypatch)
        bot._state = BotState.REPRICING
        bot._awaiting_cancel_for_reissue = True
        bot._reissue_at = 0  # expired
        push.sent.clear()

        bot._tick()

        # Should have cleared quote state and sent a new quote
        topics = [msg_decode(m)[0] for m in push.sent]
        assert "quote.new" in topics
        assert bot._quote_id is None

    def test_tick_moves_to_waiting_when_no_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reissue timer fires but session is non-CONTINUOUS → WAITING_FOR_SESSION."""
        bot, push, sub = self._ready_bot(monkeypatch)
        bot._session_state = "CLOSED"
        bot._reissue_at = 0  # expired
        push.sent.clear()

        bot._tick()

        assert bot._state == BotState.WAITING_FOR_SESSION
        assert len(push.sent) == 0

    def test_tick_periodic_qlegs_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Periodic QLEGS reconciliation request is sent from heartbeat."""
        bot, push, sub = self._ready_bot(monkeypatch)
        bot._last_qlegs_reconcile = 0.0  # force reconcile now
        push.sent.clear()

        bot._tick()

        topics = [msg_decode(m)[0] for m in push.sent]
        assert "system.quote_legs_request" in topics

    def test_dispatch_qlegs_during_main_loop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """QLEGS reply in main event loop is handled by _reconcile_qlegs."""
        bot, push, sub = self._ready_bot(monkeypatch)
        # Matching legs — no mismatch, no reissue
        bot._dispatch(
            "system.quote_legs.MM_AAPL_01",
            {
                "legs": [
                    {"quote_id": "q-001", "order_id": "bid-001", "side": "BUY"},
                    {"quote_id": "q-001", "order_id": "ask-001", "side": "SELL"},
                ]
            },
        )
        assert bot._quote_id == "q-001"
        assert bot._reissue_at is None

    def test_adopted_quote_paused_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Adopted quote with non-CONTINUOUS session starts in PAUSED."""
        bot, push, sub = _make_bot(monkeypatch)
        active_quote = {
            "symbol": "AAPL",
            "state": "ACTIVE",
            "quote_id": "q-existing",
            "bid_order_id": "bid-001",
            "ask_order_id": "ask-001",
            "bid_price": 149.95,
            "ask_price": 150.05,
        }
        sub.recv_queue.extend(
            [
                _auth_msg(),
                _symbols_msg(),
                _boot_msg([active_quote]),
                _qlegs_msg(
                    [{"quote_id": "q-existing", "order_id": "bid-001", "side": "BUY"}]
                ),
                _session_msg("CLOSED"),
            ]
        )
        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None
        )
        bot.run()

        assert bot._state == BotState.PAUSED

    def test_send_quote_no_mid_skips(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_send_quote does nothing when no mid-price is set."""
        bot, push, sub = self._ready_bot(monkeypatch)
        assert bot._pricer is not None
        bot._pricer._mid_price = None
        push.sent.clear()

        bot._send_quote()

        assert len(push.sent) == 0

    def test_handle_trade_no_op_when_mid_already_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """trade.executed is ignored when a book-derived mid is already available."""
        bot, push, sub = self._ready_bot(monkeypatch)
        # mid already set to 100.0
        bot._dispatch("trade.executed", {"symbol": "AAPL", "price": 99.0})
        # mid should NOT change
        assert bot._pricer is not None
        assert bot._pricer.mid_price == pytest.approx(100.0)

    def test_startup_qlegs_mismatch_clears_adopted_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """QLEGS at startup contradicts adopted quote → clear and reissue."""
        bot, push, sub = _make_bot(monkeypatch, initial_min=95.0, initial_max=105.0)
        active_quote = {
            "symbol": "AAPL",
            "state": "ACTIVE",
            "quote_id": "q-adopted",
            "bid_order_id": "bid-001",
            "ask_order_id": "ask-001",
            "bid_price": 149.95,
            "ask_price": 150.05,
        }
        sub.recv_queue.extend(
            [
                _auth_msg(),
                _symbols_msg(),
                _boot_msg([active_quote]),
                # QLEGS says different quote_id — mismatch!
                _qlegs_msg([{"quote_id": "q-DIFFERENT", "order_id": "bid-999"}]),
                _session_msg("CONTINUOUS"),
            ]
        )
        monkeypatch.setattr(
            "edumatcher.mm_bot.bot.signal.signal", lambda *a, **kw: None
        )
        bot.run()

        # Adopted state cleared → quote.new should have been sent
        topics_sent = [msg_decode(m)[0] for m in push.sent]
        assert "quote.new" in topics_sent
