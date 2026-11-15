"""The fast line splitter shared by the re-run and sim-forensics (WP-AUD07)."""

from __future__ import annotations

from pathlib import Path

from edumatcher.audit.rawlines import lines

_TS = "2026-07-08T09:30:00.123+00:00"


def _one(tmp_path: Path, raw: str) -> tuple[str, int | None, int | None]:
    log = tmp_path / "audit.log"
    log.write_text(raw + "\n", encoding="utf-8")
    (line,) = list(lines([log]))
    return line.chain, line.seq, line.eseq


def test_a_line_without_a_chain_has_an_empty_chain(tmp_path: Path) -> None:
    """C11: rfind's -1 used to turn into meta[5:], a garbage chain."""
    assert _one(tmp_path, f"[{_TS}] [order.new] [seq=1 eseq=2 msg=M] {{}}") == (
        "",
        1,
        2,
    )


def test_a_line_with_a_chain_keeps_it(tmp_path: Path) -> None:
    raw = f"[{_TS}] [order.new] [seq=1 eseq=2 msg=M cause=C chain=CH] {{}}"
    assert _one(tmp_path, raw) == ("CH", 1, 2)
