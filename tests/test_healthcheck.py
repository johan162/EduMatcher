from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import zmq

from edumatcher.healthcheck import (
    answer_health_ping,
    find_process_pids,
    format_bytes,
    ping_health_endpoint,
    read_last_line,
    run_with_timeout,
)
from edumatcher.messaging.bus import get_context, make_replier


def _fake_pgrep(
    monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str
) -> list[list[str]]:
    calls: list[list[str]] = []

    def _run(argv: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout)

    monkeypatch.setattr("edumatcher.healthcheck.subprocess.run", _run)
    return calls


# -- find_process_pids --------------------------------------------------------


def test_find_process_pids_matches_the_program_as_a_whole_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _fake_pgrep(monkeypatch, 0, "42\n")

    assert find_process_pids("pm-stats") == [42]
    assert calls == [["pgrep", "-f", r"(^|/)pm-stats([[:space:]]|$)"]]


def test_find_process_pids_excludes_itself_dedups_and_sorts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_pgrep(monkeypatch, 0, f"30\n{os.getpid()}\n10\n30\nnot-a-pid\n")

    assert find_process_pids("pm-audit") == [10, 30]


def test_find_process_pids_treats_no_match_as_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_pgrep(monkeypatch, 1, "")

    assert find_process_pids("pm-clearing") == []


def test_find_process_pids_raises_on_pgrep_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_pgrep(monkeypatch, 3, "")

    with pytest.raises(OSError, match="exit code 3"):
        find_process_pids("pm-clearing")


# -- ping / answer ------------------------------------------------------------


def test_ping_is_answered_with_a_utc_timestamp() -> None:
    """The client and server halves, against each other over a real socket."""
    addr = "inproc://healthcheck-ping-test"
    sock = make_replier(addr)
    try:
        responder = threading.Thread(
            target=answer_health_ping,
            args=(sock, logging.getLogger("test")),
            daemon=True,
        )
        responder.start()
        healthy, detail = ping_health_endpoint(addr, timeout_ms=2000)
        responder.join(timeout=1)
    finally:
        sock.close(0)

    assert healthy is True
    stamp = detail.removeprefix("replied at ")
    assert datetime.fromisoformat(stamp).tzinfo is not None


def test_ping_times_out_when_nothing_answers() -> None:
    addr = "inproc://healthcheck-silent-test"
    sock = make_replier(addr)  # bound, but nobody ever answers
    try:
        healthy, detail = ping_health_endpoint(addr, timeout_ms=200)
    finally:
        sock.close(0)

    assert healthy is False
    assert detail == "no reply within 200ms"


def test_answer_logs_rather_than_raises_on_socket_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A REP socket with no pending request: send() is out of order (EFSM).
    sock = get_context().socket(zmq.REP)
    sock.setsockopt(zmq.RCVTIMEO, 50)
    sock.bind("inproc://healthcheck-error-test")
    try:
        with caplog.at_level(logging.WARNING):
            answer_health_ping(sock, logging.getLogger("test"))
    finally:
        sock.close(0)

    assert "failed to answer health ping" in caplog.text


# -- run_with_timeout ---------------------------------------------------------


def test_run_with_timeout_returns_the_result() -> None:
    assert run_with_timeout(lambda: (True, "ok"), timeout_sec=5) == (True, "ok")


def test_run_with_timeout_raises_without_waiting_for_the_worker() -> None:
    release = threading.Event()
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError, match="did not finish within 0s"):
            run_with_timeout(lambda: release.wait(timeout=5), timeout_sec=0.1)
        assert time.monotonic() - started < 2
    finally:
        release.set()  # let the abandoned worker finish so it doesn't outlive the test


def test_run_with_timeout_reraises_the_workers_exception() -> None:
    def _boom() -> None:
        raise ValueError("bad check")

    with pytest.raises(ValueError, match="bad check"):
        run_with_timeout(_boom, timeout_sec=5)


# -- read_last_line -----------------------------------------------------------


def test_read_last_line_skips_trailing_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "log.jsonl"
    path.write_text("first\nsecond\n\n  \n")

    assert read_last_line(path) == "second"


def test_read_last_line_of_an_empty_file_is_none(tmp_path: Path) -> None:
    path = tmp_path / "empty.jsonl"
    path.write_text("")

    assert read_last_line(path) is None


def test_read_last_line_reads_only_the_tail(tmp_path: Path) -> None:
    path = tmp_path / "big.jsonl"
    path.write_text("x" * 1000 + "\nlast\n")

    assert read_last_line(path, max_bytes=16) == "last"


# -- format_bytes -------------------------------------------------------------


@pytest.mark.parametrize(
    "size, expected",
    [
        (0, "0B"),
        (1023, "1023B"),
        (1024, "1.0KB"),
        (1536 * 1024, "1.5MB"),
        (5 * 1024**4, "5120.0GB"),
    ],
)
def test_format_bytes(size: int, expected: str) -> None:
    assert format_bytes(size) == expected
