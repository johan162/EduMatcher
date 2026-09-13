"""pm-audit-replay's global option surface (design section 9.1, task AR-1.1).

There is no subcommand yet, so what these tests pin is the option set itself
and the two things argparse cannot express: the detail-level axis, and the
window flags that are mutually exclusive by meaning rather than by syntax.
"""

from __future__ import annotations

import pytest

from edumatcher.audit.replay.cli import (
    build_parser,
    detail_level,
    main,
    parse_duration,
    parse_id_len,
    parse_reorder_window,
    validate_args,
)


class TestParseDuration:
    @pytest.mark.parametrize(
        "text,seconds",
        [("30s", 30), ("15m", 900), ("2h", 7200), ("1d", 86400), ("1.5h", 5400)],
    )
    def test_accepts_a_number_and_a_unit(self, text: str, seconds: float) -> None:
        assert parse_duration(text) == seconds

    @pytest.mark.parametrize("text", ["15", "", "m", "xm", "-2h", "0s", "2w"])
    def test_rejects_everything_else(self, text: str) -> None:
        """A bare number is rejected on purpose: a unit the reader has to guess
        is exactly the ambiguity this tool exists to remove."""
        with pytest.raises(ValueError):
            parse_duration(text)


class TestParseReorderWindow:
    def test_a_bare_integer_is_a_fact_count(self) -> None:
        assert parse_reorder_window("2000") == (2000, None)

    def test_a_duration_is_receipt_time(self) -> None:
        assert parse_reorder_window("5s") == (None, 5.0)

    def test_naming_one_bound_leaves_the_other_unset(self) -> None:
        """So the caller can keep its default rather than losing the bound."""
        count, seconds = parse_reorder_window("5s")
        assert count is None
        count, seconds = parse_reorder_window("2000")
        assert seconds is None

    @pytest.mark.parametrize("text", ["0", "-1", "abc"])
    def test_rejects_nonsense(self, text: str) -> None:
        with pytest.raises(ValueError):
            parse_reorder_window(text)


class TestParseIdLen:
    def test_full_means_no_abbreviation(self) -> None:
        assert parse_id_len("full") is None
        assert parse_id_len("FULL") is None

    def test_a_number_is_a_prefix_length(self) -> None:
        assert parse_id_len("12") == 12

    @pytest.mark.parametrize("text", ["0", "-3", "six"])
    def test_rejects_nonsense(self, text: str) -> None:
        with pytest.raises(ValueError):
            parse_id_len(text)


class TestDetailLevel:
    @pytest.mark.parametrize(
        "argv,level",
        [
            ([], 1),
            (["-q"], 0),
            (["-v"], 2),
            (["-vv"], 3),
            (["-vvv"], 4),
            (["-vvvv"], 4),
        ],
    )
    def test_the_one_axis_of_section_8_1(self, argv: list[str], level: int) -> None:
        """-q is 0, the default is 1, and -vvv is the top; more does not go higher."""
        assert detail_level(build_parser().parse_args(argv)) == level


class TestValidateArgs:
    def test_a_plain_invocation_is_valid(self) -> None:
        assert validate_args(build_parser().parse_args([])) is None

    def test_date_and_from_are_two_ways_to_say_the_same_thing(self) -> None:
        args = build_parser().parse_args(
            ["--date", "2026-09-08", "--from", "2026-09-08"]
        )
        assert validate_args(args) is not None

    def test_last_excludes_the_absolute_window(self) -> None:
        args = build_parser().parse_args(["--last", "2h", "--date", "2026-09-08"])
        assert validate_args(args) is not None

    def test_a_backwards_window_is_rejected(self) -> None:
        args = build_parser().parse_args(
            ["--from", "2026-09-08T10:00:00", "--to", "2026-09-08T09:00:00"]
        )
        assert validate_args(args) is not None

    def test_quiet_and_verbose_contradict(self) -> None:
        args = build_parser().parse_args(["-q", "-v"])
        assert validate_args(args) is not None


class TestMain:
    def test_exits_zero(self) -> None:
        assert main([]) == 0

    def test_repeatable_filters_accumulate(self) -> None:
        args = build_parser().parse_args(
            ["--symbol", "AAPL", "--symbol", "MSFT", "--gateway", "TRADER01"]
        )
        assert args.symbol == ["AAPL", "MSFT"]
        assert args.gateway == ["TRADER01"]

    def test_a_bad_combination_exits_two(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["-q", "-v"]) == 2
        assert "-q cannot be combined" in capsys.readouterr().err

    def test_a_bad_duration_is_an_argparse_error(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["--last", "soon"])
        assert exc.value.code == 2

    def test_help_lists_every_section_9_1_option(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit):
            main(["--help"])
        text = capsys.readouterr().out
        for flag in (
            "--log-file",
            "--db",
            "--no-index",
            "--rebuild",
            "--from",
            "--to",
            "--date",
            "--last",
            "--symbol",
            "--gateway",
            "--kind",
            "--format",
            "--show-source",
            "--show-units",
            "--explain",
            "--id-len",
            "--actor-style",
            "--tz",
            "--reorder-window",
            "--no-color",
        ):
            assert flag in text, f"{flag} missing from --help"


class TestRegisteredInPmHelp:
    def test_pm_help_knows_the_command(self) -> None:
        from edumatcher.pm_help.registry import ALL_COMMANDS

        assert any(c.name == "pm-audit-replay" for c in ALL_COMMANDS)
