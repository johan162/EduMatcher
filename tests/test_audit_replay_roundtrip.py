"""The round-trip property (task AR-4.5) — the most important test here.

**Nothing may vanish silently.** For any window, every event in the audit trail
must end up in exactly one of three states:

1. **narrated** -- it produced a line;
2. **withheld** -- this detail level does not show its kind, and
   :func:`~edumatcher.audit.replay.render_text.suppressed` says so;
3. **an orphan** -- the tool could not attach it, said so, and counted it.

A narrative that quietly drops events is worse than no narrative, because it
will be believed. So this is asserted per event rather than by counting: a
count can balance while two different events swap places.

The events come from ``pm-audit-cli``'s own reader, not from the replay
pipeline, so the two tools are compared rather than one being used to check
itself.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.audit.query import AuditEntry, iter_entries
from edumatcher.audit.replay import templates
from edumatcher.audit.replay.episodes import KIND_ORPHAN, Episode, assemble
from edumatcher.audit.replay.pipeline import reconstruct
from edumatcher.audit.replay.render_text import (
    Options,
    Renderer,
    suppressed,
)
from edumatcher.audit.replay.state import StateModel

FIXTURES = Path("tests/fixtures/replay")
CAPTURED = Path("deployment/docker/data/audit.log")
LOGS = sorted(FIXTURES.glob("*.log"))
LEVELS = (0, 1, 2)


def reconstruct_log(log: Path) -> tuple[list[Episode], StateModel]:
    run, steps = reconstruct(iter_entries([log]))
    return list(assemble(steps, run.state, run.links)), run.state


def audit_events(log: Path) -> list[AuditEntry]:
    """What ``pm-audit-cli`` would return for this window."""
    return list(iter_entries([log]))


def account_for(log: Path, level: int) -> dict[tuple[str | None, int], str]:
    """Where every event of *log* ended up, keyed by its line.

    Returns one of ``narrated``, ``withheld`` or ``orphan`` per event, or
    raises if an event reached none of them -- which is the failure this whole
    module exists to catch.
    """
    episodes, state = reconstruct_log(log)
    renderer = Renderer(episodes, state, Options(level=level))
    verdicts: dict[tuple[str | None, int], str] = {}
    for episode in episodes:
        for event in episode.events:
            where = (event.fact.file, event.fact.line_no)
            assert where not in verdicts, f"{where} landed in two episodes"
            if suppressed(event.fact.kind, max(level, templates.LEVEL_DEFAULT)):
                verdicts[where] = "withheld"
            elif episode.kind == KIND_ORPHAN:
                verdicts[where] = "orphan"
            else:
                rendered = renderer.line(episode, event)
                verdicts[where] = "narrated" if rendered is not None else "withheld"
    return verdicts


class TestNothingVanishes:
    @pytest.mark.parametrize("log", LOGS, ids=lambda p: p.stem[:2])
    @pytest.mark.parametrize("level", LEVELS)
    def test_every_event_is_narrated_withheld_or_an_orphan(
        self, log: Path, level: int
    ) -> None:
        events = audit_events(log)
        verdicts = account_for(log, level)
        for entry in events:
            where = (entry.file, entry.line_no)
            assert where in verdicts, (
                f"{log.name}:{entry.line_no} [{entry.topic}] reached no episode "
                f"at all -- it was neither narrated, withheld nor reported"
            )
            assert verdicts[where] in ("narrated", "withheld", "orphan")

    @pytest.mark.parametrize("log", LOGS, ids=lambda p: p.stem[:2])
    def test_the_accounting_covers_every_line_exactly_once(self, log: Path) -> None:
        events = audit_events(log)
        verdicts = account_for(log, 1)
        assert len(verdicts) == len(events)

    @pytest.mark.skipif(
        not CAPTURED.exists(), reason="no captured session in this checkout"
    )
    @pytest.mark.parametrize("level", LEVELS)
    def test_the_property_holds_over_a_real_captured_session(self, level: int) -> None:
        """AR-4.5 asks for a full session, not only hand-written fixtures.

        This log predates two wire fixes, which is why it is worth running
        against: a trail the tool does not fully understand is exactly where a
        dropped event would hide.
        """
        events = audit_events(CAPTURED)
        assert events, "the captured session is empty"
        verdicts = account_for(CAPTURED, level)
        missing = [
            f"{e.line_no} [{e.topic}]"
            for e in events
            if (e.file, e.line_no) not in verdicts
        ]
        assert not missing, f"vanished: {missing}"


class TestWithheldIsAStatementNotAnAbsence:
    def test_a_withheld_kind_can_be_asked_about(self) -> None:
        """The distinction the property rests on.

        "Not shown at this level" has to be something the tool will say, or a
        reader cannot tell it apart from "not there".
        """
        assert suppressed("book", 1) is True
        assert suppressed("book", 3) is False

    def test_raising_the_level_only_ever_reveals(self) -> None:
        for log in LOGS:
            narrated = [
                sum(
                    1
                    for verdict in account_for(log, level).values()
                    if verdict == "narrated"
                )
                for level in LEVELS
            ]
            assert narrated[1] <= narrated[2], log.name

    def test_everything_withheld_is_withheld_for_a_declared_reason(self) -> None:
        """Not a magic count: every withheld line names a kind the level table
        holds back, and nothing else is ever withheld."""
        log = FIXTURES / "01_simple_limit_partial_fill.log"
        by_line = {
            (entry.file, entry.line_no): entry.topic for entry in audit_events(log)
        }
        verdicts = account_for(log, 1)
        withheld = [by_line[where] for where, v in verdicts.items() if v == "withheld"]
        assert withheld, "fixture 01 carries market data; something should be held"
        for topic in withheld:
            kind, _, _rest = topic.partition(".")
            assert any(
                topic.startswith(held) or held.startswith(kind)
                for held in templates.MIN_LEVEL
            ), topic


class TestAnOrphanIsCounted:
    def test_an_unattachable_event_is_reported_not_swallowed(self) -> None:
        """Section 7.2: the tool's failure to explain something is
        information the reader needs."""
        episodes, _state = reconstruct_log(FIXTURES / "03_archived_no_envelope.log")
        orphans = [e for e in episodes if e.kind == KIND_ORPHAN]
        anomalies = [
            anomaly.code
            for episode in episodes
            for event in episode.events
            for anomaly in event.step.anomalies
        ]
        assert orphans or "ORPHAN_EVENT" in anomalies
