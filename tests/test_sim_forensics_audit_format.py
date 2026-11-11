"""The simulation forensics read the audit trail in the format pm-audit writes.

The other forensics tests record with a stand-in publisher whose sequence
numbers are not the engine's.  This one records through the real
``SequencedPublisher`` and ``CausalPublisher``, follows the run loop's own echo
and cause handling, formats lines as ``AuditProcess`` does, and adds what the
audit-completeness work put in the trail: a recorder-start marker (twice, one
mid-file), ``system.gateway_reject``, a gateway expired for silence, and
``ts_ns`` on acks and fills.  Every audit-based check must pass on it.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import tests.sim_forensics_features as features
from edumatcher.audit.main import _meta_section
from edumatcher.audit.writer import header_line, recorder_start_line
from edumatcher.messaging.bus import CausalPublisher, CausalPusher, SequencedPublisher
from edumatcher.models.message import (
    decode,
    decode_push_envelope,
    encode,
    make_gateway_reject_msg,
)
from edumatcher.models.participant import DisconnectBehaviour
from edumatcher.sim_forensics import checks  # noqa: F401,E402  (registers the checks)
from edumatcher.sim_forensics.registry import REGISTRY, run_checks  # noqa: E402
from tests.sim_forensics_world import OpenDataset, opener


class _Lines:
    """The bottom of the engine's PUB socket: what pm-audit would write."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines

    def send_multipart(self, frames: list[bytes], *a: Any, **k: Any) -> None:
        topic, payload = decode(frames)
        ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        meta = _meta_section(frames)
        mid = f"[{meta}] " if meta else ""
        self.lines.append(f"[{ts}] [{topic}] {mid}{json.dumps(payload)}\n")


class _Pushed:
    def __init__(self) -> None:
        self.sent: list[list[bytes]] = []

    def send_multipart(self, frames: list[bytes], *a: Any, **k: Any) -> None:
        self.sent.append(frames)


class PmAuditRecorder:
    """Stands in for the engine's sockets with the real wrappers."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self._pub = CausalPublisher(SequencedPublisher(_Lines(self.lines)))

    def send_multipart(self, frames: list[bytes], *a: Any, **k: Any) -> Any:
        return self._pub.send_multipart(frames)

    def send_with_envelope(self, frames: list[bytes], envelope: bytes) -> Any:
        return self._pub.send_with_envelope(frames, envelope)

    def set_cause(self, envelope: Any) -> None:
        self._pub.set_cause(envelope)

    def clear_cause(self) -> None:
        self._pub.clear_cause()

    def begin_unit(self) -> None:
        self._pub.begin_unit()

    def end_unit(self) -> None:
        self._pub.end_unit()

    def close(self) -> None:
        pass

    def command(self, engine: Any, topic: str, payload: dict[str, Any]) -> None:
        pushed = _Pushed()
        CausalPusher(pushed).send_multipart(encode(topic, payload))
        frames = pushed.sent[0]
        recorded = engine._echo_command(topic, frames)
        self._pub.set_cause(decode_push_envelope(frames) if recorded else None)
        try:
            engine._dispatch_pull_message(topic, payload)
        finally:
            self._pub.clear_cause()


class _Run(features.Run):
    def finish(self) -> Path:
        reject = decode(
            make_gateway_reject_msg(
                source="ALF",
                reject_code="RATE_LIMITED",
                ts_ns=time.time_ns(),
                gateway_id="TRADER02",
                peer="10.0.0.5:4411",
                reason="x",
                count=3,
            )
        )[1]
        self.cmd("system.gateway_reject", reject)
        silent = self.engine._sessions["TRADER01"]
        silent.disconnect_behaviour = DisconnectBehaviour.CANCEL_ALL
        silent.heartbeat_interval_sec = 1
        silent.last_heartbeat = time.monotonic() - 100
        self.engine._next_silence_check = 0.0
        self.engine._expire_silent_gateways()
        return super().finish()


@pytest.fixture(scope="module")
def trail(
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    mp = pytest.MonkeyPatch()
    mp.setattr(features, "Recorder", PmAuditRecorder)
    mp.setattr(features, "Run", _Run)
    try:
        data = features.consistent(tmp_path_factory.mktemp("real") / "data")
    finally:
        mp.undo()
    log = data / "audit.log"
    body = log.read_text().splitlines(keepends=True)
    half = len(body) // 2
    log.write_text(
        "".join(
            [
                header_line() + "\n",
                recorder_start_line() + "\n",
                *body[:half],
                recorder_start_line() + "\n",  # pm-audit restarted mid-file
                *body[half:],
            ]
        )
    )
    return data


@pytest.fixture
def open_ds() -> Any:
    yield from opener()


#: The checks that read only the audit; the rest need pm-stats and pm-clearing.
AUDIT_ONLY = [
    "A5", "C7", "C8", "C9", "C10", "C11",
    "D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10", "D11",
    "E1", "E2", "E4", "F3", "F6",
]  # fmt: skip


def test_the_trail_holds_what_the_new_formats_add(trail: Path) -> None:
    text = (trail / "audit.log").read_text()
    assert text.count("# edumatcher-audit recorder-start") == 2
    assert "[system.gateway_reject]" in text
    assert '"reason": "heartbeat_timeout"' in text
    assert '"ts_ns"' in next(
        ln for ln in text.splitlines() if "[order.ack.TRADER01]" in ln
    )


def test_every_audit_based_check_passes(trail: Path, open_ds: OpenDataset) -> None:
    results = run_checks(open_ds(trail), [REGISTRY[i] for i in AUDIT_ONLY], 10)
    assert {r.check.id: (r.status, r.violations) for r in results} == {
        i: ("PASS", 0) for i in AUDIT_ONLY
    }


def test_the_silent_gateway_and_the_reject_are_inputs_to_the_re_run(
    trail: Path, open_ds: OpenDataset
) -> None:
    from edumatcher.sim_forensics.checks.rerun import HEARTBEAT_TIMER, _rerun

    commands = _rerun(open_ds(trail)).commands
    assert commands[HEARTBEAT_TIMER] == 1
    assert commands["system.gateway_reject"] == 1


def test_a_healthy_trail_replays_with_no_finding_at_warn(
    trail: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Acceptance (Audit-Replay 17): `anomalies --severity warn` is empty on a
    healthy run.  It was not -- order.ack, order.amended, order.triggered,
    engine.trace and system.book_checkpoint carried tick prices without their
    scale -- until every message that carries a tick price carried its scale."""
    from edumatcher.audit.replay.cli import main

    code = main(
        [
            "--log-file",
            str(trail / "audit.log"),
            "--no-index",
            "anomalies",
            "--severity",
            "warn",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert out.startswith("No findings"), out
