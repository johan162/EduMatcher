"""S28: the replay models amends, combos, halts and circuit-breaker
reopens, checks collars (D8) and halts (D11), and compares itself with the
engine's own order.triggered (C7) and priority_seq (D5).

Each test replays a recorded engine run (tests/sim_forensics_features.py);
the consistent run must pass, and each planted fault must be found.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.sim_forensics_features import Run, consistent
from tests.sim_forensics_world import OpenDataset, opener
from edumatcher.models.order import Side
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.registry import REGISTRY, run_checks  # noqa: E402

CHECKS = ["C7", "D1", "D10", "D11", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9"]


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


@pytest.fixture(scope="module")
def recorded(tmp_path_factory: pytest.TempPathFactory) -> str:
    return (consistent(tmp_path_factory.mktemp("rec") / "data") / "audit.log").read_text()  # fmt: skip


def failing(open_ds: OpenDataset, data: Path) -> dict[str, list[str]]:
    results = run_checks(open_ds(data), [REGISTRY[i] for i in CHECKS], 10)
    return {
        r.check.id: [str(s.get("error", "")) for s in r.samples]
        for r in results
        if r.status != "PASS"
    }


def planted(tmp_path: Path, audit: str, edit: Callable[[list[str]], list[str]]) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    (data / "audit.log").write_text("".join(edit(audit.splitlines(keepends=True))))
    return data


def first(lines: list[str], pattern: str) -> int:
    return next(i for i, ln in enumerate(lines) if re.search(pattern, ln))


def payload(line: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads(line.split("] ", 3)[3])
    return body


def with_payload(line: str, **changes: object) -> str:
    head, body = line.split("] ", 3)[:3], payload(line)
    body.update(changes)
    return "] ".join(head) + "] " + json.dumps(body) + "\n"


def test_the_recorded_run_replays_clean(
    recorded: str, tmp_path: Path, open_ds: OpenDataset
) -> None:
    data = planted(tmp_path, recorded, lambda lines: lines)
    assert failing(open_ds, data) == {}
    note = REGISTRY["D9"].fn(open_ds(data)).note
    assert "3 amends, 2 combo legs, 2 halts replayed" in note
    assert REGISTRY["C7"].fn(open_ds(data)).note == "1 stops triggered"


def test_d5_finds_an_amend_that_kept_priority_through_a_price_change(
    recorded: str, tmp_path: Path, open_ds: OpenDataset
) -> None:
    def edit(lines: list[str]) -> list[str]:
        i = first(lines, r"\[order\.amended\..*\"priority_reset\": true")
        lines[i] = with_payload(lines[i], priority_reset=False)
        return lines

    assert failing(open_ds, planted(tmp_path, recorded, edit))["D5"][0] == "amend's priority_reset is not the rule's"  # fmt: skip


def test_d5_finds_a_queue_the_engine_orders_otherwise(
    recorded: str, tmp_path: Path, open_ds: OpenDataset
) -> None:
    def edit(lines: list[str]) -> list[str]:
        i = [k for k, ln in enumerate(lines) if "[engine.trace.TSLA]" in ln][-1]
        lines[i] = with_payload(
            lines[i], priority_seq=1
        )  # ahead of the order before it
        return lines

    assert failing(open_ds, planted(tmp_path, recorded, edit)) == {"D5": ["replayed queue differs from the engine's priority_seq"]}  # fmt: skip


def test_c7_finds_a_trigger_the_engine_did_not_report(
    recorded: str, tmp_path: Path, open_ds: OpenDataset
) -> None:
    def edit(lines: list[str]) -> list[str]:
        del lines[first(lines, r"\[order\.triggered\.")]
        return lines

    assert failing(open_ds, planted(tmp_path, recorded, edit))["C7"] == ["the replay's triggered stops are not the engine's order.triggered"]  # fmt: skip


def test_d2_finds_a_halted_book_the_replay_was_not_told_about(
    recorded: str, tmp_path: Path, open_ds: OpenDataset
) -> None:
    """Without the halt, the crossing buy entered during it should have traded."""

    def edit(lines: list[str]) -> list[str]:
        del lines[first(lines, r"\[circuit_breaker\.halt\.MSFT\]")]
        return lines

    assert "D2" in failing(open_ds, planted(tmp_path, recorded, edit))


def test_d11_finds_a_continuous_trade_in_a_halted_symbol(
    recorded: str, tmp_path: Path, open_ds: OpenDataset
) -> None:
    def edit(lines: list[str]) -> list[str]:
        i = first(lines, r"\[trade\.executed\].*\"aggressor_side\": \"AUCTION\"")
        lines[i] = with_payload(lines[i], aggressor_side="BUY", match_type="CONTINUOUS")
        return lines

    assert "D11" in failing(open_ds, planted(tmp_path, recorded, edit))


def test_d5_finds_a_combo_leg_filled_beyond_its_size(
    recorded: str, tmp_path: Path, open_ds: OpenDataset
) -> None:
    def edit(lines: list[str]) -> list[str]:
        i = first(lines, r"\[order\.ack\.TRADER02\].*\"symbol\": \"MSFT\"")
        lines[i] = with_payload(lines[i], qty=4)
        return lines

    assert "fill size is not min(aggressor left, resting shown)" in failing(open_ds, planted(tmp_path, recorded, edit)).get("D5", [])  # fmt: skip


def test_d8_finds_a_collar_refusal_inside_the_collar(
    recorded: str, tmp_path: Path, open_ds: OpenDataset
) -> None:
    def edit(lines: list[str]) -> list[str]:
        i = [k for k, ln in enumerate(lines) if ln.split("] [")[1] == "order.new"][-1]
        lines[i] = with_payload(lines[i], price_ticks=payload(lines[i])["price_ticks"] // 2 + 10)  # fmt: skip
        return lines

    assert failing(open_ds, planted(tmp_path, recorded, edit)) == {"D8": ["refused as a collar breach inside the collar"]}  # fmt: skip


def test_d8_finds_an_order_accepted_outside_the_collar(
    recorded: str, tmp_path: Path, open_ds: OpenDataset
) -> None:
    def edit(lines: list[str]) -> list[str]:
        i = first(lines, r"\[risk\.band\.TSLA\]")
        band = payload(lines[i])
        lines[i] = with_payload(
            lines[i], static_low_ticks=band["reference_price_ticks"]
        )
        return lines

    # The two TSLA buys below the reference.
    assert failing(open_ds, planted(tmp_path, recorded, edit)) == {"D8": ["accepted outside the collar"] * 2}  # fmt: skip


# --- engine findings (S28) ----------------------------------------------------


def test_x28_an_unfillable_aon_combo_with_a_marketable_leg_is_rejected(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    """X28: the AON pre-check posted every leg without matching, so a
    marketable leg rested crossed (D2) -- and could later fill alone. Now
    the combo fails on entry, and the run is consistent."""
    r = Run(tmp_path / "data")
    _, ask = r.seed["AAPL"]
    mb, _ = r.seed["MSFT"]
    r.cmd(
        "order.combo",
        {"combo_id": "C2", "gateway_id": "TRADER02", "combo_type": "AON", "tif": "DAY", "legs": [
            {"symbol": "AAPL", "side": "BUY", "order_type": "LIMIT", "quantity": 5, "tick_decimals": 2, "price_ticks": ask},
            {"symbol": "MSFT", "side": "SELL", "order_type": "LIMIT", "quantity": 100000, "tick_decimals": 2, "price_ticks": mb},
        ]},
    )  # fmt: skip
    assert failing(open_ds, r.finish()) == {}


def test_x29_an_administrator_resume_does_not_uncross(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    """X29: interest that crossed during an administrator's halt is resumed
    into continuous trading crossed (D2), where a circuit-breaker reopen
    would have uncrossed it."""
    r = Run(tmp_path / "data")
    tb, ta = r.seed["TSLA"]
    r.cmd("risk.symbol_halt", {"gateway_id": "OPS01", "symbol": "TSLA", "command_id": "H1"})  # fmt: skip
    r.order(Side.BUY, 7, ta, "TRADER03", sym="TSLA")
    r.order(Side.SELL, 4, tb, "TRADER01", sym="TSLA")
    r.cmd("risk.symbol_resume", {"gateway_id": "OPS01", "symbol": "TSLA", "command_id": "H2"})  # fmt: skip
    assert set(failing(open_ds, r.finish())) == {"D2"}


# --- E: the breaker timer as an input; E7's shift with collars and breakers --


def test_the_re_runs_reproduce_the_breaker_reopen(
    recorded: str, tmp_path: Path, open_ds: OpenDataset
) -> None:
    from sim_forensics.checks.rerun import BREAKER_TIMER, _rerun

    data = planted(tmp_path, recorded, lambda lines: lines)
    ds = open_ds(data)
    for cid in ("E1", "E2", "E4", "E5", "E6", "E7"):
        assert REGISTRY[cid].fn(ds).violations == 0, cid
    assert _rerun(ds).commands[BREAKER_TIMER] == 1
    assert REGISTRY["E7"].fn(ds).note.endswith("transforms: rename, price shift")


def test_e2_finds_a_reopen_the_engine_would_not_print(
    recorded: str, tmp_path: Path, open_ds: OpenDataset
) -> None:
    def edit(lines: list[str]) -> list[str]:
        i = first(lines, r"\[auction\.result\.MSFT\].*\"reason\": \"REOPEN\"")
        lines[i] = with_payload(lines[i], eq_qty=payload(lines[i])["eq_qty"] + 1)
        return lines

    out = REGISTRY["E2"].fn(open_ds(planted(tmp_path, recorded, edit)))
    assert [s["command"] for s in out.samples] == ["circuit_breaker.timer"]


def test_the_shifted_collar_decides_in_the_original_prices() -> None:
    """Shifting a collar's reference moves its edges by k + k x pct, so a
    naive shift would accept 12 008 (12 001 un-shifted) against a 20 % band
    around 10 000; in the original prices it is refused."""
    from edumatcher.engine.collar import CollarConfig, validate_collar
    from sim_forensics.checks.differential import (
        _collar_in_original_prices,
        _ShiftedCollar,
    )

    naive = CollarConfig(symbol="X", reference_price=10_007, static_band_pct=0.2, dynamic_band_pct=0.02)  # fmt: skip
    assert not validate_collar(12_008, naive, None).rejected
    shifted = _ShiftedCollar(symbol="X", reference_price=10_000, static_band_pct=0.2, dynamic_band_pct=0.02, e7_shift=7)  # fmt: skip
    assert _collar_in_original_prices(12_008, shifted, None).rejected
    assert not _collar_in_original_prices(12_007, shifted, None).rejected
