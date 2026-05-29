from __future__ import annotations

import argparse
import time

import pytest

import edumatcher.ai_trader.main as bot_main


class _FakeSock:
    def __init__(self) -> None:
        self.sent: list[list[bytes]] = []
        self.closed = False
        self.recv_queue: list[list[bytes]] = []

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def recv_multipart(self) -> list[bytes]:
        if self.recv_queue:
            return self.recv_queue.pop(0)
        return [b"", b"{}"]

    def close(self) -> None:
        self.closed = True


class _FakePoller:
    def __init__(self, sub_sock: _FakeSock, events: list[bool]) -> None:
        self._sub_sock = sub_sock
        self._events = list(events)

    def register(self, _sock: object, _event: object) -> None:
        return

    def poll(self, timeout: int) -> list[tuple[object, int]]:
        _ = timeout
        if self._events:
            has_event = self._events.pop(0)
            if has_event:
                return [(self._sub_sock, 1)]
        return []


def _make_bot(
    monkeypatch: pytest.MonkeyPatch,
    *,
    gateway_id: str = "AI01",
    profile_name: str = "cautious",
    symbols: list[str] | None = None,
) -> tuple[bot_main.AITraderBot, _FakeSock, _FakeSock]:
    push = _FakeSock()
    sub = _FakeSock()

    monkeypatch.setattr(bot_main, "make_pusher", lambda _addr: push)
    monkeypatch.setattr(bot_main, "make_subscriber", lambda _addr, *_topics: sub)

    bot = bot_main.AITraderBot(
        gateway_id=gateway_id,
        profile_name=profile_name,
        symbols=symbols or ["AAPL"],
        seed=1,
        run_id="testrun",
        max_position=100,
        max_rejects=2,
        reject_window_sec=10.0,
        reject_cooldown_sec=1.0,
        stale_data_sec=5.0,
    )
    return bot, push, sub


class TestAITraderRuntime:
    def test_authenticate_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bot, _push, sub = _make_bot(monkeypatch)
        sub.recv_queue = [[b"system.gateway_auth.AI01", b"{}"]]

        monkeypatch.setattr(
            bot_main,
            "decode",
            lambda _frames: ("system.gateway_auth.AI01", {"accepted": True}),
        )
        monkeypatch.setattr(
            "edumatcher.ai_trader.main.zmq.Poller", lambda: _FakePoller(sub, [True])
        )

        assert bot._authenticate(timeout_sec=0.1) is True

        bot.push_sock.close()
        bot.sub_sock.close()

    def test_authenticate_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bot, _push, sub = _make_bot(monkeypatch)
        monkeypatch.setattr(
            "edumatcher.ai_trader.main.zmq.Poller",
            lambda: _FakePoller(sub, [False, False, False]),
        )

        assert bot._authenticate(timeout_sec=0.01) is False

        bot.push_sock.close()
        bot.sub_sock.close()

    def test_handle_event_paths(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bot, _push, _sub = _make_bot(monkeypatch)

        bot._handle_event(
            "book.AAPL",
            {
                "last_price": 100.1,
                "bids": [{"price": 100.0}],
                "asks": [{"price": 100.2}],
            },
        )
        bot._handle_event("trade.executed", {"symbol": "AAPL", "price": 100.15})
        bot._handle_event("system.symbols.AI01", {"symbols": ["AAPL", "MSFT"]})
        bot._handle_event("order.ack.AI01", {"accepted": True})
        bot._handle_event("order.ack.AI01", {"accepted": False})
        bot._handle_event(
            "order.fill.AI01",
            {"symbol": "AAPL", "side": "BUY", "fill_qty": 10},
        )
        bot._handle_event("order.cancelled.AI01", {})
        bot._handle_event("order.expired.AI01", {})

        assert bot.metrics.acknowledged == 1
        assert bot.metrics.rejected == 1
        assert bot.metrics.filled == 1
        assert bot.metrics.cancelled == 2
        assert bot._positions["AAPL"] == 10

        bot.push_sock.close()
        bot.sub_sock.close()

    def test_maybe_submit_order_submits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        bot, push, _sub = _make_bot(monkeypatch, profile_name="aggressive")
        now = time.monotonic()
        bot._known_symbols = ["AAPL"]
        bot._market["AAPL"] = bot_main.MarketSnapshot(
            best_bid=100.0,
            best_ask=100.2,
            last_price=100.1,
        )
        bot._last_market_update["AAPL"] = now
        bot._last_submit_ts = now - 10.0

        monkeypatch.setattr(
            bot_main,
            "make_order_new_msg",
            lambda payload: [b"order.new", str(payload).encode()],
        )

        bot._maybe_submit_order()

        assert bot.metrics.submitted == 1
        assert len(push.sent) == 1

        bot.push_sock.close()
        bot.sub_sock.close()

    def test_run_auth_failure_returns_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, _push, _sub = _make_bot(monkeypatch)
        monkeypatch.setattr(bot, "_authenticate", lambda timeout_sec=3.0: False)

        assert bot.run(duration_sec=0.01) == 1

        bot.push_sock.close()
        bot.sub_sock.close()

    def test_run_happy_path_stops_and_closes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bot, push, sub = _make_bot(monkeypatch, profile_name="aggressive")
        now = time.monotonic()
        bot._known_symbols = ["AAPL"]
        bot._market["AAPL"] = bot_main.MarketSnapshot(
            best_bid=100.0,
            best_ask=100.2,
            last_price=100.1,
        )
        bot._last_market_update["AAPL"] = now
        bot._last_submit_ts = now - 10.0

        monkeypatch.setattr(bot, "_authenticate", lambda timeout_sec=3.0: True)
        monkeypatch.setattr(
            "edumatcher.ai_trader.main.zmq.Poller",
            lambda: _FakePoller(sub, [False, False, False]),
        )
        monkeypatch.setattr(
            bot_main,
            "make_order_new_msg",
            lambda payload: [b"order.new", str(payload).encode()],
        )

        rc = bot.run(duration_sec=0.02)

        assert rc == 0
        assert push.closed is True
        assert sub.closed is True


class TestMainEntryPoint:
    def test_main_returns_bot_exit_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _FakeBot:
            def __init__(self, **_kwargs: object) -> None:
                return

            def run(self, duration_sec: float) -> int:
                _ = duration_sec
                return 7

        monkeypatch.setattr(
            bot_main,
            "_parse_args",
            lambda: argparse.Namespace(
                id="AI01",
                profile="cautious",
                symbols="AAPL",
                seed=1,
                duration=1.0,
                run_id="run-1",
                max_position=100,
                max_rejects=2,
                reject_window=10.0,
                reject_cooldown=1.0,
                stale_data=4.0,
            ),
        )
        monkeypatch.setattr(bot_main, "AITraderBot", _FakeBot)

        with pytest.raises(SystemExit) as exc:
            bot_main.main()
        assert exc.value.code == 7

    def test_main_keyboard_interrupt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _InterruptBot:
            def __init__(self, **_kwargs: object) -> None:
                raise KeyboardInterrupt()

        monkeypatch.setattr(
            bot_main,
            "_parse_args",
            lambda: argparse.Namespace(
                id="AI01",
                profile="cautious",
                symbols="",
                seed=1,
                duration=0.0,
                run_id="",
                max_position=100,
                max_rejects=2,
                reject_window=10.0,
                reject_cooldown=1.0,
                stale_data=4.0,
            ),
        )
        monkeypatch.setattr(bot_main, "AITraderBot", _InterruptBot)

        with pytest.raises(SystemExit) as exc:
            bot_main.main()
        assert exc.value.code == 0

    def test_main_exception_returns_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _ErrorBot:
            def __init__(self, **_kwargs: object) -> None:
                raise RuntimeError("boom")

        monkeypatch.setattr(
            bot_main,
            "_parse_args",
            lambda: argparse.Namespace(
                id="AI01",
                profile="cautious",
                symbols="",
                seed=1,
                duration=0.0,
                run_id="",
                max_position=100,
                max_rejects=2,
                reject_window=10.0,
                reject_cooldown=1.0,
                stale_data=4.0,
            ),
        )
        monkeypatch.setattr(bot_main, "AITraderBot", _ErrorBot)

        with pytest.raises(SystemExit) as exc:
            bot_main.main()
        assert exc.value.code == 1
