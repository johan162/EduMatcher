"""Text and JSON output formatters for pm-cverifier."""

from __future__ import annotations

import json
from typing import Any

from edumatcher.cverifier.models import (
    CheckResult,
    LayerOutcome,
    Severity,
    VerificationReport,
)

# ANSI codes
_RESET = "\033[0m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_BOLD = "\033[1m"
_DIM = "\033[2m"


def _sev_icon(sev: Severity, color: bool) -> str:
    if sev is Severity.ERROR:
        return f"{_RED}✗{_RESET}" if color else "✗"
    if sev is Severity.WARN:
        return f"{_YELLOW}⚠{_RESET}" if color else "⚠"
    return f"{_CYAN}ℹ{_RESET}" if color else "i"


def _ok_icon(color: bool) -> str:
    return f"{_GREEN}✓{_RESET}" if color else "✓"


def _divider(color: bool) -> str:
    line = "─" * 56
    return f"{_DIM}{line}{_RESET}" if color else line


# Each layer reports findings in a canonical unit.
_LAYER_UNIT = {
    "YAML syntax": ("error", "errors"),
    "Schema": ("error", "errors"),
    "Semantic": ("warning", "warnings"),
    "Completeness": ("advisory", "advisories"),
}


def _layer_count_line(outcome: LayerOutcome, color: bool) -> str:
    if outcome.status == "skipped":
        line = f"  {outcome.name}: skipped (fix schema errors first)"
        return f"{_DIM}{line}{_RESET}" if color else line

    singular, plural = _LAYER_UNIT.get(outcome.name, ("finding", "findings"))
    n = len(outcome.results)
    if n == 0:
        if outcome.name == "YAML syntax":
            return f"{_ok_icon(color)} {outcome.name}: OK"
        return f"{_ok_icon(color)} {outcome.name}: 0 {plural}"

    if any(r.severity is Severity.ERROR for r in outcome.results):
        max_sev = Severity.ERROR
    elif any(r.severity is Severity.WARN for r in outcome.results):
        max_sev = Severity.WARN
    else:
        max_sev = Severity.INFO
    unit = singular if n == 1 else plural
    return f"{_sev_icon(max_sev, color)} {outcome.name}: {n} {unit}"


def _layer_summary_lines(
    report: VerificationReport,
    color: bool,
    errors: list[CheckResult],
    warnings: list[CheckResult],
    infos: list[CheckResult],
) -> list[str]:
    if report.layers:
        return [_layer_count_line(lo, color) for lo in report.layers]

    # Fallback (reports built without per-layer data): summarise by severity.
    fallback = [
        LayerOutcome("YAML syntax", "ran", []),
        LayerOutcome("Schema", "ran", errors),
        LayerOutcome("Semantic", "ran", warnings),
        LayerOutcome("Completeness", "ran", infos),
    ]
    return [_layer_count_line(lo, color) for lo in fallback]


def format_text(
    report: VerificationReport,
    color: bool = True,
    min_severity: Severity = Severity.INFO,
) -> str:
    lines: list[str] = []
    _sev_order = {Severity.ERROR: 0, Severity.WARN: 1, Severity.INFO: 2}
    min_ord = _sev_order[min_severity]

    errors = [r for r in report.results if r.severity is Severity.ERROR]
    warnings = [r for r in report.results if r.severity is Severity.WARN]
    infos = [r for r in report.results if r.severity is Severity.INFO]

    # Header
    lines.append(f"\npm-cverifier {report.file}\n")

    # Layer summary — attribute each finding to the layer that produced it.
    lines.extend(_layer_summary_lines(report, color, errors, warnings, infos))
    lines.append("")

    # Findings
    def _render_finding(r: CheckResult) -> list[str]:
        code = f"[{r.code}]"
        sev_label = r.severity.value
        if color:
            if r.severity is Severity.ERROR:
                code = f"{_RED}{_BOLD}{code}{_RESET}"
                sev_label = f"{_RED}{sev_label}{_RESET}"
            elif r.severity is Severity.WARN:
                code = f"{_YELLOW}{_BOLD}{code}{_RESET}"
                sev_label = f"{_YELLOW}{sev_label}{_RESET}"
            else:
                code = f"{_CYAN}{code}{_RESET}"
                sev_label = f"{_CYAN}{sev_label}{_RESET}"
        block = [f"{code} {sev_label}  {r.message}"]
        if r.suggestion:
            for i, sline in enumerate(r.suggestion.splitlines()):
                prefix = "  → " if i == 0 else "    "
                block.append(f"{prefix}{sline}")
        block.append("")
        return block

    filtered = [r for r in report.results if _sev_order[r.severity] <= min_ord]

    section_errors = [r for r in filtered if r.severity is Severity.ERROR]
    section_warns = [r for r in filtered if r.severity is Severity.WARN]
    section_infos = [r for r in filtered if r.severity is Severity.INFO]

    if section_errors:
        lines.append(_divider(color))
        lines.append("Errors")
        lines.append(_divider(color))
        lines.append("")
        for r in section_errors:
            lines.extend(_render_finding(r))

    if section_warns:
        lines.append(_divider(color))
        lines.append("Warnings")
        lines.append(_divider(color))
        lines.append("")
        for r in section_warns:
            lines.extend(_render_finding(r))

    if section_infos:
        lines.append(_divider(color))
        lines.append("Advisories")
        lines.append(_divider(color))
        lines.append("")
        for r in section_infos:
            lines.extend(_render_finding(r))

    # Risk Summary
    lines.append(_divider(color))
    lines.append("Risk Summary")
    lines.append(_divider(color))
    lines.append("")
    rs = report.risk_summary
    sym_str = ", ".join(rs.symbols[:5])
    if len(rs.symbols) > 5:
        sym_str += f" … +{len(rs.symbols) - 5} more"
    lines.append(f"Symbols          {len(rs.symbols)}  ({sym_str})")

    gw_parts = [f"{gw_id}: {role}" for gw_id, role in rs.gateways.items()]
    gw_str = ", ".join(gw_parts[:4])
    if len(gw_parts) > 4:
        gw_str += f" … +{len(gw_parts) - 4} more"
    lines.append(f"Gateways         {len(rs.gateways)}  ({gw_str})")
    lines.append(
        f"Sessions         {'enabled' if rs.sessions_enabled else 'disabled'} — {rs.schedule_summary}"
    )

    collar_status = "enabled" if rs.collars_enforced else "disabled"
    lines.append(f"Collars          {collar_status} — {rs.collar_description}")

    cb_status = "enabled" if rs.circuit_breakers_enforced else "disabled"
    lines.append(f"Circuit breakers {cb_status} — {rs.cb_description}")

    mm_status = "enforced" if rs.mm_obligations_enforced else "not enforced"
    lines.append(f"MM obligations   {mm_status}")

    admin_str = (
        rs.admin_gateway if rs.admin_gateway else f"none {'⚠' if color else '[!]'}"
    )
    lines.append(f"Admin gateway    {admin_str}")

    if rs.indices:
        idx_str = ", ".join(rs.indices)
        lines.append(f"Indices          {len(rs.indices)}  ({idx_str})")

    lines.append("")

    # Verdict
    lines.append(_divider(color))
    if report.verdict == "OK":
        verdict_icon = _ok_icon(color)
        verdict_msg = f"{verdict_icon} OK — no issues found"
    elif report.verdict == "WARN":
        verdict_icon = _sev_icon(Severity.WARN, color)
        w = len(warnings)
        i = len(infos)
        parts = []
        if w:
            parts.append(f"{w} WARNING{'S' if w > 1 else ''}")
        if i:
            parts.append(f"{i} ADVISOR{'IES' if i > 1 else 'Y'}")
        verdict_msg = (
            f"{verdict_icon} {', '.join(parts)} — engine can start but review warnings"
        )
    else:
        verdict_icon = _sev_icon(Severity.ERROR, color)
        e = len(errors)
        if e == 0 and report.strict:
            # Verdict promoted to ERROR by --strict; there are no hard errors.
            w = len(warnings)
            verdict_msg = (
                f"{verdict_icon} {w} WARNING{'S' if w != 1 else ''} treated as errors "
                "(--strict) — engine could start but CI gate failed"
            )
        else:
            verdict_msg = f"{verdict_icon} {e} ERROR{'S' if e != 1 else ''} — engine will not start"
    lines.append(f"Verdict:  {verdict_msg}")
    lines.append(_divider(color))
    lines.append("")

    return "\n".join(lines)


def format_json(report: VerificationReport) -> str:
    def _result_to_dict(r: CheckResult) -> dict[str, Any]:
        return {
            "code": r.code,
            "severity": r.severity.value,
            "message": r.message,
            "suggestion": r.suggestion,
            "path": r.path,
        }

    rs = report.risk_summary
    data: dict[str, Any] = {
        "file": report.file,
        "verdict": report.verdict,
        "summary": report.summary,
        "checks": [_result_to_dict(r) for r in report.results],
        "risk_summary": {
            "symbols": rs.symbols,
            "gateways": rs.gateways,
            "sessions_enabled": rs.sessions_enabled,
            "collars_enforced": rs.collars_enforced,
            "collars_configured": rs.collars_configured,
            "circuit_breakers_enforced": rs.circuit_breakers_enforced,
            "circuit_breakers_using_defaults": not rs.circuit_breakers_configured,
            "mm_obligations_enforced": rs.mm_obligations_enforced,
            "admin_gateway": rs.admin_gateway,
            "indices": rs.indices,
        },
    }
    return json.dumps(data, indent=2)
