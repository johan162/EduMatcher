"""The log ledger: an explanation and suggested actions per WARNING+ call site.

Entries live in ``entries/*.yaml`` next to this module, shipped as package
data, so an installed ``pm-log-cli`` and the log-GUI bridge (through
``pm-log-cli ledger export``) read the same text
(docs-design/EduMatcher-Log-Ledger.md §3). An entry is keyed by
``(logger, template)``; its ``tpl`` is computed here with the same
:func:`~edumatcher.logclient.protocol.template_id` the log client stamps on
every WARNING+ row, so a row is explained by a plain dictionary lookup.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

import yaml

from edumatcher.log_ledger.scan import LEDGER_LEVELS, LEVELS, CallSite, scan_package
from edumatcher.logclient.protocol import template_id

_ENTRY_KEYS = frozenset({"logger", "template", "level", "explanation", "actions"})
_MAX_ACTIONS = 4


class LedgerError(ValueError):
    """An entries file is malformed or two entries share a key."""


@dataclass(frozen=True)
class LedgerEntry:
    tpl: str
    logger: str
    template: str
    level: str
    explanation: str
    actions: tuple[str, ...]
    source: str  # entries file name, for error messages

    def to_dict(self) -> dict[str, Any]:
        return {
            "tpl": self.tpl,
            "logger": self.logger,
            "template": self.template,
            "level": self.level,
            "explanation": self.explanation,
            "actions": list(self.actions),
        }


@functools.cache
def load_ledger() -> dict[str, LedgerEntry]:
    """Every entry of the shipped ledger, keyed by ``tpl``."""
    files = resources.files("edumatcher.log_ledger").joinpath("entries")
    texts = {
        f.name: f.read_text(encoding="utf-8")
        for f in sorted(files.iterdir(), key=lambda f: f.name)
        if f.name.endswith(".yaml")
    }
    return parse_entries(texts)


def parse_entries(texts: dict[str, str]) -> dict[str, LedgerEntry]:
    """Parse and validate entries files given as ``{file name: YAML text}``."""
    ledger: dict[str, LedgerEntry] = {}
    for name, text in texts.items():
        raw = yaml.safe_load(text) or []
        if not isinstance(raw, list):
            raise LedgerError(f"{name}: expected a list of entries")
        for index, item in enumerate(raw):
            entry = _entry(name, index, item)
            other = ledger.get(entry.tpl)
            if other is not None:
                same = (other.logger, other.template) == (entry.logger, entry.template)
                raise LedgerError(
                    f"{name} entry {index}: "
                    + (
                        f"duplicate of an entry in {other.source}"
                        if same
                        else f"tpl {entry.tpl} collides with {other.source} "
                        f"({other.logger}: {other.template!r})"
                    )
                )
            ledger[entry.tpl] = entry
    return ledger


def _entry(name: str, index: int, item: object) -> LedgerEntry:
    where = f"{name} entry {index}"
    if not isinstance(item, dict):
        raise LedgerError(f"{where}: expected a mapping")
    keys = set(item)
    missing, extra = _ENTRY_KEYS - keys, keys - _ENTRY_KEYS
    if missing or extra:
        raise LedgerError(
            f"{where}: missing {sorted(missing)}, unknown {sorted(extra)}"
        )
    for key in ("logger", "template", "level", "explanation"):
        if not isinstance(item[key], str) or not item[key].strip():
            raise LedgerError(f"{where}: {key} must be a non-empty string")
    if item["level"] not in LEDGER_LEVELS:
        raise LedgerError(f"{where}: level must be one of {sorted(LEDGER_LEVELS)}")
    actions = item["actions"]
    if (
        not isinstance(actions, list)
        or not 1 <= len(actions) <= _MAX_ACTIONS
        or not all(isinstance(a, str) and a.strip() for a in actions)
    ):
        raise LedgerError(
            f"{where}: actions must be a list of 1-{_MAX_ACTIONS} non-empty strings"
        )
    return LedgerEntry(
        tpl=template_id(item["logger"], item["template"]),
        logger=item["logger"],
        template=item["template"],
        level=item["level"],
        explanation=" ".join(item["explanation"].split()),
        actions=tuple(" ".join(a.split()) for a in actions),
        source=name,
    )


@dataclass
class CheckReport:
    """How the ledger and the source disagree (design §3.2)."""

    missing: list[CallSite] = field(default_factory=list)
    stale: list[LedgerEntry] = field(default_factory=list)
    level_mismatch: list[tuple[LedgerEntry, str]] = field(default_factory=list)
    problems: list[CallSite] = field(default_factory=list)
    generic: list[CallSite] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Generic templates are reported but are not an error."""
        return not (self.missing or self.stale or self.level_mismatch or self.problems)


def check_ledger(
    ledger: dict[str, LedgerEntry], sites: list[CallSite] | None = None
) -> CheckReport:
    """Compare ``ledger`` with the call sites found in the package source."""
    sites = scan_package() if sites is None else sites
    report = CheckReport(problems=[s for s in sites if s.problem])
    levels: dict[str, set[str]] = {}
    for site in sites:
        if site.problem or site.logger is None or site.template is None:
            continue
        tpl = template_id(site.logger, site.template)
        if tpl not in ledger:
            report.missing.append(site)
        levels.setdefault(tpl, set()).update(site.levels & LEDGER_LEVELS)
        if not site.template.replace("%s", "").replace("%r", "").strip(" :"):
            report.generic.append(site)
    for tpl, entry in ledger.items():
        if tpl not in levels:
            report.stale.append(entry)
            continue
        expected = max(levels[tpl], key=LEVELS.__getitem__)
        if entry.level != expected:
            report.level_mismatch.append((entry, expected))
    return report
