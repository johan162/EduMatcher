"""Strict numeric coercion for YAML configuration sections.

``int(5565.9)`` is ``5565`` and ``float("nan") <= 0`` is ``False``, so the
lenient ``int()``/``float()`` calls each config module used to carry let a
typo through as a silently different port, or as a timeout that never fires.
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
