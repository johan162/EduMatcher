"""tools/sim_forensics check C8 (a quote's lifecycle, from the audit).

Each test writes a small audit tape: one chain per dispatch, the messages
in the order the engine publishes them.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.sim_forensics_world import OpenDataset, opener
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.registry import REGISTRY, Outcome  # noqa: E402

GW = "MM01"


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


def ack(qid: str, bid: str = "B1", ask: str = "A1") -> tuple[str, dict[str, Any]]:
    return (f"quote.ack.{GW}", {"quote_id": qid, "accepted": True, "bid_order_id": bid, "ask_order_id": ask})  # fmt: skip


def status(qid: str, st: str) -> tuple[str, dict[str, Any]]:
    return (f"quote.status.{GW}", {"quote_id": qid, "status": st})


def trade(tid: str, buy: str, sell: str = "X") -> tuple[str, dict[str, Any]]:
    return ("trade.executed", {"id": tid, "buy_order_id": buy, "sell_order_id": sell})


def fill(oid: str, remaining: int) -> tuple[str, dict[str, Any]]:
    return (f"order.fill.{GW}", {"order_id": oid, "remaining_qty": remaining})


def cancelled(oid: str) -> tuple[str, dict[str, Any]]:
    return (f"order.cancelled.{GW}", {"order_id": oid, "cancel_reason": "QUOTE_LEG_FILLED"})  # fmt: skip


def run(open_ds: OpenDataset, tmp_path: Path, *chains: list[tuple[str, dict[str, Any]]]) -> Outcome:  # fmt: skip
    data = tmp_path / "data"
    data.mkdir()
    out, n = [], 0
    for c, chain in enumerate(chains):
        for topic, p in chain:
            n += 1
            out.append(
                f"[2026-10-24T07:30:00.000+00:00] [{topic}] "
                f"[seq={n} msg=M{n} chain=C{c}] {json.dumps(p)}\n"
            )
    (data / "audit.log").write_text("".join(out))
    return REGISTRY["C8"].fn(open_ds(data))


def errors(out: Outcome) -> list[object]:
    return [s["error"] for s in out.samples]


def test_c8_passes_a_quote_whose_bid_fill_ends_it_and_its_ask(
    open_ds: OpenDataset, tmp_path: Path
) -> None:
    """The engine after X8a's fix: ack, ACTIVE, then (in a later dispatch, or
    on entry) the bid's fill inactivates the quote and cancels the ask."""
    out = run(
        open_ds,
        tmp_path,
        [ack("Q1"), status("Q1", "ACTIVE")],
        [status("Q1", "INACTIVE_BID_FILLED"), cancelled("A1"), trade("T1", "B1"), fill("B1", 0)],  # fmt: skip
        [ack("Q2", "B2", "A2"), status("Q2", "ACTIVE"), status("Q2", "INACTIVE_BID_FILLED"), trade("T2", "B2"), fill("B2", 40), cancelled("A2")],  # fmt: skip
    )
    assert out.violations == 0, out.samples
    assert out.note.startswith("2 quotes, 2 inactivated by a fill")


def test_c8_finds_the_x8a_shape(open_ds: OpenDataset, tmp_path: Path) -> None:
    """The engine before the fix: the bid fills on entry before the quote is
    acked, then ACTIVE, the ask rests, and a later order trades with it."""
    out = run(
        open_ds,
        tmp_path,
        [status("Q1", "INACTIVE_BID_FILLED"), trade("T1", "B1"), fill("B1", 0), ack("Q1"), status("Q1", "ACTIVE")],  # fmt: skip
        [trade("T2", "Y", "A1")],
    )
    assert errors(out) == [
        "quote.status before the quote's ack",
        "ACTIVE after the quote ended",
        "sibling not cancelled in the dispatch that inactivated its quote",
        "sibling leg traded after its quote went inactive",
    ]


def test_c8_accepts_a_seeded_quote_and_a_cancel_ack(
    open_ds: OpenDataset, tmp_path: Path
) -> None:
    """A seeded quote has no quote.ack: its legs come from their order.acks.
    A quote cancel's ack carries no legs and creates no quote."""
    seed = [
        (f"order.ack.{GW}", {"order_id": "S1", "accepted": True, "is_seed": True, "side": "BUY", "quote_id": "SEED-1"}),  # fmt: skip
        (f"order.ack.{GW}", {"order_id": "S2", "accepted": True, "is_seed": True, "side": "SELL", "quote_id": "SEED-1"}),  # fmt: skip
        status("SEED-1", "ACTIVE"),
    ]
    out = run(
        open_ds,
        tmp_path,
        seed,
        [status("SEED-1", "INACTIVE_ASK_FILLED"), cancelled("S1"), trade("T1", "Y", "S2"), fill("S2", 0)],  # fmt: skip
        [(f"quote.ack.{GW}", {"quote_id": "SEED-1", "accepted": True, "bid_order_id": "", "ask_order_id": ""})],  # fmt: skip
    )
    assert out.violations == 0, out.samples


def test_c8_finds_a_seed_quotes_sibling_left_resting(
    open_ds: OpenDataset, tmp_path: Path
) -> None:
    seed = [
        (f"order.ack.{GW}", {"order_id": "S1", "accepted": True, "is_seed": True, "side": "BUY", "quote_id": "SEED-1"}),  # fmt: skip
        (f"order.ack.{GW}", {"order_id": "S2", "accepted": True, "is_seed": True, "side": "SELL", "quote_id": "SEED-1"}),  # fmt: skip
        status("SEED-1", "ACTIVE"),
    ]
    out = run(open_ds, tmp_path, seed, [status("SEED-1", "INACTIVE_ASK_FILLED"), trade("T1", "Y", "S2")])  # fmt: skip
    assert errors(out) == [
        "sibling not cancelled in the dispatch that inactivated its quote"
    ]
