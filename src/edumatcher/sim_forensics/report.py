"""Write the run's results as report.md and findings.json.

findings.json also lists its ``inputs``: every audit file and store the
checks read (name relative to the data dir, size, SHA-256), so a reader such
as the Audit GUI can tell whether a report is about the trail it holds. Each
check names the stores it ``needs``: its data scope.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from edumatcher.audit.rawlines import Unavailable, audit_files, run_config_text
from edumatcher.sim_forensics.dataset import STORES, Dataset
from edumatcher.sim_forensics.explain import EXPLAIN, INTRO
from edumatcher.sim_forensics.registry import Result


def write(ds: Dataset, results: list[Result], out_dir: Path, version: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(markdown(ds, results, version), encoding="utf-8")
    findings = [
        {
            "id": r.check.id,
            "oracle": r.check.oracle,
            "title": r.check.title,
            "status": r.status,
            "violations": r.violations,
            "note": r.note,
            "seconds": round(r.seconds, 3),
            "needs": list(r.check.needs),
            "samples": r.samples,
        }
        for r in results
    ]
    (out_dir / "findings.json").write_text(
        json.dumps(
            {
                "data_dir": str(ds.data_dir),
                "tool_version": version,
                "cut_trade_id": ds.cut_trade_id,
                "inputs": inputs(ds),
                "checks": findings,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def inputs(ds: Dataset) -> list[dict[str, object]]:
    """The audit files (oldest first), then the stores present, each hashed."""
    files = [(p, "audit") for p in audit_files(ds.data_dir)]
    files += [(ds.data_dir / f"{name}.db", "store") for name in STORES if name in ds.stores]  # fmt: skip
    out: list[dict[str, object]] = []
    for path, kind in files:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as fh:
            while chunk := fh.read(1 << 20):
                digest.update(chunk)
                size += len(chunk)
        name = path.relative_to(ds.data_dir).as_posix()
        out.append({"name": name, "kind": kind, "size": size, "sha256": digest.hexdigest()})  # fmt: skip
    return out


def _run_version(ds: Dataset) -> str | None:
    """The version that compiled the config the run's engine started on."""
    try:
        meta = json.loads(run_config_text(audit_files(ds.data_dir)))["meta"]
        return str(meta["compiler_version"])
    except Unavailable, ValueError, KeyError, TypeError:
        return None


def markdown(ds: Dataset, results: list[Result], version: str) -> str:
    run_version = _run_version(ds)
    lines = [
        "# Simulation forensics report",
        "",
        f"- Data dir: `{ds.data_dir}`",
        f"- pm-sim-forensics: {version}; the run was compiled by "
        f"{run_version or 'an unknown version'}"
        + (
            "  **(differs: the re-run checks E1-E7 and C12-C14, D12 may fail on "
            "a schema that moved; run pm-sim-forensics from the run's own build)**"
            if run_version and run_version != version
            else ""
        ),
        f"- Stores: {', '.join(sorted(ds.stores)) or 'none'}",
        f"- Session timezone: {ds.session_tz.key}",
        f"- Cut (highest trade id in every trade store): `{ds.cut_trade_id}`",
        "",
        INTRO,
        "| Check | Oracle | Title | Status | Violations | Seconds |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.check.id} | {r.check.oracle} | {r.check.title} | {r.status} "
            f"| {r.violations} | {r.seconds:.2f} |"
        )
    for r in results:
        lines += ["", f"## {r.check.id} — {r.status}", ""]
        if explanation := EXPLAIN.get(r.check.id):
            lines += [f"*{explanation}*", ""]
        if r.status == "ERROR":
            lines += ["```", r.note.rstrip(), "```"]
        elif r.note:
            lines.append(r.note)
        for sample in r.samples:
            lines.append(f"- `{json.dumps(sample, default=str)}`")
    return "\n".join(lines) + "\n"
