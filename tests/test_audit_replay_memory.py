"""WP-RPL04: the reports hold one episode at a time, and pass 1 forgets what
has been answered.

Measured before the change on one simulation part (374 707 lines):
``anomalies`` peaked at 1.62 GB because every report built a list of every
episode in its window with every payload, and pass 1 kept every cancel and
amend request of an enveloped trail (+35 MB a part). Under decision Q2 (a)
``anomalies``, ``digest`` and ``stats`` keep findings, a top-N heap or
counters, and ``episodes`` one row per episode; ``stream`` and ``story``
still hold their window.
"""

from __future__ import annotations

import json
import tracemalloc
from pathlib import Path

import pytest

from edumatcher.audit.query import iter_entries
from edumatcher.audit.replay.cli import main
from edumatcher.audit.replay.episodes import assemble
from edumatcher.audit.replay.pipeline import reconstruct
from tests.conftest import REPLAY_FIXTURES


def trail(path: Path, orders: int) -> Path:
    """*orders* healthy orders, each submitted, accepted, asked to be
    cancelled and cancelled, every line enveloped as the engine writes it."""
    lines = []
    n = 0
    #: Per topic, as the engine numbers them: one global counter would be a
    #: SEQ_GAP error on every line.
    seqs: dict[str, int] = {}

    def line(topic: str, payload: dict[str, object], cause: str = "") -> str:
        nonlocal n
        n += 1
        ms = n
        stamp = f"2026-09-08T09:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}+00:00"
        caused = f" cause=M{cause}" if cause else ""
        chain = cause or f"{n:08d}"  # an effect is in its cause's chain
        seqs[topic] = seq = seqs.get(topic, 0) + 1
        lines.append(
            f"[{stamp}] [{topic}] [seq={seq} msg=M{n:08d}{caused} chain=M{chain}] "
            f"{json.dumps(payload)}\n"
        )
        return f"{n:08d}"

    for i in range(orders):
        oid = f"{i:032x}"
        new = line(
            "order.new",
            {
                "id": oid,
                "symbol": "AAPL",
                "side": "BUY",
                "order_type": "LIMIT",
                "tif": "DAY",
                "quantity": 10,
                "remaining_qty": 10,
                "gateway_id": "TRADER01",
                "tick_decimals": 2,
                "price_ticks": 7500,
                "status": "NEW",
            },
        )
        line(
            "order.ack.TRADER01",
            {
                "order_id": oid,
                "accepted": True,
                "symbol": "AAPL",
                "gateway_id": "TRADER01",
            },
            new,
        )
        cancel = line("order.cancel", {"order_id": oid, "gateway_id": "TRADER01"})
        line(
            "order.cancelled.TRADER01",
            {"order_id": oid, "symbol": "AAPL", "remaining_qty": 10, "cum_qty": 0},
            cancel,
        )
    path.write_text("".join(lines))
    return path


def peak(argv: list[str], capsys: pytest.CaptureFixture[str]) -> int:
    tracemalloc.start()
    try:
        assert main(argv) == 0
        return tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
        capsys.readouterr()


@pytest.mark.parametrize(
    "report",
    (["anomalies", "--severity", "error"], ["digest", "--top", "5"], ["stats"]),
    ids=lambda r: r[0],
)
def test_a_report_does_not_grow_with_its_window(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], report: list[str]
) -> None:
    small = trail(tmp_path / "small.log", 1500)
    large = trail(tmp_path / "large.log", 3000)
    common = ["--reorder-window", "200"]
    first = peak(["--log-file", str(small), *common, *report], capsys)
    second = peak(["--log-file", str(large), *common, *report], capsys)
    assert second < first * 1.3, (first, second)


def test_the_episodes_table_holds_a_row_not_an_episode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    small = trail(tmp_path / "small.log", 1500)
    large = trail(tmp_path / "large.log", 3000)
    common = ["--reorder-window", "200", "episodes"]
    first = peak(["--log-file", str(small), *common], capsys)
    second = peak(["--log-file", str(large), *common], capsys)
    # 1 500 more episodes. Measured 2026-11-22: about 9.5 KB per episode
    # when the report held the episodes (four small facts each here; a real
    # trail's payloads are larger), about 2.4 KB per row -- the row, its cells
    # and the table text -- once it held rows.
    assert (second - first) / 1500 < 3000, (first, second)


@pytest.mark.parametrize(
    "log", sorted(REPLAY_FIXTURES.glob("*.log")), ids=lambda p: p.stem
)
@pytest.mark.parametrize(
    "report",
    (
        ["anomalies"],
        ["anomalies", "--format", "ndjson"],
        ["episodes"],
        ["digest"],
        ["digest", "--top", "2"],
        ["digest", "--significance", "duration"],
    ),
    ids=" ".join,
)
def test_the_reports_print_what_the_whole_window_would(
    log: Path, report: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """The bounded reports against the views fed every episode at once."""
    from edumatcher.audit.replay import render_json, views
    from edumatcher.audit.replay.cli import (
        build_parser,
        _from_log,
        _log_files,
        story_source,
    )

    argv = ["--log-file", str(log), *report]
    code = main(argv)
    out = capsys.readouterr().out
    args = build_parser().parse_args(argv)
    episodes, _state = _from_log(args, _log_files(args))
    if not episodes:
        assert code == 1
        return
    if report[0] == "anomalies" and args.format == "ndjson":
        expected = "".join(
            f"{render_json.dumps(obj)}\n"
            for obj in render_json.anomalies(episodes, story_source=story_source(args))
        )
    elif report[0] == "anomalies":
        expected = views.render_anomalies(episodes, story_source=story_source(args))
    elif report[0] == "episodes":
        expected = views.render_episodes(episodes)
    else:
        expected = views.render_digest(
            episodes, significance=args.significance, top=args.top
        )
    assert out == expected


def test_pass_one_forgets_answered_requests() -> None:
    """P1: on an enveloped trail a cancel's effect names its cause, so the
    request lists were never popped and grew by every request of the day."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        log = trail(Path(tmp) / "audit.log", 2500)
        run, steps = reconstruct(iter_entries([log]), max_facts=100, max_seconds=5.0)
        for _episode in assemble(steps, run.state, run.links, max_facts=100):
            pass
    links = run.links
    held = (
        sum(len(v) for v in links._cancel_requests.values())
        + sum(len(v) for v in links._amend_requests.values())
        + sum(len(v) for v in links._structure_cancels.values())
    )
    # What the reorder and retirement windows still hold, not 2 500.
    assert held < 300, held
    assert len(run.state._requests) < 300, len(run.state._requests)
