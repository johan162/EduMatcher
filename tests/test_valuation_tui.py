"""WP6: the interview state, the form application and the report viewer.

The applications are driven through a pipe with prompt_toolkit's DummyOutput
(80 × 40). Each chunk of keys is sent only after the previous one has been
drawn, as a person typing would, so focus moves between rendered fields.
"""

import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from edumatcher.valuation.pipeline import run
from edumatcher.valuation.presets import load_presets
from edumatcher.valuation.report.build import build_report, compare
from edumatcher.valuation.tui.app import InterviewApp
from edumatcher.valuation.tui.interview import QUICK_PAGES, Interview
from edumatcher.valuation.tui.viewer import ReportViewer
from tests.test_valuation_resolve import AURORA

PRESETS = load_presets()
F1, F2, F3, F5, F9 = "\x1bOP", "\x1b[12~", "\x1b[13~", "\x1b[15~", "\x1b[20~"
PGDN, DOWN, ESC, CTRL_D = "\x1b[6~", "\x1b[B", "\x1b", "\x04"


def drive(make: Callable[[], Any], chunks: Sequence[str]) -> tuple[Any, str]:
    """Run make().app, typing *chunks* one per redraw; return (object, result)."""
    with (
        create_pipe_input() as pipe,
        create_app_session(input=pipe, output=DummyOutput()),
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
    interview = Interview({}, PRESETS)
    churn = next(s for s in interview.fields(3) if s.key == "customers.churn")
    assert interview.hint(churn) == "auto 8% · preset"
    interview.set_text("customers.churn", "abc")  # hints keep the last valid company
    assert interview.hint(churn) == "auto 8% · preset"


def test_pages_advanced_and_quick() -> None:
    interview = Interview({}, PRESETS)
    interview.turn(-1)
    assert interview.page == 12
    basic = len(interview.fields(12))
    interview.show_advanced = True
    assert len(interview.fields(12)) == basic + 20  # the bear and bull values
    quick = Interview({}, PRESETS, quick=True)
    assert quick.pages == QUICK_PAGES
    assert quick.answered_on(1) == 0


def test_cannot_value_is_a_company_problem() -> None:
    interview = Interview({}, PRESETS)
    interview.set_text("rates.r2_override", "3")
    assert None in interview.evaluation.problems
    assert interview.evaluation.preview is None


# -- the form application -----------------------------------------------------------


def test_typing_picking_paging_and_calculating() -> None:
    interview = Interview({}, PRESETS)
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
    assert interview.page == 3 and interview.show_advanced


def test_the_form_says_whether_f3_has_advanced_fields() -> None:
    interview = Interview({}, PRESETS)
    assert [interview.advanced_on(page) for page in (1, 2, 4)] == [0, 1, 4]
    with (
        create_pipe_input() as pipe,
        create_app_session(input=pipe, output=DummyOutput()),
    ):
        app = InterviewApp(interview)
        assert app._advanced_line()[0][1] == " No advanced fields on this page"
        interview.turn(1)
        assert app._advanced_line()[0][1] == (
            " ▸ 1 advanced field hidden · F3 shows them"
        )
        interview.turn(2)
        interview.show_advanced = True
        assert app._advanced_line()[0][1] == (
            " ▾ 4 advanced fields shown · F3 hides them"
        )


def test_calculate_is_refused_while_a_field_is_invalid() -> None:
    interview = Interview({}, PRESETS)
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
