"""``digest``, ``episodes`` and ``anomalies`` (task AR-5.2).

Tests ``replay/views.py``. The older ``test_audit_replay_views.py`` covers
``stream`` and ``story``, which the design calls the narrative commands -- the
overlap in the two file names is unfortunate and predates this module.

The property that matters most is the one that mattered for ``stream``: a
report built from the index must be **character-identical** to the same report
built straight off the log. Otherwise the index is a second, subtly different
tool wearing the same name, and which one a reader got would depend on whether
a file happened to exist.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import REPLAY_FIXTURES

from edumatcher.audit.query import iter_entries
from edumatcher.audit.replay import views
from edumatcher.audit.replay.anomalies import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARN,
    Anomaly,
)
from edumatcher.audit.replay.cli import _SELECTOR_KINDS, _STORY_SELECTORS, main
from edumatcher.audit.replay.detect import Detector, detected, observed
from edumatcher.audit.replay.episodes import Episode, assemble
from edumatcher.audit.replay.pipeline import reconstruct

SIMPLE = REPLAY_FIXTURES / "01_simple_limit_partial_fill.log"
STRUCTURES = REPLAY_FIXTURES / "04_quote_oco_combo.log"


def load(path: Path) -> list[Episode]:
    run, steps = reconstruct(iter_entries([path]))
    detector = Detector(run.state)
    return list(
        detected(assemble(observed(steps, detector), run.state, run.links), detector)
    )


def run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> str:
    assert main(argv) == 0
    return capsys.readouterr().out


# ---------------------------------------------------------------------------
# The shared helper
# ---------------------------------------------------------------------------


class TestFindings:
    def test_it_returns_both_kinds_of_finding(self) -> None:
        """Per-fact findings live on a Step and episode-level ones on the
        Episode. A view that reached for one place would silently report half
        of what it found."""
        episode = next(e for e in load(STRUCTURES) if e.anchor_key.startswith("b17f"))

        codes = {anomaly.code for anomaly in views.findings(episode)}

        assert "FILL_BEFORE_ACK" in codes  # on a Step
        assert "ACK_MISSING" in codes  # on the Episode

    def test_a_clean_episode_has_none(self) -> None:
        assert all(views.findings(e) == [] for e in load(SIMPLE))


# ---------------------------------------------------------------------------
# anomalies (section 9.6)
# ---------------------------------------------------------------------------


def _episode_with(*anomalies: Anomaly) -> Episode:
    """One real episode, with its findings replaced by the ones given."""
    episode = load(SIMPLE)[0]
    episode.anomalies = anomalies
    return episode


def _finding(code: str, severity: str, at: str) -> Anomaly:
    return Anomaly(
        code=code, severity=severity, detail=f"{code} happened", receipt_ts=at
    )


class TestAnomalies:
    def test_severity_is_a_floor_not_a_filter(self) -> None:
        episode = _episode_with(
            _finding("A_ERROR", SEVERITY_ERROR, "2026-09-08T09:31:03.000+00:00"),
            _finding("A_WARN", SEVERITY_WARN, "2026-09-08T09:31:04.000+00:00"),
            _finding("A_INFO", SEVERITY_INFO, "2026-09-08T09:31:05.000+00:00"),
        )

        out = views.render_anomalies([episode], severity=SEVERITY_WARN)

        assert "A_ERROR" in out
        assert "A_WARN" in out
        assert "A_INFO" not in out

    def test_the_worst_comes_first_however_late_it_happened(self) -> None:
        episode = _episode_with(
            _finding("A_INFO", SEVERITY_INFO, "2026-09-08T09:31:01.000+00:00"),
            _finding("A_ERROR", SEVERITY_ERROR, "2026-09-08T09:31:09.000+00:00"),
        )

        out = views.render_anomalies([episode])

        assert out.index("A_ERROR") < out.index("A_INFO")

    def test_ties_on_severity_are_broken_by_time(self) -> None:
        episode = _episode_with(
            _finding("A_LATE", SEVERITY_WARN, "2026-09-08T09:31:09.000+00:00"),
            _finding("A_EARLY", SEVERITY_WARN, "2026-09-08T09:31:01.000+00:00"),
        )

        out = views.render_anomalies([episode])

        assert out.index("A_EARLY") < out.index("A_LATE")

    def test_every_finding_carries_the_command_to_run_next(self) -> None:
        out = views.render_anomalies(load(STRUCTURES), severity=SEVERITY_WARN)

        assert "-> pm-audit-replay story --order " in out

    def test_a_clean_log_says_so_rather_than_printing_nothing(self) -> None:
        out = views.render_anomalies(load(SIMPLE))

        assert out.strip() == "No findings across 8 episode(s)."

    def test_the_tally_counts_by_severity(self) -> None:
        episode = _episode_with(
            _finding("A_ERROR", SEVERITY_ERROR, "2026-09-08T09:31:03.000+00:00"),
            _finding("A_WARN", SEVERITY_WARN, "2026-09-08T09:31:04.000+00:00"),
        )

        assert "2 finding(s) (1 error, 1 warn)" in views.render_anomalies([episode])

    def test_the_story_flags_match_the_ones_story_actually_takes(self) -> None:
        """views.py names the flag and cli.py owns the selector table. This is
        what stops a rename in one from leaving the other printing a command
        that does not exist."""
        dest_of = {flag: dest for flag, dest, _metavar, _help in _STORY_SELECTORS}

        for kind, flag in views.STORY_FLAG.items():
            assert flag in dest_of, f"story takes no {flag}"
            assert _SELECTOR_KINDS[dest_of[flag]] == kind


# ---------------------------------------------------------------------------
# episodes (section 9.5)
# ---------------------------------------------------------------------------


class TestEpisodes:
    def test_one_row_per_episode(self) -> None:
        episodes = load(SIMPLE)

        body = views.render_episodes(episodes).splitlines()[2:]

        assert len(body) == len(episodes)

    def test_rows_are_chronological(self) -> None:
        rows = views.render_episodes(load(STRUCTURES)).splitlines()[2:]
        times = [row.split()[0] for row in rows]

        assert times == sorted(times)

    def test_the_anomaly_column_counts_findings(self) -> None:
        episodes = load(STRUCTURES)
        rows = views.render_episodes(episodes).splitlines()[2:]
        total = sum(int(row.split()[-1]) for row in rows)

        assert total == sum(len(views.findings(e)) for e in episodes)

    def test_csv_carries_the_full_anchor_not_an_abbreviation(self) -> None:
        """An abbreviated id in an export is one nothing downstream can join
        on."""
        out = views.render_episodes(load(SIMPLE), as_csv=True)

        assert out.splitlines()[0] == ",".join(views.EPISODE_COLUMNS)
        assert "4f2c9a1e6d8b47c3a5f09e21b7d4c6a8" in out

    def test_an_order_id_is_not_lengthened_to_disambiguate_a_trade(self) -> None:
        """Trade ids differ only in their last digits. Pooled with order ids
        they would push every order id out to fifteen characters to separate
        trades that the `kind` column already separates."""
        out = views.render_episodes(load(SIMPLE))

        assert "4f2c9a" in out
        assert "4f2c9a1e6d8b" not in out

    def test_the_outcome_filter(self, capsys: pytest.CaptureFixture[str]) -> None:
        out = run(
            [
                "--log-file",
                str(SIMPLE),
                "--no-index",
                "episodes",
                "--outcome",
                "PARTIAL",
            ],
            capsys,
        )

        assert len(out.splitlines()) == 3  # header, rule, one row
        assert "PARTIAL" in out


# ---------------------------------------------------------------------------
# digest (section 9.4)
# ---------------------------------------------------------------------------


class TestDigest:
    def test_top_truncates_and_says_what_it_left_out(self) -> None:
        episodes = load(SIMPLE)

        out = views.render_digest(episodes, top=2)

        assert f"{len(episodes) - 2} more episode(s)" in out

    def test_without_top_nothing_is_omitted(self) -> None:
        assert "more episode(s)" not in views.render_digest(load(SIMPLE))

    def test_an_episode_with_findings_outranks_one_without(self) -> None:
        episodes = load(STRUCTURES)

        out = views.render_digest(episodes, significance=views.SIGNIFICANCE_ANOMALIES)
        first = out.split("\n\n")[0]

        assert views.findings(next(e for e in episodes if e.anchor_key[:6] in first))

    def test_the_significance_rule_changes_the_order(self) -> None:
        episodes = load(STRUCTURES)

        by_anomalies = views.render_digest(
            episodes, significance=views.SIGNIFICANCE_ANOMALIES, top=1
        )
        by_duration = views.render_digest(
            episodes, significance=views.SIGNIFICANCE_DURATION, top=1
        )

        assert by_anomalies != by_duration

    def test_a_number_the_log_did_not_support_is_left_out(self) -> None:
        """Section 8.3's no-invention rule: a gateway episode has no notional,
        and printing 0.00 would be inventing one."""
        gateway = next(e for e in load(STRUCTURES) if e.kind == "gateway")

        assert "notional" not in views.render_digest([gateway])


# ---------------------------------------------------------------------------
# The property that matters
# ---------------------------------------------------------------------------


VIEWS = ("digest", "episodes", "anomalies")


class TestTheIndexAndTheLogAgree:
    @pytest.mark.parametrize("view", VIEWS)
    @pytest.mark.parametrize("fixture", (SIMPLE, STRUCTURES))
    def test_character_identical_either_way(
        self,
        view: str,
        fixture: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        common = ["--log-file", str(fixture)]
        streamed = run(common + ["--no-index", view], capsys)
        indexed = run(common + ["--db", str(tmp_path / "replay.db"), view], capsys)

        # An index path that loaded nothing would show up here as a short
        # report against a long one, so equality is the whole assertion --
        # except that neither may be empty.
        assert streamed.strip()
        assert streamed == indexed


class TestTheDetectionSettingsAreIndexed:
    def test_changing_strict_rebuilds_rather_than_serving_the_old_answer(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An index built without --strict does not contain the findings
        --strict asks for, so serving it would answer a question nobody
        asked."""
        db = str(tmp_path / "replay.db")
        common = ["--log-file", str(SIMPLE), "--db", db]

        run(common + ["index", "--stats"], capsys)
        relaxed = (tmp_path / "replay.db").stat().st_mtime_ns
        out = run(common + ["--strict", "index", "--stats"], capsys)

        assert "strict=1" in out
        assert (tmp_path / "replay.db").stat().st_mtime_ns != relaxed

    def test_csv_is_refused_where_it_would_mean_nothing(self) -> None:
        assert main(["--log-file", str(SIMPLE), "--format", "csv", "stream"]) == 2
