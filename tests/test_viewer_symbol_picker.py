"""Interactive symbol switching in pm-viewer.

The contract under test, stated as behaviour rather than implementation:

* a terminal that is not a TTY must behave exactly as the viewer did before
  the feature existed — no key handling, no crash;
* `s` and `F1` both open the picker, and both ask the engine for a fresh
  symbol list without blocking the render loop;
* typing narrows, arrows move, Enter switches the subscription, Esc does
  nothing at all;
* after a switch the viewer shows the new symbol's book and never mixes in
  the old symbol's snapshots.
"""

from __future__ import annotations

import errno
import os
import pty
from types import SimpleNamespace
from typing import Any, Callable

import pytest
import zmq
from rich.align import Align
from rich.console import Console

from edumatcher.models.generated.system import topic_symbols
from edumatcher.viewer import main as viewer_main
from edumatcher.viewer.keyboard import KeyReader, parse_keys
from edumatcher.viewer.picker import SymbolPicker, render_picker

SYMBOLS = ["AAPL", "ABNB", "AMD", "AMZN", "GOOG", "MSFT", "NVDA", "TSLA"]


def _capture(renderable: Any, *, width: int = 200, height: int = 24) -> str:
    console = Console(width=width, height=height, force_terminal=False)
    with console.capture() as capture:
        console.print(renderable)
    return capture.get()


# ========================================================================
# Key decoding
# ========================================================================


class TestKeyDecoding:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            pytest.param("s", ["s"], id="plain-char"),
            pytest.param("abc", ["a", "b", "c"], id="burst-of-chars"),
            pytest.param("\r", ["ENTER"], id="carriage-return"),
            pytest.param("\n", ["ENTER"], id="newline"),
            pytest.param("\x7f", ["BACKSPACE"], id="delete"),
            pytest.param("\b", ["BACKSPACE"], id="backspace"),
            pytest.param("\x1b", ["ESC"], id="bare-escape"),
            pytest.param("\x1b[A", ["UP"], id="arrow-up"),
            pytest.param("\x1b[B", ["DOWN"], id="arrow-down"),
            pytest.param("\x1bOA", ["UP"], id="application-mode-up"),
        ],
    )
    def test_single_keys(self, raw: str, expected: list[str]) -> None:
        assert parse_keys(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            pytest.param("\x1bOP", id="ss3"),
            pytest.param("\x1b[11~", id="vt220"),
            pytest.param("\x1b[[A", id="linux-console"),
        ],
    )
    def test_f1_is_recognised_in_every_terminal_dialect(self, raw: str) -> None:
        """The footer promises F1 works; it has to be true on more than xterm."""
        assert parse_keys(raw) == ["F1"]

    def test_an_unknown_control_sequence_is_swallowed_whole(self) -> None:
        """Otherwise a stray mouse or paste sequence types itself into the
        filter box one character at a time."""
        assert parse_keys("\x1b[200~") == []
        assert parse_keys("\x1b[<0;1;1M") == []

    def test_a_truncated_control_sequence_is_swallowed_too(self) -> None:
        """A read can split a sequence; the tail must not become keystrokes."""
        assert parse_keys("\x1b[") == []
        assert parse_keys("\x1bO") == []

    def test_a_key_after_a_sequence_is_still_seen(self) -> None:
        assert parse_keys("\x1b[Bq") == ["DOWN", "q"]

    def test_a_multi_key_burst_is_decoded_in_order(self) -> None:
        assert parse_keys("\x1b[Bms\r") == ["DOWN", "m", "s", "ENTER"]


class TestKeyReaderAvailability:
    def test_a_non_tty_stream_offers_no_keys(self) -> None:
        """Piped or captured stdin must not be switched to cbreak mode."""
        reader = KeyReader(SimpleNamespace(isatty=lambda: False, fileno=lambda: 0))
        assert reader.available is False
        with reader as opened:
            assert opened.fileno() == -1
            assert opened.read_keys() == []

    def test_a_closed_stream_offers_no_keys(self) -> None:
        def _boom() -> int:
            raise ValueError("I/O operation on closed file")

        reader = KeyReader(SimpleNamespace(isatty=lambda: True, fileno=_boom))
        assert reader.available is False


class TestKeyReaderOnARealTerminal:
    """Exercised against an actual pty, because cbreak mode and raw reads are
    precisely the parts a mock would not tell the truth about."""

    def test_it_reads_keys_and_restores_the_terminal_afterwards(self) -> None:
        import termios

        primary, secondary = pty.openpty()
        try:
            stream = SimpleNamespace(isatty=lambda: True, fileno=lambda: secondary)
            reader = KeyReader(stream)
            assert reader.available is True

            def _canonical() -> int:
                return termios.tcgetattr(secondary)[3] & (termios.ICANON | termios.ECHO)

            was_canonical = _canonical()
            assert was_canonical, "a fresh pty should start in cooked mode"

            with reader as opened:
                assert opened.fileno() == secondary
                # Keys must arrive without Enter, and without being echoed
                # into the middle of the rendered book.
                assert _canonical() == 0
                os.write(primary, b"s")
                assert opened.read_keys() == ["s"]
                os.write(primary, b"\x1b[B\r")
                assert opened.read_keys() == ["DOWN", "ENTER"]

            assert _canonical() == was_canonical
            assert reader.read_keys() == []
        finally:
            os.close(primary)
            os.close(secondary)

    def test_a_vanished_terminal_is_not_fatal(self) -> None:
        """A tty that disappears mid-session (SIGHUP, closed terminal) must
        not turn the viewer's exit into a cleanup traceback."""
        primary, secondary = pty.openpty()
        stream = SimpleNamespace(isatty=lambda: True, fileno=lambda: secondary)
        with KeyReader(stream) as reader:
            os.close(primary)
            os.close(secondary)
            assert reader.read_keys() == []

    def test_a_stream_that_cannot_be_put_in_cbreak_mode_is_skipped(self) -> None:
        """isatty() can lie; the reader must degrade instead of raising."""
        read_fd, write_fd = os.pipe()
        try:
            stream = SimpleNamespace(isatty=lambda: True, fileno=lambda: read_fd)
            with KeyReader(stream) as reader:
                assert reader.fileno() == -1
                assert reader.read_keys() == []
        finally:
            os.close(read_fd)
            os.close(write_fd)


# ========================================================================
# Picker state machine
# ========================================================================


class TestPickerSelection:
    def _picker(self) -> SymbolPicker:
        picker = SymbolPicker()
        picker.set_symbols(SYMBOLS)
        return picker

    def test_it_opens_loading_and_empty(self) -> None:
        picker = SymbolPicker()
        assert picker.loading is True
        assert picker.selection is None

    def test_symbols_are_normalised_and_deduplicated(self) -> None:
        picker = SymbolPicker()
        picker.set_symbols([" msft ", "MSFT", "aapl", ""])
        assert picker.symbols == ["AAPL", "MSFT"]
        assert picker.loading is False

    def test_the_first_symbol_is_selected_by_default(self) -> None:
        assert self._picker().selection == "AAPL"

    def test_typing_narrows_to_a_prefix(self) -> None:
        """Prefix, not substring: typing A must not offer TSLA."""
        picker = self._picker()
        for char in "am":
            picker.type_char(char)
        assert picker.matches == ["AMD", "AMZN"]

    def test_typing_is_case_insensitive(self) -> None:
        lower, upper = self._picker(), self._picker()
        lower.type_char("m")
        upper.type_char("M")
        assert lower.matches == upper.matches == ["MSFT"]

    def test_punctuation_and_control_characters_are_not_typed(self) -> None:
        picker = self._picker()
        for char in " /*\t":
            assert picker.type_char(char) is False
        assert picker.query == ""

    def test_narrowing_resets_the_selection_to_the_top(self) -> None:
        picker = self._picker()
        picker.move(4)
        picker.type_char("a")
        assert picker.selection == "AAPL"

    def test_backspace_widens_the_filter_again(self) -> None:
        picker = self._picker()
        picker.type_char("a")
        picker.type_char("m")
        picker.backspace()
        assert picker.matches == ["AAPL", "ABNB", "AMD", "AMZN"]

    def test_backspace_on_an_empty_filter_is_harmless(self) -> None:
        picker = self._picker()
        picker.backspace()
        assert picker.query == ""
        assert picker.selection == "AAPL"

    def test_the_selection_never_leaves_the_list(self) -> None:
        picker = self._picker()
        picker.move(-5)
        assert picker.selection == SYMBOLS[0]
        picker.move(500)
        assert picker.selection == SYMBOLS[-1]

    def test_a_filter_matching_nothing_selects_nothing(self) -> None:
        picker = self._picker()
        for char in "zz":
            picker.type_char(char)
        assert picker.matches == []
        assert picker.selection is None

    def test_a_late_symbol_list_keeps_the_selection_in_range(self) -> None:
        """The list arrives after the popup opens; a stale index must not
        survive into a shorter list."""
        picker = self._picker()
        picker.move(7)
        picker.set_symbols(["AAPL", "MSFT"])
        assert picker.selection in ("AAPL", "MSFT")


class TestPickerWindow:
    def _picker(self, count: int) -> SymbolPicker:
        picker = SymbolPicker()
        picker.set_symbols([f"SYM{i:03d}" for i in range(count)])
        return picker

    def test_a_short_list_needs_no_scrolling(self) -> None:
        rows, selected, above, below = self._picker(4).window(10)
        assert len(rows) == 4
        assert (selected, above, below) == (0, False, False)

    def test_a_long_list_scrolls_and_says_so(self) -> None:
        picker = self._picker(50)
        picker.move(25)
        rows, selected, above, below = picker.window(10)
        assert len(rows) == 10
        assert rows[selected] == picker.selection
        assert (above, below) == (True, True)

    @pytest.mark.parametrize("index", [0, 1, 7, 24, 48, 49])
    def test_the_selection_is_always_inside_the_window(self, index: int) -> None:
        picker = self._picker(50)
        picker.move(index)
        rows, selected, _above, _below = picker.window(10)
        assert 0 <= selected < len(rows)
        assert rows[selected] == picker.selection

    def test_the_ends_of_the_list_are_reachable(self) -> None:
        picker = self._picker(50)
        _rows, _sel, above, below = picker.window(10)
        assert (above, below) == (False, True)
        picker.move(49)
        _rows, _sel, above, below = picker.window(10)
        assert (above, below) == (True, False)


class TestPickerRendering:
    def _render(self, picker: SymbolPicker, current: str = "MSFT") -> str:
        return _capture(
            render_picker(picker, current=current, visible_rows=6), width=80, height=30
        )

    def test_it_says_so_while_the_symbol_list_is_still_on_its_way(self) -> None:
        assert "loading symbols" in self._render(SymbolPicker())

    def test_it_says_so_when_nothing_matches(self) -> None:
        picker = SymbolPicker()
        picker.set_symbols(SYMBOLS)
        picker.type_char("z")
        assert "no match" in self._render(picker)

    def test_it_shows_the_filter_and_the_key_hints(self) -> None:
        picker = SymbolPicker()
        picker.set_symbols(SYMBOLS)
        picker.type_char("a")
        out = self._render(picker)
        assert "Filter A" in out
        assert "Enter select" in out
        assert "Esc cancel" in out
        assert "AAPL" in out
        assert "TSLA" not in out

    def test_the_symbol_being_viewed_is_listed_alongside_the_others(self) -> None:
        """It is rendered differently from the selection, but it must still be
        there and pickable."""
        picker = SymbolPicker()
        picker.set_symbols(SYMBOLS)
        assert picker.selection == "AAPL"
        assert "MSFT" in self._render(picker, current="MSFT")

    def test_both_scroll_markers_appear_on_a_long_list(self) -> None:
        picker = SymbolPicker()
        picker.set_symbols([f"SYM{i:03d}" for i in range(40)])
        picker.move(20)
        out = self._render(picker)
        assert "more" in out

    def test_the_overlay_fills_the_screen_so_the_book_is_fully_covered(self) -> None:
        picker = SymbolPicker()
        picker.set_symbols(SYMBOLS)
        out = _capture(
            viewer_main._build_picker_overlay(picker, "MSFT", size=(80, 24)),
            width=80,
            height=24,
        )
        assert len(out.splitlines()) == 24

    def test_the_popup_still_fits_a_very_short_terminal(self) -> None:
        picker = SymbolPicker()
        picker.set_symbols(SYMBOLS)
        out = _capture(
            viewer_main._build_picker_overlay(picker, "MSFT", size=(80, 12)),
            width=80,
            height=12,
        )
        assert len(out.splitlines()) == 12


# ========================================================================
# The footer hint
# ========================================================================


def test_the_footer_advertises_the_symbol_switch_and_the_quit_key() -> None:
    """The hint is the only discovery path for the feature."""
    out = _capture(
        viewer_main._build_display(
            {"bids": [], "asks": [], "recent_trades": []},
            "AAPL",
            depth=2,
            size=(200, 24),
        )
    )
    assert "s / F1 change symbol" in out
    assert "Ctrl-C to quit" in out


# ========================================================================
# The main loop, driven by scripted keys and engine messages
# ========================================================================


class _Sub:
    """A SUB socket recording its subscription changes."""

    def __init__(self) -> None:
        self.subscribed: list[str] = []
        self.unsubscribed: list[str] = []
        self.closed = False

    def recv_multipart(self) -> list[bytes]:
        return [b"", b""]

    def setsockopt(self, opt: int, value: bytes) -> None:
        target = self.subscribed if opt == zmq.SUBSCRIBE else self.unsubscribed
        target.append(value.decode())

    def close(self) -> None:
        self.closed = True


class _Keys:
    """A KeyReader replacement that replays a scripted list of keypresses."""

    FD = 77

    def __init__(self, script: list[list[str]]) -> None:
        self._script = list(script)
        self.available = True

    def __enter__(self) -> "_Keys":
        return self

    def __exit__(self, *_exc: object) -> None:
        return

    def fileno(self) -> int:
        return self.FD

    def read_keys(self) -> list[str]:
        return self._script.pop(0) if self._script else []


def _run_viewer(
    monkeypatch: pytest.MonkeyPatch,
    *,
    steps: list[tuple[list[str], tuple[str, dict[str, Any]] | None]],
    symbol: str = "AAPL",
    keys_available: bool = True,
    poll_errno: int | None = None,
) -> tuple[_Sub, list[list[bytes]], list[Any]]:
    """Drive ``viewer_main.main()`` one poll per step.

    Each step says which keys were pressed and which engine message (if any)
    arrived, so a test can place a message precisely before or after a
    keypress. Returns the SUB socket, everything pushed to the engine, and
    every renderable handed to Live — the three externally visible outcomes.
    """
    inbox: list[tuple[str, dict[str, Any]]] = []
    sub = _Sub()
    pushed: list[list[bytes]] = []
    rendered: list[Any] = []
    keys = _Keys([step_keys for step_keys, _msg in steps])
    keys.available = keys_available

    class _Push:
        def send_multipart(self, frames: list[bytes]) -> None:
            pushed.append(frames)

        def close(self) -> None:
            return

    class _Poller:
        def __init__(self) -> None:
            self.step = 0

        def register(self, _sock: object, _evt: object) -> None:
            return

        def poll(self, timeout: int) -> list[tuple[object, int]]:
            _ = timeout
            if poll_errno is not None:
                raise zmq.ZMQError(poll_errno)
            if self.step >= len(steps):
                raise zmq.ZMQError(errno.EINTR)
            _step_keys, message = steps[self.step]
            self.step += 1
            ready: list[tuple[object, int]] = [(_Keys.FD, 1)]
            if message is not None:
                inbox.append(message)
                ready.append((sub, 1))
            return ready

    class _Live:
        def __init__(self, **_kw: object) -> None:
            return

        def __enter__(self) -> "_Live":
            return self

        def __exit__(self, *_exc: object) -> None:
            return

        def update(self, panel: object) -> None:
            rendered.append(panel)

        def refresh(self) -> None:
            return

    class _Thread:
        def __init__(self, target: Callable[[], None], daemon: bool) -> None:
            self._target = target
            _ = daemon

        def start(self) -> None:
            self._target()

    monkeypatch.setattr(
        "edumatcher.viewer.main.argparse.ArgumentParser.parse_args",
        lambda _self: SimpleNamespace(
            symbol=symbol,
            depth=3,
            db="data/stats.db",
            text_color="white",
            zebra_lines=False,
            zebra_lines_color="grey19",
        ),
    )
    monkeypatch.setattr(viewer_main, "make_subscriber", lambda *_a: sub)
    monkeypatch.setattr(viewer_main, "make_pusher", lambda *_a: _Push())
    monkeypatch.setattr(viewer_main, "decode", lambda _frames: inbox.pop(0))
    monkeypatch.setattr(viewer_main, "Live", _Live)
    monkeypatch.setattr(viewer_main, "KeyReader", lambda: keys)
    monkeypatch.setattr(viewer_main, "threading", SimpleNamespace(Thread=_Thread))
    monkeypatch.setattr("edumatcher.viewer.main.time.sleep", lambda _s: None)
    monkeypatch.setattr("edumatcher.viewer.main.zmq.Poller", _Poller)

    viewer_main.main()
    return sub, pushed, rendered


def _topics(pushed: list[list[bytes]]) -> list[str]:
    return [frames[0].decode() for frames in pushed]


class TestInteractiveSymbolSwitching:
    def _symbols_reply(self) -> tuple[str, dict[str, Any]]:
        return (
            topic_symbols(f"PMVIEW-{os.getpid()}"),
            {"symbols": [{"symbol": s} for s in SYMBOLS]},
        )

    def _book(self, symbol: str, price: float) -> tuple[str, dict[str, Any]]:
        return (
            f"book.{symbol}",
            {
                "bids": [{"price": price, "qty": 100, "count": 1}],
                "asks": [],
                "recent_trades": [],
            },
        )

    @pytest.mark.parametrize("key", ["s", "S", "F1"])
    def test_the_documented_keys_all_open_the_picker(
        self, monkeypatch: pytest.MonkeyPatch, key: str
    ) -> None:
        _sub, pushed, rendered = _run_viewer(monkeypatch, steps=[([key], None)])
        assert "system.symbols_request" in _topics(pushed)
        assert isinstance(rendered[-1], Align)

    def test_an_unrelated_key_does_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _sub, pushed, rendered = _run_viewer(monkeypatch, steps=[(["x"], None)])
        assert "system.symbols_request" not in _topics(pushed)
        assert not isinstance(rendered[-1], Align)

    def test_escape_closes_the_picker_and_changes_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sub, _pushed, rendered = _run_viewer(
            monkeypatch,
            steps=[(["s"], self._symbols_reply()), (["ESC"], None)],
        )
        assert sub.unsubscribed == []
        assert not isinstance(rendered[-1], Align)

    def test_enter_switches_the_subscription_to_the_chosen_symbol(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sub, pushed, _rendered = _run_viewer(
            monkeypatch,
            steps=[
                (["s"], self._symbols_reply()),
                (["m"], None),
                (["ENTER"], None),
            ],
        )
        assert sub.unsubscribed == ["book.AAPL"]
        assert sub.subscribed == ["book.MSFT"]
        # A fresh snapshot is requested so the new book is not blank until the
        # next engine publish.
        assert _topics(pushed).count("book.snapshot_request") == 2

    def test_arrows_and_backspace_steer_the_selection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sub, _pushed, _rendered = _run_viewer(
            monkeypatch,
            steps=[
                (["s"], self._symbols_reply()),
                (["n", "BACKSPACE"], None),
                (["DOWN", "DOWN", "DOWN", "UP"], None),
                (["ENTER"], None),
            ],
        )
        assert sub.subscribed == ["book.AMD"]

    def test_choosing_the_symbol_already_shown_is_a_no_op(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sub, pushed, _rendered = _run_viewer(
            monkeypatch,
            steps=[(["s"], self._symbols_reply()), (["ENTER"], None)],
        )
        assert sub.unsubscribed == []
        assert sub.subscribed == []
        assert _topics(pushed).count("book.snapshot_request") == 1

    def test_enter_with_nothing_matching_keeps_the_current_symbol(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sub, _pushed, rendered = _run_viewer(
            monkeypatch,
            steps=[
                (["s"], self._symbols_reply()),
                (["z"], None),
                (["ENTER"], None),
            ],
        )
        assert sub.subscribed == []
        assert not isinstance(rendered[-1], Align)

    def test_a_snapshot_for_the_previous_symbol_is_discarded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Messages for the old subscription can still be in flight after the
        switch; showing them under the new symbol's name would be a lie."""
        sub, _pushed, rendered = _run_viewer(
            monkeypatch,
            steps=[
                (["s"], self._symbols_reply()),
                (["m"], None),
                (["ENTER"], None),
                ([], self._book("AAPL", 1.25)),
            ],
        )
        assert sub.subscribed == ["book.MSFT"]
        assert "1.2500" not in _capture(rendered[-1])

    def test_the_new_symbols_book_is_shown_after_the_switch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _sub, _pushed, rendered = _run_viewer(
            monkeypatch,
            steps=[
                ([], self._book("AAPL", 1.25)),
                (["s"], self._symbols_reply()),
                (["m"], None),
                (["ENTER"], None),
                ([], self._book("MSFT", 99.5)),
            ],
        )
        out = _capture(rendered[-1])
        assert "MSFT" in out
        assert "99.5000" in out
        assert "1.2500" not in out

    def test_a_symbol_list_arriving_after_escape_is_kept_for_next_time(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The reply is asynchronous, so it can land after the popup closes.
        Caching it is what makes the second open instant."""
        sub, pushed, rendered = _run_viewer(
            monkeypatch,
            steps=[
                (["s"], None),
                (["ESC"], self._symbols_reply()),
                (["s"], None),
                (["DOWN"], None),
                (["ENTER"], None),
            ],
        )
        assert _topics(pushed).count("system.symbols_request") == 2
        assert sub.subscribed == ["book.ABNB"]
        assert rendered

    def test_keys_the_picker_has_no_use_for_are_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Left/right arrows and stray function keys must not type themselves
        into the filter or move the selection."""
        sub, _pushed, _rendered = _run_viewer(
            monkeypatch,
            steps=[
                (["s"], self._symbols_reply()),
                (["LEFT", "RIGHT", "F1"], None),
                (["ENTER"], None),
            ],
        )
        assert sub.subscribed == []

    def test_a_real_zmq_error_is_not_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only EINTR means "a signal arrived"; anything else is a bug worth
        seeing rather than a silent exit."""
        with pytest.raises(zmq.ZMQError):
            _run_viewer(monkeypatch, steps=[([], None)], poll_errno=errno.ENOTSOCK)

    def test_a_non_tty_terminal_still_renders_the_book(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without a TTY the viewer must behave exactly as it always did."""
        sub, pushed, rendered = _run_viewer(
            monkeypatch,
            steps=[(["s"], None), (["ENTER"], None)],
            keys_available=False,
        )
        assert sub.closed is True
        assert _topics(pushed) == ["book.snapshot_request"]
        assert rendered and not isinstance(rendered[-1], Align)
