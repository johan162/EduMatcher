"""tools/sim_forensics checks D (matching) and C7 (stop triggers).

The checks replay an audit trail, so each test writes one: a small tape of
engine messages in the format pm-audit writes. ``Tape`` keeps the messages
consistent with each other (an order the tape trades is one it acked); a
test plants a violation by writing one message the engine would not have.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from collections.abc import Mapping
from typing import Any

import pytest

from tests.sim_forensics_world import OpenDataset, opener
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.registry import REGISTRY, Outcome, run_checks  # noqa: E402

CHECKS = ["C7", "D1", "D10", "D11", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9"]
SYM = "AAPL"
CONFIG = {
    "engine": {
        "symbols": {SYM: {"tick_decimals": 2}},
        "fix_gateways": {
            gw: {"smp_action": "CANCEL_AGGRESSOR"} for gw in ("GW1", "GW2")
        },
    }
}


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


class Tape:
    """An audit trail under construction; prices in ticks (2 decimals)."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.n = 0
        self.trades = 0
        self.chain = ""
        # The replay's view kept here too, for snapshots: id → [side, price,
        # shown, peak, remaining].
        self.book: dict[str, list[Any]] = {}
        # The engine's first message carries the run's config: tick sizes and
        # the gateways' SMP modes, all the replay reads from it.
        self.put("system.startup", {"config": json.dumps(CONFIG)}, new_chain=True)
        self.put("system.startup_recovery", {"restored_orders": 0}, new_chain=True)

    def _msg(self) -> str:
        self.n += 1
        return f"{self.n:026d}"

    def put(self, topic: str, payload: dict[str, Any], new_chain: bool = False) -> None:
        msg = self._msg()
        if new_chain:
            self.chain = msg
        self.lines.append(
            f"[2026-10-24T07:00:00.000+00:00] [{topic}] "
            f"[seq={self.n} msg={msg} chain={self.chain}] {json.dumps(payload)}\n"
        )

    def phase(self, state: str) -> None:
        self.put("session.transition", {"to_state": state}, new_chain=True)
        self.put("session.state", {"state": state})

    def order(
        self,
        oid: str,
        side: str,
        qty: int,
        price: int | None = None,
        *,
        kind: str = "LIMIT",
        gw: str = "GW1",
        stop: int | None = None,
        peak: int | None = None,
        rests: bool = True,
    ) -> None:
        """Submit and ack an order; *rests* puts it in the tape's book."""
        self.put(
            "order.new",
            {
                "id": oid,
                "symbol": SYM,
                "side": side,
                "order_type": kind,
                "tif": "DAY",
                "quantity": qty,
                "gateway_id": gw,
                "tick_decimals": 2,
                "price_ticks": price,
                "stop_price_ticks": stop,
                "visible_qty": peak,
                "trail_offset_ticks": None,
            },
            new_chain=True,
        )
        self.put(
            f"order.ack.{gw}",
            {
                "order_id": oid,
                "accepted": True,
                "symbol": SYM,
                "side": side,
                "order_type": kind,
                "qty": qty,
                "smp_action": "CANCEL_AGGRESSOR",
            },
        )
        if rests and price is not None and kind in ("LIMIT", "ICEBERG"):
            self.book[oid] = [side, price, min(peak or qty, qty), peak, qty]

    def trade(
        self,
        aggressor: str,
        passive: str,
        qty: int,
        price: int,
        *,
        agg_side: str = "BUY",
        gws: tuple[str, str] = ("GW2", "GW1"),
    ) -> str:
        """A trade in the current chain; *gws* are the aggressor's and the
        resting order's gateways (in an uncross: the buyer's and the
        seller's). The tape's book follows the trade."""
        self.trades += 1
        tid = f"000001-{self.trades:09d}"
        buy_first = agg_side in ("BUY", "AUCTION")
        buy, sell = (aggressor, passive) if buy_first else (passive, aggressor)
        buy_gw, sell_gw = gws if buy_first else gws[::-1]
        self.put(
            "trade.executed",
            {
                "id": tid,
                "symbol": SYM,
                "buy_order_id": buy,
                "sell_order_id": sell,
                "buy_gateway_id": buy_gw,
                "sell_gateway_id": sell_gw,
                "price": price / 100,
                "quantity": qty,
                "aggressor_side": agg_side,
                "tick_decimals": 2,
            },
        )
        for oid in (aggressor, passive):
            entry = self.book.get(oid)
            if entry is None:
                continue
            entry[4] -= qty
            if oid == passive or agg_side == "AUCTION":
                entry[2] -= qty
                if entry[4] == 0:
                    del self.book[oid]
                elif entry[2] == 0:
                    entry[2] = min(entry[3] or entry[4], entry[4])
                    self.book[oid] = self.book.pop(oid)  # back of the queue
        return tid

    def cancelled(self, oid: str, reason: str = "", gw: str = "GW1") -> None:
        self.put(
            f"order.cancelled.{gw}",
            {"order_id": oid, "symbol": SYM, "cancel_reason": reason},
        )
        self.book.pop(oid, None)

    def snapshot(self, **override: Any) -> None:
        levels: dict[str, dict[int, list[int]]] = {"BUY": {}, "SELL": {}}
        for side, price, shown, _, _ in self.book.values():
            lv = levels[side].setdefault(price, [0, 0])
            lv[0] += shown
            lv[1] += 1

        def rows(side: str) -> list[dict[str, Any]]:
            return [
                {"price": p / 100, "qty": q, "count": c}
                for p, (q, c) in sorted(levels[side].items(), reverse=side == "BUY")
            ]

        payload = {"symbol": SYM, "tick_decimals": 2, "bids": rows("BUY")}
        payload["asks"] = rows("SELL")
        payload.update(override)
        self.put(f"book.{SYM}", payload, new_chain=True)

    def write(self, data: Path) -> Path:
        data.mkdir(parents=True)
        (data / "audit.log").write_text("".join(self.lines))
        return data


def continuous_day() -> Tape:
    """A consistent continuous session: two resting asks at one price and
    one behind, a buy that takes the first and part of the second, an armed
    sell stop that a later print triggers, and an iceberg that refills."""
    t = Tape()
    t.phase("CONTINUOUS")
    t.order("O1", "SELL", 100, 10000)
    t.order("O2", "SELL", 50, 10000)
    t.order("O3", "SELL", 40, 10100, gw="GW2")
    t.order("B1", "BUY", 60, 9900, gw="GW2")
    t.order("S1", "SELL", 30, kind="STOP", stop=9900)
    t.order("A1", "BUY", 120, 10000, gw="GW2", rests=False)
    t.trade("A1", "O1", 100, 10000)
    t.trade("A1", "O2", 20, 10000)
    t.snapshot()
    # A market sell prints at 99.00, which triggers S1; S1 sells into B1.
    t.order("M1", "SELL", 10, kind="MARKET", rests=False)
    t.trade("M1", "B1", 10, 9900, agg_side="SELL", gws=("GW1", "GW2"))
    t.trade("S1", "B1", 30, 9900, agg_side="SELL", gws=("GW1", "GW2"))
    t.snapshot()
    # An iceberg showing 20 of 100 becomes the best ask: a buy for 30 takes
    # the slice, the slice refills, and the buy takes 10 more.
    t.order("I1", "SELL", 100, 9950, kind="ICEBERG", peak=20)
    t.order("A2", "BUY", 30, 9950, gw="GW2", rests=False)
    t.trade("A2", "I1", 20, 9950)
    t.trade("A2", "I1", 10, 9950)
    t.snapshot()
    return t


def run(open_ds: OpenDataset, data: Path, check_id: str) -> Outcome:
    return REGISTRY[check_id].fn(open_ds(data))


def violations(open_ds: OpenDataset, data: Path) -> dict[str, int]:
    ds = open_ds(data)
    return {i: n for i in CHECKS if (n := REGISTRY[i].fn(ds).violations)}


def test_every_matching_check_passes_on_a_consistent_day(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    assert sorted(i for i in REGISTRY if i[0] == "D" or i == "C7") == CHECKS
    data = continuous_day().write(tmp_path / "data")
    results = run_checks(open_ds(data), [REGISTRY[i] for i in CHECKS], 10)
    assert {r.check.id: (r.status, r.samples) for r in results} == {
        i: ("PASS", []) for i in CHECKS
    }


def test_the_checks_skip_without_an_audit_from_the_engine_start(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    t = continuous_day()
    t.lines = t.lines[1:]  # rotated away: no startup line
    data = t.write(tmp_path / "data")
    results = run_checks(open_ds(data), [REGISTRY[i] for i in CHECKS], 10)
    assert {r.status for r in results} == {"SKIPPED"}
    assert "engine's start" in results[0].note


def test_d1_finds_a_crossed_snapshot(tmp_path: Path, open_ds: OpenDataset) -> None:
    t = continuous_day()
    t.snapshot(bids=[{"price": 103.0, "qty": 1, "count": 1}])
    data = t.write(tmp_path / "data")
    (sample,) = run(open_ds, data, "D1").samples
    assert (sample["bid"], sample["ask"]) == (103.0, 99.5)


def test_d2_finds_a_marketable_order_that_rested(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    t = continuous_day()
    t.order("L1", "BUY", 5, 10150, gw="GW2")  # O3 asks 101.00: should trade
    data = t.write(tmp_path / "data")
    assert violations(open_ds, data) == {"D2": 1}
    (sample,) = run(open_ds, data, "D2").samples
    assert sample["rested_last"] == "L1"


def test_d3_finds_a_fill_through_the_aggressors_limit(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    t = continuous_day()
    t.order("L1", "BUY", 5, 9940, gw="GW2", rests=False)
    t.trade("L1", "I1", 5, 9950)
    data = t.write(tmp_path / "data")
    assert violations(open_ds, data) == {"D3": 1}


def test_d4_finds_a_trade_through_a_better_price(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    t = continuous_day()
    t.order("L1", "BUY", 5, 10100, gw="GW2", rests=False)
    t.trade("L1", "O3", 5, 10100)  # I1 still asks 99.50
    data = t.write(tmp_path / "data")
    assert violations(open_ds, data) == {"D4": 1}
    (sample,) = run(open_ds, data, "D4").samples
    assert sample["better_order"] == "I1"


def test_d5_finds_a_fill_out_of_time_priority(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    t = Tape()
    t.phase("CONTINUOUS")
    t.order("O1", "SELL", 10, 10000)
    t.order("O2", "SELL", 10, 10000)
    t.order("A1", "BUY", 10, 10000, gw="GW2", rests=False)
    t.trade("A1", "O2", 10, 10000)  # O1 was first
    data = t.write(tmp_path / "data")
    assert violations(open_ds, data) == {"D5": 1}
    (sample,) = run(open_ds, data, "D5").samples
    assert sample["ahead"] == "O1"


def test_d5_finds_an_iceberg_filled_beyond_its_shown_slice(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    t = Tape()
    t.phase("CONTINUOUS")
    t.order("I1", "SELL", 100, 10200, kind="ICEBERG", peak=20)
    t.order("A1", "BUY", 30, 10200, gw="GW2", rests=False)
    t.trade("A1", "I1", 30, 10200)
    data = t.write(tmp_path / "data")
    out = run(open_ds, data, "D5")
    assert [(s["qty"], s["expected"]) for s in out.samples] == [(30, 20)]


def test_d5_a_cancel_in_the_same_dispatch_excuses_the_order_ahead(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    """O1 is pulled in the same dispatch (an SMP cancel, a quote sibling):
    the stream does not say whether before the trade, so no violation."""
    t = Tape()
    t.phase("CONTINUOUS")
    t.order("O1", "SELL", 10, 10000)
    t.order("O2", "SELL", 10, 10000)
    t.order("A1", "BUY", 10, 10000, gw="GW2", rests=False)
    t.trade("A1", "O2", 10, 10000)
    t.cancelled("O1", "SELF_MATCH_PREVENTED")
    data = t.write(tmp_path / "data")
    assert violations(open_ds, data) == {}


def opening_auction() -> Tape:
    """Crossed interest collected in the auction; it uncrosses at 100.00,
    the price that executes most (60) with the least surplus."""
    t = Tape()
    t.phase("OPENING_AUCTION")
    t.order("B1", "BUY", 50, 10100, gw="GW2")
    t.order("B2", "BUY", 30, 10000, gw="GW2")
    t.order("S1", "SELL", 40, 9900)
    t.order("S2", "SELL", 20, 10000)
    t.put("session.transition", {"to_state": "CONTINUOUS"}, new_chain=True)
    t.trade("B1", "S1", 40, 10000, agg_side="AUCTION")
    t.trade("B1", "S2", 10, 10000, agg_side="AUCTION")
    t.trade("B2", "S2", 10, 10000, agg_side="AUCTION")
    t.put(f"auction.result.{SYM}", {"symbol": SYM, "eq_price": 100.0, "eq_qty": 60})
    t.put("session.state", {"state": "CONTINUOUS"})
    t.snapshot()
    return t


def test_an_opening_uncross_passes(tmp_path: Path, open_ds: OpenDataset) -> None:
    data = opening_auction().write(tmp_path / "data")
    assert violations(open_ds, data) == {}


def test_d6_finds_an_uncross_at_the_wrong_price(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    t = opening_auction()
    t.lines = [
        (
            ln.replace('"price": 100.0,', '"price": 99.0,')
            if "trade.executed" in ln
            else ln.replace('"eq_price": 100.0', '"eq_price": 99.0')
        )
        for ln in t.lines
    ]
    data = t.write(tmp_path / "data")
    errors = [s["error"] for s in run(open_ds, data, "D6").samples]
    assert errors == ["print differs from the replay's equilibrium"]


def test_d6_finds_an_auction_result_that_disagrees_with_the_prints(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    t = opening_auction()
    t.lines = [ln.replace('"eq_qty": 60', '"eq_qty": 61') for ln in t.lines]
    data = t.write(tmp_path / "data")
    errors = [s["error"] for s in run(open_ds, data, "D6").samples]
    assert errors == ["auction.result differs from the prints"]


def indicative(t: Tape, price: float | None, qty: int, surplus: int, side: str) -> None:
    """An auction.indicative as the engine's timer publishes it."""
    t.put(
        f"auction.indicative.{SYM}",
        {"symbol": SYM, "phase": "OPENING_AUCTION", "eq_price": price, "eq_qty": qty, "imbalance_qty": surplus, "imbalance_side": side},  # fmt: skip
        new_chain=True,
    )


def auction_with_indicatives(final: tuple[float | None, int, int, str]) -> Tape:
    """The opening auction, with an indicative after the first order (no
    cross yet) and one after the last: 100.00 executes 60, 20 more to buy."""
    t = Tape()
    t.phase("OPENING_AUCTION")
    t.order("B1", "BUY", 50, 10100, gw="GW2")
    indicative(t, None, 0, 0, "")
    t.order("B2", "BUY", 30, 10000, gw="GW2")
    t.order("S1", "SELL", 40, 9900)
    t.order("S2", "SELL", 20, 10000)
    indicative(t, *final)
    return t


def test_d10_passes_indicatives_that_are_the_books_uncross(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    data = auction_with_indicatives((100.0, 60, 20, "BUY")).write(tmp_path / "data")
    out = run(open_ds, data, "D10")
    assert out.violations == 0, out.samples
    assert out.note == "2 indicatives compared"


@pytest.mark.parametrize(
    "final",
    [(101.0, 60, 20, "BUY"), (100.0, 50, 20, "BUY"), (100.0, 60, 0, ""), (100.0, 60, 20, "SELL")],  # fmt: skip
)
def test_d10_finds_an_indicative_the_book_does_not_make(
    tmp_path: Path, open_ds: OpenDataset, final: tuple[float, int, int, str]
) -> None:
    data = auction_with_indicatives(final).write(tmp_path / "data")
    (sample,) = run(open_ds, data, "D10").samples
    assert sample["replay"] == [10000, 60, 20, "BUY"]


def test_the_linear_uncross_is_the_definition() -> None:
    """``_uncross_of`` against the definition, summed price by price."""
    import random

    from sim_forensics.checks.matching import _Book, _Order, _uncross_of

    rng = random.Random(7)
    for _ in range(300):
        book = _Book(SYM, 2)
        bids: list[tuple[int, int]] = []
        asks: list[tuple[int, int]] = []
        for i in range(rng.randint(0, 12)):
            side, price, qty = rng.choice(("BUY", "SELL")), rng.randint(95, 105), rng.randint(1, 50)  # fmt: skip
            book.rest(_Order(f"O{i}", side, "LIMIT", price, qty, "GW", "NONE"), i)
            (bids if side == "BUY" else asks).append((price, qty))
        want = None
        if bids and asks:
            keys = []
            for p in sorted({p for p, _ in bids + asks}):
                b = sum(q for x, q in bids if x >= p)
                a = sum(q for x, q in asks if x <= p)
                side = "BUY" if b > a else "SELL" if a > b else ""
                keys.append((-min(b, a), abs(b - a), p, side))
            best = min(keys)
            want = None if best[0] == 0 else (best[2], -best[0], best[1], best[3])
        assert _uncross_of(book) == want


def test_d7_finds_a_continuous_self_trade(tmp_path: Path, open_ds: OpenDataset) -> None:
    t = continuous_day()
    t.order("L1", "BUY", 5, 10100, gw="GW2", rests=False)  # O3 is GW2's too
    t.trade("L1", "O3", 5, 10100, gws=("GW2", "GW2"))
    data = t.write(tmp_path / "data")
    assert violations(open_ds, data) == {"D4": 1, "D7": 1}


def test_d8_finds_a_price_off_the_tick_grid(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    t = continuous_day()
    t.lines = [
        (
            ln.replace('"price": 99.5,', '"price": 99.505,', 1)
            if "trade.executed" in ln
            else ln
        )
        for ln in t.lines
    ]
    data = t.write(tmp_path / "data")
    assert run(open_ds, data, "D8").violations == 2


def test_d9_finds_a_snapshot_that_differs_from_the_replay(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    t = continuous_day()
    t.snapshot(asks=[{"price": 101.0, "qty": 41, "count": 1}])
    t.snapshot(asks=[{"price": 101.0, "qty": 41, "count": 1}])  # same episode
    data = t.write(tmp_path / "data")
    out = run(open_ds, data, "D9")
    assert out.violations == 1
    assert "SELL 10100: engine (41, 1) replay (40, 1)" in str(out.samples[0]["levels"])
    assert "2 differ" in out.note


def test_c7_finds_a_stop_that_traded_before_its_trigger(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    t = Tape()
    t.phase("CONTINUOUS")
    t.order("B1", "BUY", 50, 9900, gw="GW2")
    t.order("O1", "SELL", 10, 10000)
    t.order("A1", "BUY", 10, 10000, gw="GW2", rests=False)
    t.trade("A1", "O1", 10, 10000)  # last = 100.00
    t.order("S1", "SELL", 30, kind="STOP", gw="GW1", stop=9800)
    t.order("M1", "SELL", 10, kind="MARKET", rests=False)
    t.trade("M1", "B1", 10, 9900, agg_side="SELL", gws=("GW1", "GW2"))
    t.trade("S1", "B1", 30, 9900, agg_side="SELL", gws=("GW1", "GW2"))  # 99 > 98
    data = t.write(tmp_path / "data")
    assert violations(open_ds, data) == {"C7": 1}
    (sample,) = run(open_ds, data, "C7").samples
    assert sample["error"] == "the engine traded a stop the replay had not triggered"


def test_c7_finds_a_stop_the_engine_should_have_triggered(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    t = continuous_day()
    t.order("S2", "SELL", 5, kind="STOP", gw="GW2", stop=9900)
    t.order("M2", "SELL", 5, kind="MARKET", rests=False)
    t.trade("M2", "B1", 5, 9900, agg_side="SELL", gws=("GW1", "GW2"))
    # The engine stays silent about S2, which a print at 99.00 triggers.
    data = t.write(tmp_path / "data")
    (sample,) = run(open_ds, data, "C7").samples
    assert sample["error"] == "replay triggered the stop; the engine reported nothing"
    assert sample["order_id"] == "S2"


def test_c7_ratchets_a_trailing_stop(tmp_path: Path, open_ds: OpenDataset) -> None:
    """A sell trailing stop 1.00 behind: a print at 101.00 lifts it to
    100.00, so the next print at 100.00 triggers it."""
    t = Tape()
    t.phase("CONTINUOUS")
    t.order("O1", "SELL", 10, 10100)
    t.order("B1", "BUY", 50, 10000, gw="GW2")
    t.put(
        "order.new",
        {
            "id": "TS",
            "symbol": SYM,
            "side": "SELL",
            "order_type": "TRAILING_STOP",
            "quantity": 20,
            "gateway_id": "GW1",
            "tick_decimals": 2,
            "price_ticks": None,
            "stop_price_ticks": None,
            "visible_qty": None,
            "trail_offset_ticks": 100,
        },
        new_chain=True,
    )
    t.put(
        "order.ack.GW1",
        {
            "order_id": "TS",
            "accepted": True,
            "stop_price": 98.0,
            "smp_action": "CANCEL_AGGRESSOR",
        },
    )
    t.order("A1", "BUY", 10, 10100, gw="GW2", rests=False)
    t.trade("A1", "O1", 10, 10100)  # the stop ratchets to 100.00
    t.order("M1", "SELL", 5, kind="MARKET", rests=False)
    t.trade("M1", "B1", 5, 10000, agg_side="SELL", gws=("GW1", "GW2"))
    t.trade("TS", "B1", 20, 10000, agg_side="SELL", gws=("GW1", "GW2"))
    data = t.write(tmp_path / "data")
    assert violations(open_ds, data) == {}


def test_a_cascade_runs_its_stops_in_release_order(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    """One print releases a buy stop-limit and a sell stop. The engine runs
    them first-in first-out: the stop-limit trades nothing and rests, then
    the sell stop trades into it -- the next trade's aggressor is not the
    next stop to run."""
    t = Tape()
    t.phase("CONTINUOUS")
    t.order("B1", "BUY", 10, 10100, gw="GW2")
    t.order("SL", "BUY", 50, 10200, kind="STOP_LIMIT", stop=10050)
    t.order("SS", "SELL", 20, kind="STOP", gw="GW2", stop=10100)
    t.order("A1", "SELL", 10, 10100, rests=False)
    t.trade("A1", "B1", 10, 10100, agg_side="SELL", gws=("GW1", "GW2"))
    t.book["SL"] = ["BUY", 10200, 50, None, 50]
    t.trade("SS", "SL", 20, 10200, agg_side="SELL", gws=("GW2", "GW1"))
    t.snapshot()
    data = t.write(tmp_path / "data")
    assert violations(open_ds, data) == {}


def quoting_day() -> Tape:
    """Seed quotes at startup, an OCO, and an MM quote whose ask is hit and
    whose bid the engine pulls in the same dispatch."""
    t = Tape()
    for oid, side, price in (("Q0B", "BUY", 9900), ("Q0A", "SELL", 10100)):
        t.put(
            "order.ack.MM01",
            {
                "order_id": oid,
                "accepted": True,
                "is_seed": True,
                "symbol": SYM,
                "side": side,
                "qty": 100,
                "price": price / 100,
            },
            new_chain=True,
        )
        t.book[oid] = [side, price, 100, None, 100]
    t.phase("CONTINUOUS")
    t.order("R1", "BUY", 10, 9800)
    t.order("R2", "BUY", 20, 9700)
    t.put(
        "order.oco",
        {
            "oco_id": "K",
            "gateway_id": "GW1",
            "symbol": SYM,
            "quantity": 20,
            "leg1": {"side": "SELL", "order_type": "LIMIT", "price_ticks": 10200},
            "leg2": {"side": "SELL", "order_type": "STOP", "stop_price_ticks": 9800},
        },
        new_chain=True,
    )
    t.put(
        "oco.ack.GW1",
        {"oco_id": "K", "accepted": True, "order_id_1": "K1", "order_id_2": "K2"},
    )
    t.book["K1"] = ["SELL", 10200, 20, None, 20]
    t.put(
        "quote.new",
        {
            "gateway_id": "MM01",
            "symbol": SYM,
            "bid_price_ticks": 9950,
            "bid_qty": 50,
            "ask_price_ticks": 10050,
            "ask_qty": 50,
        },
        new_chain=True,
    )
    t.put(
        "quote.ack.MM01",
        {"accepted": True, "symbol": SYM, "bid_order_id": "QB", "ask_order_id": "QA"},
    )
    t.book["QB"] = ["BUY", 9950, 50, None, 50]
    t.book["QA"] = ["SELL", 10050, 50, None, 50]
    t.order("A1", "BUY", 30, 10050, gw="GW2", rests=False)
    t.trade("A1", "QA", 30, 10050, gws=("GW2", "MM01"))
    t.cancelled("QB", "QUOTE_LEG_FILLED", gw="MM01")
    t.snapshot()
    return t


def test_seeds_quotes_and_oco_legs_are_replayed(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    data = quoting_day().write(tmp_path / "data")
    assert violations(open_ds, data) == {}


def test_d7_finds_a_triggered_oco_leg_trading_with_its_owner(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    """X9: the engine gave OCO legs no SMP action, so a stop leg triggered
    by a cascade traded with its owner's resting bid."""
    t = quoting_day()
    t.order("A2", "SELL", 110, 9800, gw="GW2", rests=False)
    t.trade("A2", "Q0B", 100, 9900, agg_side="SELL", gws=("GW2", "MM01"))
    t.trade("A2", "R1", 10, 9800, agg_side="SELL", gws=("GW2", "GW1"))
    t.trade("K2", "R2", 20, 9700, agg_side="SELL", gws=("GW1", "GW1"))
    t.put("oco.cancelled.GW1", {"oco_id": "K", "cancelled_order_id": "K1"})
    t.book.pop("K1")
    t.snapshot()
    data = t.write(tmp_path / "data")
    assert violations(open_ds, data) == {"D7": 1}


def test_d9_finds_a_fill_whose_remaining_qty_differs(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    t = continuous_day()
    t.order("L1", "BUY", 5, 9950, gw="GW2", rests=False)
    tid = t.trade("L1", "I1", 5, 9950)
    t.put(
        "order.fill.GW1",
        {
            "order_id": "I1",
            "symbol": SYM,
            "fill_qty": 5,
            "remaining_qty": 66,
            "trade_ids": [tid],
        },
    )
    data = t.write(tmp_path / "data")
    (sample,) = run(open_ds, data, "D9").samples
    assert (sample["engine"], sample["replay"]) == (66, 65)


def test_the_replay_continues_across_an_engine_restart(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    """Its books come back from the restart's checkpoints (S25; a real
    restart is in test_sim_forensics_checkpoints.py)."""
    t = continuous_day()
    t.put("system.startup", {"config": json.dumps(CONFIG)}, new_chain=True)
    data = t.write(tmp_path / "data")
    (result,) = run_checks(open_ds(data), [REGISTRY["D9"]], 10)
    assert result.status == "PASS"
    assert "1 engine restart(s)" in result.note


def test_d9_finds_a_trade_by_an_order_the_replay_was_not_matching(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    t = continuous_day()
    t.order("L1", "BUY", 5, 9900, gw="GW2")  # rests below the ask
    t.order("X1", "SELL", 5, 10300, rests=False)  # trades, yet L1 is named
    t.trade("L1", "I1", 5, 9950)
    data = t.write(tmp_path / "data")
    out = run(open_ds, data, "D9")
    assert [s["error"] for s in out.samples] == [
        "trade by an order the replay was not matching"
    ]


def _with_context(
    t: Tape, prints: Mapping[str, object], result: Mapping[str, object]
) -> Tape:
    """The S23 fields on the tape's uncross prints and auction.result."""
    out = []
    for ln in t.lines:
        head, body = ln.split("] {", 1)
        p = json.loads("{" + body)
        if "[trade.executed]" in head:
            p.update(prints)
        elif "[auction.result." in head:
            p.update(result)
        out.append(f"{head}] {json.dumps(p)}\n")
    t.lines = out
    return t


def test_d6_passes_prints_tied_to_their_auction(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    ids = {"auction_id": "AUC-000001-000001"}
    t = _with_context(opening_auction(), {"match_type": "OPENING_AUCTION", **ids}, ids)
    assert violations(open_ds, t.write(tmp_path / "data")) == {}


@pytest.mark.parametrize(
    "prints, error",
    [
        ({"match_type": "CONTINUOUS", "auction_id": "AUC-000001-000001"}, "uncross print marked CONTINUOUS"),  # fmt: skip
        ({"match_type": "OPENING_AUCTION", "auction_id": "AUC-000001-000009"}, "print's auction_id is not its auction.result's"),  # fmt: skip
    ],
)
def test_d6_finds_a_print_its_context_misdescribes(
    tmp_path: Path, open_ds: OpenDataset, prints: dict[str, object], error: str
) -> None:
    t = _with_context(opening_auction(), prints, {"auction_id": "AUC-000001-000001"})
    errors = {
        s["error"] for s in run(open_ds, t.write(tmp_path / "data"), "D6").samples
    }
    assert errors == {error}


def test_d6_finds_a_continuous_match_marked_as_an_auction(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    t = _with_context(continuous_day(), {"match_type": "OPENING_AUCTION"}, {})
    errors = {
        s["error"] for s in run(open_ds, t.write(tmp_path / "data"), "D6").samples
    }
    assert errors == {"continuous match not marked CONTINUOUS"}
