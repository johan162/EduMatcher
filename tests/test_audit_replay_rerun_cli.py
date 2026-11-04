"""``pm-audit-replay rerun``: the audit's commands through a fresh engine (A4)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from edumatcher.audit.replay.cli import main
from edumatcher.audit.writer import recorder_start_line
from tests.test_sim_forensics_rerun import edit, record


def run(data: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(["--log-file", str(data / "audit.log"), "rerun"])
    return code, capsys.readouterr().out


def test_a_clean_run_exits_zero_and_says_what_it_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run(record(tmp_path / "data"), capsys)
    assert code == 0
    assert "8 commands" in out
    assert "hidden inputs: 0" in out
    assert "outputs: 0 differing episodes" in out
    assert "final book: 0 differences" in out


def test_a_silent_gateway_expiry_counts_as_a_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run(record(tmp_path / "data", silent="TRADER02"), capsys)
    assert code == 0
    assert "9 commands" in out
    assert "hidden inputs: 0" in out


def test_a_difference_exits_one_and_names_the_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = record(tmp_path / "data")
    edit(data, "[order.ack.TRADER02]", lambda ln: [])
    code, out = run(data, capsys)
    assert code == 1
    assert "hidden inputs: 0" not in out or "outputs: 0" not in out


def test_a_trail_without_the_engine_start_is_unavailable_not_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = record(tmp_path / "data")
    edit(data, "[system.startup]", lambda ln: [])
    code = main(["--log-file", str(data / "audit.log"), "rerun"])
    assert code == 3
    assert "cannot re-run" in capsys.readouterr().err


def test_a_missing_book_file_is_said_not_passed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = record(tmp_path / "data")
    (data / "gtc_orders.json").unlink()
    code, out = run(data, capsys)
    assert code == 0
    assert "final book: not checked" in out


def stamp_eseq(data: Path) -> None:
    """Number every line as the engine's socket-wide sequence does (``eseq``,
    from 1 at each engine start); the test recorder writes none."""
    path = data / "audit.log"
    out, n = [], 0
    for ln in path.read_text().splitlines(keepends=True):
        n = 1 if "[system.startup]" in ln else n + 1
        out.append(re.sub(r"\[seq=(\d+) ", rf"[seq=\1 eseq={n} ", ln, count=1))
    path.write_text("".join(out))


def edit_body(data: Path, find: str, change: Any, *, last: bool = False) -> None:
    """Change the JSON payload of the first (or *last*) line containing *find*."""
    path = data / "audit.log"
    lines = path.read_text().splitlines(keepends=True)
    hits = [k for k, ln in enumerate(lines) if find in ln]
    i = hits[-1] if last else hits[0]
    head, _, body = lines[i].partition("] {")
    payload = json.loads("{" + body)
    change(payload)
    lines[i] = f"{head}] {json.dumps(payload)}\n"
    path.write_text("".join(lines))


class TestRestarts:
    """An engine restart in the trail is re-run as one: the re-run persists its
    book as the live engine did on the way down and starts the next run from
    it (it was "the engine restarted during the run": nothing re-run)."""

    def test_a_restart_is_rerun_through_a_restored_engine(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code, out = run(record(tmp_path / "data", restart=True), capsys)
        assert code == 0, out
        assert "outputs: 0 differing episodes" in out
        assert "1 engine restart re-run" in out
        assert "final book: 0 differences" in out

    def test_a_restored_book_unlike_the_live_one_is_a_difference(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """As after a kill -9: the live engine came back from an older
        checkpoint than the book it had when it stopped."""
        data = record(tmp_path / "data", restart=True)

        def lose_one(p: dict[str, Any]) -> None:
            p["asks"] = p["asks"][1:]

        edit_body(data, '"reason": "STARTUP"', lose_one, last=True)
        code, out = run(data, capsys)
        assert code == 1
        assert "system.book_checkpoint.AAPL.asks" in out

    def test_a_first_run_that_began_from_persisted_state_is_unavailable(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        data = record(tmp_path / "data")
        edit_body(
            data,
            "[system.startup_recovery]",
            lambda p: p.update(restored_orders=3),
        )
        code = main(["--log-file", str(data / "audit.log"), "rerun"])
        assert code == 3
        assert "3 orders restored" in capsys.readouterr().err


class TestAnIncompleteTrail:
    """The re-run's premise is that the trail is the engine's whole input and
    output; where it provably is not, it says so instead of a verdict."""

    def test_a_trail_with_its_engine_sequence_whole_reruns_clean(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        data = record(tmp_path / "data", restart=True)
        stamp_eseq(data)
        code, out = run(data, capsys)
        assert code == 0, out

    def test_a_missing_engine_message_is_unavailable(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        data = record(tmp_path / "data")
        stamp_eseq(data)
        edit(data, "[order.ack.TRADER02]", lambda ln: [])
        code = main(["--log-file", str(data / "audit.log"), "rerun"])
        assert code == 3
        err = capsys.readouterr().err
        assert "engine-wide sequence jumps" in err

    def test_a_recorder_restart_while_the_engine_ran_is_unavailable(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        data = record(tmp_path / "data")
        edit(
            data, "[order.ack.TRADER02]", lambda ln: [recorder_start_line() + "\n", ln]
        )
        code = main(["--log-file", str(data / "audit.log"), "rerun"])
        assert code == 3
        assert "pm-audit restarted while the engine ran" in capsys.readouterr().err

    def test_a_recorder_restart_the_sequence_proves_lossless_is_whole(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        data = record(tmp_path / "data")
        stamp_eseq(data)
        edit(
            data, "[order.ack.TRADER02]", lambda ln: [recorder_start_line() + "\n", ln]
        )
        code, out = run(data, capsys)
        assert code == 0, out

    def test_a_recorder_restarted_with_the_engine_is_whole(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The container restart: the old engine's last word (system.eod) is
        in, then pm-audit's start, then the new engine's."""
        data = record(tmp_path / "data", restart=True)
        lines = (data / "audit.log").read_text().splitlines(keepends=True)
        second = [k for k, ln in enumerate(lines) if "[system.startup]" in ln][1]
        lines.insert(second, recorder_start_line() + "\n")
        lines.insert(0, recorder_start_line() + "\n")
        (data / "audit.log").write_text("".join(lines))
        code, out = run(data, capsys)
        assert code == 0, out


def test_a_run_that_is_not_the_first_start_of_its_data_dir_reruns_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The engine's run sequence persists across starts (it prefixes every trade
    id and rides on every trade), so the ninth start of a data dir is the
    ordinary case, not the first.  The re-run takes it from `system.startup`."""
    code, out = run(record(tmp_path / "data", run_seq=9), capsys)
    assert code == 0, out
    assert "outputs: 0 differing episodes" in out
