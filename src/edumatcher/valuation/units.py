"""Typed values ↔ the text the student types (design §19.2).

One parser and one formatter serve the interview, the scenario files and the
report, so a value always round-trips: ``parse(spec, format_value(spec, v, m))``
gives ``v`` back to the precision shown.

* Percentages are typed in points: ``12`` and ``12%`` both mean 12%, and
  ``0.5`` means 0.5%, never 50%.
* Money and counts take ``k``, ``m`` and ``bn`` suffixes, commas and
  underscores: ``40bn``, ``300m``, ``2.5k``, ``90,000,000``, ``1_000``. The
  Swedish ``mkr`` (miljoner) and ``md`` / ``mdr`` (miljard, 1,000 million: an
  English billion, not a Swedish biljon) are accepted too, and are how
  amounts are shown in the Swedish market. Decimals use a point, as in the
  rest of the interview.
* Ratios take an optional ``x`` or ``×``: ``10x``.
* Empty text means "not answered" (the automatic value is used); ``none``
  explicitly empties an optional field.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from edumatcher.valuation.fields import BY_KEY, Const, FieldSpec, Unit


class ParseError(ValueError):
    pass


#: Sentinel for empty text: the student has not answered, so the default applies.
NOT_ANSWERED = object()

_SUFFIX = {"k": 1e3, "m": 1e6, "mkr": 1e6, "bn": 1e9, "md": 1e9, "mdr": 1e9}
_NUMBER = re.compile(
    r"([-+]?\d+(?:\.\d*)?|[-+]?\.\d+)\s*(mdr|md|mkr|bn|k|m)?", re.IGNORECASE
)
_WHOLE = (Unit.COUNT, Unit.YEARS, Unit.DAYS)


def _number(text: str) -> float:
    cleaned = text.replace(",", "").replace("_", "").strip()
    match = _NUMBER.fullmatch(cleaned)
    if match is None:
        raise ParseError(f"{text!r} is not a number")
    value = float(match.group(1))
    if match.group(2):
        value *= _SUFFIX[match.group(2).lower()]
    return value


def parse(spec: FieldSpec, text: str) -> Any:
    """The value *text* stands for, or NOT_ANSWERED when it is empty."""
    text = text.strip()
    if not text:
        return NOT_ANSWERED
    if spec.unit in (Unit.TEXT, Unit.CHOICE):  # verbatim: "none" can be a choice
        return text
    if text.lower() == "none":
        if not spec.optional:
            raise ParseError(f"{spec.label} needs a value")
        return None
    if spec.unit is Unit.BOOL:
        lowered = text.lower()
        if lowered in ("yes", "y", "true", "on"):
            return True
        if lowered in ("no", "n", "false", "off"):
            return False
        raise ParseError(f"{text!r} is not yes or no")
    if spec.unit is Unit.PERCENT:
        return _number(text.removesuffix("%")) / 100
    if spec.unit is Unit.RATIO:
        return _number(text.rstrip("x×X"))
    value = _number(text)
    if spec.unit in _WHOLE:
        if value != int(value):
            raise ParseError(f"{text!r} is not a whole number")
        return int(value)
    return value


#: The suffixes amounts are shown with: Swedish in the Swedish market.
_SHOWN = {"se": (("mdr", 1e9), ("mkr", 1e6))}
_ENGLISH = (("bn", 1e9), ("m", 1e6))
_market_default = BY_KEY["company.market"].default
assert isinstance(_market_default, Const)
_DEFAULT_MARKET: str = _market_default.value


def market_of(values: Mapping[str, Any]) -> str:
    """The market of these answers or values: their own, else the default."""
    return str(values.get("company.market", _DEFAULT_MARKET))


def _compact(value: float, market: str) -> str:
    for suffix, scale in _SHOWN.get(market, _ENGLISH):
        if abs(value) >= scale:
            return f"{value / scale:.6g}{suffix}"
    return f"{value:,.6g}" if value != int(value) else f"{int(value):,}"


def format_value(spec: FieldSpec, value: Any, market: str) -> str:
    """How *value* is shown in *market*, and how it would be typed."""
    if value is None:
        return "none"
    if spec.unit is Unit.BOOL:
        return "yes" if value else "no"
    if spec.unit in (Unit.TEXT, Unit.CHOICE):
        return str(value)
    if spec.unit is Unit.PERCENT:
        return f"{value * 100:.6g}%"
    if spec.unit is Unit.RATIO:
        return f"{value:.6g}x"
    if spec.unit is Unit.MONEY:
        return _compact(value, market)
    if spec.unit in _WHOLE:
        return f"{int(value):,}"
    return f"{value:.6g}"
