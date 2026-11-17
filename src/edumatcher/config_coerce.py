"""Strict coercion for YAML configuration sections.

``int(5565.9)`` is ``5565``, ``float("nan") <= 0`` is ``False`` and
``bool("false")`` is ``True``, so the lenient ``int()``/``float()``/``bool()``
calls each config module used to carry let a typo through as a silently
different port, as a timeout that never fires, or as a switch turned on.
These helpers reject any value that would lose information instead.

*label* is the dotted path the operator wrote in ``engine_config.yaml``, so
the error names the key they need to fix.
"""

from __future__ import annotations

import math

_SCALAR = (int, float, str, bytes, bytearray)


def as_int(raw: object, label: str) -> int:
    """Coerce *raw* to ``int``, rejecting non-integral and non-finite values."""
    if isinstance(raw, bool) or not isinstance(raw, _SCALAR):
        raise ValueError(f"{label} must be an integer")
    if isinstance(raw, int):
        return int(raw)
    if isinstance(raw, (str, bytes, bytearray)):
        try:
            # Exactly first: float() rounds anything past 2**53, so
            # "9007199254740993" would be accepted as a different number.
            return int(raw)
        except ValueError:
            pass  # not a plain integer literal; "1e3" still goes via float
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if not math.isfinite(value) or value != int(value):
        raise ValueError(f"{label} must be an integer")
    return int(value)


def as_float(raw: object, label: str, *, positive: bool = False) -> float:
    """Coerce *raw* to a finite ``float``; optionally require it to be > 0.

    The finiteness check has to come first: ``nan <= 0`` is ``False``, so a
    NaN would otherwise pass the positivity check and then make every
    comparison against it false for the lifetime of the process.
    """
    if isinstance(raw, bool) or not isinstance(raw, _SCALAR):
        raise ValueError(f"{label} must be a number")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
    if not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if positive and value <= 0:
        raise ValueError(f"{label} must be > 0")
    return value


def as_bool(raw: object, label: str) -> bool:
    """Require a YAML boolean: ``bool("false")`` is ``True``."""
    if not isinstance(raw, bool):
        raise ValueError(f"{label} must be true or false, got {raw!r}")
    return raw


def as_str(raw: object, label: str) -> str:
    """Require a string: ``str(5)`` would turn a misplaced number into a name."""
    if not isinstance(raw, str):
        raise ValueError(f"{label} must be a string, got {raw!r}")
    return raw
