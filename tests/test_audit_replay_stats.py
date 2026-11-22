"""The confidence report and its subcommand (task AR-2.5).

The report is a diagnostic on the **audit trail**, not on the tool. On a log
recorded since the envelope landed, RECORDED should dominate; a large share
anywhere else means a publisher is bypassing ``CausalPublisher``, or that the
window reaches back before the envelope existed. Both are worth knowing before
anyone draws a conclusion from the narration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.audit.query import iter_entries
from edumatcher.audit.replay import stats as stats_report
from edumatcher.audit.replay.cli import main, reorder_bounds, window_bounds
from edumatcher.audit.replay.episodes import Episode
from edumatcher.audit.replay.links import Confidence
from edumatcher.audit.replay.pipeline import reconstruct
from tests.replay_goldens import fixture_log

HEALTHY = "01_simple_limit_partial_fill"
HALTED = "02_halted_reject_and_kill_switch"
ARCHIVE = "03_archived_no_envelope"


def collect(name: str) -> stats_report.Stats:
    _run, steps = reconstruct(iter_entries([fixture_log(name)]))
    return stats_report.collect(steps)


class TestTheDistribution:
    def test_an_enveloped_log_is_dominated_by_recorded_links(self) -> None:
        """CP-2's second condition, on a log recorded since the envelope."""
        stats = collect(HEALTHY)
        assert stats.envelope_share() == 1.0
        assert stats.links[Confidence.RECORDED] > 0
        assert stats.links[Confidence.HEURISTIC] == 0
        assert stats.links[Confidence.NONE] == 0

    def test_an_archive_has_no_recorded_links_at_all(self) -> None:
        """The same command measures how much of a history predates the
        envelope, which is the other thing it is for."""
        stats = collect(ARCHIVE)
        assert stats.envelope_share() == 0.0
        assert stats.links[Confidence.RECORDED] == 0
        assert stats.links[Confidence.CERTAIN] > 0
        assert stats.links[Confidence.HEURISTIC] == 1

    def test_origins_and_orphans_are_counted_apart(self) -> None:
        healthy = collect(HEALTHY)
        archive = collect(ARCHIVE)
        assert (healthy.origins, healthy.orphans) == (6, 0)
        assert (archive.origins, archive.orphans) == (0, 3)

    def test_anomalies_are_counted_by_code_and_severity(self) -> None:
        stats = collect(HALTED)
        assert stats.anomalies["EFFECT_COUNT_MISMATCH"] == 1
        assert stats.severities["warn"] == 1

    def test_the_counts_add_up(self) -> None:
        stats = collect(HEALTHY)
        assert stats.facts == 10
        assert stats.total_links == sum(stats.relations.values())


class TestTheReport:
    def test_it_shows_shares_beside_counts(self) -> None:
        text = stats_report.render(collect(HEALTHY))
        assert "RECORDED" in text
        assert "%" in text
        assert "10 fact(s) reconstructed." in text

    def test_a_clean_log_says_so_rather_than_printing_nothing(self) -> None:
        assert "(none)" in stats_report.render(collect(HEALTHY))

    def test_findings_are_listed_with_a_severity_summary(self) -> None:
        text = stats_report.render(collect(HALTED))
        assert "EFFECT_COUNT_MISMATCH" in text
        assert "1 warn" in text

    def test_an_empty_window_is_not_a_wall_of_zeroes(self) -> None:
        assert stats_report.render(stats_report.Stats()) == "No facts in window.\n"

    def test_every_confidence_level_appears_even_at_zero(self) -> None:
        """A level missing from the report reads as "not measured"; a level at
        0.0% reads as "measured, none found"."""
        text = stats_report.render(collect(HEALTHY))
        for level in Confidence:
            assert level.value in text


class TestTheSubcommand:
    def test_it_runs_against_a_log_and_prints_the_distribution(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--log-file", str(fixture_log(HALTED)), "stats"]) == 0
        out = capsys.readouterr().out
        assert "Link confidence" in out
        assert "EFFECT_COUNT_MISMATCH" in out

    def test_a_missing_log_is_an_error_not_an_empty_report(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--log-file", str(tmp_path / "nope.log"), "stats"]) == 1
        assert "no audit log" in capsys.readouterr().err

    def test_no_subcommand_is_a_usage_error(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 2

    def test_a_rejected_option_combination_still_exits_two(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            main(["--date", "2026-09-08", "--from", "2026-09-08T09:00:00", "stats"])
            == 2
        )
        assert "cannot be combined" in capsys.readouterr().err


class TestWindowAndWindowBounds:
    def test_a_date_sets_no_window_because_the_day_is_its_files(self) -> None:
        assert window_bounds(_parsed(["--date", "2026-09-08", "stats"])) == (None, None)

    def test_last_is_relative_to_now(self) -> None:
        start, end = window_bounds(_parsed(["--last", "15m", "stats"]))
        assert start is not None and end is not None
        assert 890 <= (end - start).total_seconds() <= 910

    def test_no_window_flag_means_no_bounds(self) -> None:
        assert window_bounds(_parsed(["stats"])) == (None, None)

    def test_naming_one_reorder_bound_keeps_the_other_default(self) -> None:
        """The whole reason --reorder-window parses to a pair."""
        facts, seconds = reorder_bounds(_parsed(["--reorder-window", "5s", "stats"]))
        assert seconds == 5.0
        assert facts == stats_defaults()[0]

    def test_no_reorder_flag_means_both_defaults(self) -> None:
        assert reorder_bounds(_parsed(["stats"])) == stats_defaults()


def stats_defaults() -> tuple[int, float]:
    from edumatcher.audit.replay.cli import (
        DEFAULT_REORDER_FACTS,
        DEFAULT_REORDER_SECONDS,
    )

    return DEFAULT_REORDER_FACTS, DEFAULT_REORDER_SECONDS


def _parsed(argv: list[str]):
    from edumatcher.audit.replay.cli import build_parser

    return build_parser().parse_args(argv)


def _stats_findings(text: str) -> dict[str, int]:
    """The "Anomalies" section of a ``stats`` report, as code -> count."""
    section = text.split("Anomalies\n", 1)[1]
    found: dict[str, int] = {}
    for line in section.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            found[parts[0]] = int(parts[1])
    return found


def _anomaly_findings(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> dict[str, int]:
    import json
    from collections import Counter

    assert main([*argv, "anomalies", "--format", "ndjson"]) in (0, 1)
    out = capsys.readouterr().out
    return dict(Counter(json.loads(line)["code"] for line in out.splitlines()))


class TestStatsCountsWhatAnomaliesReports:
    """WP-RPL06 (C3): ``stats`` ran no detector and retired nothing, so its
    "Anomalies" section listed different findings from ``anomalies`` on the
    same window, and it ignored ``--symbol``/``--gateway``/``--kind``."""

    @pytest.mark.parametrize(
        "name",
        [path.stem for path in sorted(fixture_log(HEALTHY).parent.glob("*.log"))],
    )
    def test_the_findings_are_the_ones_anomalies_lists(
        self, name: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        argv = ["--log-file", str(fixture_log(name))]
        expected = _anomaly_findings(argv, capsys)
        assert main([*argv, "stats"]) == 0
        assert _stats_findings(capsys.readouterr().out) == expected

    def test_a_symbol_filter_narrows_the_counts(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log = str(fixture_log(HALTED))
        assert main(["--log-file", log, "stats"]) == 0
        whole = capsys.readouterr().out.splitlines()[0]
        assert main(["--log-file", log, "--symbol", "NOPE", "stats"]) in (0, 1)
        assert "No facts in window." in capsys.readouterr().out
        argv = ["--log-file", log, "--kind", "command"]
        expected = _anomaly_findings(argv, capsys)
        assert main([*argv, "stats"]) == 0
        narrowed = capsys.readouterr().out
        assert narrowed.splitlines()[0] != whole
        assert _stats_findings(narrowed) == expected

    def test_every_fact_is_still_counted_once(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        for name in (HEALTHY, HALTED, ARCHIVE):
            log = fixture_log(name)
            lines = [ln for ln in log.read_text().splitlines() if ln.strip()]
            assert main(["--log-file", str(log), "stats"]) == 0
            first = capsys.readouterr().out.splitlines()[0]
            assert first == f"{len(lines)} fact(s) reconstructed."
            assert (
                collect(name).links
                == stats_report.collect_episodes(_episodes(log)).links
            )


def _episodes(log: Path) -> list[Episode]:
    from edumatcher.audit.replay.detect import Detector, detected, observed
    from edumatcher.audit.replay.episodes import assemble

    run, steps = reconstruct(iter_entries([log]))
    detector = Detector(run.state)
    return list(
        detected(assemble(observed(steps, detector), run.state, run.links), detector)
    )
