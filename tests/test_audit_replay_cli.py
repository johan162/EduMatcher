"""pm-audit-replay's option surface and index policy (sections 9.1, 9.7).

Two things argparse cannot express are pinned here -- the detail-level axis,
and the window flags that are mutually exclusive by meaning rather than by
syntax -- and, since AR-3.4 was dropped, the rule that decides when the index
is rebuilt. That rule is the whole of what "incremental" means now, so each of
its branches gets a test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import REPLAY_FIXTURES, opened

from edumatcher.audit.replay.cli import (
    build_parser,
    detail_level,
    main,
    parse_duration,
    parse_id_len,
    parse_reorder_window,
    validate_args,
)
from edumatcher.audit.replay.index import (
    META_RULES_VERSION,
    RULES_VERSION,
    describe,
    open_index,
    reading,
    open_readonly,
    write_meta,
)

FIXTURES = REPLAY_FIXTURES
SIMPLE = FIXTURES / "01_simple_limit_partial_fill.log"
ARCHIVED = FIXTURES / "03_archived_no_envelope.log"


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


class TestTheIndexPolicy:
    """One decision in one place: when is a rebuild due (design section 9.7).

    AR-3.4 was dropped, so "the log grew" is handled by rebuilding rather than
    by resuming -- which makes *noticing* that it grew load-bearing. Without
    the fingerprint check a reader would get this morning's episodes all
    afternoon and have no way to tell.
    """

    def _args(self, tmp_path: Path, *extra: str) -> list[str]:
        log = tmp_path / "audit.log"
        if not log.exists():
            log.write_bytes(SIMPLE.read_bytes())
        return [
            "--log-file",
            str(log),
            "--db",
            str(tmp_path / "replay.db"),
            *extra,
            "index",
        ]

    def _built_at(self, tmp_path: Path) -> str:
        conn = opened(open_readonly(tmp_path / "replay.db"))
        return describe(conn)["built_at"]

    def test_a_missing_index_is_built(self, tmp_path: Path) -> None:
        assert main(self._args(tmp_path)) == 0
        assert (tmp_path / "replay.db").exists()

    def test_a_current_index_is_read_not_rebuilt(self, tmp_path: Path) -> None:
        main(self._args(tmp_path))
        _mark(tmp_path / "replay.db")
        main(self._args(tmp_path))
        assert self._built_at(tmp_path) == _MARK

    def test_an_appended_log_forces_a_rebuild(self, tmp_path: Path) -> None:
        main(self._args(tmp_path))
        before = _episode_count(tmp_path / "replay.db")
        log = tmp_path / "audit.log"
        with log.open("ab") as handle:
            handle.write(ARCHIVED.read_bytes())
        main(self._args(tmp_path))
        assert _episode_count(tmp_path / "replay.db") > before

    def test_a_stale_rules_version_forces_a_rebuild(self, tmp_path: Path) -> None:
        main(self._args(tmp_path))
        conn = opened(open_index(tmp_path / "replay.db"))
        write_meta(conn, META_RULES_VERSION, "0")
        conn.commit()
        conn.close()
        assert main(self._args(tmp_path)) == 0
        conn = opened(open_readonly(tmp_path / "replay.db"))
        assert describe(conn)[META_RULES_VERSION] == str(RULES_VERSION)

    def test_rebuild_forces_one_even_when_nothing_changed(self, tmp_path: Path) -> None:
        main(self._args(tmp_path))
        _mark(tmp_path / "replay.db")
        main(self._args(tmp_path, "--rebuild"))
        assert self._built_at(tmp_path) != _MARK

    def test_no_index_leaves_index_nothing_to_do(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(self._args(tmp_path, "--no-index")) == 2
        assert "nothing for index to do" in capsys.readouterr().out
        assert not (tmp_path / "replay.db").exists()

    def test_stats_reports_what_the_index_holds(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        main(
            self._args(
                tmp_path,
            )
            + ["--stats"]
        )
        text = capsys.readouterr().out
        assert "episodes by kind" in text
        assert "rules_version" in text

    def test_a_missing_log_is_an_error_not_an_empty_index(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(
            [
                "--log-file",
                str(tmp_path / "nope.log"),
                "--db",
                str(tmp_path / "replay.db"),
                "index",
            ]
        )
        assert code == 1
        assert "no audit log" in capsys.readouterr().err


#: ``built_at`` has one-second resolution, so comparing two real stamps cannot
#: tell a rebuild from a reuse in a test that does both immediately. A sentinel
#: can: it survives a reuse and is overwritten by a rebuild.
_MARK = "1970-01-01T00:00:00+00:00"


def _mark(db: Path) -> None:
    conn = opened(open_index(db))
    write_meta(conn, "built_at", _MARK)
    conn.commit()
    conn.close()


def _episode_count(db: Path) -> int:
    with reading(db) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0])


class TestRegisteredInPmHelp:
    def test_pm_help_knows_the_command(self) -> None:
        from edumatcher.pm_help.registry import ALL_COMMANDS

        assert any(c.name == "pm-audit-replay" for c in ALL_COMMANDS)
