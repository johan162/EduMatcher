"""tools/sim_forensics check C9: IOC, FOK and MARKET orders end in the
dispatch that brought them, and a FOK fills all or nothing."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.sim_forensics_world import OpenDataset, opener
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.registry import REGISTRY, Outcome  # noqa: E402

GW = "GW1"
Msg = tuple[str, dict[str, Any]]


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


def new(oid: str, kind: str) -> Msg:
    return ("order.new", {"id": oid, "order_type": kind, "gateway_id": GW})


def ack(oid: str, accepted: bool = True, code: str | None = None) -> Msg:
    return (f"order.ack.{GW}", {"order_id": oid, "accepted": accepted, "reject_code": code})  # fmt: skip


def fill(oid: str, qty: int, remaining: int) -> Msg:
    return (f"order.fill.{GW}", {"order_id": oid, "fill_qty": qty, "remaining_qty": remaining})  # fmt: skip


def cancelled(oid: str, reason: str) -> Msg:
    return (f"order.cancelled.{GW}", {"order_id": oid, "cancel_reason": reason})


def c9(open_ds: OpenDataset, tmp_path: Path, *chains: list[Msg]) -> Outcome:
    data = tmp_path / "data"
    data.mkdir()
    out, n = [], 0
    for c, chain in enumerate(chains):
        for topic, p in chain:
            n += 1
            out.append(
                f"[2026-10-28T07:30:00.000+00:00] [{topic}] "
                f"[seq={n} msg=M{n} chain=C{c}] {json.dumps(p)}\n"
            )
    (data / "audit.log").write_text("".join(out))
    return REGISTRY["C9"].fn(open_ds(data))


def errors(out: Outcome) -> list[tuple[object, object]]:
    return [(s["order_id"], s["error"]) for s in out.samples]


def test_c9_passes_orders_that_end_in_their_dispatch(
    open_ds: OpenDataset, tmp_path: Path
) -> None:
    out = c9(
        open_ds,
        tmp_path,
        [new("I1", "IOC"), ack("I1"), fill("I1", 5, 5), cancelled("I1", "INSUFFICIENT_LIQUIDITY")],  # fmt: skip
        [new("M1", "MARKET"), ack("M1"), fill("M1", 10, 0)],
        [new("F1", "FOK"), ack("F1"), fill("F1", 4, 6), fill("F1", 6, 0)],
        [new("F2", "FOK"), ack("F2", False, "INSUFFICIENT_LIQUIDITY")],
        # The documented SMP case: acked, then cancelled without a fill.
        [new("F3", "FOK"), ack("F3"), cancelled("F3", "SELF_MATCH_PREVENTED")],
        [new("L1", "LIMIT"), ack("L1")],  # rests: not C9's business
        [("order.cancel", {"order_id": "I1"}), ack("I1", False, "ORDER_NOT_FOUND")],
    )
    assert out.violations == 0, out.samples
    assert out.note == "FOK CANCELLED 1, FOK FILLED 1, FOK REJECTED 1, IOC CANCELLED 1, MARKET FILLED 1"  # fmt: skip


def test_c9_finds_an_order_that_outlives_its_dispatch(
    open_ds: OpenDataset, tmp_path: Path
) -> None:
    out = c9(
        open_ds,
        tmp_path,
        [new("I1", "IOC"), ack("I1"), fill("I1", 5, 5)],  # the rest rests
        [fill("I1", 5, 0)],
    )
    assert errors(out) == [("I1", "still live after its dispatch")]


def test_c9_finds_fok_breaking_all_or_nothing(
    open_ds: OpenDataset, tmp_path: Path
) -> None:
    out = c9(
        open_ds,
        tmp_path,
        [new("F1", "FOK"), ack("F1"), fill("F1", 4, 6), cancelled("F1", "SELF_MATCH_PREVENTED")],  # fmt: skip
        [new("F2", "FOK"), ack("F2"), cancelled("F2", "INSUFFICIENT_LIQUIDITY")],
        [new("F3", "FOK"), ack("F3"), ack("F3", False, "INSUFFICIENT_LIQUIDITY")],
    )
    assert errors(out) == [
        ("F1", "FOK traded part, then cancelled"),
        ("F2", "FOK cancelled for a reason other than SMP"),
        ("F3", "FOK acked, then rejected"),
    ]
