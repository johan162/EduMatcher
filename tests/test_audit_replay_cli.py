"""pm-audit-replay's option surface and index policy (sections 9.1, 9.7).

Two things argparse cannot express are pinned here -- the detail-level axis,
and the window flags that are mutually exclusive by meaning rather than by
syntax -- and, since AR-3.4 was dropped, the rule that decides when the index
is rebuilt. That rule is the whole of what "incremental" means now, so each of
its branches gets a test.
"""

from __future__ import annotations

from pathlib import Path

import json

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
    META_SCHEMA_VERSION,
    RULES_VERSION,
    SCHEMA_VERSION,
    describe,
    open_index,
    reading,
    open_readonly,
    write_meta,
)

FIXTURES = REPLAY_FIXTURES
SIMPLE = FIXTURES / "01_simple_limit_partial_fill.log"
ARCHIVED = FIXTURES / "03_archived_no_envelope.log"
HALTED = FIXTURES / "02_halted_reject_and_kill_switch.log"
COMBO = FIXTURES / "04_quote_oco_combo.log"


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
        assert detail_level(build_parser().parse_args([*argv, "stream"])) == level


class TestValidateArgs:
    def test_a_plain_invocation_is_valid(self) -> None:
        assert validate_args(build_parser().parse_args(["stream"])) is None

    def test_date_and_from_are_two_ways_to_say_the_same_thing(self) -> None:
        args = build_parser().parse_args(
            ["--date", "2026-09-08", "--from", "2026-09-08", "stream"]
        )
        assert validate_args(args) is not None

    def test_last_excludes_the_absolute_window(self) -> None:
        args = build_parser().parse_args(
            ["--last", "2h", "--date", "2026-09-08", "stream"]
        )
        assert validate_args(args) is not None

    def test_a_backwards_window_is_rejected(self) -> None:
        args = build_parser().parse_args(
            ["--from", "2026-09-08T10:00:00", "--to", "2026-09-08T09:00:00", "stream"]
        )
        assert validate_args(args) is not None

    def test_quiet_and_verbose_contradict(self) -> None:
        args = build_parser().parse_args(["-q", "-v", "stream"])
        assert validate_args(args) is not None


class TestMain:
    def test_a_subcommand_is_required(self, capsys: pytest.CaptureFixture[str]) -> None:
        """WP-RPL09 (C12): no subcommand printed nothing and exited 0."""
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 2
        assert "usage:" in capsys.readouterr().err

    def test_repeatable_filters_accumulate(self) -> None:
        args = build_parser().parse_args(
            ["--symbol", "AAPL", "--symbol", "MSFT", "--gateway", "TRADER01", "stream"]
        )
        assert args.symbol == ["AAPL", "MSFT"]
        assert args.gateway == ["TRADER01"]

    def test_a_bad_combination_exits_two(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["-q", "-v", "stream"]) == 2
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

    def test_a_stale_schema_version_forces_a_rebuild(self, tmp_path: Path) -> None:
        """The sibling of the rules check, and until schema 2 it had never
        fired: an index whose *tables* are the wrong shape is refused for the
        same reason one whose rows mean something else is, and there is no
        migration path by design."""
        main(self._args(tmp_path))
        conn = opened(open_index(tmp_path / "replay.db"))
        write_meta(conn, META_SCHEMA_VERSION, "0")
        conn.commit()
        conn.close()
        assert main(self._args(tmp_path)) == 0
        conn = opened(open_readonly(tmp_path / "replay.db"))
        assert describe(conn)[META_SCHEMA_VERSION] == str(SCHEMA_VERSION)

    def test_an_index_of_the_wrong_shape_is_discarded_not_reused(
        self, tmp_path: Path
    ) -> None:
        """The bump has to do something, and nothing else would do it.

        `CREATE TABLE IF NOT EXISTS` leaves a table that already exists in the
        wrong shape alone, and `clear()` empties rows without touching
        columns -- so a real pre-bump file is not repaired by rebuilding it.
        It failed on the first insert naming a column that was not there.

        Ages a file properly rather than only its metadata: the columns go
        too, which is what a database written by the older code actually
        looks like.
        """
        main(self._args(tmp_path))
        db = tmp_path / "replay.db"
        conn = opened(open_index(db))
        write_meta(conn, META_SCHEMA_VERSION, str(SCHEMA_VERSION - 1))
        conn.execute("ALTER TABLE anomalies DROP COLUMN file")
        conn.execute("ALTER TABLE anomalies DROP COLUMN line_no")
        conn.commit()
        conn.close()

        assert main(self._args(tmp_path)) == 0

        conn = opened(open_readonly(db))
        assert describe(conn)[META_SCHEMA_VERSION] == str(SCHEMA_VERSION)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(anomalies)")}
        assert {"file", "line_no"} <= columns

    def test_rebuild_forces_one_even_when_nothing_changed(self, tmp_path: Path) -> None:
        main(self._args(tmp_path))
        _mark(tmp_path / "replay.db")
        main(self._args(tmp_path, "--rebuild"))
        assert self._built_at(tmp_path) != _MARK

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


class TestTheFormatSwitch:
    """``--format`` chooses a rendering, never a subset of the content.

    Every one of these was accepted and silently ignored before AR-6.1: the
    tool printed a table and exited 0 for `--format json`, which a script
    finds out about only by failing to parse it.
    """

    def _stream(self, tmp_path: Path, *extra: str) -> list[str]:
        return [
            "--log-file",
            str(SIMPLE),
            "stream",
            *extra,
        ]

    def test_ndjson_is_one_object_per_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(self._stream(tmp_path, "--format", "ndjson")) == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines
        assert all(json.loads(line)["type"] for line in lines)

    def test_json_wraps_them_with_a_header(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(self._stream(tmp_path, "--format", "json")) == 0
        doc = json.loads(capsys.readouterr().out)
        assert doc["rules_version"] == RULES_VERSION
        assert doc["source_files"] == [str(SIMPLE)]
        assert doc["counts"]["beat"] == len(
            [o for o in doc["objects"] if o["type"] == "beat"]
        )

    def test_a_format_a_command_cannot_produce_is_refused(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--log-file", str(SIMPLE), "digest", "--format", "json"]) == 2
        assert "only available for" in capsys.readouterr().err

    def test_markdown_is_refused_where_there_is_no_narrative(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert (
            main(
                [
                    "--log-file",
                    str(SIMPLE),
                    "anomalies",
                    "--format",
                    "markdown",
                ]
            )
            == 2
        )
        assert "only available for" in capsys.readouterr().err

    def test_csv_is_still_only_for_episodes(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(self._stream(Path("."), "--format", "csv")) == 2
        assert "only available for `episodes`" in capsys.readouterr().err


class TestAFindingKeepsItsSourceLine:
    """``Anomaly`` carries a file and line because a finding a reader cannot
    go and look at is a finding they cannot act on -- and the index dropped
    both until schema 2, so a finding read back had lost the one thing that
    makes it actionable."""

    def _anomalies(self, args: list[str]) -> list[dict[str, object]]:
        assert main(args) == 0
        out = self._capsys.readouterr().out
        return [json.loads(line) for line in out.splitlines()]

    @pytest.fixture(autouse=True)
    def _capture(self, capsys: pytest.CaptureFixture[str]) -> None:
        self._capsys = capsys

    def test_the_index_round_trips_the_full_path_and_the_line(
        self, tmp_path: Path
    ) -> None:
        args = [
            "--log-file",
            str(HALTED),
            "anomalies",
            "--severity",
            "info",
            "--format",
            "ndjson",
        ]
        from edumatcher.audit.replay import render_json
        from edumatcher.audit.replay.reader import episodes_in_window

        db = tmp_path / "replay.db"
        direct = self._anomalies(args)
        assert main(["--log-file", str(HALTED), "--db", str(db), "index"]) == 0
        self._capsys.readouterr()
        with reading(db) as conn:
            indexed = [
                json.loads(render_json.dumps(obj))
                for obj in render_json.anomalies(episodes_in_window(conn))
            ]

        def located(found: list[dict[str, object]]) -> list[str]:
            return sorted(repr((f["code"], f["source"])) for f in found)

        assert direct and located(direct) == located(indexed)
        for finding in indexed:
            source = finding["source"]
            assert isinstance(source, dict)
            # The path as it was given, not shortened: `episode_events.file`
            # stores it the same way and `Fact.source` is what abbreviates.
            assert source["file"] == str(HALTED)
            assert isinstance(source["line"], int) and source["line"] > 0


class TestTheIndexChangesNothingButSpeed:
    """CP-6's third gate. The index is a cache of the reconstruction, so a
    narrative built from it must be the same narrative, character for
    character -- in the machine-readable shapes most of all, where a
    difference no human is reading would go unnoticed for a long time.
    """

    @pytest.mark.parametrize(
        "log", sorted(FIXTURES.glob("*.log")), ids=lambda p: p.stem
    )
    @pytest.mark.parametrize("fmt", ("text", "ndjson", "markdown"))
    def test_a_run_off_the_index_narrates_identically(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        log: Path,
        fmt: str,
    ) -> None:
        """Read back through ``reader`` -- what ``story`` narrates -- and
        rendered by the same choke point ``stream`` uses."""
        from edumatcher.audit.replay import cli, reader

        db = tmp_path / "replay.db"
        args = ["--log-file", str(log), "stream", "-vv", "--format", fmt]
        assert main(args) == 0
        without = capsys.readouterr().out
        assert main(["--log-file", str(log), "--db", str(db), "index"]) == 0
        capsys.readouterr()
        with reading(db) as conn:
            namespace = build_parser().parse_args(args)
            cli._narrate(
                reader.episodes_in_window(conn), reader.actors(conn), namespace
            )
        withindex = capsys.readouterr().out

        assert withindex == without


class TestTheIndexCoversTheWholeLog:
    """A cache may not depend on the question that populated it.

    `build_index` used to narrow the build by `--from`/`--to`/`--date`/
    `--last`, while the currency check is a source-file fingerprint that
    cannot see a window. A narrow build followed by a wider query therefore
    answered from a truncated model and said nothing about it -- reporting an
    OCO as OPEN where the trail plainly said CANCELLED, exit 0.
    """

    def test_a_window_is_refused_on_the_index_command(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Refused rather than ignored: silently indexing more than was asked
        for is the same class of untruth as the bug it replaces."""
        assert (
            main(
                [
                    "--log-file",
                    str(COMBO),
                    "--db",
                    "/tmp/unused.db",
                    "--from",
                    "2026-09-08",
                    "index",
                ]
            )
            == 2
        )
        assert "covers the whole log" in capsys.readouterr().err

    def test_a_narrow_query_does_not_narrow_the_index(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db = str(tmp_path / "replay.db")
        # Populate the index through a narrow query...
        assert (
            main(
                [
                    "--log-file",
                    str(COMBO),
                    "--db",
                    db,
                    "--to",
                    "2026-09-08T10:15:00.020+00:00",
                    "episodes",
                ]
            )
            == 0
        )
        capsys.readouterr()
        # ...then ask a wider one of the same index.
        assert main(["--log-file", str(COMBO), "--db", db, "episodes"]) == 0
        indexed = capsys.readouterr().out
        assert main(["--log-file", str(COMBO), "episodes"]) == 0
        direct = capsys.readouterr().out

        assert indexed == direct
        assert "CANCELLED" in indexed


class TestTheDisplaySwitchesReachTheCli:
    """The wiring, as distinct from the rendering the other file covers.

    A switch that works in the renderer and is not read by `render_options`
    is exactly the state `--tz` and `--no-color` were in before AR-6.2:
    accepted by the parser, shown by `--help`, and doing nothing.
    """

    def test_tz_moves_the_clock_in_the_narration(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = ["--log-file", str(SIMPLE), "stream"]
        assert main(args) == 0
        utc = capsys.readouterr().out
        assert main([*args[:2], "--tz", "Europe/Stockholm", "stream"]) == 0
        local = capsys.readouterr().out

        assert utc.splitlines()[0].startswith("09:31:02.110")
        assert local.splitlines()[0].startswith("11:31:02.110")

    def test_tz_reaches_the_views_too(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert (
            main(
                [
                    "--log-file",
                    str(SIMPLE),
                    "--tz",
                    "Europe/Stockholm",
                    "episodes",
                ]
            )
            == 0
        )
        assert "11:31:02" in capsys.readouterr().out

    def test_an_unknown_zone_is_an_argument_error(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(
                [
                    "--log-file",
                    str(SIMPLE),
                    "--tz",
                    "Mars/Olympus",
                    "stream",
                ]
            )
        assert exc.value.code == 2

    def test_force_color_survives_a_pipe(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """pytest's capture is not a terminal, which is exactly the situation
        `... | less -R` is in."""
        assert main(["--log-file", str(SIMPLE), "--force-color", "episodes"]) == 0

        assert "\033[" in capsys.readouterr().out

    def test_the_two_colour_flags_are_refused_together(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Checked in validate_args rather than by an argparse mutually
        exclusive group, because the options are added to the top-level parser
        AND to every subparser -- a group would catch `stream --no-color
        --force-color` and miss `--no-color stream --force-color`."""
        assert (
            main(
                [
                    "--log-file",
                    str(SIMPLE),
                    "--no-color",
                    "episodes",
                    "--force-color",
                ]
            )
            == 2
        )
        assert "cannot be combined" in capsys.readouterr().err

    def test_captured_output_is_never_coloured(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """pytest's capture is not a terminal, which is the same answer a
        pipe and a redirect give — and the reason every other test in the
        suite kept passing when colour landed."""
        assert main(["--log-file", str(SIMPLE), "episodes"]) == 0

        assert "\033[" not in capsys.readouterr().out


class TestRegisteredInPmHelp:
    def test_pm_help_knows_the_command(self) -> None:
        from edumatcher.pm_help.registry import ALL_COMMANDS

        assert any(c.name == "pm-audit-replay" for c in ALL_COMMANDS)


class TestDbNamesOnlyAnIndex:
    """WP-RPL01 (H1): `--db` naming another file is exit 2, and the file is
    left exactly as it was -- not deleted and replaced by an index."""

    @staticmethod
    def _ledger(path: Path) -> None:
        import sqlite3

        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE money (amount INTEGER)")
        conn.execute("INSERT INTO money VALUES (100)")
        conn.commit()
        conn.close()

    @pytest.mark.parametrize(
        "command",
        (
            ["--rebuild", "story", "--order", "4f2c9a"],
            ["story", "--order", "4f2c9a"],
            ["index", "--rebuild"],
        ),
    )
    def test_a_foreign_database_is_refused(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], command: list[str]
    ) -> None:
        import sqlite3

        other = tmp_path / "clearing.db"
        self._ledger(other)
        argv = ["--log-file", str(SIMPLE), "--db", str(other), *command]
        assert main(argv) == 2
        assert str(other) in capsys.readouterr().err
        conn = sqlite3.connect(other)
        assert conn.execute("SELECT amount FROM money").fetchall() == [(100,)]
        conn.close()

    def test_a_text_file_is_refused_unchanged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        notes = tmp_path / "notes.txt"
        notes.write_bytes(b"hello index\n")
        argv = ["--log-file", str(SIMPLE), "--db", str(notes), "index", "--rebuild"]
        assert main(argv) == 2
        assert "not an episode index" in capsys.readouterr().err
        assert notes.read_bytes() == b"hello index\n"


class TestCliEdges:
    """WP-RPL09: C5, C12, C13 and P3."""

    def _run(
        self, capsys: pytest.CaptureFixture[str], *argv: str
    ) -> tuple[int, str, str]:
        code = main(["--log-file", str(SIMPLE), *argv])
        out = capsys.readouterr()
        return code, out.out, out.err

    def test_to_a_date_includes_that_day(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out, _err = self._run(capsys, "--to", "2026-09-08", "episodes")
        assert code == 0
        assert "order" in out
        code, out, _err = self._run(
            capsys, "--from", "2026-09-08", "--to", "2026-09-08", "stream"
        )
        assert code == 0 and out

    @pytest.mark.parametrize("command", ("episodes", "digest", "anomalies"))
    def test_an_empty_window_exits_one(
        self, capsys: pytest.CaptureFixture[str], command: str
    ) -> None:
        code, _out, err = self._run(capsys, "--to", "2026-09-07", command)
        assert code == 1
        assert "nothing to narrate in this window" in err

    def test_stats_with_no_facts_exits_one(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out, _err = self._run(capsys, "--to", "2026-09-07", "stats")
        assert code == 1
        assert "No facts in window." in out

    @pytest.mark.parametrize(
        "argv",
        (
            ["digest", "--top", "0"],
            ["digest", "--top", "-1"],
            ["--clock-skew-warn", "-1", "anomalies"],
            ["--clock-skew-warn", "nan", "anomalies"],
            ["--clock-skew-warn", "inf", "anomalies"],
        ),
    )
    def test_out_of_range_values_are_refused(self, argv: list[str]) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["--log-file", str(SIMPLE), *argv])
        assert exc.value.code == 2

    def test_the_suggested_story_reads_the_same_trail(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        db = tmp_path / "my index.db"
        argv = ["--log-file", str(HALTED), "--db", str(db)]
        assert main([*argv, "anomalies"]) == 0
        text = capsys.readouterr().out
        suggestions = [ln for ln in text.splitlines() if "-> pm-audit-replay" in ln]
        assert suggestions
        for line in suggestions:
            assert f"--log-file {HALTED}" in line
            assert f"--db '{db}'" in line
        assert main([*argv, "anomalies", "--format", "ndjson"]) == 0
        found = [json.loads(ln) for ln in capsys.readouterr().out.splitlines()]
        assert all(f"--db '{db}'" in str(f["story"]) for f in found if f["story"])

    def test_the_suggestion_keeps_a_date(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        data = tmp_path / "data"
        (data / "audit").mkdir(parents=True)
        (data / "audit" / "audit-2026-09-08.1.log").write_bytes(HALTED.read_bytes())
        argv = ["--log-file", str(data / "audit.log"), "--date", "2026-09-08"]
        assert main([*argv, "anomalies"]) == 0
        lines = [ln for ln in capsys.readouterr().out.splitlines() if "->" in ln]
        assert lines and all("--date 2026-09-08" in ln for ln in lines)

    def test_a_to_bound_stops_the_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from edumatcher.audit import query

        data = tmp_path / "data"
        (data / "audit").mkdir(parents=True)
        first = SIMPLE.read_text(encoding="utf-8")
        later = first.replace("2026-09-08T", "2026-09-09T")
        (data / "audit" / "audit-2026-09-08.1.log").write_text(first)
        (data / "audit" / "audit-2026-09-08.2.log").write_text(later + later)
        (data / "audit.log").write_text("")

        calls = {"n": 0}
        real = query.parse_line

        def counted(raw: str) -> object:
            calls["n"] += 1
            return real(raw)

        monkeypatch.setattr(query, "parse_line", counted)
        argv = ["--log-file", str(data / "audit.log")]
        assert main([*argv, "--to", "2026-09-08", "episodes"]) == 0
        first_lines = len([ln for ln in first.splitlines() if ln.strip()])
        # The first line of the later part shows the read is past the bound.
        assert calls["n"] <= first_lines + 1


class TestOnlyStoryUsesTheIndex:
    """WP-RPL03 (Q1 a): the reports read their window straight off the log
    and never build an index; ``story`` builds one when it has none (or rules
    or detection changed, or on ``--rebuild``) and answers a trail that has
    grown since from the index as it stands, saying how far it reaches. A
    rebuild per call cost 73 minutes and 50 GB on a live simulation day."""

    def _log(self, tmp_path: Path) -> Path:
        log = tmp_path / "audit.log"
        log.write_bytes(SIMPLE.read_bytes())
        return log

    @pytest.mark.parametrize(
        "command", ("stream", "episodes", "digest", "anomalies", "stats")
    )
    def test_a_report_creates_no_index(self, tmp_path: Path, command: str) -> None:
        log = self._log(tmp_path)
        db = tmp_path / "replay.db"
        argv = ["--log-file", str(log), "--db", str(db), "--from", "2026-09-08"]
        assert main([*argv, command]) == 0
        assert not db.exists()

    def test_story_answers_a_grown_trail_from_its_index(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log = self._log(tmp_path)
        db = tmp_path / "replay.db"
        argv = ["--log-file", str(log), "--db", str(db)]
        assert main([*argv, "index"]) == 0
        _mark(db)
        with reading(db) as conn:
            covered_to = describe(conn)["covered_to"]
        with log.open("ab") as handle:
            handle.write(SIMPLE.read_bytes().splitlines(keepends=True)[-1])
        capsys.readouterr()

        assert main([*argv, "story", "--order", "4f2c9a"]) == 0
        out = capsys.readouterr()
        assert out.out
        assert covered_to in out.err and "--rebuild" in out.err
        with reading(db) as conn:
            assert describe(conn)["built_at"] == _MARK

    def test_story_builds_an_index_it_does_not_have(self, tmp_path: Path) -> None:
        log = self._log(tmp_path)
        db = tmp_path / "replay.db"
        assert (
            main(
                ["--log-file", str(log), "--db", str(db), "story", "--order", "4f2c9a"]
            )
            == 0
        )
        assert db.exists()

    def test_story_rebuilds_for_other_detection_settings(self, tmp_path: Path) -> None:
        log = self._log(tmp_path)
        db = tmp_path / "replay.db"
        argv = ["--log-file", str(log), "--db", str(db)]
        assert main([*argv, "index"]) == 0
        _mark(db)
        assert main([*argv, "--strict", "story", "--order", "4f2c9a"]) == 0
        with reading(db) as conn:
            assert describe(conn)["built_at"] != _MARK

    def test_rebuild_forces_story_to_rebuild(self, tmp_path: Path) -> None:
        log = self._log(tmp_path)
        db = tmp_path / "replay.db"
        argv = ["--log-file", str(log), "--db", str(db)]
        assert main([*argv, "index"]) == 0
        _mark(db)
        assert main([*argv, "--rebuild", "story", "--order", "4f2c9a"]) == 0
        with reading(db) as conn:
            assert describe(conn)["built_at"] != _MARK

    def test_index_refreshes_a_grown_trail(self, tmp_path: Path) -> None:
        log = self._log(tmp_path)
        db = tmp_path / "replay.db"
        argv = ["--log-file", str(log), "--db", str(db), "index"]
        assert main(argv) == 0
        _mark(db)
        with log.open("ab") as handle:
            handle.write(ARCHIVED.read_bytes())
        assert main(argv) == 0
        with reading(db) as conn:
            assert describe(conn)["built_at"] != _MARK

    def test_a_window_is_the_lines_of_the_window(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """C4: from the index a window was the episodes that *opened* in it,
        reconstructed from the whole trail; off the log it was the window's
        lines. One path now: the lines, so an order whose submission is
        before ``--from`` is there by its tail, with or without an index."""
        db = tmp_path / "replay.db"
        assert main(["--log-file", str(SIMPLE), "--db", str(db), "index"]) == 0
        capsys.readouterr()
        # Between order 4f2c9a's acceptance (.121) and its fill (.122).
        argv = ["--log-file", str(SIMPLE), "--db", str(db)]
        assert main([*argv, "--from", "2026-09-08T09:31:02.121", "episodes"]) == 0
        assert "4f2c9a" in capsys.readouterr().out

    @pytest.mark.parametrize("command", ("stream", "episodes", "anomalies", "stats"))
    def test_rebuild_is_refused_where_there_is_no_index(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
    ) -> None:
        argv = ["--log-file", str(SIMPLE), "--db", str(tmp_path / "r.db")]
        assert main([*argv, "--rebuild", command]) == 2
        assert "--rebuild" in capsys.readouterr().err

    def test_no_index_is_gone(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["--log-file", str(SIMPLE), "--no-index", "stream"])
        assert exc.value.code == 2


def test_a_part_that_ends_before_the_window_is_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WP-RPL03 follow-up: skipping a closed part line by line cost 0.2 s per
    256 MB part, 14 s of a live day's ``--last 15m``. A closed part whose last
    line is before ``--from`` is not opened at all."""
    from edumatcher.audit import query

    data = tmp_path / "data"
    (data / "audit").mkdir(parents=True)
    early = SIMPLE.read_text(encoding="utf-8")
    later = early.replace("2026-09-08T", "2026-09-09T")
    (data / "audit" / "audit-2026-09-08.1.log").write_text(early)
    (data / "audit" / "audit-2026-09-08.2.log").write_text(later)
    (data / "audit.log").write_text(later)

    opened: list[str] = []
    real = query.open_log_file

    def recorded(path: Path) -> object:
        opened.append(path.name)
        return real(path)

    monkeypatch.setattr(query, "open_log_file", recorded)
    argv = ["--log-file", str(data / "audit.log"), "--from", "2026-09-09"]
    assert main([*argv, "episodes"]) == 0
    assert opened == ["audit-2026-09-08.2.log", "audit.log"]
