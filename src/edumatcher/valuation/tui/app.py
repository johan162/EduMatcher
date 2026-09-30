"""The interview application and the interview ↔ report loop (design §19).

Twelve pages of forms, a live preview, F-keys for the glossary, the review
page, the level of detail (F3), calculation and saving. F5 hands over to the report
viewer; its "back" returns here with every answer kept.
"""

from __future__ import annotations

import textwrap
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.key_binding.bindings.focus import focus_next, focus_previous
from prompt_toolkit.layout import (
    AnyContainer,
    Container,
    Dimension,
    DynamicContainer,
    Float,
    FloatContainer,
    FormattedTextControl,
    HSplit,
    Layout,
    ScrollablePane,
    VSplit,
    Window,
)
from prompt_toolkit.widgets import TextArea

from edumatcher.valuation.fields import FIELDS, PAGES, SECTORS, FieldSpec, Level, Unit
from edumatcher.valuation.model.offering import Outcome
from edumatcher.valuation.pipeline import Run, run
from edumatcher.valuation.presets import Presets
from edumatcher.valuation.report.build import build_report, compare
from edumatcher.valuation.resolve import choices
from edumatcher.valuation.scenario_io import dump
from edumatcher.valuation.tui.interview import Interview
from edumatcher.valuation.tui.viewer import ReportViewer
from edumatcher.valuation.tui.widgets import (
    STYLE,
    GlossaryPanel,
    PickList,
    TextPrompt,
)
from edumatcher.valuation.units import format_value

_KEYS = (
    " Tab next · PgDn page · Enter pick · Ctrl-D clear · F1 glossary · "
    "F2 review · F3 level · F5 calculate · F9 save · Esc quit"
)
_AUTO = "(automatic)"


class InterviewApp:
    def __init__(self, interview: Interview, save: Path | None = None) -> None:
        self.iv = interview
        self.save_path = save
        self.message = ""
        self.review: TextArea | None = None
        self.inputs: dict[str, TextArea] = {}
        self._forms: dict[tuple[int, Level], Container] = {}
        self.floats = FloatContainer(
            HSplit(
                [
                    Window(
                        FormattedTextControl(self._title), height=1, style="class:title"
                    ),
                    VSplit(
                        [
                            Window(FormattedTextControl(self._pages), width=32),
                            HSplit(
                                [
                                    DynamicContainer(self._body),
                                    Window(
                                        FormattedTextControl(self._level_line),
                                        height=1,
                                    ),
                                ]
                            ),
                            Window(FormattedTextControl(self._preview), width=22),
                        ]
                    ),
                    # 5 lines of field help, plus one for a status message.
                    Window(FormattedTextControl(self._help), height=6, wrap_lines=True),
                    Window(FormattedTextControl(_KEYS), height=1, style="class:keys"),
                ]
            ),
            floats=[],
        )
        self.app: Application[str] = Application(
            layout=Layout(self.floats, focused_element=self._first_input()),
            key_bindings=self._bindings(),
            style=STYLE,
            full_screen=True,
        )

    def run(self) -> str:
        """ "calculate" or "quit"."""
        return self.app.run()

    # -- the form -----------------------------------------------------------------

    def _input(self, spec: FieldSpec) -> TextArea:
        area = self.inputs.get(spec.key)
        if area is not None:
            return area
        area = TextArea(
            text=self.iv.texts.get(spec.key, ""),
            multiline=False,
            width=13,
            accept_handler=lambda buffer: self._enter(spec),
        )
        area.window.style = lambda: (
            "class:input.error"
            if spec.key in self.iv.evaluation.problems
            else "class:input"
        )
        area.buffer.on_text_changed += lambda buffer: self.iv.set_text(
            spec.key, buffer.text
        )
        self.inputs[spec.key] = area
        return area

    def _row(self, spec: FieldSpec) -> Container:
        def hint() -> StyleAndTextTuples:
            if self.iv.texts.get(spec.key):
                return [("class:mine", " ✎ you")]
            return [("class:hint", " " + self.iv.hint(spec))]

        return VSplit(
            [
                Window(
                    FormattedTextControl(" " + spec.label),
                    width=Dimension(min=12, preferred=30, max=30),
                ),
                self._input(spec),
                Window(FormattedTextControl(hint), wrap_lines=False),
            ],
            height=1,
        )

    def _form(self) -> Container:
        key = (self.iv.page, self.iv.level)
        if key not in self._forms:
            rows = [self._row(spec) for spec in self.iv.fields()]
            self._forms[key] = ScrollablePane(HSplit(rows))
        return self._forms[key]

    def _body(self) -> AnyContainer:
        return self.review if self.review is not None else self._form()

    def _first_input(self) -> TextArea:
        self._form()  # builds the inputs of the current page
        return self.inputs[self.iv.fields()[0].key]

    def _focused(self) -> FieldSpec | None:
        control = self.app.layout.current_control
        for spec in self.iv.fields():
            area = self.inputs.get(spec.key)
            if area is not None and area.control is control:
                return spec
        return None

    def _enter(self, spec: FieldSpec) -> bool:
        options = choices(spec, self.iv.presets)
        if spec.unit is Unit.BOOL:
            options = ("yes", "no")
        if options is None:
            self.app.layout.focus_next()
            return True
        area = self.inputs[spec.key]

        def done(value: str | None) -> None:
            self.floats.floats.clear()
            if value is not None:
                area.text = "" if value == _AUTO else value
            self.app.layout.focus(area)

        describe = self._describe_sector if spec.choices == SECTORS else None
        pick = PickList(
            spec.label, (_AUTO, *options), area.text or _AUTO, done, describe
        )
        self.floats.floats.append(Float(pick.container))
        self.app.layout.focus(pick.control)
        return True

    def _describe_sector(self, key: str) -> tuple[str, str]:
        """A sector's ICB industry and description, for its pick-list line."""
        preset = self.iv.presets.sectors.get(key)
        return ("", "") if preset is None else (preset.industry, preset.description)

    # -- the side panes -------------------------------------------------------------

    def _title(self) -> StyleAndTextTuples:
        v = self.iv.evaluation.resolved.values
        page = self.iv.page_index + 1
        text = (
            f" pm-valuation ─ {v['company.name']} ({v['company.ticker']}) ─ "
            f"page {page} / {len(self.iv.pages)} ─ {self.iv.level.name.capitalize()}"
            + (" ─ review" if self.review is not None else "")
        )
        return [("", text)]

    def _pages(self) -> StyleAndTextTuples:
        out: StyleAndTextTuples = [("bold", " PAGES\n")]
        for number in self.iv.pages:
            mine = self.iv.answered_on(number)
            style = "class:page.current" if number == self.iv.page else "class:page"
            marker = "▶" if number == self.iv.page else " "
            count = f" ✎{mine}" if mine else ""
            out.append((style, f"{marker}{number:>2} {PAGES[number - 1]:<21}{count}\n"))
        return out

    def _level_line(self) -> StyleAndTextTuples:
        """The level, what F3 changes on this page, and answers it hides."""
        if self.review is not None:
            return []
        level = self.iv.level.name.capitalize()
        after = self.iv.next_level().name.capitalize()
        if self.iv.level is Level.EXPERT:
            text = f" Level {level}: every field · F3 → {after}"
        else:
            count = self.iv.added_on(self.iv.page)
            more = f"{count} more field{'s' * (count != 1)}" if count else "no more"
            text = f" Level {level} · F3 → {after}: {more} on this page"
        hidden = self.iv.hidden_answers()
        if hidden:
            text += f" · {hidden} answer{'s' * (hidden != 1)} hidden at this level"
        return [("class:hint", text)]

    def _preview(self) -> StyleAndTextTuples:
        ev = self.iv.evaluation
        out: StyleAndTextTuples = [("bold", " LIVE PREVIEW\n\n")]
        if ev.preview is None:
            count = len(ev.problems)
            out.append(("class:bad", f" {count} problem{'s' * (count != 1)} to fix\n"))
            if None in ev.problems:
                out.append(("class:error", f" {ev.problems[None]}\n"))
            return out
        val, pr = ev.preview.valuation, ev.preview.pricing
        low, high = pr.price_range
        out += [
            ("", " Fair value\n"),
            ("class:preview.value", f"   {val.fair_value:>10.2f}\n"),
            ("", f" DCF   {val.dcf_price:>10.2f}\n"),
            ("", f" Comps {val.comps_price:>10.2f}\n\n"),
            ("", f" Range {low:.2f}–{high:.2f}\n"),
        ]
        if pr.range_moved:
            out.append(("class:hint", "  (moved by the floor)\n"))
        if pr.listing is not None:
            out.append(("", f" Offer {pr.listing.price:.2f} at {pr.coverage:.1f}×\n"))
        verdict = {
            Outcome.PRICED: ("class:good", "PROCEED"),
            Outcome.THIN_BOOK: ("class:warn", "THIN BOOK"),
            Outcome.POSTPONED: ("class:bad", "POSTPONE"),
        }[pr.outcome]
        out += [("", "\n "), (verdict[0], verdict[1] + "\n")]
        warnings = len(ev.preview.findings)
        if warnings:
            out.append(("class:warn", f"\n ⚠ {warnings} note{'s' * (warnings != 1)}\n"))
        return out

    def _help(self) -> StyleAndTextTuples:
        out: StyleAndTextTuples = []
        if self.message:
            out.append(("class:message", f" {self.message}\n"))
        spec = self._focused()
        if spec is None:
            return out
        # Wrapped here at word boundaries; the window would break mid-word.
        width = self.app.output.get_size().columns - 1
        problem = self.iv.evaluation.problems.get(spec.key)
        if problem:
            return out + [("class:error", self._wrap(f" {problem}", width))]
        return out + [("class:help", self._wrap(f" {spec.label} — {spec.help}", width))]

    @staticmethod
    def _wrap(text: str, width: int) -> str:
        return textwrap.fill(text, width, subsequent_indent=" ", break_on_hyphens=False)

    # -- keys ------------------------------------------------------------------------

    def _bindings(self) -> KeyBindings:
        kb = KeyBindings()
        no_float = Condition(lambda: not self.floats.floats)
        in_form = Condition(lambda: not self.floats.floats and self.review is None)

        kb.add("tab", filter=in_form)(focus_next)
        kb.add("down", filter=in_form)(focus_next)
        kb.add("s-tab", filter=in_form)(focus_previous)
        kb.add("up", filter=in_form)(focus_previous)

        @kb.add("pagedown", filter=in_form)
        def _next_page(event: KeyPressEvent) -> None:
            self._turn(+1)

        @kb.add("pageup", filter=in_form)
        def _previous_page(event: KeyPressEvent) -> None:
            self._turn(-1)

        @kb.add("c-d", filter=in_form)
        def _clear(event: KeyPressEvent) -> None:
            spec = self._focused()
            if spec is not None:
                self.inputs[spec.key].text = ""

        @kb.add("f1", filter=no_float)
        def _glossary(event: KeyPressEvent) -> None:
            back = self.app.layout.current_window

            def close() -> None:
                self.floats.floats.clear()
                self.app.layout.focus(back)

            panel = GlossaryPanel(close)
            self.floats.floats.append(Float(panel.container))
            self.app.layout.focus(panel.search)

        @kb.add("f2", filter=no_float)
        def _review(event: KeyPressEvent) -> None:
            if self.review is None:
                self.review = TextArea(
                    text=self._review_text(), read_only=True, scrollbar=True
                )
                self.app.layout.focus(self.review)
            else:
                self.review = None
                self.app.layout.focus(self._first_input())

        @kb.add("f3", filter=in_form)
        def _level(event: KeyPressEvent) -> None:
            self.iv.cycle_level()
            self.app.layout.focus(self._first_input())

        @kb.add("f5", filter=no_float)
        def _calculate(event: KeyPressEvent) -> None:
            problems = self.iv.evaluation.problems
            if problems:
                first = next(iter(problems.values()))
                self.message = f"Fix {len(problems)} problem(s) first: {first}"
                return
            event.app.exit(result="calculate")

        @kb.add("f9", filter=no_float)
        def _save(event: KeyPressEvent) -> None:
            back = self.app.layout.current_window
            ticker = self.iv.evaluation.resolved.values["company.ticker"]
            default = self.save_path or Path(f"{ticker.lower()}.yaml")

            def done(value: str | None) -> None:
                self.floats.floats.clear()
                self.app.layout.focus(back)
                if value:
                    self._write(Path(value))

            prompt = TextPrompt("Save the scenario to", str(default), done)
            self.floats.floats.append(Float(prompt.container))
            self.app.layout.focus(prompt.area)

        @kb.add("escape", filter=no_float, eager=True)
        @kb.add("c-q", filter=no_float)
        def _quit(event: KeyPressEvent) -> None:
            if not self.iv.dirty:
                event.app.exit(result="quit")
                return
            back = self.app.layout.current_window
            stay, leave = "No, keep working", "Yes, quit without saving"

            def done(value: str | None) -> None:
                self.floats.floats.clear()
                if value == leave:
                    self.app.exit(result="quit")
                else:
                    self.app.layout.focus(back)

            confirm = PickList("Unsaved changes. Quit?", (stay, leave), stay, done)
            self.floats.floats.append(Float(confirm.container))
            self.app.layout.focus(confirm.control)

        return kb

    def _turn(self, step: int) -> None:
        self.iv.turn(step)
        self.message = ""
        self.app.layout.focus(self._first_input())

    def _write(self, path: Path) -> None:
        answers = self.iv.evaluation.answers
        try:
            path.write_text(dump(answers), encoding="utf-8")
        except OSError as exc:
            self.message = f"Could not save: {exc}"
            return
        self.save_path = path
        self.iv.dirty = False
        skipped = len(self.iv.texts) - len(answers)
        self.message = f"Saved {len(answers)} answers to {path}" + (
            f" ({skipped} invalid or empty left out)" if skipped else ""
        )

    def _review_text(self) -> str:
        ev = self.iv.evaluation
        lines: list[str] = []
        market = ev.resolved.values["company.market"]
        for number, title in enumerate(PAGES, 1):
            lines.append(f"── {number} {title} " + "─" * 40)
            for spec in (spec for spec in FIELDS if spec.page == number):
                value = format_value(spec, ev.resolved.values[spec.key], market)
                source = ev.resolved.sources[spec.key].value
                lines.append(f"  {spec.label:<40} {value:>22}   {source}")
        if ev.problems:
            lines.append("── Problems " + "─" * 40)
            lines += [f"  {message}" for message in ev.problems.values()]
        if ev.preview is not None and ev.preview.findings:
            lines.append("── Notes " + "─" * 40)
            lines += [f"  {f.code}: {f.message}" for f in ev.preview.findings]
        return "\n".join(lines)


def interview(
    answers: Mapping[str, Any],
    presets: Presets,
    level: Level = Level.BEGINNER,
    save: Path | None = None,
    export: Path | None = None,
    pdf: Path | None = None,
    paper: str = "a4",
) -> None:
    """Interview, calculate, show the report; repeat until the student quits."""
    state = Interview(answers, presets, level)
    previous: Run | None = None
    while True:
        app = InterviewApp(state, save)
        if app.run() == "quit":
            return
        save = app.save_path
        print("Calculating…", flush=True)
        current = run(state.evaluation.answers, presets)
        report = build_report(current, presets)
        comparison = None if previous is None else compare(previous, current)
        viewer = ReportViewer(report, current, comparison, export, pdf, paper)
        action = viewer.run()
        export, pdf = viewer.export_path, viewer.pdf_path
        previous = current
        if action == "quit":
            return
