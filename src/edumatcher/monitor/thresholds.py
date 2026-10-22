"""Threshold rules with hysteresis (design §9.6).

Every second the collector hands in one :class:`Reading` per rule and subject
it can measure. A warning of a configurable rule is raised only after ``RAISE_AFTER`` consecutive
evaluations over its threshold (a single noisy sample is not a breach); a
critical level, and a warning of a fixed rule (a counter that moved, a late
loop), is raised at once. A level falls only after ``CLEAR_AFTER``
consecutive evaluations at the lower level, and an evaluation counts only
once the value is ``CLEAR_RATIO`` of the way back inside the threshold it
breached, so a value hovering around a threshold produces one breach and one
clear, not a flood. A reading that stops arriving (the process went away)
counts as OK.

Every level change is a :class:`Change`: the collector publishes it as a
``THRESHOLD`` event and logs one line through LALF (WARNING for a warn
breach, ERROR for a critical one), so log-gui alerting covers notification
and there is no second alerting system.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from edumatcher.monitor.config import (
    INVERTED_THRESHOLDS,
    MonitorThresholds,
    ThresholdBand,
)

#: Consecutive evaluations over a warn threshold before the breach is raised.
RAISE_AFTER = 5

#: Consecutive evaluations at a lower level before a breach clears or eases.
CLEAR_AFTER = 30

#: A breach holds until the value is back inside this fraction of the
#: threshold it crossed (inverted rules: beyond threshold / CLEAR_RATIO).
CLEAR_RATIO = 0.8

#: Fixed rules that are not in the ``monitor.thresholds`` configuration.
#: ``loop_age_ms``: a loop over 1 s late is a warning; its critical level is
#: the HUNG state (§10), not a threshold.
LOOP_AGE_RULE = "loop_age_ms"
LOOP_AGE_WARN_MS = 1000.0

#: Ratios judged only above a minimum sample (I68): two refused requests out
#: of three is not an exchange in trouble, and a book of three heap entries
#: with one stale is not a compaction problem.
MIN_REQUESTS_5M = 20
MIN_HEAP_ENTRIES = 100

_LEVELS = ("OK", "WARN", "CRIT")


@dataclass(frozen=True)
class Reading:
    """One measured value for one rule and subject."""

    rule: str
    subject: str
    value: float
    warn: float
    crit: float | None = None  # None: the rule has no critical level
    inverted: bool = False  # a LOW value is bad (disk free)
    debounce: bool = True  # False: a warning is raised at once

    def level(self) -> str:
        if self.inverted:
            if self.crit is not None and self.value < self.crit:
                return "CRIT"
            return "WARN" if self.value < self.warn else "OK"
        if self.crit is not None and self.value > self.crit:
            return "CRIT"
        return "WARN" if self.value > self.warn else "OK"

    def threshold(self, level: str) -> float:
        return self.crit if level == "CRIT" and self.crit is not None else self.warn

    def holds(self, level: str) -> bool:
        """Whether the value is still too close to ``level``'s threshold for
        that level to count as cleared."""
        limit = self.threshold(level)
        edge = limit / CLEAR_RATIO if self.inverted else limit * CLEAR_RATIO
        if level == "CRIT" and (
            edge > self.warn if self.inverted else edge < self.warn
        ):
            # The deadband would reach into the warn band: a value there is a
            # warning, not a critical level on its way down.
            return False
        return self.value < edge if self.inverted else self.value > edge


def band_reading(
    thresholds: MonitorThresholds, rule: str, subject: str, value: float
) -> Reading:
    """A reading of a configured rule, with its configured band."""
    band: ThresholdBand = getattr(thresholds, rule)
    return Reading(
        rule, subject, value, band.warn, band.crit, rule in INVERTED_THRESHOLDS
    )


def increase_reading(rule: str, subject: str, increase: float) -> Reading:
    """``any increase in 5 min`` (§9.6): WARN on anything above zero."""
    return Reading(rule, subject, increase, warn=0.0, debounce=False)


@dataclass(frozen=True)
class Change:
    """A level change of one rule on one subject."""

    rule: str
    subject: str
    previous: str  # OK / WARN / CRIT
    level: str
    value: float
    threshold: float
    inverted: bool

    @property
    def severity(self) -> str:
        return "INFO" if self.level == "OK" else self.level

    @property
    def detail(self) -> str:
        if self.level == "OK":
            return f"{self.rule} cleared ({self.value:g})"
        op = "<" if self.inverted else ">"
        return f"{self.rule} {self.level} {self.value:g} {op} {self.threshold:g}"


@dataclass
class _Track:
    level: str = "OK"
    since: str = ""
    value: float = 0.0
    threshold: float = 0.0
    lower_streak: int = 0
    #: The highest level seen during the current run of lower evaluations;
    #: the level settles there, so a CRIT never jumps past an intervening WARN.
    lower_max: str = "OK"


class ThresholdBook:
    """The breach state of every rule and subject."""

    def __init__(
        self, clear_after: int = CLEAR_AFTER, raise_after: int = RAISE_AFTER
    ) -> None:
        self.clear_after = clear_after
        self.raise_after = raise_after
        self._tracks: dict[tuple[str, str], _Track] = {}
        #: Consecutive warn evaluations of subjects not yet in breach.
        self._pending: dict[tuple[str, str], int] = {}
        self._inverted: dict[tuple[str, str], bool] = {}

    def evaluate(self, readings: Iterable[Reading], now_iso: str) -> list[Change]:
        """Apply one second's readings; return the level changes."""
        changes: list[Change] = []
        seen: set[tuple[str, str]] = set()
        for reading in readings:
            key = (reading.rule, reading.subject)
            seen.add(key)
            self._inverted[key] = reading.inverted
            target = reading.level()
            track = self._tracks.get(key)
            if (
                track is not None
                and _LEVELS.index(target) < _LEVELS.index(track.level)
                and reading.holds(track.level)
            ):
                target = track.level
            change = self._step(key, target, reading.value, reading, now_iso)
            if change is not None:
                changes.append(change)
        for key in [k for k in self._pending if k not in seen]:
            del self._pending[key]
        for key in [k for k in self._tracks if k not in seen]:
            track = self._tracks[key]
            change = self._step(key, "OK", track.value, None, now_iso)
            if change is not None:
                changes.append(change)
        return changes

    def _step(
        self,
        key: tuple[str, str],
        target: str,
        value: float,
        reading: Reading | None,
        now_iso: str,
    ) -> Change | None:
        track = self._tracks.get(key)
        if track is None:
            if target == "OK":
                self._pending.pop(key, None)
                return None
            if target == "WARN" and reading is not None and reading.debounce:
                streak = self._pending.get(key, 0) + 1
                if streak < self.raise_after:
                    self._pending[key] = streak
                    return None
            self._pending.pop(key, None)
            track = self._tracks[key] = _Track()
        rank = _LEVELS.index
        previous = track.level
        if reading is not None:
            track.value = value
        if rank(target) > rank(track.level):
            track.level = target
            track.lower_streak = 0
            if previous == "OK":
                track.since = now_iso
        elif rank(target) < rank(track.level):
            if track.lower_streak == 0 or rank(target) > rank(track.lower_max):
                track.lower_max = target
            track.lower_streak += 1
            if track.lower_streak < self.clear_after:
                return None
            track.level = track.lower_max
            track.lower_streak = 0
        else:
            track.lower_streak = 0
            if reading is not None and target != "OK":
                track.threshold = reading.threshold(target)
            return None
        if reading is not None and track.level != "OK":
            track.threshold = reading.threshold(track.level)
        change = Change(
            rule=key[0],
            subject=key[1],
            previous=previous,
            level=track.level,
            value=track.value,
            threshold=track.threshold,
            inverted=self._inverted.get(key, False),
        )
        if track.level == "OK":
            del self._tracks[key]
        return change

    def active(self) -> list[dict[str, Any]]:
        """``ActiveBreach`` records of everything in breach now."""
        return [
            {
                "rule": rule[:64],
                "subject": subject[:200],
                "level": t.level,
                "value": t.value,
                "threshold": t.threshold,
                "since": t.since,
            }
            for (rule, subject), t in sorted(self._tracks.items())
        ]

    def breached_subjects(self) -> set[str]:
        return {subject for (_rule, subject) in self._tracks}
