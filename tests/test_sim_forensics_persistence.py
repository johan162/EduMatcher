"""tools/sim_forensics checks G1-G2 (what the engine persists).

G1 reads gtc_orders.json written from real ``Order.to_dict()``; G2 runs on
the shared world (trade ids of run_seq 1) with engine_run_seq.json and,
where a test needs an engine start, a one-line audit.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from edumatcher.models.order import TIF, Order, OrderStatus, OrderType, Side
from tests.sim_forensics_world import OpenDataset, build, opener, sql
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.registry import REGISTRY, Outcome, run_checks  # noqa: E402


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


@pytest.fixture
def world(tmp_path: Path) -> Path:
    data = build(tmp_path / "data")
    (data / "engine_run_seq.json").write_text(json.dumps({"run_seq": 1}))
    return data


def run(open_ds: OpenDataset, data: Path, check_id: str) -> Outcome:
    return REGISTRY[check_id].fn(open_ds(data))


def resting(**changes: Any) -> dict[str, Any]:
    o = Order.create(
        symbol="AAPL",
        side=Side.SELL,
        order_type=OrderType.STOP_LIMIT,
        quantity=50,
        gateway_id="GW1",
        tif=TIF.GTC,
        price_ticks=14900,
        stop_price_ticks=14950,
    )
    return {**o.to_dict(), **changes}


def persist(
    data: Path, *orders: dict[str, Any], combos: tuple[dict[str, Any], ...] = ()
) -> None:
    (data / "gtc_orders.json").write_text(json.dumps(list(orders)))
    (data / "gtc_combos.json").write_text(json.dumps(list(combos)))


# --- G1 ----------------------------------------------------------------------


def test_g1_passes_on_live_well_formed_orders(
    world: Path, open_ds: OpenDataset
) -> None:
    persist(world, resting(), resting(remaining_qty=20, status="PARTIAL"))
    out = run(open_ds, world, "G1")
    assert out.violations == 0, out.samples
    assert out.note == "2 orders, 0 combos persisted"


@pytest.mark.parametrize(
    "changes, error",
    [
        ({"status": OrderStatus.FILLED.value, "remaining_qty": 0}, "status FILLED"),
        ({"remaining_qty": 51}, "remaining_qty outside (0, quantity]"),
        ({"remaining_qty": 20}, "status disagrees with its quantities"),
        ({"price_ticks": None}, "no integer price_ticks"),
        ({"stop_price_ticks": 149.5}, "no integer stop_price_ticks"),
        ({"tick_decimals": 4}, "tick_decimals 4 != 2"),
    ],
)
def test_g1_finds_a_persisted_order_that_cannot_be_resting(
    world: Path, open_ds: OpenDataset, changes: dict[str, Any], error: str
) -> None:
    sql(
        world / "stats.db",
        "INSERT INTO instruments VALUES ('AAPL', 2, 0.01, NULL, 'config', 'now')",
    )
    persist(world, resting(**changes))
    (sample,) = run(open_ds, world, "G1").samples
    assert error in sample["errors"]  # type: ignore[operator]


def test_g1_finds_a_finished_combo(world: Path, open_ds: OpenDataset) -> None:
    combo = {"id": "C1", "status": "MATCHED", "tif": "GTC"}
    persist(world, combos=(combo,))
    assert run(open_ds, world, "G1").samples == [
        {"combo_id": "C1", "errors": ["status MATCHED, tif GTC"]}
    ]


# --- G2 ----------------------------------------------------------------------


def start_engine_at(data: Path, at: str) -> None:
    (data / "audit.log").write_text(
        f"[2026-06-15T{at}+00:00] [system.startup] "
        '[seq=1 msg=M1 chain=M1] {"run_seq": 1}\n'
    )


def test_g2_passes_when_trade_ids_carry_the_persisted_run_seq(
    world: Path, open_ds: OpenDataset
) -> None:
    start_engine_at(world, "07:00:00.000")
    results = run_checks(open_ds(world), [REGISTRY["G2"]], 10)
    assert (results[0].status, results[0].violations) == ("PASS", 0)
    assert "1 run_seq(s) in trade_log" in results[0].note


def test_g2_finds_a_trade_id_above_the_persisted_run_seq(
    world: Path, open_ds: OpenDataset
) -> None:
    (world / "engine_run_seq.json").write_text(json.dumps({"run_seq": 0}))
    out = run(open_ds, world, "G2")
    assert out.violations == 4
    assert out.samples[0]["error"] == "run_seq above 0"


def test_g2_finds_a_run_seq_that_falls(world: Path, open_ds: OpenDataset) -> None:
    """A trade of run_seq 2 before trades of run_seq 1: either the counter
    file was reset or an old engine kept running."""
    (world / "engine_run_seq.json").write_text(json.dumps({"run_seq": 2}))
    sql(world / "stats.db", "UPDATE trade_log SET trade_id = '000002-000000001' WHERE trade_id = '000001-000000001'")  # fmt: skip
    out = run(open_ds, world, "G2")
    assert [s["error"] for s in out.samples] == ["run_seq 1 after run_seq 2"] * 3


def test_g2_finds_trades_after_the_last_start_with_an_old_run_seq(
    world: Path, open_ds: OpenDataset
) -> None:
    """The audit shows an engine start at 08:30, the file run_seq 2: the two
    trades after it must carry 2."""
    (world / "engine_run_seq.json").write_text(json.dumps({"run_seq": 2}))
    start_engine_at(world, "08:30:00.000")
    out = run(open_ds, world, "G2")
    assert [s["trade_id"] for s in out.samples] == [
        "000001-000000003",
        "000001-000000004",
    ]
