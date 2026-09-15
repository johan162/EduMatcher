"""Pass 1, composed: entries in, reconstructed steps out (section 6.1).

The order the three stages run in is the whole content of this module, and it
is not arbitrary. Facts are ordered before anything reads them, because a
state model fed in receipt order would see an ack after the fill it preceded.
The state model runs before the link resolver, because the resolver asks it
what was true -- a rejection naming CIRCUIT_BREAKER_ACTIVE is explained by the
halt that is in force at that moment, which is only in the model if the halt
has already been applied.

Pass 2, the renderers, reads what this produces and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

from edumatcher.audit.query import AuditEntry
from edumatcher.audit.replay.anomalies import Anomaly
from edumatcher.audit.replay.facts import Fact, normalise
from edumatcher.audit.replay.links import LinkResolver, Resolution
from edumatcher.audit.replay.ordering import (
    DEFAULT_MAX_FACTS,
    DEFAULT_MAX_SECONDS,
    ordered,
)
from edumatcher.audit.replay.state import StateModel


@dataclass(frozen=True, slots=True)
class Step:
    """One fact, reconstructed.

    ``anomalies`` gathers all three sources -- what normalisation and ordering
    already found on the Fact, what the state model made of it, and what the
    resolver could not reconcile -- so a caller counting findings has one place
    to look rather than three.
    """

    fact: Fact
    resolution: Resolution
    anomalies: tuple[Anomaly, ...]


class Reconstruction:
    """The state model and the link resolver, driven together.

    Held as one object rather than passed around as two because they are not
    independent: the resolver holds a reference to the model, and feeding one
    without the other produces a resolver that silently cannot explain a
    rejection.
    """

    def __init__(self) -> None:
        self.state = StateModel()
        self.links = LinkResolver(self.state)

    def run(self, facts: Iterable[Fact]) -> Iterator[Step]:
        for fact in facts:
            from_state = self.state.apply(fact)
            resolution = self.links.feed(fact)
            yield Step(
                fact=fact,
                resolution=resolution,
                anomalies=fact.anomalies + from_state + resolution.anomalies,
            )


def reconstruct(
    entries: Iterable[AuditEntry],
    *,
    max_facts: int = DEFAULT_MAX_FACTS,
    max_seconds: float = DEFAULT_MAX_SECONDS,
) -> tuple[Reconstruction, Iterator[Step]]:
    """Normalise, order, then reconstruct.

    Returns the :class:`Reconstruction` alongside the iterator so a caller can
    read the final state once the stream is exhausted -- which is what the
    stats report and, in phase 3, the episode assembler both need.
    """
    run = Reconstruction()
    facts = ordered(normalise(entries), max_facts=max_facts, max_seconds=max_seconds)
    return run, run.run(facts)
