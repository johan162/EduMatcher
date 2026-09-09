"""Tests for pm-help / pm-man.

Covers the registry's internal consistency (every command is well-formed,
every name/alias resolves) and the CLI's two modes: the full command index
(mode A) and a single command's man page (mode B).
"""

from __future__ import annotations

import sys

import pytest

from edumatcher.pm_help.cli import main
from edumatcher.pm_help.registry import (
    ALL_COMMANDS,
    CATEGORY_ORDER,
    close_matches,
    commands_by_category,
    get_command,
)

# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------


def test_every_command_name_is_unique() -> None:
    names = [cmd.name for cmd in ALL_COMMANDS]
    assert len(names) == len(set(names))


def test_every_command_has_required_fields() -> None:
    for cmd in ALL_COMMANDS:
        assert cmd.name, cmd
        assert cmd.name == "pm-help" or cmd.name.startswith("pm-"), cmd.name
        assert cmd.category in CATEGORY_ORDER, f"{cmd.name} has unknown category {cmd.category!r}"
        assert cmd.summary, f"{cmd.name} has no summary"
        assert not cmd.summary.endswith("  "), cmd.name
        assert cmd.synopsis, f"{cmd.name} has no synopsis"


def test_every_related_command_exists() -> None:
    for cmd in ALL_COMMANDS:
        for related in cmd.related:
            assert get_command(related) is not None, f"{cmd.name} references unknown related command {related!r}"


def test_commands_by_category_covers_every_command() -> None:
    grouped_names = {cmd.name for _cat, cmds in commands_by_category() for cmd in cmds}
    assert grouped_names == {cmd.name for cmd in ALL_COMMANDS}


def test_get_command_exact_match() -> None:
    cmd = get_command("pm-viewer")
    assert cmd is not None
    assert cmd.name == "pm-viewer"


def test_get_command_accepts_missing_pm_prefix() -> None:
    assert get_command("viewer") is get_command("pm-viewer")


def test_get_command_resolves_alias() -> None:
    assert get_command("pm-man") is get_command("pm-help")


def test_get_command_unknown_returns_none() -> None:
    assert get_command("pm-does-not-exist") is None


def test_close_matches_suggests_something_reasonable() -> None:
    suggestions = close_matches("pm-viewr")
    assert "pm-viewer" in suggestions


# ---------------------------------------------------------------------------
# CLI: mode A -- the full command index
# ---------------------------------------------------------------------------


def test_index_mode_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0


def test_index_mode_lists_every_command(capsys: pytest.CaptureFixture[str]) -> None:
    main([])
    out = capsys.readouterr().out
    for cmd in ALL_COMMANDS:
        assert cmd.name in out, f"{cmd.name} missing from the command index"


def test_index_mode_prints_version_and_data_dir(capsys: pytest.CaptureFixture[str]) -> None:
    main([])
    out = capsys.readouterr().out
    assert "EduMatcher data:" in out
    assert "Config source:" in out
    assert "Config compiled:" in out


def test_index_mode_table_format_uses_box_drawing(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--format", "table"])
    out = capsys.readouterr().out
    assert "╭" in out  # rounded box corner (╭)


def test_index_mode_text_format_has_no_box_drawing(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--format", "text"])
    out = capsys.readouterr().out
    assert "╭" not in out
    assert "pm-viewer" in out


def test_index_mode_verbose_adds_examples(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--format", "text", "-v"])
    out = capsys.readouterr().out
    cmd = get_command("pm-alf-console")
    assert cmd is not None and cmd.examples
    assert "e.g." in out


def test_index_mode_categories_appear_as_section_titles(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--format", "text"])
    out = capsys.readouterr().out
    for category in CATEGORY_ORDER:
        assert category in out


# ---------------------------------------------------------------------------
# CLI: mode B -- a single command's man page
# ---------------------------------------------------------------------------


def test_man_page_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["pm-viewer"]) == 0


def test_man_page_has_standard_sections(capsys: pytest.CaptureFixture[str]) -> None:
    main(["pm-alf-console"])
    out = capsys.readouterr().out
    for section in ("NAME", "SYNOPSIS", "DESCRIPTION", "OPTIONS", "RELATED COMMANDS", "EXAMPLES", "SEE ALSO"):
        assert section in out, f"missing {section!r} section"


def test_man_page_accepts_bare_name_without_pm_prefix(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["viewer"]) == 0
    out = capsys.readouterr().out
    assert "pm-viewer" in out


def test_man_page_shows_subcommands_when_present(capsys: pytest.CaptureFixture[str]) -> None:
    main(["pm-opctl-cli"])
    out = capsys.readouterr().out
    assert "SUBCOMMANDS" in out
    assert "start" in out
    assert "clear" in out


def test_man_page_every_command_renders_without_error(capsys: pytest.CaptureFixture[str]) -> None:
    """Smoke test: every registered command must render a man page cleanly."""
    for cmd in ALL_COMMANDS:
        assert main([cmd.name]) == 0
        out = capsys.readouterr().out
        assert cmd.name in out


def test_unknown_command_exits_nonzero_with_suggestion(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["pm-viewr"])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "unknown command" in err
    assert "pm-viewer" in err


# ---------------------------------------------------------------------------
# pm-help / pm-man alias behaviour
# ---------------------------------------------------------------------------


def test_prog_name_follows_argv0(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["pm-man"])
    main([])
    out = capsys.readouterr().out
    assert out.startswith("pm-man (EduMatcher)")


def test_prog_name_defaults_to_pm_help(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["pm-help"])
    main([])
    out = capsys.readouterr().out
    assert out.startswith("pm-help (EduMatcher)")


def test_version_flag_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
