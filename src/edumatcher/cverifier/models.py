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
    #: The included file the finding's ``path`` is defined in; empty when it
    #: is the main file.
    file: str = ""
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
    order_limits_configured: bool = False
    order_limits_description: str = ""
    circuit_breakers_enforced: bool = False
    circuit_breakers_configured: bool = False
    cb_description: str = ""
    mm_obligations_enforced: bool = False
    mm_description: str = ""
    admin_gateway: str | None = None
    indices: list[str] = field(default_factory=list)
    #: Filled when the summary is built from the loaded EngineConfig.
    collared_symbols: list[str] = field(default_factory=list)
    circuit_breaker_symbols: list[str] = field(default_factory=list)
    mm_obligation_gateways: list[str] = field(default_factory=list)
    #: True when built from what the engine loader produced; False when read
    #: from a file the loader refuses (a best-effort reading of the YAML).
    loaded: bool = False


@dataclass
class LayerOutcome:
    """The result of running (or skipping) one verification layer."""

    name: str  # display name, e.g. "Schema"
    status: str = "ran"  # "ran" or "skipped"
    results: list[CheckResult] = field(default_factory=list)
    #: Why a skipped layer did not run, e.g. "fix the YAML error first".
    skip_reason: str = ""


@dataclass
class VerificationReport:
    file: str
    results: list[CheckResult]
    summary: dict[str, int]
    risk_summary: RiskSummary
    verdict: str  # "OK", "WARN", "ERROR"
    layers: list[LayerOutcome] = field(default_factory=list)
    strict: bool = False
