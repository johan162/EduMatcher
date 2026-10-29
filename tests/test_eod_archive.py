"""The day's closing state is archived (S26) and G3 checks it against the
close's checkpoint and the next day's start."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

import edumatcher.engine.main as engine_main
from edumatcher.models.order import TIF, OrderType, Side
from tests.engine_harness import connect, make_engine, order_payload
from tests.sim_forensics_world import OpenDataset, opener
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.registry import REGISTRY, Outcome  # noqa: E402


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


def test_the_close_archives_the_books_long_orders(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(engine_main, "DATA_DIR", tmp_path)
    e, _ = make_engine(monkeypatch, tmp_path, sessions_enabled=True)
    connect(e)
    for state in ("PRE_OPEN", "CONTINUOUS"):
        e._handle_session_transition({"to_state": state})
    gtc = order_payload(Side.BUY, OrderType.LIMIT, 5, "GW01", price=99.0, tif=TIF.GTC)
    day = order_payload(Side.BUY, OrderType.LIMIT, 5, "GW01", price=98.0)
    for p in (gtc, day):
        e._handle_new_order(p)
    e._handle_session_transition({"to_state": "CLOSED"})
    archive = tmp_path / "eod" / datetime.now().date().isoformat()
    kept = json.loads((archive / "gtc_orders.json").read_text())
    assert [o["id"] for o in kept] == [gtc["id"]]  # the DAY order expired
    assert (archive / "book_stats.json").is_file() and (archive / "gtc_combos.json").is_file()  # fmt: skip


def _checkpoint(ts: str, reason: str, phase: str, orders: list[tuple[str, int]]) -> str:
    rows = [{"order_id": oid, "remaining_qty": left} for oid, left in orders]
    p = {"symbol": "AAPL", "reason": reason, "phase": phase, "bids": rows, "asks": [], "buy_stops": [], "sell_stops": [], "trailing_stops": []}  # fmt: skip
    return (
        f"[{ts}] [system.book_checkpoint.AAPL] [seq=1 msg=M chain=M] {json.dumps(p)}\n"
    )


def g3(open_ds: OpenDataset, tmp_path: Path, archived: list[tuple[str, int]], close: list[tuple[str, int]], start: list[tuple[str, int]], extra: str = "", before: str = "") -> Outcome:  # fmt: skip
    data = tmp_path / "data"
    (data / "eod" / "2026-10-28").mkdir(parents=True)
    (data / "eod" / "2026-10-28" / "gtc_orders.json").write_text(
        json.dumps([{"id": oid, "remaining_qty": left} for oid, left in archived])
    )
    (data / "audit.log").write_text(
        before
        + _checkpoint("2026-10-28T15:30:00.000+00:00", "PHASE", "CLOSED", close)
        + extra
        + _checkpoint("2026-10-29T07:00:00.000+00:00", "STARTUP", "CLOSED", start)
    )
    return REGISTRY["G3"].fn(open_ds(data))


def test_g3_passes_a_book_that_carries_over(
    open_ds: OpenDataset, tmp_path: Path
) -> None:
    out = g3(open_ds, tmp_path, [("G1", 5)], [("G1", 5)], [("G1", 5), ("S1", 1000)],
             extra='[2026-10-29T07:00:00.000+00:00] [order.ack.MM01] [seq=1 msg=M chain=M] {"order_id": "S1", "accepted": true, "is_seed": true}\n')  # fmt: skip
    assert out.violations == 0, out.samples
    assert out.note == "1 archived days, 1 with their close in the audit"


@pytest.mark.parametrize(
    "close, start, against",
    [
        ([("G1", 4)], [("G1", 5)], "the close"),
        ([("G1", 5)], [], "the next start"),
    ],
)
def test_g3_finds_a_book_that_changed_overnight(
    open_ds: OpenDataset, tmp_path: Path, close: Any, start: Any, against: str
) -> None:
    out = g3(open_ds, tmp_path, [("G1", 5)], close, start)
    (sample,) = out.samples
    assert sample["against"] == against


def test_g3_takes_the_close_not_a_start_before_the_open(
    open_ds: OpenDataset, tmp_path: Path
) -> None:
    """2026-10-29 run: the engine started that morning in CLOSED, and G3
    compared the archive with that start's (empty) book."""
    out = g3(open_ds, tmp_path, [("G1", 5)], [("G1", 5)], [("G1", 5)],
             before=_checkpoint("2026-10-28T07:00:00.000+00:00", "STARTUP", "CLOSED", []))  # fmt: skip
    assert out.violations == 0, out.samples
