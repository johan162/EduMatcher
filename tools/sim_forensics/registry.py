"""The check contract, the registry, and running checks."""

from __future__ import annotations

import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from multiprocessing import get_context
from pathlib import Path
from typing import Literal

from sim_forensics.dataset import Dataset

from edumatcher.audit.rawlines import Unavailable

#: Oracle types — workplan §3.
ORACLES = (
    "conservation",
    "cross-store",
    "lifecycle",
    "book-state",
    "replay",
    "statistical",
)

#: INFO is the status of every "statistical" check: its count and samples
#: are pointers to look at, not violations, so they never fail a run.
Status = Literal["PASS", "FAIL", "INFO", "SKIPPED", "ERROR"]
Sample = dict[str, object]


@dataclass
class Outcome:
    """What a check function returns: how many violations, and examples."""

    violations: int
    samples: list[Sample] = field(default_factory=list)
    note: str = ""


#: Raised by a check whose stores are present but cannot answer it. The same
#: class the shipped audit reader raises, so a check need not translate it.
Skipped = Unavailable


@dataclass(frozen=True)
class Check:
    id: str
    oracle: str
    title: str
    #: Stores (dataset.STORES) the check reads; a missing one skips it.
    needs: tuple[str, ...]
    fn: Callable[[Dataset], Outcome]
    #: Costs several engine re-runs: only run when asked for (``--slow``).
    slow: bool = False
    #: Reads the outcomes of the checks that failed (``failed_outcomes``), so
    #: it runs after every other check has.
    needs_findings: bool = False


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
    id: str,
    oracle: str,
    title: str,
    needs: tuple[str, ...],
    slow: bool = False,
    needs_findings: bool = False,
) -> Callable[[Callable[[Dataset], Outcome]], Callable[[Dataset], Outcome]]:
    """Register a check function under *id*."""
    if oracle not in ORACLES:
        raise ValueError(f"{id}: unknown oracle {oracle!r}")

    def register(fn: Callable[[Dataset], Outcome]) -> Callable[[Dataset], Outcome]:
        if id in REGISTRY:
            raise ValueError(f"duplicate check id {id}")
        REGISTRY[id] = Check(id, oracle, title, needs, fn, slow, needs_findings)
        return fn

    return register


def run_checks(
    ds: Dataset,
    checks: Iterable[Check],
    max_samples: int,
    slow: bool = False,
    jobs: int = 1,
) -> list[Result]:
    """Run *checks*; a slow one only if *slow*. With *jobs* > 1 the checks
    run in that many processes, one module's checks together (they share the
    results of their expensive passes), and come back in the order given."""
    chosen = list(checks)
    runnable = [c for c in chosen if slow or not c.slow]
    done: dict[str, Result] = {}
    if jobs > 1:
        done = _run_parallel(ds, runnable, max_samples, jobs)
    else:
        for c in runnable:
            done[c.id] = _run_one(ds, c, max_samples)
    skipped = "slow: run with --slow, or name it with --check"
    return [done.get(c.id) or Result(c, "SKIPPED", 0, [], skipped, 0.0) for c in chosen]


def _run_group(
    data_dir: Path, ids: list[str], max_samples: int, keep_failed: bool
) -> tuple[list[tuple[str, Status, int, list[Sample], str, float]], dict[str, Outcome]]:
    """Worker: run the checks *ids* on their own opening of the data dir."""
    import sim_forensics.checks  # noqa: F401  (registers the checks)

    with Dataset.open(data_dir) as ds:
        out = []
        for i in ids:
            r = _run_one(ds, REGISTRY[i], max_samples)
            out.append((i, r.status, r.violations, r.samples, r.note, r.seconds))
        return out, dict(failed_outcomes(ds)) if keep_failed else {}


def _run_parallel(
    ds: Dataset, checks: list[Check], max_samples: int, jobs: int
) -> dict[str, Result]:
    groups: dict[str, list[Check]] = {}
    for c in checks:
        if not c.needs_findings:
            groups.setdefault(c.fn.__module__, []).append(c)
    last = [c for c in checks if c.needs_findings]
    done: dict[str, Result] = {}
    findings = failed_outcomes(ds)
    with ProcessPoolExecutor(
        min(jobs, len(groups) or 1), mp_context=get_context("spawn")
    ) as pool:
        futures = [
            pool.submit(
                _run_group, ds.data_dir, [c.id for c in g], max_samples, bool(last)
            )
            for g in groups.values()
        ]
        for future in futures:
            rows, failed = future.result()
            findings.update(failed)
            for i, status, violations, samples, note, seconds in rows:
                done[i] = Result(
                    REGISTRY[i], status, violations, samples, note, seconds
                )
    for c in last:
        done[c.id] = _run_one(ds, c, max_samples)
    return done


def failed_outcomes(ds: Dataset) -> dict[str, Outcome]:
    """The uncapped outcome of every check that has failed so far, by id
    (H1 reads them; checks run in id order, so A-G come before it)."""
    failed = ds.cache.setdefault("failed", {})
    assert isinstance(failed, dict)
    return failed


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
    if c.oracle == "statistical":
        status = "INFO"
    elif out.violations:
        failed_outcomes(ds)[c.id] = out
    return Result(
        c,
        status,
        out.violations,
        out.samples[:max_samples],
        out.note,
        time.monotonic() - start,
    )
