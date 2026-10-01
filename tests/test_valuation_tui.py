"""WP6: the interview state, the form application and the report viewer.

The applications are driven through a pipe with prompt_toolkit's DummyOutput,
sized 120 × 40 as the interview is laid out for. Each chunk of keys is sent only after the previous one has been
drawn, as a person typing would, so focus moves between rendered fields.
"""

import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from edumatcher.cli_version import package_version
from edumatcher.valuation.fields import Level
from edumatcher.valuation.pipeline import run
from edumatcher.valuation.presets import load_presets
from edumatcher.valuation.report.build import build_report, compare
from edumatcher.valuation.tui.app import InterviewApp
from edumatcher.valuation.tui.interview import Interview
from edumatcher.valuation.tui.viewer import ReportViewer
from edumatcher.valuation.tui.widgets import PickList
from tests.test_valuation_resolve import AURORA

PRESETS = load_presets()
F1, F2, F3, F5, F9 = "\x1bOP", "\x1b[12~", "\x1b[13~", "\x1b[15~", "\x1b[20~"
PGDN, DOWN, ESC, CTRL_D = "\x1b[6~", "\x1b[B", "\x1b", "\x04"


def drive(make: Callable[[], Any], chunks: Sequence[str]) -> tuple[Any, str]:
    """Run make().app, typing *chunks* one per redraw; return (object, result)."""
    output = DummyOutput()
    output.get_size = lambda: Size(rows=40, columns=120)
    with (
        create_pipe_input() as pipe,
        create_app_session(input=pipe, output=output),
    ):
        obj = make()
        queue = list(chunks)

        def next_chunk(_: object) -> None:
            if queue:
                pipe.send_text(queue.pop(0))

        obj.app.after_render += next_chunk

        async def main() -> str:
            loop = asyncio.get_running_loop()
            loop.call_later(20, lambda: obj.app.exit(result="timeout"))
            return await obj.app.run_async()

        return obj, asyncio.run(main())


# -- the interview state ------------------------------------------------------------


def test_texts_start_from_the_answers() -> None:
    interview = Interview(AURORA, PRESETS)
    assert interview.texts["customers.last_fy_revenue"] == "90m"
    assert interview.evaluation.valid
    assert interview.evaluation.preview is not None
    assert interview.evaluation.preview.valuation.fair_value == pytest.approx(
        16.85, abs=0.005
    )


def test_problems_are_keyed_to_their_field() -> None:
    interview = Interview({}, PRESETS)
    interview.set_text("customers.churn", "lots")
    assert interview.evaluation.problems == {
        "customers.churn": "'lots' is not a number"
    }
    interview.set_text("customers.churn", "150")
    assert "outside" in interview.evaluation.problems["customers.churn"]
    interview.set_text("customers.last_fy_revenue", "9")  # customers round to 0
    interview.set_text("customers.churn", "")
    assert set(interview.evaluation.problems) == {"customers.now"}
    assert interview.dirty


def test_hints_show_the_automatic_value() -> None:
    interview = Interview({}, PRESETS, Level.EXPERT)
    churn = next(s for s in interview.fields(3) if s.key == "customers.churn")
    assert interview.hint(churn) == "8% · preset"
    interview.set_text("customers.churn", "abc")  # hints keep the last valid company
    assert interview.hint(churn) == "8% · preset"


def test_levels_add_fields_and_pages() -> None:
    interview = Interview({}, PRESETS)
    assert interview.level is Level.BEGINNER
    counts = []
    for level in Level:
        interview.level = level
        counts.append(sum(len(interview.fields(n)) for n in interview.pages))
    assert counts == [16, 43, 88, 129]
    interview.level = Level.BEGINNER
    assert interview.pages == (1, 2, 3, 6, 7, 8, 9, 11)
    interview.turn(-1)
    assert interview.page == 11


def test_f3_cycles_the_level_and_keeps_the_page() -> None:
    interview = Interview({}, PRESETS, Level.EXPERT)
    interview.turn(3)
    assert interview.page == 4  # People: no beginner fields
    interview.cycle_level()
    assert interview.level is Level.BEGINNER
    assert interview.page == 6  # the next page shown at beginner
    interview.cycle_level()
    assert (interview.level, interview.page) == (Level.INTERMEDIATE, 6)


def test_cannot_value_is_a_company_problem() -> None:
    interview = Interview({}, PRESETS)
    interview.set_text("rates.r2_override", "3")
    assert None in interview.evaluation.problems
    assert interview.evaluation.preview is None


# -- the form application -----------------------------------------------------------


def test_typing_picking_paging_and_calculating() -> None:
    interview = Interview({}, PRESETS, Level.EXPERT)
    keys = [
        "Aurora Metrics Inc.", "\t", "\t", "\r", DOWN, DOWN, "\r",  # sector pick-list
        PGDN, PGDN, "90m", "\t", "1800", "\t",
        F3, F2, F2, F1, "churn", ESC, F5,
    ]  # fmt: skip
    app, result = drive(lambda: InterviewApp(interview), keys)
    assert result == "calculate"
    assert interview.texts == {
        "company.name": "Aurora Metrics Inc.",
        "company.sector": "consumer_subscription",
        "customers.last_fy_revenue": "90m",
        "customers.now": "1800",
    }
    assert interview.page == 3 and interview.level is Level.BEGINNER


def test_the_form_says_what_f3_adds_and_what_it_hides() -> None:
    interview = Interview({"offering.min_discount": 0.08}, PRESETS)
    assert [interview.added_on(page) for page in (1, 2, 4)] == [2, 2, 3]
    with (
        create_pipe_input() as pipe,
        create_app_session(input=pipe, output=DummyOutput()),
    ):
        app = InterviewApp(interview)
        assert app._level_line()[0][1] == (
            " F3 → Intermediate: 2 more fields here · 1 answer hidden "
        )
        interview.level = Level.ADVANCED
        assert (
            app._level_line()[0][1] == " F3 → Expert: no more here · 1 answer hidden "
        )
        interview.level = Level.EXPERT
        assert app._level_line()[0][1] == " Every field shown · F3 → Beginner "


def test_the_sector_pick_list_is_grouped_by_industry() -> None:
    sectors = PRESETS.sectors
    pick = PickList(
        "Sector preset",
        ("(automatic)", *sectors),
        "consulting",
        lambda value: None,
        lambda key: ("", "") if key not in sectors else
        (sectors[key].industry, sectors[key].description),
    )  # fmt: skip
    lines, rows = pick._lines()
    texts = [text.strip() for _, text in lines]
    assert texts[:3] == [
        "(automatic)",
        "Technology",
        "b2b_saas               Business software sold as annual subscriptions",
    ]
    assert len(lines) == 1 + 18 + 7  # automatic, the presets, 7 industry headings
    assert lines[rows[pick.index]][0] == "class:pick.current"
    assert texts[rows[pick.index]].startswith("consulting")


def test_the_title_bar_carries_the_edumatcher_brand() -> None:
    interview = Interview({}, PRESETS)
    with (
        create_pipe_input() as pipe,
        create_app_session(input=pipe, output=DummyOutput()),
    ):
        app = InterviewApp(interview)
        title = "".join(fragment[1] for fragment in app._title())
        assert app._title()[0] == ("class:brand", " EduMatcher ")
        assert title.startswith(f" EduMatcher   pm-valuation {package_version()}")
        assert "Newco AB (NEWC)" in title and "Level Beginner" in title
        assert app._body_title() == "1 Company"


def test_calculate_is_refused_while_a_field_is_invalid() -> None:
    interview = Interview({}, PRESETS, Level.EXPERT)
    keys = [PGDN, PGDN, "\t", "\t", "\t", "\t", "lots", F5, CTRL_D, F5]
    app, result = drive(lambda: InterviewApp(interview), keys)
    assert result == "calculate"  # after Ctrl-D cleared the bad churn
    assert "customers.churn" not in interview.texts
    assert app.message.startswith("Fix 1 problem(s) first: 'lots' is not a number")


def test_save_and_quit(tmp_path: Path) -> None:
    interview = Interview({}, PRESETS)
    target = tmp_path / "case.yaml"
    app, result = drive(
        lambda: InterviewApp(interview, target), ["Newco", F9, "\r", ESC]
    )
    assert result == "quit"
    assert target.read_text("utf-8").startswith(
        "pm_valuation: 1\ncompany:\n  name: Newco"
    )
    assert not interview.dirty


def test_quitting_with_unsaved_changes_asks() -> None:
    interview = Interview({}, PRESETS)
    app, result = drive(
        lambda: InterviewApp(interview), ["Newco", ESC, "\r", ESC, DOWN, "\r"]
    )
    assert result == "quit"  # the first answer was "keep working"


# -- the report viewer ----------------------------------------------------------------


@pytest.fixture(scope="module")
def report_run():
    return run({**AURORA, "simulation.draws": 200}, PRESETS)


def test_viewer_sections_compare_export_back(report_run, tmp_path: Path) -> None:
    report = build_report(report_run, PRESETS)
    target, pdf = tmp_path / "report.md", tmp_path / "report.pdf"

    def make() -> ReportViewer:
        comparison = compare(report_run, report_run)
        return ReportViewer(report, report_run, comparison, target, pdf, "letter")

    viewer, result = drive(make, ["\t", "\t", "c", "e", "p", "b"])
    assert result == "back"
    assert viewer.comparing
    assert target.read_text("utf-8").startswith("# Aurora Metrics Inc.")
    assert pdf.read_bytes().startswith(b"%PDF")
    assert viewer.message == f"PDF written to {pdf}"


def test_viewer_scrolls_to_each_section(report_run) -> None:
    report = build_report(report_run, PRESETS)
    viewer, result = drive(lambda: ReportViewer(report, report_run), ["\t", "\t", "q"])
    assert result == "quit"
    assert viewer.top == viewer.starts[1]  # the second section, at the top
    assert viewer._current() == 1


def test_viewer_without_a_previous_run(report_run) -> None:
    viewer, result = drive(
        lambda: ReportViewer(build_report(report_run, PRESETS), report_run), ["c", "q"]
    )
    assert viewer.message.startswith("Nothing to compare yet")
