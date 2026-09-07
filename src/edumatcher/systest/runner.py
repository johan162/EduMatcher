"""Scenario execution: the ``Runner``.

Executes a parsed :class:`~edumatcher.systest.scenario.Scenario`'s Steps in
order against a concrete :class:`Binding` of Actors to transports, recording
Label→real-id mappings and Barrier ordering markers as raw evidence for the
Canonicaliser (``systest/canonical.py``) to consume.

See design.md Components §3 (Runner) and Requirements 3.4, 3.6, 3.8, 3.9.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from edumatcher.systest.drivers.base import (
    Ack,
    Driver,
    Event,
    NewOrderRequest,
    OrderAmendment,
)
from edumatcher.systest.scenario import Barrier, Scenario, Step

__all__ = [
    "Binding",
    "LabelMap",
    "Orchestrator",
    "CollectorSet",
    "BarrierMarker",
    "RunResult",
    "Runner",
]

#: An assignment of each Actor in a Scenario to a Transport (e.g.
#: ``{"trader1": "alf", "trader2": "rest"}``), per requirements.md's
#: Glossary entry for "Binding".
Binding = dict[str, str]

#: Label -> real order/trade id, recorded by the Runner per Requirement 3.6
#: and threaded through to ``canonical.py::canonicalise(raw_artefact,
#: label_map, actor_map)`` (design.md Components §11) unmodified, so this
#: stays a plain ``dict[str, str]`` rather than a wrapper type.
LabelMap = dict[str, str]


class Orchestrator(Protocol):
    """The subset of the real Orchestrator's interface the Runner calls.

    ``systest/orchestrator.py`` (task 7) is currently only a module
    docstring with no concrete ``Orchestrator`` class yet, so this is a
    local structural :class:`typing.Protocol` expressing only what
    ``Runner.run()`` depends on -- a ``barrier: quiesce`` Step per
    Requirement 3.8 -- pending task 7's concrete implementation. See
    design.md Components §8 for the full Orchestrator interface, of which
    this is a slice.
    """

    def quiesce(self, *, idle_ms: int = 250) -> None:
        """Block until system-wide idle per the Quiesce_Protocol."""
        ...


class CollectorSet(Protocol):
    """The subset of the real CollectorSet's interface the Runner needs.

    ``systest/collectors/__init__.py`` (task 9) is currently only a module
    docstring with no concrete ``CollectorSet`` class yet. Per design.md
    Components §3 (Runner) and Requirement 3's text, the Runner's own
    contract is Scenario execution, Label recording, and Barrier semantics
    -- issuing a Collector snapshot request at a Barrier is the
    Collector/Orchestrator's own responsibility (design.md Components §9,
    the ``BookCollector`` row), not the Runner's. This Protocol is
    therefore intentionally empty: the Runner holds a reference to the
    ``collectors`` argument (matching the design.md §3 constructor
    signature) but does not yet call anything on it. Extend this once a
    concrete requirement for the Runner to talk to Collectors is
    identified.
    """


@dataclass(frozen=True, slots=True)
class BarrierMarker:
    """One Barrier occurrence recorded in the Runner's ordering log.

    ``kind`` is ``"quiesce"`` or ``"sync"`` (mirrors
    :class:`~edumatcher.systest.scenario.Barrier.barrier`); ``step_index``
    is the Barrier's position in ``scenario.steps``; ``actors`` is the
    ``sync`` Barrier's named Actor list (empty for ``quiesce``).

    Per Requirement 3.9, the Runner only ever appends a marker here on a
    Barrier Step -- never between two unbarriered Steps -- so the *absence*
    of an ordering assertion between unbarriered Steps' artefacts holds by
    construction of this log, rather than by any extra check the Runner
    must perform.
    """

    kind: str
    step_index: int
    actors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RunResult:
    """Raw evidence from one Scenario run, for the Canonicaliser to consume.

    ``label_map`` is the Label→real-id mapping recorded per Requirement
    3.6; ``events`` is every Driver's drained unsolicited events, keyed by
    Actor name; ``barrier_markers`` is the total-order log described by
    :class:`BarrierMarker`, satisfying Requirement 3.8's ordering guarantee
    and Requirement 3.9's non-ordering guarantee together.
    """

    label_map: LabelMap
    events: dict[str, list[Event]]
    barrier_markers: list[BarrierMarker]


class Runner:
    """Executes a Scenario's Steps in order, honouring its Barriers.

    See design.md Components §3 for the full contract. Constructed with a
    parsed :class:`~edumatcher.systest.scenario.Scenario`, its
    :class:`Binding`, one bound :class:`Driver` per Actor, an
    :class:`Orchestrator`, and a :class:`CollectorSet`.
    """

    def __init__(
        self,
        scenario: Scenario,
        binding: Binding,
        drivers: dict[str, Driver],
        orchestrator: Orchestrator,
        collectors: CollectorSet,
    ) -> None:
        self._scenario = scenario
        self._binding = binding
        self._drivers = drivers
        self._orchestrator = orchestrator
        self._collectors = collectors

    def run(self) -> RunResult:
        """Execute every Step in order, honouring Barriers.

        Returns raw evidence (per-actor label→id map, driver events,
        Barrier ordering log) for the Canonicaliser to consume.
        """
        label_map: LabelMap = {}
        events: dict[str, list[Event]] = {
            actor: [] for actor in self._scenario.actors
        }
        barrier_markers: list[BarrierMarker] = []

        for index, step in enumerate(self._scenario.steps):
            if isinstance(step, Barrier):
                barrier_markers.append(self._run_barrier(step, index, events))
                continue
            self._run_step(step, label_map, events)

        return RunResult(
            label_map=label_map,
            events=events,
            barrier_markers=barrier_markers,
        )

    def _run_step(
        self,
        step: Step,
        label_map: LabelMap,
        events: dict[str, list[Event]],
    ) -> None:
        """Dispatch one non-Barrier Step to its Actor's bound Driver.

        Requirement 3.4: ``actor``/``action`` are mandatory on ``step``
        (enforced by the Scenario schema at load time, task 5); ``label``,
        ``order``, and ``expect`` are each optional and handled as such
        here.
        """
        driver = self._drivers[step.actor]
        ack: Ack | None = None

        if step.action == "connect":
            driver.connect()
        elif step.action == "disconnect":
            driver.disconnect()
        elif step.action == "new_order":
            ack = driver.new_order(self._build_new_order_request(step))
        elif step.action == "cancel_order":
            ack = driver.cancel_order(self._resolve_target_id(step, label_map))
        elif step.action == "amend_order":
            ack = driver.amend_order(
                self._resolve_target_id(step, label_map),
                self._build_order_amendment(step),
            )

        # Requirement 3.6: a labelled new_order/cancel_order/amend_order
        # Step records label -> resulting real id for the run's duration.
        if step.label is not None and ack is not None and ack.order_id is not None:
            label_map[step.label] = ack.order_id

        events[step.actor].extend(driver.events())

    def _build_new_order_request(self, step: Step) -> NewOrderRequest:
        """Build a :class:`NewOrderRequest` from a ``new_order`` Step's
        ``order:`` payload.

        ``OrderPayload.price`` is a verbatim decimal string (or ``None``
        for MARKET); ``NewOrderRequest.price`` is ``float | None``. Only a
        simple ``float()`` cast is applied here -- tick-precise conversion
        is the Canonicaliser's Rule R6 job (design.md Components §11), not
        this layer's.

        ``client_tag`` correlation-tag minting (the
        ``{ACTOR}-{SCENARIO}-{SEQ}`` scheme, design.md §A.1.8) is a Driver
        concern per Requirement 5.3, not the Runner's -- so this leaves
        ``client_tag`` unset unless the Step itself declares a ``label``,
        in which case the label doubles as a simple, inspectable
        correlation tag.
        """
        order = step.order
        assert order is not None  # Scenario schema requires order for new_order
        return NewOrderRequest(
            symbol=order.symbol,
            side=order.side,
            order_type=order.type,
            quantity=order.qty,
            tif=order.tif,
            price=float(order.price) if order.price is not None else None,
            client_tag=step.label,
        )

    def _build_order_amendment(self, step: Step) -> OrderAmendment:
        """Build an :class:`OrderAmendment` from an ``amend_order`` Step's
        optional ``order:`` payload (design.md allows ``order`` to be
        unset for cancel/amend Steps).
        """
        order = step.order
        if order is None:
            return OrderAmendment()
        return OrderAmendment(
            price=float(order.price) if order.price is not None else None,
            quantity=order.qty,
        )

    def _resolve_target_id(self, step: Step, label_map: LabelMap) -> str:
        """Resolve the real order id a ``cancel_order``/``amend_order`` Step
        acts on.

        The current Scenario schema (``scenario.py``) exposes no field
        distinct from ``step.label`` identifying which prior Label a
        cancel/amend Step targets -- ``step.label`` is otherwise defined
        (Requirement 3.6) as the Label *assigned by* a Step that mints or
        acts on an id. Absent a dedicated "target label" field, this
        assumes a cancel/amend Step reuses the same Label as the
        ``new_order`` Step it targets, and resolves it via the Runner's
        own ``LabelMap``. If the Label was not previously recorded (e.g. a
        Scenario acting on an id from outside this run), ``step.label`` is
        treated as already a real id. This is a documented assumption that
        may need a dedicated Scenario schema field in a later task.
        """
        if step.label is not None and step.label in label_map:
            return label_map[step.label]
        assert step.label is not None, (
            "cancel_order/amend_order Step must carry a label identifying "
            "its target order, per this Runner's documented assumption"
        )
        return step.label

    def _run_barrier(
        self,
        barrier: Barrier,
        step_index: int,
        events: dict[str, list[Event]],
    ) -> BarrierMarker:
        """Execute one Barrier Step and return its ordering-log marker.

        Requirement 3.8: ``quiesce`` waits for system-wide idle and
        establishes a total order between the Steps immediately before and
        after it; ``sync`` waits only for the named Actors' acknowledgements.

        Phase 1 Drivers are synchronous -- each verb (``new_order`` etc.)
        already returns its ``Ack`` before returning control to the Runner
        -- so "waiting on acknowledgement queues" for a ``sync`` Barrier
        reduces, in this single-threaded Runner, to draining ``events()``
        for exactly the named Actors (never every Actor, and never calling
        ``quiesce()``, which is reserved for the ``quiesce`` Barrier alone).
        """
        if barrier.barrier == "quiesce":
            self._orchestrator.quiesce()
            return BarrierMarker(kind="quiesce", step_index=step_index)

        for actor in barrier.actors:
            events[actor].extend(self._drivers[actor].events())
        return BarrierMarker(
            kind="sync", step_index=step_index, actors=tuple(barrier.actors)
        )
