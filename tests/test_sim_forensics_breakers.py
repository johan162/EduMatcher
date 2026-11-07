"""tools/sim_forensics check D12 (S32): each circuit-breaker halt,
extension and reopen follows from the trades and the config.

A real engine (s3-complex: TSLA's L1 at 7 %, 10 minutes; a corridor of
10 %, widened by 10 % then 20 %) on a clock the test moves, its audit lines
stamped by that clock: a print 8 % off the reference halts TSLA, crossing
interest 25 % off keeps it from reopening until the corridor has widened
twice, then it reopens there. The audit must pass D12; a planted edit must
be found.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

import edumatcher.models.clock as models_clock
import tests.sim_forensics_features as features
from edumatcher.models.clock import reset_clock_for_tests
from edumatcher.models.order import Side
from tests.sim_forensics_world import OpenDataset, opener
from tests.test_sim_forensics_rerun import Recorder
from sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from sim_forensics.registry import REGISTRY  # noqa: E402

T0 = int(datetime(2026, 10, 24, 7, tzinfo=timezone.utc).timestamp()) * 10**9


@pytest.fixture
def open_ds() -> Iterator[OpenDataset]:
    yield from opener()


class Clock:
    """The engine's ``time`` (``models.clock``) and the audit lines' stamp."""

    def __init__(self) -> None:
        self.ns = T0

    def time_ns(self) -> int:
        return self.ns


class StampedRecorder(Recorder):
    """The test recorder, its lines stamped with the clock's time."""

    clock = Clock()

    def _line(self, topic: str, msg: str, chain: str, payload: Any) -> None:
        stamp = datetime.fromtimestamp(self.clock.ns / 1e9, timezone.utc).isoformat(timespec="milliseconds")  # fmt: skip
        self.lines.append(f"[{stamp}] [{topic}] [seq={self.n} msg={msg} chain={chain}] {json.dumps(payload)}\n")  # fmt: skip


def halted_and_reopened(data: Path) -> Path:
    clock = StampedRecorder.clock = Clock()
    reset_clock_for_tests()
    with mock.patch.object(models_clock, "time", clock), mock.patch.object(features, "Recorder", StampedRecorder):  # fmt: skip
        r = features.Run(data)
        r.engine._enforce_collars = (
            False  # the prices below are a collar's business, not D12's
        )
        for mm in ("MM01", "MM02"):
            r.cmd("risk.kill_switch_gateway", {"gateway_id": "OPS01", "target_gateway_id": mm, "symbol": "TSLA", "quotes_only": True})  # fmt: skip
        seed, _ = r.seed["TSLA"]
        cb = r.engine._circuit_breakers["TSLA"]
        ref = cb.reference_price
        assert ref is not None
        clock.ns += 10**9
        jump = int(ref * 1.08)
        r.order(Side.SELL, 10, jump, "TRADER01", sym="TSLA")
        r.order(Side.BUY, 10, jump, "TRADER02", sym="TSLA")  # trips L1
        assert cb.halted
        far = int(ref * 1.25)
        r.order(Side.SELL, 10, far, "TRADER01", sym="TSLA")
        r.order(
            Side.BUY, 10, far, "TRADER02", sym="TSLA"
        )  # rests: the call collects it
        for _ in range(3):  # extend, extend, reopen
            assert cb.resume_at_ns is not None
            clock.ns = cb.resume_at_ns + 1
            r.engine._flush_circuit_breakers()
        assert not cb.halted
        return r.finish()


@pytest.fixture(scope="module")
def recorded(tmp_path_factory: pytest.TempPathFactory) -> str:
    return (halted_and_reopened(tmp_path_factory.mktemp("rec") / "data") / "audit.log").read_text()  # fmt: skip


def d12(open_ds: OpenDataset, tmp_path: Path, audit: str) -> Any:
    data = tmp_path / "data"
    data.mkdir()
    (data / "audit.log").write_text(audit)
    return REGISTRY["D12"].fn(open_ds(data))


def test_a_halt_two_extensions_and_a_reopen_pass(
    recorded: str, tmp_path: Path, open_ds: OpenDataset
) -> None:
    out = d12(open_ds, tmp_path, recorded)
    assert (out.violations, out.samples) == (0, [])
    for seen in ("breaker halts 1", "extensions 2", "reopens 1"):
        assert seen in out.note


def _edit(topic: str, **change: Any) -> Callable[[list[str]], list[str]]:
    def edit(lines: list[str]) -> list[str]:
        i = next(k for k, ln in enumerate(lines) if f"[{topic}" in ln)
        head, body = lines[i].split("] {", 1)
        p = json.loads("{" + body)
        for key, f in change.items():
            p[key] = f(p[key])
        lines[i] = f"{head}] {json.dumps(p)}\n"
        return lines

    return edit


def _drop(topic: str) -> Callable[[list[str]], list[str]]:
    return lambda lines: [ln for ln in lines if f"[{topic}" not in ln]


@pytest.mark.parametrize(
    "plant, error",
    [
        (_edit("circuit_breaker.halt.TSLA", reference_price=lambda v: v + 1), "the halt's numbers are not the breach's"),  # fmt: skip
        (_edit("circuit_breaker.halt.TSLA", resume_at_ns=lambda v: v + 10**12), "the halt's call end is not the level's duration"),  # fmt: skip
        (_drop("circuit_breaker.halt.TSLA"), "a print breached a level, but no halt followed"),  # fmt: skip
        (_edit("circuit_breaker.extend.TSLA", corridor_high=lambda v: v + 1), "the extended corridor is not the ladder's"),  # fmt: skip
        (_edit("circuit_breaker.extend.TSLA", resume_at_ns=lambda v: v - 10**11), "the extension's call is shorter than its rung"),  # fmt: skip
    ],
)
def test_d12_names_a_planted_fault(
    recorded: str,
    tmp_path: Path,
    open_ds: OpenDataset,
    plant: Callable[[list[str]], list[str]],
    error: str,
) -> None:
    out = d12(open_ds, tmp_path, "".join(plant(recorded.splitlines(keepends=True))))
    assert error in [s["error"] for s in out.samples]


def test_d12_finds_a_reopen_before_the_calls_end(
    recorded: str, tmp_path: Path, open_ds: OpenDataset
) -> None:
    """The last call's end pushed past the reopen."""
    lines = recorded.splitlines(keepends=True)
    i = max(k for k, ln in enumerate(lines) if "[circuit_breaker.extend.TSLA" in ln)
    lines = _edit("circuit_breaker.extend.TSLA", resume_at_ns=lambda v: v + 10**11)(lines[i:])  # fmt: skip
    out = d12(open_ds, tmp_path, "".join(recorded.splitlines(keepends=True)[:i] + lines))  # fmt: skip
    assert "reopened before the call's end" in [s["error"] for s in out.samples]
