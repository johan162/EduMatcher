"""A ``pm-sim-forensics`` report, attached to a snapshot (design §2, §4.1, §6;
workplan AG4).

The checks are pm-sim-forensics' own and are never re-run here: this reads
the ``findings.json`` it wrote. Where: ``forensics/`` beside the collection
directory, the tool's default ``--out`` for a data dir. No route names a
path.

When a snapshot is pinned, the report's bytes are copied into the snapshot
and hashed (the hash is part of the snapshot id), and its ``inputs`` (every
audit file and store it read, with size and SHA-256) are compared with the
audit files the snapshot pins. A report whose audit inputs differ is about
another trail (``DIFFERENT_INPUTS``): it is shown on the descriptor with the
files that differ, and its checks are not findings of this snapshot.

Of a matching report, ``FAIL`` (``error``), ``ERROR`` (``warn``: the check
itself broke) and ``SKIPPED`` (``info``: its data was absent) checks are
findings in the consistency lane, with their sample rows and data scope
(the stores each check needs and the report's trade cut). ``PASS`` and
``INFO`` are counted and never findings.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edumatcher.audit.service.capabilities import (
    AVAILABLE,
    CapabilityState,
    Reason,
    unavailable,
)
from edumatcher.audit.service.findings import CONSISTENCY

#: The finding code of an imported check (its id is ``check.id``).
CODE = "SIM_FORENSICS"
#: The report's copy inside a snapshot's directory.
PINNED = "forensics.json"
#: Statuses that are findings, and their severity.
_SEVERITY = {"FAIL": "error", "ERROR": "warn", "SKIPPED": "info"}


def report_path(collection_root: Path) -> Path:
    """Where pm-sim-forensics writes a data dir's report by default."""
    return collection_root.parent / "forensics" / "findings.json"


@dataclass(frozen=True)
class ForensicsInput:
    name: str
    kind: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ForensicsPin:
    """What the descriptor says of an attached, readable report."""

    sha256: str
    size: int
    tool_version: str | None
    cut_trade_id: str | None
    #: Checks per status (PASS included).
    statuses: dict[str, int]
    inputs: tuple[ForensicsInput, ...]
    #: Audit files the report and the snapshot disagree on (empty: same).
    differing: tuple[str, ...]

    @property
    def inputs_match(self) -> bool:
        return not self.differing


@dataclass(frozen=True)
class Attachment:
    sha256: str
    #: None when the report cannot be read.
    pin: ForensicsPin | None
    state: CapabilityState


def attach(
    collection_root: Path, pinned: Mapping[str, tuple[int, str]], work: Path
) -> Attachment | None:
    """Copy the collection's report into *work* and compare its audit inputs
    with *pinned* (name -> bytes read, SHA-256); None when there is none."""
    try:
        raw = report_path(collection_root).read_bytes()
    except FileNotFoundError:
        return None
    (work / PINNED).write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    try:
        report = _parse(raw)
    except ValueError as exc:
        return Attachment(
            sha,
            None,
            unavailable(
                Reason.REPORT_UNREADABLE, f"the pm-sim-forensics report: {exc}"
            ),
        )
    inputs = tuple(ForensicsInput(**i) for i in report["inputs"])
    read = {i.name: (i.size, i.sha256) for i in inputs if i.kind == "audit"}
    differing = tuple(
        sorted(n for n in read.keys() | pinned.keys() if read.get(n) != pinned.get(n))
    )
    pin = ForensicsPin(
        sha256=sha,
        size=len(raw),
        tool_version=_text(report.get("tool_version")),
        cut_trade_id=_text(report.get("cut_trade_id")),
        statuses=dict(Counter(str(c["status"]) for c in report["checks"])),
        inputs=inputs,
        differing=differing,
    )
    state = (
        AVAILABLE
        if not differing
        else unavailable(
            Reason.DIFFERENT_INPUTS,
            "the pm-sim-forensics report read other audit files than the "
            f"snapshot pins: {', '.join(differing)}",
        )
    )
    return Attachment(sha, pin, state)


def findings(snapshot_dir: Path) -> list[dict[str, Any]]:
    """The pinned report's FAIL, ERROR and SKIPPED checks as finding rows."""
    report = _parse((snapshot_dir / PINNED).read_bytes())
    cut = _text(report.get("cut_trade_id"))
    rows = []
    for c in report["checks"]:
        severity = _SEVERITY.get(c["status"])
        if severity is None:
            continue
        rows.append(
            {
                "origin": "forensics",
                "code": CODE,
                "severity": severity,
                "lane": CONSISTENCY,
                "episode": None,
                "receipt_ts": None,
                "detail": f"{c['id']} {c['status']}: {c.get('title', '')}",
                "source": None,
                "check": {
                    "id": c["id"],
                    "oracle": c.get("oracle"),
                    "title": c.get("title"),
                    "status": c["status"],
                    "violations": c.get("violations"),
                    "note": c.get("note", ""),
                    "samples": c.get("samples") or [],
                    "scope": {
                        "stores": list(c.get("needs") or []),
                        "cut_trade_id": cut,
                    },
                },
            }
        )
    return rows


def _parse(raw: bytes) -> dict[str, Any]:
    """The report, checked for what this reader relies on."""
    try:
        report = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"not JSON ({exc})") from None
    if not isinstance(report, dict):
        raise ValueError("not a JSON object")
    checks, inputs = report.get("checks"), report.get("inputs")
    if not isinstance(checks, list) or not all(
        isinstance(c, dict) and isinstance(c.get("id"), str) and isinstance(c.get("status"), str)  # fmt: skip
        for c in checks
    ):
        raise ValueError("no list of checks with id and status")
    fields = {"name": str, "kind": str, "size": int, "sha256": str}
    if not isinstance(inputs, list) or not all(
        isinstance(i, dict)
        and i.keys() == fields.keys()
        and all(isinstance(i[k], t) for k, t in fields.items())
        for i in inputs
    ):
        raise ValueError("no list of inputs (written by a pm-sim-forensics older than this reader)")  # fmt: skip
    return report


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


__all__ = [
    "CODE",
    "Attachment",
    "ForensicsInput",
    "ForensicsPin",
    "attach",
    "findings",
    "report_path",
]
