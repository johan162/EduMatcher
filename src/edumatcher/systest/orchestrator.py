"""Process lifecycle, readiness gates, snapshot restore, and quiescence.

Implements the ``Orchestrator``: snapshot restore / store re-initialisation
before any process starts, starting and stopping the EduMatcher process set
in dependency order, per-process Readiness_Gate probes, Collector
attachment, the Quiesce_Protocol, and artefact archiving on run end.

See design.md Components §8 (Orchestrator).
"""
