"""Evidence Collectors: one component per dissemination/evidence sink.

Each Collector captures evidence from one sink (execution reports, audit
journal, stats database, clearing ledger, CALF/RALF/drop-copy spy output,
engine book snapshot, operational log, index, or process exit codes) so the
Canonicaliser and Assertion layers can reason over a uniform capture of
system behaviour.

See design.md Components §9 (Collectors).

Task 7.2 introduced :class:`CollectorSet` -- the Orchestrator's Collector-
attachment extension point (design.md Components §8, Requirement 8.6) -- as
a minimal placeholder so ``Orchestrator.start_all()`` can call
``CollectorSet.attach_all()`` as its last step, strictly before the Runner
is handed control, without prematurely implementing the concrete per-sink
Collectors (E1-E11) that task 9 adds.

Task 7.3 extends the :class:`Collector` Protocol with the two further hooks
the Quiesce_Protocol and artefact archiving need from *any* Collector,
before task 9 supplies concrete ones:

* :meth:`Collector.is_idle` -- "has this dissemination sink been silent for
  ``idle_ms``", the second of ``quiesce()``'s three stability conditions
  (Requirement 8.7).
* :meth:`Collector.capture_file` -- the sink's own self-managed capture
  file (a spy tool's redirected stdout, for the E4-E7 sinks task 9.2
  describes), if it has one, so ``Orchestrator.archive_artifacts()`` can
  copy it under ``artifacts/<scenario>/<transport>/`` (Requirement 8.8)
  without the Orchestrator needing to know each sink's capture-file
  convention itself.

Both remain structural additions to the same minimal Protocol style task
7.2 established -- no concrete Collector exists yet, so
:meth:`CollectorSet.all_idle` and :meth:`CollectorSet.capture_files` are
correct today by construction (``all()`` over an empty sequence is
``True``; an empty list of capture files) rather than by a special case.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Protocol

__all__ = ["Collector", "CollectorSet"]


class Collector(Protocol):
    """The Orchestrator's only dependency on what a Collector is.

    Task 9 implements one concrete Collector per evidence sink E1-E11
    (``collectors/execution.py``, ``collectors/audit.py``,
    ``collectors/stats.py``, ...), each exposing:

    * :meth:`attach` -- subscribe to its sink (the engine bus, a spy tool's
      stdout, a driver's event queue, ...) so that no event between
      process start and the first Scenario Step is missed (Requirement
      8.6).
    * :meth:`is_idle` -- report whether this sink has observed no new
      event for at least ``idle_ms`` milliseconds, for
      ``Orchestrator.quiesce()``'s "every dissemination Collector has been
      silent for ``idle_ms``" condition (Requirement 8.7). A Collector with
      nothing to disseminate (e.g. a store-only sink with no live stream)
      returns ``True`` unconditionally -- it is vacuously always idle.
    * :meth:`capture_file` -- this sink's own self-managed capture file
      (e.g. a spy tool's redirected stdout), or ``None`` if it keeps no
      such file, so ``Orchestrator.archive_artifacts()`` can copy it
      without hard-coding each sink's capture-file convention.

    Kept a structural :class:`typing.Protocol` -- as narrow as the
    Orchestrator's own dependency on a Collector, never the sink-specific
    typed accessors a concrete Collector (task 9) additionally exposes for
    the Canonicaliser/Assertion layers to consume.
    """

    def attach(self) -> None: ...

    def is_idle(self, idle_ms: int) -> bool: ...

    def capture_file(self) -> Path | None: ...


class CollectorSet:
    """An ordered collection of Collectors, attached together.

    Task 7.2 introduces this as the Orchestrator's Collector-attachment
    extension point: ``Orchestrator.start_all()`` calls :meth:`attach_all`
    as its literal last step, after every process has passed its
    Readiness_Gate probe and strictly before the Runner is handed control
    (design.md Components §8, Requirement 8.6).

    Today no concrete Collector exists yet (task 9), so a ``CollectorSet``
    constructed with no ``collectors`` argument is empty and
    :meth:`attach_all` is a safe no-op -- this keeps ``start_all()``'s
    contract ("Collectors attach last, before any Actor connects") correct
    without prematurely implementing the real per-sink Collectors.

    Task 9 extends this by constructing a ``CollectorSet`` with the eleven
    concrete Collectors (or calling :meth:`add` for each as they are built),
    so ``attach_all()`` attaches every evidence sink in one call with no
    Orchestrator change required.
    """

    def __init__(self, collectors: Iterable[Collector] | None = None) -> None:
        self._collectors: list[Collector] = list(collectors) if collectors else []

    def add(self, collector: Collector) -> None:
        """Register one more Collector to be attached by :meth:`attach_all`."""
        self._collectors.append(collector)

    def attach_all(self) -> None:
        """Attach every registered Collector, in the order they were added.

        Requirement 8.6: the Orchestrator calls this as the last step of
        ``start_all()``, so every Collector is subscribed before any Actor
        connects and before the Runner is handed control.
        """
        for collector in self._collectors:
            collector.attach()

    def all_idle(self, idle_ms: int) -> bool:
        """Whether every registered Collector has been silent for ``idle_ms``.

        Requirement 8.7: one of ``Orchestrator.quiesce()``'s three
        stability conditions. Vacuously ``True`` when no Collector is
        registered yet (task 9 not yet run) -- correct by construction,
        not a special case: an empty set of dissemination sinks is
        trivially all-idle.
        """
        return all(collector.is_idle(idle_ms) for collector in self._collectors)

    def capture_files(self) -> list[Path]:
        """Every registered Collector's own capture file, if it has one.

        Requirement 8.8: ``Orchestrator.archive_artifacts()`` copies each
        of these under ``artifacts/<scenario>/<transport>/`` on run end.
        Collectors with no self-managed capture file (``capture_file()``
        returns ``None``) are simply omitted.
        """
        files: list[Path] = []
        for collector in self._collectors:
            capture_file = collector.capture_file()
            if capture_file is not None:
                files.append(capture_file)
        return files

    def __len__(self) -> int:
        return len(self._collectors)
