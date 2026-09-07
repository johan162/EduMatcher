"""CLI dispatch tests for ``pm-systest`` (Requirements 1.4, 1.5).

Covers ``main()``'s behaviour before any subcommand-specific logic runs:
no subcommand, an unrecognized subcommand, and each of the six recognized
subcommands parsing and dispatching to their (currently stub) handlers
without starting any process.
"""

from __future__ import annotations

import pytest

from edumatcher.systest.cli import _SUBCOMMANDS, main

_SUBCOMMAND_TUPLE: tuple[str, ...] = _SUBCOMMANDS


class TestNoSubcommand:
    """Requirement 1.4: no subcommand prints usage and exits non-zero."""

    def test_exits_non_zero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code != 0

    def test_usage_on_stderr_lists_all_subcommands(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit):
            main([])
        captured = capsys.readouterr()
        assert captured.out == ""
        for subcommand in _SUBCOMMAND_TUPLE:
            assert (
                subcommand in captured.err
            ), f"usage output missing subcommand {subcommand!r}: {captured.err!r}"


class TestUnrecognizedSubcommand:
    """Requirement 1.5: an unknown subcommand is rejected, naming it."""

    def test_exits_non_zero_without_starting_a_process(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main(["bogus"])
        assert exc_info.value.code != 0

    def test_error_on_stderr_names_the_bad_subcommand(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit):
            main(["bogus"])
        captured = capsys.readouterr()
        assert "bogus" in captured.err


class TestRecognizedSubcommandsDispatchWithoutStartingAProcess:
    """Each of the six subcommands parses and dispatches to its stub handler.

    The current implementation (task 1.2) constructs no ``Orchestrator`` and
    starts no process for any subcommand; the stub handlers simply print a
    "not yet implemented" message and return 0. A bare "no exception, exit
    code 0" check is therefore sufficient evidence that dispatch reached the
    handler rather than falling through to an error path.
    """

    @pytest.mark.parametrize("subcommand", _SUBCOMMAND_TUPLE)
    def test_dispatches_and_returns_zero(
        self, subcommand: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = main([subcommand])
        assert result == 0
        captured = capsys.readouterr()
        assert captured.err == ""


def test_all_six_subcommands_are_covered() -> None:
    """Guards against a subcommand being silently added/removed from the CLI."""
    assert _SUBCOMMAND_TUPLE == ("run", "list", "record", "compare", "verify", "report")
