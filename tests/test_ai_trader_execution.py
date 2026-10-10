"""ai_trader.execution and session_policy: intents become valid orders."""

from __future__ import annotations

import random

import pytest

from edumatcher.ai_trader.execution import (
    ExecutionSpec,
    Executor,
    TagFactory,
    clamp_qty,
)
from edumatcher.ai_trader.market_state import SymbolState
from edumatcher.ai_trader.session_policy import (
    auction_tif,
    is_call_phase,
    order_allowed,
)
from edumatcher.ai_trader.strategies import Intent
from edumatcher.models.order import TIF, OrderType

PHASES = ["PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS", "CLOSING_AUCTION", "CLOSED"]


class TestSessionPolicy:
    @pytest.mark.parametrize("phase", PHASES)
    @pytest.mark.parametrize("otype", list(OrderType))
    @pytest.mark.parametrize("tif", list(TIF))
    def test_matrix(self, phase: str, otype: OrderType, tif: TIF) -> None:
        allowed = order_allowed(phase, otype, tif, halted=False)
        if phase == "CLOSED":
            assert not allowed
        elif phase == "CONTINUOUS":
            assert allowed is (tif in (TIF.DAY, TIF.GTC))
        else:
            resting = otype in (OrderType.LIMIT, OrderType.ICEBERG)
            auction = {"OPENING_AUCTION": TIF.ATO, "CLOSING_AUCTION": TIF.ATC}.get(
                phase
            )
            assert allowed is (
                resting and (tif in (TIF.DAY, TIF.GTC) or tif == auction)
            )

    def test_halted_blocks_everything(self) -> None:
        assert not order_allowed("CONTINUOUS", OrderType.LIMIT, TIF.DAY, halted=True)

    def test_auction_helpers(self) -> None:
        assert auction_tif("OPENING_AUCTION") == TIF.ATO
        assert auction_tif("CLOSING_AUCTION") == TIF.ATC
        assert auction_tif("PRE_OPEN") is None
        assert [p for p in PHASES if is_call_phase(p)] == [
            "PRE_OPEN",
            "OPENING_AUCTION",
            "CLOSING_AUCTION",
        ]


def _st(bid: int | None = 990, ask: int | None = 1010, **kw: object) -> SymbolState:
    return SymbolState("AAPL", best_bid=bid, best_ask=ask, last_trade=1000, **kw)  # type: ignore[arg-type]


def _orders(
    spec: ExecutionSpec,
    side: str = "BUY",
    urgency: float = 0.1,
    st: SymbolState | None = None,
    qty: int = 100,
    phase: str = "CONTINUOUS",
    seed: int = 1,
):
    ex = Executor(spec)
    return ex, ex.orders_for(
        Intent("AAPL", side, urgency),
        st or _st(),
        qty,
        phase,
        0.0,
        random.Random(seed),
        TagFactory("AI001"),
    )


class TestContinuous:
    def test_passive_buy_behind_bid(self) -> None:
        _, [o] = _orders(ExecutionSpec(style="passive", offset_ticks=2))
        assert (o.order_type, o.tif, o.price_ticks, o.qty) == (
            OrderType.LIMIT,
            TIF.DAY,
            988,
            100,
        )
        assert o.tag == "AI001-1"

    def test_passive_sell_above_ask_gtc(self) -> None:
        _, [o] = _orders(
            ExecutionSpec(style="passive", offset_ticks=1, tif="GTC"), side="SELL"
        )
        assert (o.price_ticks, o.tif) == (1011, TIF.GTC)

    def test_join_the_touch(self) -> None:
        _, [o] = _orders(ExecutionSpec(style="passive", offset_ticks=0))
        assert o.price_ticks == 990

    def test_passive_never_crosses_a_one_sided_reference(self) -> None:
        # No bid: priced off the reference, but kept below the ask.
        _, [o] = _orders(
            ExecutionSpec(style="passive", offset_ticks=0), st=_st(bid=None, ask=1000)
        )
        assert o.price_ticks == 999

    def test_marketable_crosses(self) -> None:
        _, [o] = _orders(ExecutionSpec(style="marketable", cross_ticks=2))
        assert (o.order_type, o.price_ticks) == (OrderType.LIMIT, 1012)

    def test_a_crossing_order_is_priced_at_the_intent_limit(self) -> None:
        ex = Executor(ExecutionSpec(style="marketable", cross_ticks=2))
        [o] = ex.orders_for(
            Intent("AAPL", "BUY", 0.9, limit=1100),
            _st(),
            100,
            "CONTINUOUS",
            0.0,
            random.Random(1),
            TagFactory("AI001"),
        )
        assert (o.order_type, o.price_ticks) == (OrderType.LIMIT, 1100)
        ioc = Executor(ExecutionSpec(style="sweep", sweep_type="IOC"))
        [o] = ioc.orders_for(
            Intent("AAPL", "SELL", 0.9, limit=950),
            _st(),
            100,
            "CONTINUOUS",
            0.0,
            random.Random(1),
            TagFactory("AI001"),
        )
        assert (o.order_type, o.price_ticks) == (OrderType.IOC, 950)

    def test_urgency_turns_passive_marketable(self) -> None:
        _, [o] = _orders(ExecutionSpec(style="passive", urgency_cross=0.5), urgency=0.9)
        assert o.price_ticks == 1010

    @pytest.mark.parametrize("sweep", ["MARKET", "IOC", "FOK"])
    def test_sweep_types(self, sweep: str) -> None:
        _, [o] = _orders(
            ExecutionSpec(style="sweep", sweep_type=sweep, cross_ticks=1), side="SELL"
        )
        assert o.order_type == OrderType(sweep)
        assert o.price_ticks == (None if sweep == "MARKET" else 989)
        assert o.tif == TIF.DAY

    def test_sweep_into_empty_side_rests_instead(self) -> None:
        _, [o] = _orders(ExecutionSpec(style="sweep"), st=_st(ask=None))
        assert o.order_type == OrderType.LIMIT and o.price_ticks == 989

    def test_iceberg(self) -> None:
        _, [o] = _orders(ExecutionSpec(style="iceberg", visible_fraction=0.2), qty=100)
        assert (o.order_type, o.visible_qty) == (OrderType.ICEBERG, 20)

    def test_iceberg_too_small_becomes_limit(self) -> None:
        _, [o] = _orders(ExecutionSpec(style="iceberg"), qty=1)
        assert (o.order_type, o.visible_qty) == (OrderType.LIMIT, None)

    def test_iceberg_visible_strictly_below_qty(self) -> None:
        # ALF requires VISIBLE < QTY.
        _, [o] = _orders(ExecutionSpec(style="iceberg", visible_fraction=1.0), qty=5)
        assert o.visible_qty == 4

    def test_no_reference_no_order(self) -> None:
        st = SymbolState("AAPL")
        _, out = _orders(ExecutionSpec(), st=st)
        assert out == []

    def test_halted_no_order(self) -> None:
        _, out = _orders(ExecutionSpec(), st=_st(halted=True))
        assert out == []


class TestClamps:
    def test_collar_clamps_price(self) -> None:
        st = _st(bid=990, ask=1010, collar_static_pct=0.01, static_ref=1000)
        _, [o] = _orders(ExecutionSpec(style="marketable", cross_ticks=50), st=st)
        assert o.price_ticks == st.collar_band()[1]  # type: ignore[index]

    def test_max_order_qty(self) -> None:
        _, [o] = _orders(ExecutionSpec(), st=_st(max_order_qty=7))
        assert o.qty == 7

    def test_max_order_value(self) -> None:
        st = _st(max_order_value=50.0)  # 50 money / 9.88 per share
        assert clamp_qty(st, 100, 988) == 5

    def test_qty_clamped_to_zero_means_no_order(self) -> None:
        _, out = _orders(ExecutionSpec(), st=_st(max_order_value=1.0))
        assert out == []


class TestCallPhases:
    @pytest.mark.parametrize(
        ("phase", "tif"),
        [
            ("PRE_OPEN", TIF.DAY),
            ("OPENING_AUCTION", TIF.ATO),
            ("CLOSING_AUCTION", TIF.ATC),
        ],
    )
    def test_auction_orders_straddle_the_reference(self, phase: str, tif: TIF) -> None:
        st = _st(indicative_price=1000)
        prices = set()
        for seed in range(200):
            _, out = _orders(
                ExecutionSpec(auction_participation=1.0, offset_ticks=1),
                st=st,
                phase=phase,
                seed=seed,
                side="BUY",
            )
            [o] = out
            assert (o.order_type, o.tif) == (OrderType.LIMIT, tif)
            prices.add(o.price_ticks)
        assert min(prices) < 1000 < max(prices)  # some buyers cross the reference

    def test_participation_zero_sits_out(self) -> None:
        _, out = _orders(
            ExecutionSpec(auction_participation=0.0), phase="OPENING_AUCTION"
        )
        assert out == []

    def test_sweep_style_becomes_a_limit_in_auctions(self) -> None:
        _, [o] = _orders(
            ExecutionSpec(style="sweep", auction_participation=1.0),
            phase="CLOSING_AUCTION",
        )
        assert o.order_type == OrderType.LIMIT and o.tif == TIF.ATC


class TestTwap:
    def test_parent_is_sliced_over_the_horizon(self) -> None:
        spec = ExecutionSpec(
            style="twap", slices=4, horizon_sec=40.0, child_style="passive"
        )
        ex = Executor(spec)
        tags = TagFactory("AI001")
        rng = random.Random(1)
        st = _st()
        first = ex.orders_for(
            Intent("AAPL", "BUY", 0.1), st, 10, "CONTINUOUS", 0.0, rng, tags
        )
        assert [o.qty for o in first] == [3]
        assert ex.due_twap_slices({"AAPL": st}, "CONTINUOUS", 5.0, rng, tags) == []
        sizes = [
            o.qty
            for t in (10.0, 20.0, 30.0)
            for o in ex.due_twap_slices({"AAPL": st}, "CONTINUOUS", t, rng, tags)
        ]
        assert [3] + sizes == [3, 3, 2, 2]
        assert sum([3] + sizes) == 10
        assert ex.twaps == {}

    def test_second_intent_does_not_start_a_second_parent(self) -> None:
        ex = Executor(ExecutionSpec(style="twap", slices=5, horizon_sec=50))
        tags, rng = TagFactory("AI001"), random.Random(1)
        ex.orders_for(
            Intent("AAPL", "BUY", 0.1), _st(), 100, "CONTINUOUS", 0.0, rng, tags
        )
        again = ex.orders_for(
            Intent("AAPL", "SELL", 0.1), _st(), 100, "CONTINUOUS", 1.0, rng, tags
        )
        assert again == [] and ex.twaps["AAPL"].side == "BUY"

    def test_slices_pause_outside_continuous(self) -> None:
        ex = Executor(ExecutionSpec(style="twap", slices=2, horizon_sec=10))
        tags, rng = TagFactory("AI001"), random.Random(1)
        ex.orders_for(
            Intent("AAPL", "BUY", 0.1), _st(), 10, "CONTINUOUS", 0.0, rng, tags
        )
        assert (
            ex.due_twap_slices({"AAPL": _st()}, "CLOSING_AUCTION", 100.0, rng, tags)
            == []
        )

    def test_cancel_twaps(self) -> None:
        ex = Executor(ExecutionSpec(style="twap"))
        ex.orders_for(
            Intent("AAPL", "BUY", 0.1),
            _st(),
            10,
            "CONTINUOUS",
            0.0,
            random.Random(1),
            TagFactory("A"),
        )
        ex.cancel_twaps()
        assert ex.twaps == {}


def test_tags_fit_alf_charset() -> None:
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    tags = TagFactory("ai001")
    t = ""
    for _ in range(5000):
        t = tags()
    assert set(t) <= allowed and len(t) <= 64 and t == "AI001-1388"
