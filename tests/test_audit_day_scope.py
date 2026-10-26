"""Reader scope: live trail by default, ``--date`` for a day, archive paths (Z5)."""

from __future__ import annotations

import json
import time
from datetime import timezone
from pathlib import Path

import pytest
from compression import zstd

from edumatcher.audit.archive import archive_day
from edumatcher.audit.cli import main as cli_main
from edumatcher.audit.query import discover_day_files, discover_log_files, iter_entries
from edumatcher.audit.replay import index as episode_index
from edumatcher.audit.replay.cli import main as replay_main
from tests.conftest import REPLAY_FIXTURES

COMBO = REPLAY_FIXTURES / "04_quote_oco_combo.log"
DAY = "2026-09-08"  # the day the fixture was recorded on
NEXT = "2026-09-09"


def _line(day: str, n: int, topic: str = "order.new") -> str:
    return f'[{day}T10:00:{n:02d}.000+00:00] [{topic}] {{"order_id": "{day}-{n}"}}'


@pytest.fixture(autouse=True)
def _utc_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("edumatcher.audit.cli.session_timezone", lambda: timezone.utc)
    monkeypatch.setattr(
        "edumatcher.audit.replay.cli.session_timezone", lambda: timezone.utc
    )


def _write(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{x}\n" for x in lines), encoding="utf-8")
    return path


def _cli(monkeypatch: pytest.MonkeyPatch, root: Path, *argv: str) -> int:
    monkeypatch.setattr(
        "sys.argv", ["pm-audit-cli", "--log-file", str(root / "audit.log"), *argv]
    )
    try:
        cli_main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


@pytest.fixture()
def trail(tmp_path: Path) -> Path:
    """Yesterday as two parts, today in audit.log."""
    _write(tmp_path / "audit" / f"audit-{DAY}.1.log", [_line(DAY, 1), _line(DAY, 2)])
    _write(tmp_path / "audit" / f"audit-{DAY}.2.log", [_line(DAY, 3)])
    _write(tmp_path / "audit.log", [_line(NEXT, 1)])
    return tmp_path


def _order_ids(out: str) -> list[str]:
    return [r["order_id"] for r in json.loads(out)]


class TestDiscoverDayFiles:
    def test_parts_then_the_active_file_when_it_holds_the_day(
        self, trail: Path
    ) -> None:
        parts = [trail / "audit" / f"audit-{DAY}.{n}.log" for n in (1, 2)]
        assert discover_day_files(trail / "audit.log", DAY, timezone.utc) == parts
        assert discover_day_files(trail / "audit.log", NEXT, timezone.utc) == [
            trail / "audit.log"
        ]

    def test_the_archive_replaces_the_parts(self, trail: Path) -> None:
        archive_day(trail / "audit", DAY, today=NEXT)
        archive = trail / "audit" / f"audit-{DAY}.log.zst"
        assert discover_day_files(trail / "audit.log", DAY, timezone.utc) == [archive]

    def test_an_unknown_day_has_no_files(self, trail: Path) -> None:
        assert discover_day_files(trail / "audit.log", "2020-01-01", timezone.utc) == []


class TestExplicitFile:
    def test_an_archive_path_is_read_alone(self, trail: Path) -> None:
        archive_day(trail / "audit", DAY, today=NEXT)
        archive = trail / "audit" / f"audit-{DAY}.log.zst"
        assert discover_log_files(archive) == [archive]
        assert len(list(iter_entries(discover_log_files(archive)))) == 3

    def test_a_part_path_is_read_alone(self, trail: Path) -> None:
        part = trail / "audit" / f"audit-{DAY}.2.log"
        assert discover_log_files(part) == [part]

    def test_date_with_an_archive_path_is_refused(
        self,
        monkeypatch: pytest.MonkeyPatch,
        trail: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        archive_day(trail / "audit", DAY, today=NEXT)
        archive = trail / "audit" / f"audit-{DAY}.log.zst"
        monkeypatch.setattr(
            "sys.argv",
            ["pm-audit-cli", "--log-file", str(archive), "events", "--date", DAY],
        )
        with pytest.raises(SystemExit) as exc:
            cli_main()
        assert exc.value.code == 2
        assert "archive --log-file" in capsys.readouterr().err
        assert (
            replay_main(
                ["--log-file", str(archive), "--date", DAY, "--no-index", "stats"]
            )
            == 2
        )


class TestAuditCliScope:
    def test_the_default_is_the_live_trail_only(
        self,
        monkeypatch: pytest.MonkeyPatch,
        trail: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        archive_day(trail / "audit", DAY, today=NEXT)
        assert _cli(monkeypatch, trail, "--format", "json", "events") == 0
        assert _order_ids(capsys.readouterr().out) == [f"{NEXT}-1"]

    def test_date_reads_the_parts_before_archiving(
        self,
        monkeypatch: pytest.MonkeyPatch,
        trail: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert (
            _cli(monkeypatch, trail, "--format", "json", "events", "--date", DAY) == 0
        )
        assert _order_ids(capsys.readouterr().out) == [f"{DAY}-{n}" for n in (1, 2, 3)]

    def test_date_reads_the_archive_after_archiving(
        self,
        monkeypatch: pytest.MonkeyPatch,
        trail: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        archive_day(trail / "audit", DAY, today=NEXT)
        assert (
            _cli(monkeypatch, trail, "--format", "json", "events", "--date", DAY) == 0
        )
        assert _order_ids(capsys.readouterr().out) == [f"{DAY}-{n}" for n in (1, 2, 3)]

    def test_date_is_the_trading_day_not_a_utc_window(
        self,
        monkeypatch: pytest.MonkeyPatch,
        trail: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A line stamped the previous UTC evening can belong to the day's file."""
        _write(
            trail / "audit" / f"audit-{DAY}.3.log",
            [f'[{DAY}T23:30:00.000+00:00] [order.new] {{"order_id": "late"}}'],
        )
        assert (
            _cli(monkeypatch, trail, "--format", "json", "events", "--date", DAY) == 0
        )
        assert "late" in _order_ids(capsys.readouterr().out)

    def test_an_unknown_day_is_an_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        trail: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        assert _cli(monkeypatch, trail, "events", "--date", "2020-01-01") == 1
        assert "No audit data for 2020-01-01" in capsys.readouterr().err

    def test_date_and_follow_are_mutually_exclusive(
        self, monkeypatch: pytest.MonkeyPatch, trail: Path
    ) -> None:
        assert _cli(monkeypatch, trail, "events", "--date", DAY, "--follow") == 2

    def test_an_archive_path_as_log_file_reads_just_that_day(
        self,
        monkeypatch: pytest.MonkeyPatch,
        trail: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        archive_day(trail / "audit", DAY, today=NEXT)
        archive = trail / "audit" / f"audit-{DAY}.log.zst"
        monkeypatch.setattr(
            "sys.argv",
            ["pm-audit-cli", "--log-file", str(archive), "--format", "json", "events"],
        )
        cli_main()
        assert _order_ids(capsys.readouterr().out) == [f"{DAY}-{n}" for n in (1, 2, 3)]


class TestFollowAcrossRollover:
    def test_every_line_is_printed_once(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        log = _write(tmp_path / "audit.log", [_line(DAY, 1), _line(DAY, 2)])
        calls = {"n": 0}

        def sleep(_s: float) -> None:
            calls["n"] += 1
            if calls["n"] == 1:  # lines arrive, then the day closes
                with log.open("a", encoding="utf-8") as fh:
                    fh.write(_line(DAY, 3) + "\n")
                log.rename(tmp_path / "audit.log.tmp")
                (tmp_path / "audit").mkdir()
                (tmp_path / "audit.log.tmp").rename(
                    tmp_path / "audit" / f"audit-{DAY}.1.log"
                )
                _write(log, [_line(NEXT, 1)])
            elif calls["n"] == 2:  # and a line after the rollover
                with log.open("a", encoding="utf-8") as fh:
                    fh.write(_line(NEXT, 2) + "\n")
            else:
                raise KeyboardInterrupt

        monkeypatch.setattr(time, "sleep", sleep)
        assert (
            _cli(monkeypatch, tmp_path, "--format", "json", "events", "--follow") == 0
        )
        seen: list[str] = []
        decoder = json.JSONDecoder()
        text = capsys.readouterr().out.strip()
        i = 0
        while i < len(text):
            obj, i = decoder.raw_decode(text, i)
            seen += [r["order_id"] for r in obj]
            while i < len(text) and text[i].isspace():
                i += 1
        assert seen == [f"{DAY}-1", f"{DAY}-2", f"{DAY}-3", f"{NEXT}-1", f"{NEXT}-2"]


class TestHealthStats:
    def test_parts_and_archives_with_the_ratio(self, trail: Path) -> None:
        from edumatcher.audit.cli import _collect_log_stats

        before = _collect_log_stats(trail / "audit.log", None, None)
        assert (before["parts"], before["archives"]) == (2, 0)
        archive_day(trail / "audit", DAY, today=NEXT)
        after = _collect_log_stats(trail / "audit.log", None, None)
        assert (after["parts"], after["archives"]) == (0, 1)
        assert after["archives_content_bytes"] == before["parts_bytes"]
        assert after["archives_bytes"] > 0


def _split_fixture(root: Path) -> Path:
    """The combo fixture as day D's two parts, plus an empty active file."""
    lines = COMBO.read_text(encoding="utf-8").splitlines()
    half = len(lines) // 2
    _write(root / "audit" / f"audit-{DAY}.1.log", lines[:half])
    _write(root / "audit" / f"audit-{DAY}.2.log", lines[half:])
    _write(root / "audit.log", [])
    return root / "audit.log"


class TestReplayScope:
    def _run(
        self, log: Path, db: Path, *extra: str, capsys: pytest.CaptureFixture[str]
    ) -> str:
        capsys.readouterr()
        argv = ["--log-file", str(log), "--db", str(db), *extra, "episodes"]
        assert replay_main(argv) == 0
        return capsys.readouterr().out

    def test_the_default_reads_the_live_trail_not_an_archive(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log = _split_fixture(tmp_path)
        archive_day(tmp_path / "audit", DAY, today=NEXT)
        capsys.readouterr()
        assert replay_main(["--log-file", str(log), "--no-index", "episodes"]) == 0
        # Only the header and its rule: the archived day is not in the live trail.
        assert len(capsys.readouterr().out.strip().splitlines()) == 2

    def test_date_replays_an_archive_like_the_plain_fixture(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log = _split_fixture(tmp_path)
        plain = self._run(COMBO, tmp_path / "plain.db", capsys=capsys)
        from_parts = self._run(log, tmp_path / "a.db", "--date", DAY, capsys=capsys)
        archive_day(tmp_path / "audit", DAY, today=NEXT)
        from_archive = self._run(log, tmp_path / "b.db", "--date", DAY, capsys=capsys)
        assert plain
        assert from_parts == plain
        assert from_archive == plain

    def test_the_index_rebuilds_after_archiving_and_finds_the_same_episodes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log = _split_fixture(tmp_path)
        db = tmp_path / "replay.db"
        before = self._run(log, db, "--date", DAY, capsys=capsys)
        parts = discover_day_files(log, DAY, timezone.utc)
        with episode_index.reading(db) as conn:
            assert episode_index.is_current(conn, parts)

        archive_day(tmp_path / "audit", DAY, today=NEXT)
        after = self._run(log, db, "--date", DAY, capsys=capsys)

        archive = discover_day_files(log, DAY, timezone.utc)
        assert archive != parts
        with episode_index.reading(db) as conn:
            assert not episode_index.is_current(conn, parts)
            assert episode_index.is_current(conn, archive)
        assert after == before

    def test_an_archive_path_replays_by_itself(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _split_fixture(tmp_path)
        archive_day(tmp_path / "audit", DAY, today=NEXT)
        archive = tmp_path / "audit" / f"audit-{DAY}.log.zst"
        out = self._run(archive, tmp_path / "c.db", capsys=capsys)
        assert out == self._run(COMBO, tmp_path / "d.db", capsys=capsys)


def test_the_archive_really_is_zstd(trail: Path) -> None:
    archive_day(trail / "audit", DAY, today=NEXT)
    with zstd.open(trail / "audit" / f"audit-{DAY}.log.zst", "rt") as fh:
        assert fh.read().count("\n") == 3
