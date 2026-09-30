"""The report viewer: the rich report in a scrollable pane with a section index."""

from __future__ import annotations

import io
import shutil
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import ANSI, StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import (
    FormattedTextControl,
    HSplit,
    Layout,
    VSplit,
    Window,
)
from rich.console import Console

from edumatcher.valuation.pipeline import Run
from edumatcher.valuation.report.build import Report, Section
from edumatcher.valuation.report.render_md import render_markdown
from edumatcher.valuation.report.render_rich import render_report, render_section
from edumatcher.valuation.tui.widgets import STYLE

_KEYS = (
    " ↑↓ PgUp PgDn scroll · Tab / Shift-Tab section · c compare · "
    "e export · p PDF · b back to the interview · q quit"
)
_INDEX_WIDTH = 34


def _ansi_lines(renderable: object, width: int) -> list[str]:
    buffer = io.StringIO()
    console = Console(file=buffer, width=width, force_terminal=True, color_system="256")
    console.print(renderable)
    return buffer.getvalue().rstrip("\n").split("\n")


class ReportViewer:
    def __init__(
        self,
        report: Report,
        result: Run,
        comparison: Section | None = None,
        export: Path | None = None,
        pdf: Path | None = None,
        paper: str = "a4",
    ) -> None:
        self.report, self.result = report, result
        self.export_path = export
        self.pdf_path, self.paper = pdf, paper
        self.message = ""
        width = max(60, shutil.get_terminal_size().columns - _INDEX_WIDTH - 1)
        self.lines: list[str] = []
        self.starts: list[int] = []  # the first line of each section
        head = _ansi_lines(
            render_report(Report(report.title, report.verdict, ())), width
        )
        self.lines += head
        for section in report.sections:
            self.starts.append(len(self.lines))
            self.lines += _ansi_lines(render_section(section), width)
        self.compare_lines = (
            None
            if comparison is None
            else _ansi_lines(render_section(comparison), width)
        )
        self.comparing = False
        self.top = 0
        self.app: Application[str] = Application(
            layout=Layout(
                HSplit(
                    [
                        VSplit(
                            [
                                Window(
                                    FormattedTextControl(self._index),
                                    width=_INDEX_WIDTH,
                                ),
                                Window(
                                    FormattedTextControl(self._page, focusable=True),
                                    wrap_lines=False,
                                ),
                            ]
                        ),
                        Window(FormattedTextControl(self._status), height=1),
                        Window(
                            FormattedTextControl(_KEYS), height=1, style="class:keys"
                        ),
                    ]
                )
            ),
            key_bindings=self._bindings(),
            style=STYLE,
            full_screen=True,
        )

    def run(self) -> str:
        """ "back" or "quit"."""
        return self.app.run()

    # -- rendering ------------------------------------------------------------------

    def _height(self) -> int:
        return max(1, self.app.output.get_size().rows - 2)

    def _visible(self) -> list[str]:
        return (
            self.compare_lines if self.comparing and self.compare_lines else self.lines
        )

    def _page(self) -> ANSI:
        lines = self._visible()
        return ANSI("\n".join(lines[self.top : self.top + self._height()]))

    def _current(self) -> int:
        return max(
            (i for i, start in enumerate(self.starts) if start <= self.top), default=0
        )

    def _index(self) -> StyleAndTextTuples:
        out: StyleAndTextTuples = [("bold", " SECTIONS\n")]
        current = -1 if self.comparing else self._current()
        for i, section in enumerate(self.report.sections):
            style = "class:page.current" if i == current else ""
            out.append((style, f" {section.title[:_INDEX_WIDTH - 2]}\n"))
        if self.compare_lines is not None:
            style = "class:page.current" if self.comparing else ""
            out.append((style, "\n c  Compared with the previous run\n"))
        return out

    def _status(self) -> StyleAndTextTuples:
        return [("class:message", f" {self.message}")] if self.message else []

    # -- keys -----------------------------------------------------------------------

    def _scroll(self, delta: int) -> None:
        last = max(0, len(self._visible()) - self._height())
        self.top = min(last, max(0, self.top + delta))

    def _bindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("down")
        def _down(event: KeyPressEvent) -> None:
            self._scroll(1)

        @kb.add("up")
        def _up(event: KeyPressEvent) -> None:
            self._scroll(-1)

        @kb.add("pagedown")
        @kb.add(" ")
        def _page_down(event: KeyPressEvent) -> None:
            self._scroll(self._height() - 1)

        @kb.add("pageup")
        def _page_up(event: KeyPressEvent) -> None:
            self._scroll(-(self._height() - 1))

        @kb.add("home")
        def _home(event: KeyPressEvent) -> None:
            self.top = 0

        @kb.add("end")
        def _end(event: KeyPressEvent) -> None:
            self._scroll(len(self._visible()))

        @kb.add("tab")
        def _next(event: KeyPressEvent) -> None:
            if not self.comparing:
                later = [s for s in self.starts if s > self.top]
                if later:
                    self.top = 0
                    self._scroll(later[0])

        @kb.add("s-tab")
        def _previous(event: KeyPressEvent) -> None:
            if not self.comparing:
                earlier = [s for s in self.starts if s < self.top]
                self.top = 0
                self._scroll(earlier[-1] if earlier else 0)

        @kb.add("c")
        def _compare(event: KeyPressEvent) -> None:
            if self.compare_lines is None:
                self.message = "Nothing to compare yet: press b, change an answer, F5."
                return
            self.comparing = not self.comparing
            self.top = 0

        company = self.report.title.split(" (")[0].lower().replace(" ", "-")

        @kb.add("e")
        def _export(event: KeyPressEvent) -> None:
            path = self.export_path or Path(f"{company}-valuation.md")
            try:
                path.write_text(render_markdown(self.report), encoding="utf-8")
            except OSError as exc:
                self.message = f"Could not export: {exc}"
                return
            self.export_path = path
            self.message = f"Report written to {path}"

        @kb.add("p")
        def _pdf(event: KeyPressEvent) -> None:
            from edumatcher.valuation.report.render_pdf import write_pdf

            path = self.pdf_path or Path(f"{company}-valuation.pdf")
            try:
                write_pdf(self.result, self.report, path, self.paper)
            except OSError as exc:
                self.message = f"Could not write the PDF: {exc}"
                return
            self.pdf_path = path
            self.message = f"PDF written to {path}"

        @kb.add("b")
        def _back(event: KeyPressEvent) -> None:
            event.app.exit(result="back")

        @kb.add("q")
        @kb.add("c-q")
        def _quit(event: KeyPressEvent) -> None:
            event.app.exit(result="quit")

        return kb
