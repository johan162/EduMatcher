"""pm-audit-replay over a trail the real engine wrote (WP-RPL02).

The replay fixtures are hand-made and hold no OCO cancelled by request, no
quote cancel and no cancel that lost the race to a fill, so the reports came
out clean on them while a simulation trail produced thousands of false
warnings per part: OCO and quote legs reported as cancelled with no request
(H2), and an order split into three episodes by a cancel and its refusal
arriving after the fill (C1). :func:`record` drives a real ``Engine``, so
these trails have exactly the shape a running exchange writes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from edumatcher.audit.replay.cli import main
from tests.test_sim_forensics_rerun import edit, record


@pytest.fixture(scope="module")
def trail(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A run that cancels an OCO and a quote by request, then asks to cancel
    an order it has already filled."""
    return record(tmp_path_factory.mktemp("recorded") / "data", cancels=True)


def _copy(trail: Path, tmp_path: Path) -> Path:
    data = tmp_path / "data"
    data.mkdir()
    (data / "audit.log").write_bytes((trail / "audit.log").read_bytes())
    return data


def _findings(
    log: Path, capsys: pytest.CaptureFixture[str], code: str
) -> list[dict[str, object]]:
    assert main(["--log-file", str(log), "anomalies", "--format", "ndjson"]) == 0
    found = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    return [finding for finding in found if finding["code"] == code]


def _lines(log: Path, topic: str) -> list[dict[str, Any]]:
    return [
        json.loads(line.split("] ", 3)[3])
        for line in log.read_text().splitlines()
        if f"[{topic}]" in line
    ]


def _filled_buy(log: Path) -> str:
    """The order the run asks to cancel after it filled."""
    return str(_lines(log, "order.cancel")[-1]["order_id"])


class TestARequestedCancelIsSolicited:
    def test_oco_legs_cancelled_by_oco_cancel_are_not_unsolicited(
        self, trail: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        legs = {
            str(p["order_id"])
            for p in _lines(trail / "audit.log", "order.cancelled.TRADER01")
            if p.get("oco_group_id")
        }
        assert len(legs) == 2
        found = _findings(trail / "audit.log", capsys, "CANCEL_UNSOLICITED")
        assert not [f for f in found if any(leg in str(f["detail"]) for leg in legs)]

    def test_quote_legs_cancelled_by_quote_cancel_are_not_unsolicited(
        self, trail: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        acks = _lines(trail / "audit.log", "quote.cancel_ack.MM01")
        legs = {str(o) for ack in acks for o in ack["cancelled_order_ids"]}
        assert legs
        found = _findings(trail / "audit.log", capsys, "CANCEL_UNSOLICITED")
        assert not [f for f in found if any(leg in str(f["detail"]) for leg in legs)]

    def test_a_cancel_with_no_cause_no_reason_and_no_request_still_fires(
        self, trail: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        data = _copy(trail, tmp_path)
        edit(
            data,
            '"oco_group_id": "K1", "remaining_qty"',
            lambda ln: [ln.replace(" cause=", " was=", 1)],
        )
        found = _findings(data / "audit.log", capsys, "CANCEL_UNSOLICITED")
        assert len(found) == 1


class TestALateRequestJoinsItsOrder:
    def test_a_cancel_refused_after_the_fill_is_one_episode(
        self, trail: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log = trail / "audit.log"
        buy = _filled_buy(log)
        argv = ["--log-file", str(log), "episodes", "--format", "csv"]
        assert main([*argv, "--id-len", "full"]) == 0
        rows = [row for row in capsys.readouterr().out.splitlines() if buy in row]
        assert len(rows) == 1
        assert "FILLED" in rows[0]
        assert not _findings(log, capsys, "CANCEL_UNMATCHED")

    @pytest.mark.parametrize("length", (None, 10))
    def test_story_tells_the_fill_the_cancel_and_the_refusal(
        self,
        trail: Path,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        length: int | None,
    ) -> None:
        log = trail / "audit.log"
        buy = _filled_buy(log)
        selector = buy if length is None else buy[:length]
        argv = ["--log-file", str(log), "--db", str(tmp_path / "replay.db")]
        assert main([*argv, "story", "--order", selector, "--format", "ndjson"]) == 0
        topics = [
            json.loads(line).get("topic")
            for line in capsys.readouterr().out.splitlines()
        ]
        assert "order.cancel" in topics
        assert topics.count("order.ack.TRADER01") >= 2  # the accept and the refusal
        assert any(str(t).startswith("order.fill") for t in topics)

    def test_a_cancel_with_no_answer_is_still_unmatched(
        self, trail: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        data = _copy(trail, tmp_path)
        edit(data, "Order not found", lambda ln: [])
        found = _findings(data / "audit.log", capsys, "CANCEL_UNMATCHED")
        assert len(found) == 1
