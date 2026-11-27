"""pm-sim-forensics' report in the Audit GUI (AG4, design §2, §4.1, §6).

The report is the one ``pm-sim-forensics`` itself wrote for the world's run
(variant ``forensics_report``), found where the tool writes it by default:
``forensics/`` beside the data directory. Its checks are never re-run here.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from edumatcher.sim_forensics.registry import REGISTRY
from tests import audit_gui_world as aw
from tests.audit_gui_world import World, build, make_audit_app
from tests.test_api_gateway_audit import _get, _post, _snapshot

_FORENSICS = "SIM_FORENSICS"


def _pin(app: Any) -> dict[str, Any]:
    status, body = _post(app, "/snapshots", {"collection_id": "world"})
    assert status == 201, body
    return body


def _all_findings(app: Any, sid: str, query: str = "") -> dict[str, Any]:
    status, body = _get(app, f"/findings?snapshot_id={sid}&limit=1000{query}")
    assert status == 200, body
    assert not body["has_more"]
    return body


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> World:
    return build(tmp_path_factory.mktemp("audit-world"), forensics_report=True)


@pytest.fixture(scope="module")
def report(world: World) -> dict[str, Any]:
    assert world.forensics_report is not None
    assert world.forensics_report.parent == world.data.parent / "forensics"
    return dict(json.loads(world.forensics_report.read_text()))


@pytest.fixture(scope="module")
def app(world: World) -> Any:
    return make_audit_app(world)


@pytest.fixture(scope="module")
def sid(app: Any) -> str:
    return _snapshot(app)


def test_the_snapshot_pins_the_report_and_its_inputs(
    app: Any, world: World, report: dict[str, Any]
) -> None:
    assert world.forensics_report is not None
    body = _pin(app)
    assert body["capabilities"]["forensics"] == {
        "available": True,
        "reason": None,
        "detail": "",
    }
    pinned = body["forensics"]
    raw = world.forensics_report.read_bytes()
    assert (pinned["sha256"], pinned["size"]) == (hashlib.sha256(raw).hexdigest(), len(raw))  # fmt: skip
    assert pinned["tool_version"] == report["tool_version"]
    assert pinned["cut_trade_id"] == report["cut_trade_id"]
    assert pinned["statuses"] == dict(Counter(aw.FORENSICS_STATUSES.values()))
    assert pinned["inputs"] == report["inputs"]
    assert [i["name"] for i in pinned["inputs"] if i["kind"] == "audit"] == [
        "audit.log"
    ]
    assert (pinned["inputs_match"], pinned["differing"]) == (True, [])
    # The descriptor never carries a host path.
    assert str(world.data) not in json.dumps(body)


def test_failed_checks_are_consistency_findings_with_their_samples_and_scope(
    app: Any, sid: str, report: dict[str, Any]
) -> None:
    body = _all_findings(app, sid, f"&code={_FORENSICS}")
    rows = {r["check"]["id"]: r for r in body["findings"]}
    assert {i: r["check"]["status"] for i, r in rows.items()} == {
        i: s for i, s in aw.FORENSICS_STATUSES.items() if s != "PASS"
    }
    assert {r["lane"] for r in rows.values()} == {"consistency"}
    assert {r["origin"] for r in rows.values()} == {"forensics"}
    failed = rows["E2"]
    expected = next(c for c in report["checks"] if c["id"] == "E2")
    assert failed["severity"] == "error"
    assert failed["check"]["samples"] == expected["samples"]
    assert failed["check"]["violations"] == expected["violations"]
    assert failed["check"]["scope"] == {
        "stores": list(REGISTRY["E2"].needs),
        "cut_trade_id": report["cut_trade_id"],
    }
    # SKIPPED and ERROR are their own states, never a pass.
    assert (rows["C1"]["severity"], rows["E4"]["severity"]) == ("info", "warn")
    assert body["forensics"] == {
        "available": True,
        "reason": None,
        "detail": "",
        "statuses": dict(Counter(aw.FORENSICS_STATUSES.values())),
    }


def test_a_passed_check_is_never_a_finding(app: Any, sid: str) -> None:
    every = _all_findings(app, sid)["findings"]
    ids = [r["check"]["id"] for r in every if r["origin"] == "forensics"]
    assert "E1" not in ids
    assert len(ids) == 3
    # Worst first: the failed check sorts among the errors.
    severities = [r["severity"] for r in every]
    assert severities == sorted(severities, key=["error", "warn", "info"].index)
    lanes = _all_findings(app, sid, "&lane=consistency")["lanes"]
    assert lanes["consistency"]["count"] >= 3


def test_the_pinned_report_is_read_not_the_file_on_disk(
    tmp_path: Path,
) -> None:
    world = build(tmp_path, forensics_report=True)
    assert world.forensics_report is not None
    app = make_audit_app(world)
    sid = _snapshot(app)
    world.forensics_report.write_text("{}")
    rows = _all_findings(app, sid, f"&code={_FORENSICS}")["findings"]
    assert len(rows) == 3


def test_a_report_on_other_inputs_is_flagged_not_merged(tmp_path: Path) -> None:
    world = build(tmp_path, forensics_report=True)
    with world.audit_log.open("a") as fh:
        fh.write('[2026-06-15T08:00:00.001+00:00] [system.eod] {"books": []}\n')
    app = make_audit_app(world)
    body = _pin(app)
    state = body["capabilities"]["forensics"]
    assert (state["available"], state["reason"]) == (False, "DIFFERENT_INPUTS")
    assert "audit.log" in state["detail"]
    assert (body["forensics"]["inputs_match"], body["forensics"]["differing"]) == (False, ["audit.log"])  # fmt: skip
    findings = _all_findings(app, body["snapshot_id"])
    assert not any(r["origin"] == "forensics" for r in findings["findings"])
    assert findings["forensics"]["reason"] == "DIFFERENT_INPUTS"


def test_no_report_is_not_attached_and_an_unreadable_one_says_so(
    tmp_path: Path,
) -> None:
    world = build(tmp_path)
    app = make_audit_app(world)
    bare = _pin(app)
    assert bare["forensics"] is None
    assert bare["capabilities"]["forensics"]["reason"] == "NOT_ATTACHED"
    assert _all_findings(app, bare["snapshot_id"])["forensics"]["statuses"] is None
    report = world.data.parent / "forensics" / "findings.json"
    report.parent.mkdir()
    report.write_text('{"checks": ')
    broken = _pin(app)
    # The report is part of what a snapshot pins: a new one is a new snapshot.
    assert broken["snapshot_id"] != bare["snapshot_id"]
    assert broken["capabilities"]["forensics"]["reason"] == "REPORT_UNREADABLE"
    assert broken["forensics"] is None
