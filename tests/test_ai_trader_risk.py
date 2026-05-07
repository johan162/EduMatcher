from __future__ import annotations

import time

from edumatcher.ai_trader.main import AITraderBot, MarketSnapshot


class TestAITraderRisk:
    def _make_bot(self) -> AITraderBot:
        return AITraderBot(
            gateway_id="AI99",
            profile_name="cautious",
            symbols=["AAPL"],
            seed=7,
            run_id="testrun",
            max_position=100,
            max_rejects=2,
            reject_window_sec=10.0,
            reject_cooldown_sec=1.0,
            stale_data_sec=0.2,
        )

    def test_position_limit_biases_side(self) -> None:
        bot = self._make_bot()
        bot._market["AAPL"] = MarketSnapshot(
            best_bid=100.0, best_ask=100.1, last_price=100.05
        )
        bot._last_market_update["AAPL"] = time.monotonic()
        bot._positions["AAPL"] = 100

        payload = bot._make_order_payload("AAPL")

        bot.push_sock.close()
        bot.sub_sock.close()

        assert payload is not None
        assert payload["side"] == "SELL"

    def test_reject_breaker_trips(self) -> None:
        bot = self._make_bot()
        bot._on_reject()
        bot._on_reject()

        bot.push_sock.close()
        bot.sub_sock.close()

        assert bot._risk_pause_until > time.monotonic()

    def test_stale_data_blocks_submission(self) -> None:
        bot = self._make_bot()
        bot._market["AAPL"] = MarketSnapshot(
            best_bid=100.0, best_ask=100.2, last_price=100.1
        )
        bot._last_market_update["AAPL"] = time.monotonic() - 1.0

        payload = bot._make_order_payload("AAPL")

        bot.push_sock.close()
        bot.sub_sock.close()

        assert payload is None
