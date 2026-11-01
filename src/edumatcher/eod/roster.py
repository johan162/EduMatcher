"""``roster.yaml`` — which person runs which gateway.

::

    traders:
      - gateway: GW_ALICE
        name: Alice Andersson
        email: alice@example.org      # printed on the statement, never used to send
        opening_balance: 0            # display currency, at most 2 decimals

A missing file is an empty roster: every statement is then keyed by gateway id.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from edumatcher.eod.settle import EXCHANGE

_KEYS = {"gateway", "name", "email", "opening_balance"}


class RosterError(ValueError):
    """The roster file is unusable; the message names the line."""


@dataclass(frozen=True)
class Trader:
    gateway: str
    name: str
    email: str | None
    opening_minor: int


def load_roster(path: Path) -> dict[str, Trader]:
    """Read the roster, keyed by upper-cased gateway id."""
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict) or "traders" not in data:
        raise RosterError(f"{path}: line 1: expected a 'traders' list")
    items = data["traders"]
    if not isinstance(items, list):
        raise RosterError(f"{path}: line 1: 'traders' must be a list")
    lines = _item_lines(text)
    roster: dict[str, Trader] = {}
    for index, item in enumerate(items):
        line = lines[index] if index < len(lines) else 1
        trader = _trader(path, line, item)
        if trader.gateway in roster:
            raise RosterError(
                f"{path}: line {line}: duplicate gateway {trader.gateway}"
            )
        roster[trader.gateway] = trader
    return roster


def _item_lines(text: str) -> list[int]:
    """1-based line of each entry under ``traders``."""
    root = yaml.compose(text)
    if not isinstance(root, yaml.MappingNode):
        return []
    for key, value in root.value:
        if key.value == "traders" and isinstance(value, yaml.SequenceNode):
            return [node.start_mark.line + 1 for node in value.value]
    return []


def _trader(path: Path, line: int, item: Any) -> Trader:
    where = f"{path}: line {line}"
    if not isinstance(item, dict):
        raise RosterError(f"{where}: each trader must be a mapping")
    unknown = sorted(set(item) - _KEYS)
    if unknown:
        raise RosterError(f"{where}: unknown key {unknown[0]}")
    gateway = str(item.get("gateway") or "").strip().upper()
    if not gateway:
        raise RosterError(f"{where}: a trader needs a gateway")
    if gateway == EXCHANGE:
        raise RosterError(f"{where}: a gateway may not be called {EXCHANGE}")
    return Trader(
        gateway,
        str(item.get("name") or gateway),
        str(item["email"]) if item.get("email") else None,
        _opening(where, item.get("opening_balance", 0)),
    )


def _opening(where: str, value: Any) -> int:
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise RosterError(f"{where}: opening_balance must be a number") from None
    if not amount.is_finite():  # YAML .inf / .nan
        raise RosterError(f"{where}: opening_balance must be a number")
    minor = amount * 100
    if minor != minor.to_integral_value():
        raise RosterError(f"{where}: opening_balance has more than 2 decimals")
    return int(minor)
