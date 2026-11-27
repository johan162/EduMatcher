"""What a snapshot's evidence can support, and why not when it cannot.

The Audit GUI asks this per snapshot, not per software release: one old
archive may support stories but not recorded causality or re-run (design
§6). A capability that is unavailable carries a stable :class:`Reason` code
and a sentence naming the evidence behind it, so a view can say exactly why
it is empty instead of showing an empty success (design §8.1).

Reason codes (stable; new codes may be added, none is renamed):

``NO_EVENTS``
    The snapshot holds no audit record.
``NO_ENVELOPES``
    No record carries a causal envelope (``msg=``): a trail recorded before
    envelopes existed. Stories are told from timing alone.
``NO_TICK_SCALE``
    A symbol's records carry no ``tick_decimals``, or no record names a
    priced symbol: prices cannot be shown in money.
``NO_BOOK_OBSERVATIONS``
    No ``book.*`` or ``depth.*`` record: no depth heatmap or quoted spread.
``NO_ENGINE_START``
    The trail does not begin with ``system.startup``, so the engine's
    starting state and configuration are unknown.
``NO_RECORDED_CONFIG``
    A run's ``system.startup`` carries no configuration (the engine ran on a
    YAML file).
``RERUN_UNAVAILABLE``
    Needs an engine re-run, which is itself unavailable.
``NOT_ATTACHED``
    An optional source (simulator context, ``pm-sim-forensics`` report) is
    not attached to this snapshot.
``NOT_IN_RELEASE``
    The analysis belongs to a later release (the R2 behavioural lane).
``UNKNOWN_SNAPSHOT``
    No snapshot has this id (or the id is malformed).
``SOURCE_MISSING``
    A file the snapshot pinned, or the collection directory, is gone.
``SOURCE_CHANGED``
    A retained file no longer has the size and hash the snapshot pinned.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from edumatcher.models.generated.system import TOPIC_STARTUP


class Capability(str, Enum):
    """An analysis the GUI may offer for a snapshot."""

    STORIES = "stories"
    CAUSALITY = "causality"
    PRICES = "prices"
    BOOK = "book"
    RERUN = "rerun"
    QUEUE = "queue"
    SIM_CONTEXT = "sim_context"
    FORENSICS = "forensics"


class Reason(str, Enum):
    """Why a capability or a snapshot is unavailable (see the module doc)."""

    NO_EVENTS = "NO_EVENTS"
    NO_ENVELOPES = "NO_ENVELOPES"
    NO_TICK_SCALE = "NO_TICK_SCALE"
    NO_BOOK_OBSERVATIONS = "NO_BOOK_OBSERVATIONS"
    NO_ENGINE_START = "NO_ENGINE_START"
    NO_RECORDED_CONFIG = "NO_RECORDED_CONFIG"
    RERUN_UNAVAILABLE = "RERUN_UNAVAILABLE"
    NOT_ATTACHED = "NOT_ATTACHED"
    NOT_IN_RELEASE = "NOT_IN_RELEASE"
    UNKNOWN_SNAPSHOT = "UNKNOWN_SNAPSHOT"
    SOURCE_MISSING = "SOURCE_MISSING"
    SOURCE_CHANGED = "SOURCE_CHANGED"


@dataclass(frozen=True)
class CapabilityState:
    """``reason`` is None exactly when the capability is available."""

    available: bool
    reason: Reason | None = None
    detail: str = ""


AVAILABLE = CapabilityState(True)


def unavailable(reason: Reason, detail: str) -> CapabilityState:
    return CapabilityState(False, reason, detail)


@dataclass(frozen=True)
class Evidence:
    """What one pass over a snapshot's records found, as capabilities need it."""

    entries: int
    first_topic: str | None
    with_envelope: int
    book_observations: int
    #: Symbols named by priced records, and those that never said their scale.
    priced_symbols: frozenset[str]
    unscaled_symbols: frozenset[str]
    #: ``(run_seq, startup ts)`` of each run whose startup has no config.
    runs_without_config: tuple[tuple[int | None, str], ...]


def evaluate(ev: Evidence) -> dict[Capability, CapabilityState]:
    """Every capability's state for evidence *ev*."""
    if ev.entries == 0:
        none = unavailable(Reason.NO_EVENTS, "the snapshot holds no audit record")
        states = dict.fromkeys(Capability, none)
    else:
        states = {
            Capability.STORIES: AVAILABLE,
            Capability.CAUSALITY: _causality(ev),
            Capability.PRICES: _prices(ev),
            Capability.BOOK: _book(ev),
            Capability.RERUN: _rerun(ev),
        }
        states[Capability.QUEUE] = (
            AVAILABLE
            if states[Capability.RERUN].available
            else unavailable(
                Reason.RERUN_UNAVAILABLE,
                "an exact queue needs an engine re-run: "
                + states[Capability.RERUN].detail,
            )
        )
    states[Capability.SIM_CONTEXT] = unavailable(
        Reason.NOT_ATTACHED, "no simulator context database is attached"
    )
    states[Capability.FORENSICS] = unavailable(
        Reason.NOT_ATTACHED, "no pm-sim-forensics report is attached"
    )
    return states


def _causality(ev: Evidence) -> CapabilityState:
    if ev.with_envelope:
        return AVAILABLE
    return unavailable(
        Reason.NO_ENVELOPES,
        f"none of the {ev.entries} records carries a causal envelope",
    )


def _prices(ev: Evidence) -> CapabilityState:
    if not ev.priced_symbols:
        return unavailable(Reason.NO_TICK_SCALE, "no record names a priced symbol")
    if ev.unscaled_symbols:
        names = ", ".join(sorted(ev.unscaled_symbols))
        return unavailable(Reason.NO_TICK_SCALE, f"no tick_decimals recorded for {names}")  # fmt: skip
    return AVAILABLE


def _book(ev: Evidence) -> CapabilityState:
    if ev.book_observations:
        return AVAILABLE
    return unavailable(
        Reason.NO_BOOK_OBSERVATIONS, "no book.* or depth.* record was retained"
    )


def _rerun(ev: Evidence) -> CapabilityState:
    if ev.first_topic != TOPIC_STARTUP:
        return unavailable(
            Reason.NO_ENGINE_START,
            f"the trail begins with {ev.first_topic}, not the engine's "
            f"{TOPIC_STARTUP}",
        )
    if ev.runs_without_config:
        runs = ", ".join(f"run {'?' if seq is None else seq} (started {ts})" for seq, ts in ev.runs_without_config)  # fmt: skip
        return unavailable(
            Reason.NO_RECORDED_CONFIG,
            f"system.startup carries no configuration for {runs}",
        )
    return AVAILABLE
