"""Layer 1 — YAML syntax and top-level type checks (Y001–Y005)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from edumatcher.config_include import (
    INCLUDE_KEY,
    ConfigIncludeError,
    LoadedConfig,
    load_config_mapping,
)
from edumatcher.cverifier.models import CheckResult, Severity


def check(raw: dict[str, Any] | None, path: Path) -> list[CheckResult]:  # noqa: ARG001
    """Run Layer 1 checks.  *raw* is always None here; *path* is the file path."""
    return load(path)[0]


def load_with_origins(
    path: Path,
) -> tuple[list[CheckResult], dict[str, Any] | None, LoadedConfig | None]:
    """Read and parse the file once, resolving its includes.

    Returns the Layer 1 findings and the parsed mapping (or None when the file
    is missing, unreadable, not valid YAML, or not a top-level mapping).  The
    caller can reuse the returned mapping instead of re-reading the file.  The
    third item says which file each part came from; it is None unless the file
    has an ``include:`` list.
    """
    results: list[CheckResult] = []

    if not path.exists():
        results.append(
            CheckResult(
                code="Y001",
                severity=Severity.ERROR,
                message=f"File '{path}' not found.",
                suggestion="Check the path and try again.",
                path=str(path),
            )
        )
        return results, None, None

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        results.append(
            CheckResult(
                code="Y002",
                severity=Severity.ERROR,
                message=f"Cannot read '{path}': {exc.strerror}.",
                suggestion="Check file permissions.",
                path=str(path),
            )
        )
        return results, None, None

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = (mark.line + 1) if mark else "?"
        detail = getattr(exc, "problem", str(exc))
        results.append(
            CheckResult(
                code="Y003",
                severity=Severity.ERROR,
                message=f"YAML parse error at line {line}: {detail}.",
                suggestion="Fix the indentation or quoting at that line.",
                path=str(path),
            )
        )
        return results, None, None

    if not isinstance(data, dict):
        results.append(
            CheckResult(
                code="Y004",
                severity=Severity.ERROR,
                message=(
                    f"Config must be a YAML mapping (key: value pairs). "
                    f"Got {type(data).__name__}."
                ),
                suggestion="Start with 'symbols:' at the top level.",
                path=str(path),
            )
        )
        return results, None, None

    if INCLUDE_KEY in data:
        try:
            loaded = load_config_mapping(path)
        except ConfigIncludeError as exc:
            results.append(
                CheckResult(
                    code="Y005",
                    severity=Severity.ERROR,
                    message=f"{exc}.",
                    suggestion="Fix the 'include:' list or the named file.",
                    path=str(path),
                )
            )
            return results, None, None
        return results, loaded.data, loaded

    return results, data, None


def load(path: Path) -> tuple[list[CheckResult], dict[str, Any] | None]:
    """``load_with_origins`` without the origin map."""
    results, data, _ = load_with_origins(path)
    return results, data
