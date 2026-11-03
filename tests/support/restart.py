from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

Component = TypeVar("Component")
Observable = TypeVar("Observable")
Durable = TypeVar("Durable")


def restart_equivalence(
    current: Component,
    *,
    restart: Callable[[], Component],
    snapshot: Callable[[Component], Observable],
    durable: Callable[[], Durable],
) -> None:
    """Compare durable bytes/state and externally visible values across a restart.

    The caller flushes pending writes before calling and owns cleanup of both
    component instances. ``restart`` must construct a fresh instance from disk.
    """
    before_durable = durable()
    before_observable = snapshot(current)
    restored = restart()
    after_durable = durable()
    assert after_durable == before_durable, "durable state changed across restart"
    assert snapshot(restored) == before_observable, "observables changed across restart"
