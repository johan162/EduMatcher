"""Core data types for the pm-cverifier tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    ERROR = "ERROR"
    WARN = "WARN"
    INFO = "INFO"


@dataclass
class CheckResult:
    code: str
    severity: Severity
    message: str
    suggestion: str
    path: str = ""
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskSummary:
    symbols: list[str] = field(default_factory=list)
    gateways: dict[str, str] = field(default_factory=dict)  # id -> role
    sessions_enabled: bool = False
    schedule_summary: str = ""
    collars_enforced: bool = False
    collars_configured: bool = False
    collar_description: str = ""
    circuit_breakers_enforced: bool = False
    circuit_breakers_configured: bool = False
    cb_description: str = ""
    mm_obligations_enforced: bool = False
    admin_gateway: str | None = None
    indices: list[str] = field(default_factory=list)


@dataclass
class LayerOutcome:
    """The result of running (or skipping) one verification layer."""

    name: str  # display name, e.g. "Schema"
    status: str = "ran"  # "ran" or "skipped"
    results: list[CheckResult] = field(default_factory=list)


@dataclass
class VerificationReport:
    file: str
    results: list[CheckResult]
    summary: dict[str, int]
    risk_summary: RiskSummary
    verdict: str  # "OK", "WARN", "ERROR"
    layers: list[LayerOutcome] = field(default_factory=list)
    strict: bool = False
