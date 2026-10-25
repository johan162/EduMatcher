"""tools/sim_forensics checks C (order lifecycle).

Same approach as test_sim_forensics_bookkeeping: the consistent world of
sim_forensics_world, one planted violation per test.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.sim_forensics_world import (
    RESTING,
    RESTING_TS_NS,
    SEC,
    TRADES,
    OpenDataset,
    build,
    iso,
    ns,
    opener,
    sql,
)
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.registry import REGISTRY, Outcome, run_checks  # noqa: E402

C = ["C1", "C2", "C3", "C4", "C5", "C6"]
LATE = iso(ns("10:00:00"))


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


@pytest.fixture
def world(tmp_path: Path) -> Path:
    return build(tmp_path / "data")


def run(open_ds: OpenDataset, data: Path, check_id: str) -> Outcome:
    return REGISTRY[check_id].fn(open_ds(data))


def event(data: Path, et: str, oid: str, gw: str, **cols: object) -> None:
    """Append one order event for *oid* at 10:00 (after the whole tape)."""
    names = ["ts", "event_type", "order_id", "gateway_id", "symbol", *cols]
    sql(
        data / "stats.db",
        f"INSERT INTO order_events ({', '.join(names)}) "
        f"VALUES ({', '.join('?' * len(names))})",
        LATE,
        et,
        oid,
        gw,
        "AAPL",
        *cols.values(),
    )


def book(data: Path, *orders: dict[str, object]) -> None:
    (data / "gtc_orders.json").write_text(json.dumps(list(orders)))


def errors(out: Outcome) -> list[tuple[object, object]]:
    return [(s.get("order_id"), s.get("error")) for s in out.samples]


def test_every_c_check_passes_on_a_consistent_run(
    world: Path, open_ds: OpenDataset
) -> None:
    # C7 and C8 read the audit: tests/test_sim_forensics_matching.py and
    # tests/test_sim_forensics_quotes.py.
    assert sorted(i for i in REGISTRY if i[0] == "C" and i not in ("C7", "C8")) == C
    results = run_checks(open_ds(world), [REGISTRY[i] for i in C], 10)
    assert {r.check.id: (r.status, r.samples) for r in results} == {
        i: ("PASS", []) for i in C
    }


# --- C1 / C2: the sequence ---------------------------------------------------


def test_c1_finds_an_order_rejected_after_it_was_accepted(
    world: Path, open_ds: OpenDataset
) -> None:
    """The FOK pattern of finding X5: ACK accepted=true, then accepted=false."""
    event(world, "REJECT", "O9", "GW3", reason="Insufficient liquidity")
    out = run(open_ds, world, "C1")
    assert errors(out) == [("O9", "rejected after it was accepted")]
    assert out.samples[0]["events"] == "ACK REJECT"


def test_c1_finds_a_second_ack(world: Path, open_ds: OpenDataset) -> None:
    sql(
        world / "stats.db",
        "INSERT INTO order_events (ts, event_type, order_id, gateway_id, symbol, "
        "quantity) VALUES (?, 'ACK', 'O9', 'GW3', 'MSFT', 50)",
        iso(RESTING_TS_NS + SEC),
    )
    assert errors(run(open_ds, world, "C1")) == [("O9", "second ACK")]


def test_c1_finds_a_fill_without_an_ack_unless_the_gateway_quotes(
    world: Path, open_ds: OpenDataset
) -> None:
    sql(
        world / "stats.db",
        "DELETE FROM order_events WHERE order_id = 'O3' AND event_type = 'ACK'",
    )
    assert errors(run(open_ds, world, "C1")) == [("O3", "FILL without an ACK")]

    # Quote legs are acknowledged per quote, so a quoting gateway's order may
    # start with its first FILL.
    event(world, "QUOTE_ACK", "Q1", "GW2")
    assert run(open_ds, world, "C1").violations == 0


def test_c1_does_not_demand_acks_older_than_the_retention(
    world: Path, open_ds: OpenDataset
) -> None:
    sql(
        world / "stats.db",
        "DELETE FROM order_events WHERE order_id = 'O3' AND event_type = 'ACK'",
    )
    sql(
        world / "stats.db",
        "INSERT INTO stats_meta VALUES ('keep_order_events_days', '0.01')",
    )
    out = run(open_ds, world, "C1")
    assert out.violations == 0
    assert "not checked" in out.note


def test_c2_finds_an_event_after_a_terminal_state_but_not_a_rejected_command(
    world: Path, open_ds: OpenDataset
) -> None:
    # O1 is FILLED. A rejected cancel of it is fine; a cancel is not.
    event(world, "REJECT", "O1", "GW1", reason="Order not found")
    assert run(open_ds, world, "C2").violations == 0
    event(world, "CANCEL", "O1", "GW1")
    event(world, "FILL", "O1", "GW1", fill_qty=1, remaining_qty=0, status="FILLED")
    out = run(open_ds, world, "C2")
    assert errors(out) == [("O1", "CANCEL after FILLED")]  # reported once
    assert out.samples[0]["events"] == "ACK FILL+ REJECT CANCEL FILL+"


def test_c2_finds_a_quote_leg_filling_after_its_cancel(
    world: Path, open_ds: OpenDataset
) -> None:
    """The shape of finding X3: CANCEL(QUOTE_LEG_FILLED), FILL, CANCEL."""
    event(world, "QUOTE_ACK", "Q1", "MM")
    event(world, "CANCEL", "L1", "MM", reason="QUOTE_LEG_FILLED")
    event(world, "FILL", "L1", "MM", quantity=10, fill_qty=10, remaining_qty=0, status="FILLED")  # fmt: skip
    assert errors(run(open_ds, world, "C2")) == [("L1", "FILL after CANCELLED")]


# --- C3: quantities ------------------------------------------------------------


def test_c3_finds_a_wrong_remaining_qty_and_status(
    world: Path, open_ds: OpenDataset
) -> None:
    sql(
        world / "stats.db",
        "UPDATE order_events SET remaining_qty = 5 "
        "WHERE order_id = 'O1' AND event_type = 'FILL'",
    )
    out = run(open_ds, world, "C3")
    assert [s["order_id"] for s in out.samples] == ["O1"]
    assert sorted(out.samples[0]["problems"]) == ["remaining_qty", "status"]


def test_c3_follows_partial_fills(world: Path, open_ds: OpenDataset) -> None:
    event(world, "FILL", "O9", "GW3", quantity=50, fill_qty=20, remaining_qty=30, status="PARTIAL")  # fmt: skip
    event(world, "FILL", "O9", "GW3", quantity=50, fill_qty=20, remaining_qty=20, status="PARTIAL")  # fmt: skip
    out = run(open_ds, world, "C3")
    assert out.samples[0]["problems"] == {
        "remaining_qty": {"stored": 20, "expected": 10}
    }


# --- C4: the persisted book ----------------------------------------------------


def test_c4_finds_a_live_order_missing_from_the_book(
    world: Path, open_ds: OpenDataset
) -> None:
    book(world)
    assert errors(run(open_ds, world, "C4")) == [
        ("O9", "live in order_events, not in the book")
    ]


def test_c4_finds_a_finished_order_still_in_the_book(
    world: Path, open_ds: OpenDataset
) -> None:
    book(world, RESTING, {**RESTING, "id": "O1"})
    assert errors(run(open_ds, world, "C4")) == [("O1", "in the book but FILLED")]


def test_c4_finds_a_remaining_qty_mismatch(world: Path, open_ds: OpenDataset) -> None:
    book(world, {**RESTING, "remaining_qty": 40, "status": "PARTIAL"})
    out = run(open_ds, world, "C4")
    assert out.samples == [
        {
            "order_id": "O9",
            "error": "remaining_qty differs",
            "order_events": 50,
            "book": 40,
        }
    ]


def test_c4_finds_book_entries_without_order_events_but_not_quiet_quote_legs(
    world: Path, open_ds: OpenDataset
) -> None:
    book(
        world,
        RESTING,
        {**RESTING, "id": "X1"},
        {**RESTING, "id": "L1", "origin": "QUOTE"},
        {**RESTING, "id": "X2", "status": "PARTIAL"},
    )
    assert errors(run(open_ds, world, "C4")) == [
        ("X1", "in the book, no order events"),
        ("X2", "book status disagrees with its quantities"),
        ("X2", "in the book, no order events"),
    ]


def test_c4_finds_a_day_order_resting_after_the_close(
    world: Path, open_ds: OpenDataset
) -> None:
    sql(
        world / "clearing.db",
        "INSERT INTO session_events (event_type, ts_ns, trade_date, payload_json) "
        "VALUES ('PHASE', ?, '2026-06-15', '{\"state\": \"CLOSED\"}')",
        ns("15:30:00"),
    )
    assert errors(run(open_ds, world, "C4")) == [
        ("O9", "DAY order resting after the close")
    ]


def test_c4_is_skipped_without_the_persisted_book(
    world: Path, open_ds: OpenDataset
) -> None:
    (world / "gtc_orders.json").unlink()
    (result,) = run_checks(open_ds(world), [REGISTRY["C4"]], 10)
    assert result.status == "SKIPPED"


# --- C5: OCO -------------------------------------------------------------------


def oco(data: Path, *legs: str) -> None:
    for leg in legs:
        event(data, "ACK", leg, "GW1", quantity=10, oco_group_id="G")


def fill(data: Path, oid: str, qty: int, remaining: int) -> None:
    status = "FILLED" if remaining == 0 else "PARTIAL"
    event(data, "FILL", oid, "GW1", quantity=10, fill_qty=qty, remaining_qty=remaining, status=status, oco_group_id="G")  # fmt: skip


def test_c5_accepts_a_sibling_closed_by_oco_cancel(
    world: Path, open_ds: OpenDataset
) -> None:
    oco(world, "A", "B")
    fill(world, "A", 10, 0)
    event(world, "OCO_CANCEL", "G", "GW1", reason="OCO sibling A reached FILLED")
    out = run(open_ds, world, "C5")
    assert out.violations == 0
    assert "1 siblings closed only by OCO_CANCEL" in out.note


def test_c5_finds_a_sibling_left_live(world: Path, open_ds: OpenDataset) -> None:
    oco(world, "A", "B")
    fill(world, "A", 10, 0)
    assert errors(run(open_ds, world, "C5")) == [("B", "still live after sibling A FILLED")]  # fmt: skip


def test_c5_finds_a_fill_after_the_sibling_filled(
    world: Path, open_ds: OpenDataset
) -> None:
    oco(world, "A", "B")
    fill(world, "A", 10, 0)
    fill(world, "B", 4, 6)
    event(world, "OCO_CANCEL", "G", "GW1")
    assert errors(run(open_ds, world, "C5")) == [("B", "fill after sibling FILLED")]


def oco_rule_cancel(data: Path, leg: str, reason: str) -> None:
    """oco.cancelled as pm-stats records it: the OCO_CANCEL row, then the
    leg's own CANCEL row (X7)."""
    event(data, "OCO_CANCEL", "G", "GW1", reason=reason)
    event(data, "CANCEL", leg, "GW1", reason=reason, oco_group_id="G")


def test_c5_finds_a_fill_after_the_sibling_was_cancelled(
    world: Path, open_ds: OpenDataset
) -> None:
    """The sim's second shape (X15): a stop leg the cascade cancelled, its
    limit sibling left live and filled later."""
    oco(world, "A", "B")
    event(world, "CANCEL", "A", "GW1", reason="INSUFFICIENT_LIQUIDITY", oco_group_id="G")  # fmt: skip
    fill(world, "B", 10, 0)
    assert errors(run(open_ds, world, "C5")) == [("B", "fill after sibling CANCELLED")]  # fmt: skip


def test_c5_finds_a_sibling_that_outlived_its_filled_leg(
    world: Path, open_ds: OpenDataset
) -> None:
    """X15 in the quote path: the sibling of a leg a quote filled was never
    pulled; its owner cancelled it later, so it did not end live."""
    oco(world, "A", "B")
    fill(world, "A", 10, 0)
    event(world, "CANCEL", "B", "GW1", oco_group_id="G")
    assert errors(run(open_ds, world, "C5")) == [("B", "CANCEL after sibling FILLED")]  # fmt: skip


def test_c5_accepts_the_sibling_pulled_before_the_legs_fill_is_published(
    world: Path, open_ds: OpenDataset
) -> None:
    """Since X15 the engine pulls the sibling inside the dispatch, so its
    cancel comes before the fill that caused it."""
    oco(world, "A", "B")
    oco_rule_cancel(world, "B", "OCO sibling A reached FILLED")
    fill(world, "A", 10, 0)
    out = run(open_ds, world, "C5")
    assert out.violations == 0
    assert "0 siblings closed only by OCO_CANCEL" in out.note


def test_c5_finds_a_group_without_two_legs(world: Path, open_ds: OpenDataset) -> None:
    oco(world, "A", "B", "C")
    assert run(open_ds, world, "C5").samples == [
        {"oco_group_id": "G", "error": "3 legs"}
    ]


# --- C6: reasons and reject counts -------------------------------------------


def test_c6_finds_a_cancel_reason_outside_the_spec(
    world: Path, open_ds: OpenDataset
) -> None:
    event(world, "CANCEL", "O9", "GW3", reason="BECAUSE")
    assert run(open_ds, world, "C6").samples == [
        {"cancel_reason": "BECAUSE", "count": 1}
    ]


def test_c6_leaves_the_oco_sibling_rows_free_text_alone(
    world: Path, open_ds: OpenDataset
) -> None:
    """The 2026-10-25 run's 4 622 C6 failures: pm-stats's X7 row carries
    oco.cancelled's reason, which no spec code list covers. The same text on
    a CANCEL that no OCO_CANCEL row precedes is still reported."""
    oco(world, "A", "B")
    oco_rule_cancel(world, "B", "OCO sibling A reached FILLED")
    event(world, "CANCEL", "O9", "GW3", reason="OCO sibling A reached FILLED")
    out = run(open_ds, world, "C6")
    assert out.samples == [
        {"cancel_reason": "OCO sibling A reached FILLED", "count": 1}
    ]
    assert out.note.startswith("1 OCO sibling cancels")


def test_c6_finds_rejects_the_engine_did_not_count(
    world: Path, open_ds: OpenDataset
) -> None:
    sql(
        world / "stats.db",
        "INSERT INTO order_events (ts, event_type, order_id, gateway_id, symbol) "
        "VALUES (?, 'REJECT', 'R1', 'GW1', 'AAPL')",
        iso(TRADES[0].ts_ns),
    )
    out = run(open_ds, world, "C6")
    assert [(s["label"], s["counter_total"], s["rows_before_sample"]) for s in out.samples] == [  # fmt: skip
        ("GW1", 0, 1)
    ]
