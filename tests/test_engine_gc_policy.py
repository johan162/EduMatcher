"""The engine's garbage-collection policy: freeze after the open, collect idle."""

from __future__ import annotations

import gc
from collections.abc import Iterator

import pytest

from edumatcher.engine import gc_policy
from edumatcher.engine.gc_policy import GcPolicy


def _record(calls: list[int], gen: int) -> int:
    calls.append(gen)
    return 0


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def policy() -> Iterator[tuple[GcPolicy, Clock]]:
    clock = Clock()
    p = GcPolicy(clock)
    p.start()
    yield p, clock
    p.stop()


def test_start_raises_thresholds_and_stop_restores_them() -> None:
    before = gc.get_threshold()
    p = GcPolicy()
    p.start()
    assert gc.get_threshold() == gc_policy.SAFETY_THRESHOLDS
    p.stop()
    assert gc.get_threshold() == before


def test_freeze_waits_for_the_delay_and_an_idle_tick(
    policy: tuple[GcPolicy, Clock],
) -> None:
    p, clock = policy
    base = gc.get_freeze_count()
    p.arm_freeze()
    clock.now += gc_policy.FREEZE_DELAY_SEC - 1
    p.tick(idle=True)
    assert gc.get_freeze_count() == base
    clock.now += 2
    p.tick(idle=False)  # due, but busy and not overdue
    assert gc.get_freeze_count() == base
    assert p.freeze_at
    p.tick(idle=True)
    assert gc.get_freeze_count() > base
    assert p.freeze_at == 0.0


def test_an_overdue_freeze_does_not_wait_for_idle(
    policy: tuple[GcPolicy, Clock],
) -> None:
    p, clock = policy
    p.arm_freeze()
    clock.now += gc_policy.FREEZE_DELAY_SEC + gc_policy.FREEZE_FORCE_AFTER_SEC
    p.tick(idle=False)
    assert p.freeze_at == 0.0


def test_busy_ticks_never_collect(
    policy: tuple[GcPolicy, Clock], monkeypatch: pytest.MonkeyPatch
) -> None:
    p, clock = policy
    calls: list[int] = []
    monkeypatch.setattr(gc, "collect", lambda gen=2: _record(calls, gen))
    clock.now += 10_000
    p.tick(idle=False)
    assert calls == []


def test_idle_ticks_collect_young_then_full_now_and_then(
    policy: tuple[GcPolicy, Clock], monkeypatch: pytest.MonkeyPatch
) -> None:
    p, clock = policy
    calls: list[int] = []
    monkeypatch.setattr(gc, "collect", lambda gen=2: _record(calls, gen))
    p.tick(idle=True)
    clock.now += gc_policy.FULL_COLLECT_EVERY_SEC
    p.tick(idle=True)
    p.tick(idle=True)
    assert calls == [1, 2, 1]
