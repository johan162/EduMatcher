from __future__ import annotations

from edumatcher.ai_trader.main import AITraderBot, MarketSnapshot, _as_float
from edumatcher.ai_trader.personality import available_profiles, get_profile


class TestPersonalityProfiles:
    def test_available_profiles(self) -> None:
        names = available_profiles()
        assert "aggressive" in names
        assert "cautious" in names
        assert "many-small" in names
        assert "few-large" in names

    def test_get_profile_unknown_raises(self) -> None:
        try:
            get_profile("unknown")
            assert False, "expected ValueError"
        except ValueError:
            assert True

    def test_sample_qty_within_bounds(self) -> None:
        prof = get_profile("many-small")
        import random

        rng = random.Random(7)
        for _ in range(100):
            qty = prof.sample_qty(rng)
            assert prof.order_size_min <= qty <= prof.order_size_max


class TestAITraderHelpers:
    def test_as_float(self) -> None:
        assert _as_float("12.5") == 12.5
        assert _as_float(3) == 3.0
        assert _as_float(None) is None
        assert _as_float("x") is None

    def test_make_order_payload_requires_market_data(self) -> None:
        bot = AITraderBot(
            gateway_id="AI01",
            profile_name="cautious",
            symbols=["AAPL"],
            seed=1,
            run_id="r1",
            max_position=100,
            max_rejects=5,
            reject_window_sec=5.0,
            reject_cooldown_sec=2.0,
            stale_data_sec=4.0,
        )
        payload = bot._make_order_payload("AAPL")
        bot.push_sock.close()
        bot.sub_sock.close()
        assert payload is None

    def test_make_order_payload_uses_snapshot(self) -> None:
        bot = AITraderBot(
            gateway_id="AI02",
            profile_name="aggressive",
            symbols=["AAPL"],
            seed=2,
            run_id="r2",
            max_position=100,
            max_rejects=5,
            reject_window_sec=5.0,
            reject_cooldown_sec=2.0,
            stale_data_sec=4.0,
        )
        bot._market["AAPL"] = MarketSnapshot(
            best_bid=100.0, best_ask=100.2, last_price=100.1
        )
        payload = bot._make_order_payload("AAPL")
        bot.push_sock.close()
        bot.sub_sock.close()

        assert payload is not None
        assert payload["symbol"] == "AAPL"
        assert payload["order_type"] == "LIMIT"
        assert payload["quantity"] > 0
        assert payload["price"] > 0
        assert payload["gateway_id"] == "AI02"
