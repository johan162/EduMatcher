"""The check contract, the registry, and running checks."""

from __future__ import annotations

import time
import traceback
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Literal

from sim_forensics.dataset import Dataset

#: Oracle types — workplan §3.
ORACLES = (
    "conservation",
    "cross-store",
    "lifecycle",
    "book-state",
    "replay",
    "statistical",
)

Status = Literal["PASS", "FAIL", "SKIPPED", "ERROR"]
Sample = dict[str, object]


@dataclass
class Outcome:
    """What a check function returns: how many violations, and examples."""

    violations: int
    samples: list[Sample] = field(default_factory=list)
    note: str = ""


class Skipped(Exception):
    """Raised by a check whose stores are present but cannot answer it."""


@dataclass(frozen=True)
class Check:
    id: str
    oracle: str
    title: str
    #: Stores (dataset.STORES) the check reads; a missing one skips it.
    needs: tuple[str, ...]
    fn: Callable[[Dataset], Outcome]


@dataclass
class Result:
    check: Check
    status: Status
    violations: int
    samples: list[Sample]
    note: str
    seconds: float


REGISTRY: dict[str, Check] = {}


def check(
    id: str, oracle: str, title: str, needs: tuple[str, ...]
) -> Callable[[Callable[[Dataset], Outcome]], Callable[[Dataset], Outcome]]:
    """Register a check function under *id*."""
    if oracle not in ORACLES:
        raise ValueError(f"{id}: unknown oracle {oracle!r}")

    def register(fn: Callable[[Dataset], Outcome]) -> Callable[[Dataset], Outcome]:
        if id in REGISTRY:
            raise ValueError(f"duplicate check id {id}")
        REGISTRY[id] = Check(id, oracle, title, needs, fn)
        return fn

    return register


def run_checks(ds: Dataset, checks: Iterable[Check], max_samples: int) -> list[Result]:
    return [_run_one(ds, c, max_samples) for c in checks]


def _run_one(ds: Dataset, c: Check, max_samples: int) -> Result:
    missing = [s for s in c.needs if s not in ds.stores]
    if missing:
        note = f"store(s) not in data dir: {', '.join(missing)}"
        return Result(c, "SKIPPED", 0, [], note, 0.0)
    start = time.monotonic()
    try:
        out = c.fn(ds)
    except Skipped as exc:
        return Result(c, "SKIPPED", 0, [], str(exc), time.monotonic() - start)
    except Exception:
        # A check broken by real data must not hide the other checks' results.
        return Result(
            c, "ERROR", 0, [], traceback.format_exc(), time.monotonic() - start
        )
    status: Status = "FAIL" if out.violations else "PASS"
    return Result(
        c,
        status,
        out.violations,
        out.samples[:max_samples],
        out.note,
        time.monotonic() - start,
    )
