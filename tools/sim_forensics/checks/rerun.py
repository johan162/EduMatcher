"""E — the run's commands, re-run through a fresh engine.

The re-run itself is ``edumatcher.audit.replay.rerun`` (also reachable as
``pm-audit-replay rerun``); these checks run it once per dataset and report
its three verdicts: E1 hidden inputs, E2 same outputs, E4 final book.
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from sim_forensics.dataset import Dataset
from sim_forensics.registry import Outcome, Skipped, check

from edumatcher.audit.rawlines import Unavailable
from edumatcher.audit.replay.rerun import (  # noqa: F401  (re-exported for the checks and tests)
    _ID_PREFIX,
    _ORDER_ID,
    BREAKER_TIMER,
    HEARTBEAT_TIMER,
    Rerun,
    _compare,
    _Ids,
    _Sink,
    apply,
    fresh_engine,
    inputs,
    live_clock,
)

__all__ = [
    "_ID_PREFIX",
    "_ORDER_ID",
    "BREAKER_TIMER",
    "HEARTBEAT_TIMER",
    "Rerun",
    "_compare",
    "_Ids",
    "_Sink",
    "_rerun",
    "apply",
    "fresh_engine",
    "inputs",
    "live_clock",
]


def _rerun(ds: Dataset) -> Rerun:
    cached = ds.cache.get("rerun")
    if isinstance(cached, Unavailable):
        raise cached
    if isinstance(cached, Rerun):
        return cached
    r = Rerun(ds.data_dir)
    try:
        r.run()
    except Skipped as exc:
        ds.cache["rerun"] = exc
        raise
    ds.cache["rerun"] = r
    return r


@check(
    "E1",
    "replay",
    "Every state change the engine published answers a command in the audit",
    needs=(),
)
def hidden_inputs(ds: Dataset) -> Outcome:
    r = _rerun(ds)
    total = sum(r.commands.values())
    top = ", ".join(f"{t} {n}" for t, n in r.commands.most_common(6))
    return Outcome(r.counts["E1"], r.samples["E1"], f"{total} commands ({top}, …)")


@check(
    "E2",
    "replay",
    "A fresh engine fed the audit's commands publishes what the live engine did",
    needs=(),
)
def same_outputs(ds: Dataset) -> Outcome:
    r = _rerun(ds)
    return Outcome(r.counts["E2"], r.samples["E2"], r.note())


@check(
    "E4",
    "replay",
    "The re-run's final resting book is the engine's persisted book",
    needs=(),
)
def final_book(ds: Dataset) -> Outcome:
    r = _rerun(ds)
    return Outcome(r.counts["E4"], r.samples["E4"])
