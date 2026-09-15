"""``--tz`` and ``--no-color`` (task AR-6.2).

Both are display switches, and the property that matters for both is the same
one: they change how a line *looks* and never what the tool found. So the
tests here are mostly about what must NOT move — the set of lines, the
machine-readable objects, and a column's alignment.
"""

from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.conftest import REPLAY_FIXTURES

from edumatcher.audit.query import iter_entries
from edumatcher.audit.replay import render_json, render_text, terminal, views
from edumatcher.audit.replay.detect import Detector, detected, observed
from edumatcher.audit.replay.episodes import Episode, assemble
from edumatcher.audit.replay.pipeline import reconstruct
from edumatcher.audit.replay.state import StateModel
from edumatcher.audit.replay.render_text import Options

SIMPLE = REPLAY_FIXTURES / "01_simple_limit_partial_fill.log"
HALTED = REPLAY_FIXTURES / "02_halted_reject_and_kill_switch.log"
LIVE = terminal.Palette(enabled=True)
ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def run(log: Path) -> tuple[list[Episode], StateModel]:
    reconstruction, steps = reconstruct(iter_entries([log]))
    detector = Detector(reconstruction.state)
    episodes = list(
        detected(
            assemble(
                observed(steps, detector),
                reconstruction.state,
                reconstruction.links,
            ),
            detector,
        )
    )
    return episodes, reconstruction.state


def strip(text: str) -> str:
    return ESCAPE.sub("", text)


class TestThePalette:
    def test_disabled_is_the_identity(self) -> None:
        assert terminal.PLAIN.red("x") == "x"
        assert terminal.PLAIN.bold("") == ""

    def test_enabled_wraps_and_resets(self) -> None:
        assert LIVE.red("x") == "\033[31mx\033[0m"

    def test_an_empty_string_is_never_painted(self) -> None:
        """Otherwise a blank cell becomes four invisible characters that
        still take up width."""
        assert LIVE.dim("") == ""


class TestWhenColourIsOn:
    """The user's rule: a terminal gets colour, anything else does not."""

    def test_a_terminal_gets_colour(self) -> None:
        assert terminal.palette_for(False, _Tty(True)).enabled

    def test_a_redirected_stream_does_not(self) -> None:
        assert not terminal.palette_for(False, io.StringIO()).enabled

    def test_the_flag_wins_over_a_terminal(self) -> None:
        assert not terminal.palette_for(True, _Tty(True)).enabled

    def test_no_color_in_the_environment_wins_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        assert not terminal.palette_for(False, _Tty(True)).enabled

    def test_a_stream_that_cannot_say_is_not_a_terminal(self) -> None:
        """A closed or exotic stream answers the question this asks -- it is
        not a reason to fail a report."""
        assert not terminal.palette_for(False, _Tty(ValueError())).enabled


class TestForcingItOn:
    """The tty check is a guess at what is on the other end of the pipe, and
    ``| less -R`` is the case where it guesses wrong: a pager that renders
    colour, behind a pipe that reads as "not a terminal"."""

    def test_a_pipe_can_be_told_it_ends_at_a_terminal(self) -> None:
        assert terminal.palette_for(stream=io.StringIO(), force=True).enabled

    def test_it_beats_no_color_in_the_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A flag the reader typed is a more specific instruction than an
        environment default they may not remember setting."""
        monkeypatch.setenv("NO_COLOR", "1")

        assert terminal.palette_for(stream=_Tty(True), force=True).enabled

    def test_the_default_is_still_to_guess(self) -> None:
        assert not terminal.palette_for(stream=io.StringIO()).enabled


class _Tty:
    def __init__(self, answer: object) -> None:
        self._answer = answer

    def isatty(self) -> bool:
        if isinstance(self._answer, Exception):
            raise self._answer
        return bool(self._answer)


class TestColourChangesNothingButLooks:
    def test_stripping_the_colour_gives_the_plain_output(self) -> None:
        episodes, state = run(SIMPLE)
        plain = render_text.narrate(episodes, state, Options(level=2, explain=True))
        painted = render_text.narrate(
            episodes, state, Options(level=2, explain=True, palette=LIVE)
        )

        assert [strip(line) for line in painted] == plain

    def test_the_episodes_table_still_lines_up(self) -> None:
        """Padding happens before painting, and this is what says so.

        Paint first and `ljust` counts the escape characters as width, so the
        *visible* cell comes out several characters short -- and stripping the
        colour back off would no longer give the plain table. Equality here is
        the whole check.
        """
        episodes, _state = run(SIMPLE)

        assert strip(views.render_episodes(episodes, palette=LIVE)) == (
            views.render_episodes(episodes)
        )

    def test_the_outcome_column_is_the_one_with_a_hue(self) -> None:
        episodes, _state = run(SIMPLE)
        painted = views.render_episodes(episodes, palette=LIVE)

        assert "\033[32mFILLED" in painted

    def test_the_anomalies_report_is_the_same_report(self) -> None:
        episodes, _state = run(HALTED)

        assert strip(
            views.render_anomalies(episodes, severity="info", palette=LIVE)
        ) == views.render_anomalies(episodes, severity="info")

    def test_severity_is_what_gets_a_hue(self) -> None:
        episodes, _state = run(HALTED)
        painted = views.render_anomalies(episodes, severity="info", palette=LIVE)

        assert "\033[33mWARN" in painted

    def test_csv_is_data_and_is_never_painted(self) -> None:
        episodes, _state = run(SIMPLE)

        assert not ESCAPE.search(
            views.render_episodes(episodes, as_csv=True, palette=LIVE)
        )

    def test_no_colour_reaches_the_machine_readable_objects(self) -> None:
        episodes, state = run(SIMPLE)
        objects = list(
            render_json.objects(episodes, state, Options(level=2, palette=LIVE))
        )

        assert objects
        assert not ESCAPE.search(json.dumps(objects))

    def test_nor_the_markdown(self) -> None:
        episodes, state = run(SIMPLE)
        lines = render_json.markdown(episodes, state, Options(palette=LIVE))

        assert lines
        assert not ESCAPE.search("\n".join(lines))


class TestTheZone:
    STOCKHOLM = terminal.parse_tz("Europe/Stockholm")

    def test_an_unknown_zone_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown timezone"):
            terminal.parse_tz("Mars/Olympus")

    def test_the_clock_moves(self) -> None:
        when = datetime(2026, 9, 8, 9, 31, 2, 122000, tzinfo=timezone.utc)

        assert terminal.clock(when) == "09:31:02.122"
        assert terminal.clock(when, self.STOCKHOLM) == "11:31:02.122"

    def test_a_recorded_timestamp_moves_with_its_offset(self) -> None:
        moved = terminal.moment("2026-09-08T09:31:02.122+00:00", self.STOCKHOLM)

        assert moved.startswith("2026-09-08T11:31:02.122")
        assert moved.endswith("+02:00")

    def test_a_timestamp_that_will_not_parse_is_left_alone(self) -> None:
        """A display helper that refused to print an odd timestamp would lose
        the one thing the reader could have grepped for."""
        assert terminal.moment("not-a-time", self.STOCKHOLM) == "not-a-time"

    def test_the_narration_follows_it(self) -> None:
        episodes, state = run(SIMPLE)
        utc = render_text.narrate(episodes, state, Options())
        local = render_text.narrate(episodes, state, Options(tz=self.STOCKHOLM))

        assert utc[0].startswith("09:31:02.110")
        assert local[0].startswith("11:31:02.110")

    def test_it_moves_the_clock_and_nothing_else(self) -> None:
        episodes, state = run(SIMPLE)
        utc = render_text.narrate(episodes, state, Options(level=2))
        local = render_text.narrate(
            episodes, state, Options(level=2, tz=self.STOCKHOLM)
        )

        assert len(utc) == len(local)
        assert [line.split("  ", 1)[-1] for line in utc] == [
            line.split("  ", 1)[-1] for line in local
        ]

    def test_the_views_follow_it(self) -> None:
        episodes, _state = run(SIMPLE)

        assert "11:31:02" in views.render_episodes(episodes, tz=self.STOCKHOLM)
        assert "11:31:02" in views.render_digest(episodes, tz=self.STOCKHOLM)

    def test_the_findings_follow_it(self) -> None:
        episodes, _state = run(HALTED)
        utc = views.render_anomalies(episodes, severity="info")
        local = views.render_anomalies(episodes, severity="info", tz=self.STOCKHOLM)

        assert "09:44:10.019" in utc
        assert "11:44:10.019" in local

    def test_the_object_model_keeps_the_recorded_time(self) -> None:
        """A display switch that moved these would make the two formats
        disagree about when something happened, which is the one thing the
        machine-readable renderer exists to prevent."""
        episodes, state = run(SIMPLE)
        objects = list(render_json.objects(episodes, state, Options(tz=self.STOCKHOLM)))
        beats = [o for o in objects if o["type"] == "beat"]

        assert beats
        assert all(b["receipt_ts"].endswith("+00:00") for b in beats)
