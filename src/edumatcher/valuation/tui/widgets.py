"""prompt_toolkit pieces shared by the interview and the report viewer."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from prompt_toolkit.data_structures import Point
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import (
    AnyContainer,
    AnyDimension,
    Dimension,
    FormattedTextControl,
    HSplit,
    VSplit,
    Window,
)
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea

from edumatcher.valuation.glossary import GLOSSARY

STYLE = Style.from_dict(
    {
        # The EduMatcher terminal look (pm-viewer, pm-board): a white-on-blue
        # brand badge, grey labels, cyan values and rounded blue frames.
        "brand": "bold #ffffff bg:ansiblue",
        "title.label": "#9e9e9e",
        "title.value": "ansicyan",
        "title.sep": "#585858",
        "box.border": "ansiblue",
        "box.title": "bold",
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


TitleText = Callable[[], StyleAndTextTuples]


def Box(
    body: AnyContainer,
    title: str | Callable[[], str],
    bottom: TitleText | None = None,
    width: AnyDimension = None,
    height: AnyDimension = None,
) -> HSplit:
    """A rounded blue frame with a title in its top border and, optionally,
    a line of text in its bottom border, like pm-viewer's panels."""

    def edge(char: str, width: int | None = None, height: int | None = None) -> Window:
        return Window(char=char, style="class:box.border", width=width, height=height)

    def text(get: TitleText) -> Window:
        return Window(FormattedTextControl(get), height=1, dont_extend_width=True)

    def heading() -> StyleAndTextTuples:
        name = title if isinstance(title, str) else title()
        return [("class:box.title", f" {name} ")]

    top = [edge("╭", width=1, height=1), edge("─", width=1, height=1), text(heading)]
    end = [edge("─", height=1), edge("╮", width=1, height=1)]
    low = [edge("╰", width=1, height=1), edge("─", width=1, height=1)]
    if bottom is not None:
        low.append(text(bottom))
    low += [edge("─", height=1), edge("╯", width=1, height=1)]
    return HSplit(
        [
            VSplit([*top, *end], height=1),
            VSplit([edge("│", width=1), body, edge("│", width=1)]),
            VSplit(low, height=1),
        ],
        width=width,
        height=height,
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
        self.container: AnyContainer = Box(
            Window(
                self.control,
                width=Dimension(min=24),
                height=Dimension(max=lines, preferred=lines),
            ),
            title,
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
        self.container: AnyContainer = Box(self.area, title)


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
        self.container: AnyContainer = Box(
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
            "Glossary (Esc to close)",
            width=Dimension(preferred=76),
        )

    def _entries(self) -> StyleAndTextTuples:
        needle = self.search.text.strip().lower()
        out: StyleAndTextTuples = []
        for term, meaning in GLOSSARY:
            if needle in term.lower() or needle in meaning.lower():
                out += [("bold", term), ("", f": {meaning}\n")]
        return out or [("class:hint", "No entry matches.")]
