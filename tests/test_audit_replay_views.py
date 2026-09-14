"""``stream`` and ``story`` (tasks AR-4.3, AR-4.4).

The plan names two acceptance criteria and both have a test here: ``story
--order`` on a partially filled order shows both sides of every trade, and
``story --command`` on a kill switch reaches the orders it cancelled.

The property that matters most is quieter. An episode read back out of the
index must narrate **identically** to the same episode reconstructed from the
log -- otherwise the index is a second, subtly different tool wearing the
same name, and which one a reader got would depend on whether a file happened
to exist.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.audit.query import iter_entries
from edumatcher.audit.replay import reader
from edumatcher.audit.replay.cli import main
from edumatcher.audit.replay.episodes import Episode, assemble
from edumatcher.audit.replay.index import build, open_readonly
from edumatcher.audit.replay.pipeline import reconstruct
from edumatcher.audit.replay.render_text import Options, narrate
from edumatcher.audit.replay.state import StateModel

FIXTURES = Path("tests/fixtures/replay")
SIMPLE = FIXTURES / "01_simple_limit_partial_fill.log"
KILL_SWITCH = FIXTURES / "02_halted_reject_and_kill_switch.log"
ARCHIVE = FIXTURES / "03_archived_no_envelope.log"
STRUCTURES = FIXTURES / "04_quote_oco_combo.log"
DAY = FIXTURES / "05_session_and_index.log"
ALL = (SIMPLE, KILL_SWITCH, ARCHIVE, STRUCTURES, DAY)

ORDER = "4f2c9a1e6d8b47c3a5f09e21b7d4c6a8"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


def cli(log: Path, tmp_path: Path, *argv: str) -> list[str]:
    return [
        "--log-file",
        str(log),
        "--db",
        str(tmp_path / "replay.db"),
        *argv,
    ]


def run(log: Path, tmp_path: Path, *argv: str) -> int:
    return main(cli(log, tmp_path, *argv))


# ---------------------------------------------------------------------------
# The index must not be a second tool
# ---------------------------------------------------------------------------


class TestTheIndexNarratesIdentically:
    @pytest.mark.parametrize("log", ALL, ids=lambda p: p.stem[:2])
    @pytest.mark.parametrize("level", [0, 1, 2])
    def test_from_the_index_equals_from_the_log(
        self, log: Path, level: int, tmp_path: Path
    ) -> None:
        live, state = _reconstruct(log)
        from_log = narrate(live, state, Options(level=level))

        db = tmp_path / "replay.db"
        stored_episodes, stored_state = _via_index(log, db)
        from_index = narrate(stored_episodes, stored_state, Options(level=level))

        assert from_index == from_log

    def test_descriptive_actors_survive_the_round_trip(self, tmp_path: Path) -> None:
        """The one thing the narrator reads from the state model.

        Without the ``actors`` table hydrated, ``--actor-style=descriptive``
        would silently do nothing whenever the story came from the index --
        the worst kind of broken flag, because it looks like the data simply
        had no description.
        """
        episodes, state = _via_index(SIMPLE, tmp_path / "replay.db")
        rendered = narrate(episodes, state, Options(level=1, descriptive_actors=True))
        assert any("Nordic Equities desk" in line for line in rendered)


def _reconstruct(log: Path) -> tuple[list[Episode], StateModel]:
    run_, steps = reconstruct(iter_entries([log]))
    return list(assemble(steps, run_.state, run_.links)), run_.state


def _via_index(log: Path, db: Path) -> tuple[list[Episode], StateModel]:
    run_, steps = reconstruct(iter_entries([log]))
    build(db, assemble(steps, run_.state, run_.links), run_.state, [log])
    conn = open_readonly(db)
    return reader.episodes_in_window(conn), reader.actors(conn)


# ---------------------------------------------------------------------------
# stream
# ---------------------------------------------------------------------------


class TestStream:
    def test_narrates_the_window(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run(SIMPLE, tmp_path, "stream") == 0
        assert "TRADER01 submitted buy limit 200 AAPL" in capsys.readouterr().out

    def test_a_global_option_works_on_either_side_of_the_subcommand(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Section 9.2's own examples put them after; argparse wants before."""
        run(SIMPLE, tmp_path, "stream", "--symbol", "AAPL")
        after = capsys.readouterr().out
        run(SIMPLE, tmp_path, "--symbol", "AAPL", "stream")
        before = capsys.readouterr().out
        assert after == before
        assert after

    def test_quiet_is_outcomes_only(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run(SIMPLE, tmp_path, "stream", "-q")
        out = capsys.readouterr().out
        assert "still working at the end of the window" in out
        assert "submitted" not in out

    def test_a_filter_narrows_rather_than_empties(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run(KILL_SWITCH, tmp_path, "stream", "--gateway", "TRADER07")
        narrowed = capsys.readouterr().out.splitlines()
        run(KILL_SWITCH, tmp_path, "stream")
        everything = capsys.readouterr().out.splitlines()
        assert 0 < len(narrowed) < len(everything)

    def test_no_index_answers_the_same_question(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run(SIMPLE, tmp_path, "stream", "--symbol", "AAPL")
        indexed = capsys.readouterr().out
        run(SIMPLE, tmp_path, "stream", "--symbol", "AAPL", "--no-index")
        streamed = capsys.readouterr().out
        assert indexed == streamed

    def test_an_empty_window_says_so_rather_than_printing_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = run(SIMPLE, tmp_path, "stream", "--symbol", "NOSUCH")
        assert code == 1
        assert "nothing to narrate" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# story
# ---------------------------------------------------------------------------


class TestStory:
    def test_an_order_shows_both_sides_of_every_trade(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """AR-4.4's first acceptance criterion."""
        assert run(SIMPLE, tmp_path, "story", "--order", "4f2c9a") == 0
        out = capsys.readouterr().out
        assert "TRADER01's buy" in out and "TRADER02's sell" in out
        assert out.count("@ 74.80") >= 3  # the print and both fills

    def test_a_kill_switch_reaches_the_orders_it_cancelled(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """AR-4.4's second, and the reason ``--command`` needed its own dest.

        ``--command`` would otherwise write to ``args.command``, which is
        where argparse records the chosen subcommand -- so this exact
        invocation silently did nothing at all.
        """
        assert run(KILL_SWITCH, tmp_path, "story", "--command", "8812") == 0
        out = capsys.readouterr().out
        assert "pulled the kill switch" in out
        assert out.count("was cancelled — a kill switch") == 2

    def test_a_prefix_is_enough(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run(SIMPLE, tmp_path, "story", "--order", "4f2c9a")
        short = capsys.readouterr().out
        run(SIMPLE, tmp_path, "story", "--order", ORDER)
        full = capsys.readouterr().out
        assert short == full

    def test_a_chain_needs_no_depth(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        episodes, _state = _via_index(SIMPLE, tmp_path / "replay.db")
        # The order's chain, not merely the first one: every enveloped fact
        # has a correlation_id, and a gateway connecting is a chain of one.
        chain = next(
            e.correlation_id for e in episodes if e.kind == "order" and e.correlation_id
        )
        assert run(SIMPLE, tmp_path, "story", "--chain", chain) == 0
        out = capsys.readouterr().out
        assert "submitted buy limit" in out
        assert "AAPL traded" in out

    def test_depth_bounds_the_walk(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        run(SIMPLE, tmp_path, "story", "--order", "4f2c9a", "--depth", "0")
        alone = capsys.readouterr().out.splitlines()
        run(SIMPLE, tmp_path, "story", "--order", "4f2c9a", "--depth", "2")
        reached = capsys.readouterr().out.splitlines()
        assert len(alone) < len(reached)

    def test_strict_causality_refuses_to_traverse_a_guess(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Fixture 03 predates the envelope, so nothing in it is RECORDED."""
        run(ARCHIVE, tmp_path, "story", "--order", "cccc00")
        inferred = capsys.readouterr().out
        run(ARCHIVE, tmp_path, "story", "--order", "cccc00", "--strict-causality")
        recorded = capsys.readouterr().out
        assert "MSFT traded" in inferred
        assert "MSFT traded" not in recorded

    def test_a_miss_says_where_to_look_next(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = run(SIMPLE, tmp_path, "story", "--order", "deadbeef")
        assert code == 1
        assert "no order matching" in capsys.readouterr().err

    def test_a_miss_inside_a_window_suggests_widening_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = run(
            SIMPLE, tmp_path, "--date", "2026-09-08", "story", "--order", "deadbeef"
        )
        assert code == 1
        assert "--from/--to" in capsys.readouterr().err

    def test_selectors_are_mutually_exclusive(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            run(SIMPLE, tmp_path, "story", "--order", "a", "--trade", "b")

    def test_one_selector_is_required(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            run(SIMPLE, tmp_path, "story")

    def test_story_needs_the_index_and_says_so(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = run(SIMPLE, tmp_path, "story", "--order", "4f2c9a", "--no-index")
        assert code == 2
        assert "drop --no-index" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "flag,value,expected",
        [
            ("--quote", "Q-MM01-AAPL-7", "quoted AAPL"),
            ("--oco", "OCO-TRADER03-11", "one-cancels-other"),
            ("--combo", "CMB-TRADER03-4", "all-or-none combo"),
        ],
    )
    def test_the_structure_selectors_find_their_episode(
        self,
        flag: str,
        value: str,
        expected: str,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert run(STRUCTURES, tmp_path, "story", flag, value) == 0
        assert expected in capsys.readouterr().out

    def test_the_client_tag_selector_finds_by_the_trader_s_own_string(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert run(STRUCTURES, tmp_path, "story", "--client-tag", "bracket-1") == 0
        assert "one-cancels-other" in capsys.readouterr().out

    def test_the_msg_selector_finds_one_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        episodes, _state = _via_index(SIMPLE, tmp_path / "replay.db")
        msg = next(
            event.fact.msg_id
            for episode in episodes
            for event in episode.events
            if event.fact.msg_id
        )
        assert run(SIMPLE, tmp_path, "story", "--msg", msg) == 0
        assert capsys.readouterr().out
