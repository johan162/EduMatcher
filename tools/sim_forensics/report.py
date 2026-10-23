"""Write the run's results as report.md and findings.json."""

from __future__ import annotations

import json
from pathlib import Path

from sim_forensics.dataset import Dataset
from sim_forensics.registry import Result


def write(ds: Dataset, results: list[Result], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.md").write_text(markdown(ds, results), encoding="utf-8")
    findings = [
        {
            "id": r.check.id,
            "oracle": r.check.oracle,
            "title": r.check.title,
            "status": r.status,
            "violations": r.violations,
            "note": r.note,
            "seconds": round(r.seconds, 3),
            "samples": r.samples,
        }
        for r in results
    ]
    (out_dir / "findings.json").write_text(
        json.dumps(
            {
                "data_dir": str(ds.data_dir),
                "cut_trade_id": ds.cut_trade_id,
                "checks": findings,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def markdown(ds: Dataset, results: list[Result]) -> str:
    lines = [
        "# Simulation forensics report",
        "",
        f"- Data dir: `{ds.data_dir}`",
        f"- Stores: {', '.join(sorted(ds.stores)) or 'none'}",
        f"- Session timezone: {ds.session_tz.key}",
        f"- Cut (highest trade id in every trade store): `{ds.cut_trade_id}`",
        "",
        "| Check | Oracle | Title | Status | Violations | Seconds |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.check.id} | {r.check.oracle} | {r.check.title} | {r.status} "
            f"| {r.violations} | {r.seconds:.2f} |"
        )
    for r in results:
        if r.status == "PASS" and not r.note:
            continue
        lines += ["", f"## {r.check.id} — {r.status}", ""]
        if r.status == "ERROR":
            lines += ["```", r.note.rstrip(), "```"]
        elif r.note:
            lines.append(r.note)
        for sample in r.samples:
            lines.append(f"- `{json.dumps(sample, default=str)}`")
    return "\n".join(lines) + "\n"
