"""The evidence manifest: ``audit/manifest.jsonl`` and ``pm-audit-cli verify`` (A1)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from compression import zstd

from edumatcher.audit.archive import apply_retention, archive_day
from edumatcher.audit.cli import main as cli_main
from edumatcher.audit.manifest import MANIFEST_NAME, read_entries, verify

D1, D2, D3 = "2026-10-24", "2026-10-25", "2026-10-26"
TODAY = "2026-10-27"


def _make_day(audit_dir: Path, day: str, parts: int = 2) -> None:
    audit_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, parts + 1):
        text = "".join(
            f'[{day}T10:00:{n % 60:02d}.000+00:00] [order.new] {{"id": "{i}-{n}"}}\n'
            for n in range(20)
        )
        (audit_dir / f"audit-{day}.{i}.log").write_text(text)


def _archived(audit_dir: Path, *days: str) -> None:
    for day in days:
        _make_day(audit_dir, day)
        archive_day(audit_dir, day, today=TODAY)


def _rewrite_archive(audit_dir: Path, day: str, old: bytes, new: bytes) -> None:
    path = audit_dir / f"audit-{day}.log.zst"
    with zstd.open(path, "rb") as fh:
        data = fh.read()
    assert old in data
    with zstd.open(path, "wb") as fh:
        fh.write(data.replace(old, new, 1))


class TestWrittenByArchiveDay:
    def test_each_archived_day_appends_one_chained_entry(self, tmp_path: Path) -> None:
        _archived(tmp_path, D1, D2)
        entries = read_entries(tmp_path)
        assert [e["day"] for e in entries] == [D1, D2]
        assert entries[0]["prev"] == "0" * 64
        assert entries[0]["lines"] == 40
        assert re.fullmatch(r"[0-9a-f]{64}", entries[0]["sha256"])
        assert verify(tmp_path) == []

    def test_a_crash_after_the_rename_still_gets_a_manifest_entry(
        self, tmp_path: Path
    ) -> None:
        _make_day(tmp_path, D1)

        def crash(step: str) -> None:
            if step == "renamed":
                raise KeyboardInterrupt

        with pytest.raises(KeyboardInterrupt):
            archive_day(tmp_path, D1, today=TODAY, on_step=crash)
        archive_day(tmp_path, D1, today=TODAY)
        assert [e["day"] for e in read_entries(tmp_path)] == [D1]
        assert verify(tmp_path) == []

    def test_a_reopened_day_appends_a_superseding_entry(self, tmp_path: Path) -> None:
        _archived(tmp_path, D1)
        (tmp_path / f"audit-{D1}.1.log").write_text(
            f'[{D1}T23:59:59.000+00:00] [order.new] {{"id": "late"}}\n'
        )
        archive_day(tmp_path, D1, today=TODAY)
        entries = read_entries(tmp_path)
        assert [e["day"] for e in entries] == [D1, D1]
        assert entries[1]["lines"] == 41
        assert verify(tmp_path) == []


class TestVerify:
    def test_a_changed_byte_in_an_archive_names_the_day(self, tmp_path: Path) -> None:
        _archived(tmp_path, D1, D2)
        _rewrite_archive(tmp_path, D1, b'"1-3"', b'"1-9"')
        problems = verify(tmp_path)
        assert [p.day for p in problems] == [D1]
        assert "content" in problems[0].message

    def test_an_edited_manifest_entry_breaks_the_chain_after_it(
        self, tmp_path: Path
    ) -> None:
        _archived(tmp_path, D1, D2, D3)
        path = tmp_path / MANIFEST_NAME
        lines = path.read_text().splitlines()
        first = json.loads(lines[0])
        first["lines"] += 1
        lines[0] = json.dumps(first, sort_keys=True)
        path.write_text("\n".join(lines) + "\n")
        messages = [p.message for p in verify(tmp_path)]
        assert any("chain" in m for m in messages)

    def test_a_removed_middle_entry_breaks_the_chain(self, tmp_path: Path) -> None:
        _archived(tmp_path, D1, D2, D3)
        path = tmp_path / MANIFEST_NAME
        lines = path.read_text().splitlines()
        del lines[1]
        path.write_text("\n".join(lines) + "\n")
        assert any("chain" in p.message for p in verify(tmp_path))

    def test_an_archive_with_no_entry_is_reported(self, tmp_path: Path) -> None:
        _archived(tmp_path, D1, D2)
        path = tmp_path / MANIFEST_NAME
        path.write_text(path.read_text().splitlines()[0] + "\n")
        problems = verify(tmp_path)
        assert [p.day for p in problems] == [D2]
        assert "no manifest entry" in problems[0].message

    def test_a_missing_archive_is_reported_unless_retired(self, tmp_path: Path) -> None:
        _archived(tmp_path, D1)
        (tmp_path / f"audit-{D1}.log.zst").unlink()
        problems = verify(tmp_path)
        assert [p.day for p in problems] == [D1]
        assert "missing" in problems[0].message

    def test_retention_leaves_a_verifiable_chain(self, tmp_path: Path) -> None:
        _archived(tmp_path, D1, D2)
        removed = apply_retention(tmp_path, 2, TODAY)
        assert [p.name for p in removed] == [f"audit-{D1}.log.zst"]
        kinds = [e["kind"] for e in read_entries(tmp_path)]
        assert kinds == ["day", "day", "retired"]
        assert verify(tmp_path) == []

    def test_a_torn_final_line_is_reported(self, tmp_path: Path) -> None:
        _archived(tmp_path, D1)
        with (tmp_path / MANIFEST_NAME).open("a") as fh:
            fh.write('{"kind": "day", "da')
        assert verify(tmp_path)

    def test_no_manifest_and_no_archives_is_clean(self, tmp_path: Path) -> None:
        assert verify(tmp_path) == []


class TestCli:
    def _run(
        self, tmp_path: Path, *args: str, capsys: pytest.CaptureFixture[str]
    ) -> tuple[int, str]:
        log = tmp_path / "audit.log"
        with pytest.raises(SystemExit) as exc:
            import sys

            old = sys.argv
            sys.argv = ["pm-audit-cli", "--log-file", str(log), "verify", *args]
            try:
                cli_main()
            finally:
                sys.argv = old
        return int(exc.value.code or 0), capsys.readouterr().out

    def test_clean_chain_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _archived(tmp_path / "audit", D1, D2)
        code, out = self._run(tmp_path, capsys=capsys)
        assert code == 0
        assert "2 day(s)" in out

    def test_tamper_exits_one_and_names_the_day(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _archived(tmp_path / "audit", D1)
        _rewrite_archive(tmp_path / "audit", D1, b'"1-3"', b'"1-9"')
        code, out = self._run(tmp_path, capsys=capsys)
        assert code == 1
        assert D1 in out

    def test_date_restricts_the_check(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _archived(tmp_path / "audit", D1, D2)
        _rewrite_archive(tmp_path / "audit", D1, b'"1-3"', b'"1-9"')
        code, _ = self._run(tmp_path, "--date", D2, capsys=capsys)
        assert code == 0
