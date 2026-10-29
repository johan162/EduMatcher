"""tools/sim_forensics check C11 (running totals from the S22 fields) and
D8's agreement of a trade's display price with its price_ticks."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.sim_forensics_world import OpenDataset, opener
from tests.test_sim_forensics_matching import continuous_day
from tests.test_sim_forensics_rerun import edit, record
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.registry import REGISTRY, Outcome, run_checks  # noqa: E402


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


def c11(open_ds: OpenDataset, data: Path) -> Outcome:
    return REGISTRY["C11"].fn(open_ds(data))


def test_c11_passes_a_real_engines_recording(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    out = c11(open_ds, record(tmp_path / "data"))
    assert out.violations == 0, out.samples
    assert re.match(r"[1-9]\d* fills, [1-9]\d* cancels/expiries", out.note)


@pytest.mark.parametrize(
    "key, error",
    [
        ("cum_qty", "running totals are not the sum of the fills"),
        ("fill_notional_ticks", "fill notional is not its trades' price × quantity"),
    ],
)
def test_c11_finds_a_fill_that_does_not_add_up(
    tmp_path: Path, open_ds: OpenDataset, key: str, error: str
) -> None:
    data = record(tmp_path / "data")
    edit(data, "[order.fill.", lambda ln: [re.sub(rf'"{key}": (\d+)', lambda m: f'"{key}": {int(m[1]) + 1}', ln)])  # fmt: skip
    assert error in {s["error"] for s in c11(open_ds, data).samples}


def test_c11_finds_a_cancel_that_misreports_what_had_filled(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    data = record(tmp_path / "data")
    edit(data, "[order.cancelled.", lambda ln: [re.sub(r'"cum_qty": (\d+)', lambda m: f'"cum_qty": {int(m[1]) + 1}', ln)])  # fmt: skip
    (sample,) = c11(open_ds, data).samples
    assert sample["error"] == "a cancel or expiry's cum_qty is not what had filled"


def test_c11_skips_an_audit_from_before_the_fields(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    data = continuous_day().write(tmp_path / "data")  # tapes without them
    (result,) = run_checks(open_ds(data), [REGISTRY["C11"]], 10)
    assert result.status == "SKIPPED"


def test_d8_finds_a_display_price_that_is_not_its_ticks(
    tmp_path: Path, open_ds: OpenDataset
) -> None:
    t = continuous_day()
    i = next(k for k, ln in enumerate(t.lines) if "[trade.executed]" in ln)
    head, body = t.lines[i].split("] {", 1)
    payload = json.loads("{" + body)
    payload["price_ticks"] = round(payload["price"] * 100) + 1
    t.lines[i] = f"{head}] {json.dumps(payload)}\n"
    out = REGISTRY["D8"].fn(open_ds(t.write(tmp_path / "data")))
    assert [s.get("error") for s in out.samples] == ["display price is not price_ticks"]
