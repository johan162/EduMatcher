"""prompt_toolkit pieces shared by the interview and the report viewer."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import (
    AnyContainer,
    Dimension,
    FormattedTextControl,
    HSplit,
    Window,
)
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea

from edumatcher.valuation.glossary import GLOSSARY

STYLE = Style.from_dict(
    {
        "title": "reverse bold",
        "keys": "reverse",
        "page": "",
        "page.current": "bold reverse",
        "label": "",
        "input": "bg:#303030 #ffffff",
        "input.error": "bg:#800000 #ffffff",
        "hint": "#888888",
        "mine": "#5fafff",
        "help": "#bbbbbb",
        "error": "bold #ff5f5f",
        "message": "bold #ffd75f",
        "preview.value": "bold",
        "good": "bold #5fd75f",
        "bad": "bold #ff5f5f",
        "warn": "#ffd75f",
        "pick.current": "reverse",
    }
)


class PickList:
    """A focusable list: ↑/↓ to move, Enter to pick, Esc to cancel.

    *describe*, when given, maps an option to (heading, description): options
    are listed under a heading line whenever it changes, each followed by its
    description. Headings cannot be picked.
    """

    def __init__(
        self,
        title: str,
        options: Sequence[str],
        current: str,
        on_done: Callable[[str | None], None],
        describe: Callable[[str], tuple[str, str]] | None = None,
    ) -> None:
        self.options = list(options)
        self.describe = describe
        self.index = self.options.index(current) if current in self.options else 0
        kb = KeyBindings()

        @kb.add("up")
        def _up(event: KeyPressEvent) -> None:
            self.index = (self.index - 1) % len(self.options)

        @kb.add("down")
        def _down(event: KeyPressEvent) -> None:
            self.index = (self.index + 1) % len(self.options)

        @kb.add("enter")
        def _pick(event: KeyPressEvent) -> None:
            on_done(self.options[self.index])

        @kb.add("escape", eager=True)
        def _cancel(event: KeyPressEvent) -> None:
            on_done(None)

        self.control = FormattedTextControl(
            self._fragments,
            focusable=True,
            key_bindings=kb,
            show_cursor=False,
            get_cursor_position=lambda: Point(0, self._lines()[1][self.index]),
        )
        lines = len(self._lines()[0])
        self.container: AnyContainer = Frame(
            Window(
                self.control,
                width=Dimension(min=24),
                height=Dimension(max=lines, preferred=lines),
            ),
            title=title,
        )

    def _lines(self) -> tuple[list[tuple[str, str]], list[int]]:
        """(style, text) per line, and the line each option is on."""
        lines: list[tuple[str, str]] = []
        rows: list[int] = []
        width = max(len(option) for option in self.options)
        heading = ""
        for i, option in enumerate(self.options):
            style = "class:pick.current" if i == self.index else ""
            if self.describe is None:
                rows.append(len(lines))
                lines.append((style, f" {option} "))
                continue
            group, description = self.describe(option)
            if group and group != heading:
                heading = group
                lines.append(("bold", f" {group}"))
            rows.append(len(lines))
            lines.append((style, f"   {option:<{width}}  {description} "))
        return lines, rows

    def _fragments(self) -> StyleAndTextTuples:
        return [(style, text + "\n") for style, text in self._lines()[0]]


class TextPrompt:
    """One line of input in a frame: Enter to accept, Esc to cancel."""

    def __init__(
        self, title: str, text: str, on_done: Callable[[str | None], None]
    ) -> None:
        self.area = TextArea(
            text=text,
            multiline=False,
            width=Dimension(min=40),
            accept_handler=lambda buffer: _accept(buffer.text),
        )
        self.area.buffer.cursor_position = len(text)

        def _accept(value: str) -> bool:
            on_done(value)
            return True

        kb = KeyBindings()

        @kb.add("escape", eager=True)
        def _cancel(event: KeyPressEvent) -> None:
            on_done(None)

        self.area.control.key_bindings = kb
        self.container: AnyContainer = Frame(self.area, title=title)


class GlossaryPanel:
    """F1: the glossary, filtered by what is typed in its search line."""

    def __init__(self, on_close: Callable[[], None]) -> None:
        self.search = TextArea(multiline=False, prompt="search: ")
        kb = KeyBindings()

        @kb.add("escape", eager=True)
        @kb.add("f1")
        def _close(event: KeyPressEvent) -> None:
            on_close()

        self.search.control.key_bindings = kb
        self.container: AnyContainer = Frame(
            HSplit(
                [
                    self.search,
                    Window(
                        FormattedTextControl(self._entries),
                        height=Dimension(max=18),
                        wrap_lines=True,
                    ),
                ]
            ),
            title="Glossary (Esc to close)",
            width=Dimension(preferred=76),
        )

    def _entries(self) -> StyleAndTextTuples:
        needle = self.search.text.strip().lower()
        out: StyleAndTextTuples = []
        for term, meaning in GLOSSARY:
            if needle in term.lower() or needle in meaning.lower():
                out += [("bold", term), ("", f": {meaning}\n")]
        return out or [("class:hint", "No entry matches.")]
