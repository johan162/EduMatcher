"""Threshold rules with hysteresis (design §9.6).

Every second the collector hands in one :class:`Reading` per rule and subject
it can measure. A warning is raised only after ``RAISE_AFTER`` consecutive
evaluations over its threshold (a single noisy sample is not a breach), or
after ``WINDOWED_RAISE_AFTER`` for a rule whose figure covers a window (one
burst holds it for the whole window); a critical level, and a warning of an
"any increase" rule (a counter that moved), is raised at once. A level falls only after ``CLEAR_AFTER``
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

#: ... for a rule whose figure covers a window: longer than the window, so a
#: burst that the figure holds for all of it is not a breach, but latency that
#: outlasts it is. ``engine.handle_us_p99`` covers the engine's last 60 s
#: (``engine.metrics.LATENCY_HORIZON_NS``), about 390 sampled messages at the
#: simulation's rate, so its p99 is the fourth-worst of them (WP-MHD03).
WINDOWED_RAISE_AFTER = 90
RULE_RAISE_AFTER = {"engine_handle_p99_us": WINDOWED_RAISE_AFTER}

#: Consecutive evaluations at a lower level before a breach clears or eases.
CLEAR_AFTER = 30

#: A breach holds until the value is back inside this fraction of the
#: threshold it crossed (inverted rules: beyond threshold / CLEAR_RATIO).
CLEAR_RATIO = 0.8

#: Fixed rules that are not in the ``monitor.thresholds`` configuration,
#: raised after ``RAISE_AFTER`` like the configured ones: one late iteration
#: is not a degraded loop, and a stuck one is HUNG at 5 s anyway (WP-MHD04).
#: ``loop_age_ms``: a loop over 1 s late is a warning; its critical level is
#: the HUNG state (§10), not a threshold.
LOOP_AGE_RULE = "loop_age_ms"
LOOP_AGE_WARN_MS = 1000.0
#: ``loop_lag_ms``: the worst gap between two loop iterations since the
#: previous beacon over 1 s is a warning. Every loop's designed wait is well
#: below it (I36).
LOOP_LAG_RULE = "loop_lag_ms"
LOOP_LAG_WARN_MS = 1000.0

#: Ratios judged only above a minimum sample (I68): two refused requests out
#: of three is not an exchange in trouble.
MIN_REQUESTS_5M = 20

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
    #: Consecutive evaluations over warn before a warning is raised; 1: at once.
    raise_after: int = RAISE_AFTER

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
        rule,
        subject,
        value,
        band.warn,
        band.crit,
        rule in INVERTED_THRESHOLDS,
        RULE_RAISE_AFTER.get(rule, RAISE_AFTER),
    )


def increase_reading(rule: str, subject: str, increase: float) -> Reading:
    """``any increase in 5 min`` (§9.6): WARN on anything above zero."""
    return Reading(rule, subject, increase, warn=0.0, raise_after=1)


def fmt_value(value: float) -> str:
    """A reading for people: up to three decimals, never an exponent (``:g``
    printed a 1.2 s p99 as ``1.23457e+06``)."""
    return f"{value:.3f}".rstrip("0").rstrip(".")


def breach_text(
    rule: str, level: str, value: float, threshold: float, inverted: bool
) -> str:
    """``rule LEVEL value > threshold``; a breach held while its value is
    back inside the threshold (on its way to clearing) says so instead."""
    over = value < threshold if inverted else value > threshold
    if not over:
        return f"{rule} {level} clearing ({fmt_value(value)})"
    op = "<" if inverted else ">"
    return f"{rule} {level} {fmt_value(value)} {op} {fmt_value(threshold)}"


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
    #: False: no reading arrived (the rule declined to judge, the process
    #: went away), so ``value`` is the last one judged, not a current one.
    judged: bool = True

    @property
    def severity(self) -> str:
        return "INFO" if self.level == "OK" else self.level

    @property
    def detail(self) -> str:
        if self.level == "OK":
            if not self.judged:
                return f"{self.rule} cleared (no longer judged; last {fmt_value(self.value)})"
            return f"{self.rule} cleared ({fmt_value(self.value)})"
        return breach_text(
            self.rule, self.level, self.value, self.threshold, self.inverted
        )


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

    def __init__(self, clear_after: int = CLEAR_AFTER) -> None:
        self.clear_after = clear_after
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
            if target == "WARN" and reading is not None:
                streak = self._pending.get(key, 0) + 1
                if streak < reading.raise_after:
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
            judged=reading is not None,
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

    def reasons(self) -> dict[str, list[str]]:
        """Every subject in breach and its breaches as text, in rule order."""
        out: dict[str, list[str]] = {}
        for (rule, subject), t in sorted(self._tracks.items()):
            out.setdefault(subject, []).append(
                breach_text(
                    rule,
                    t.level,
                    t.value,
                    t.threshold,
                    self._inverted.get((rule, subject), False),
                )
            )
        return out
