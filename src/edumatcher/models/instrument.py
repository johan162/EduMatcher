"""
models/instrument.py — Per-symbol trading-state enum.

Names the two states a symbol can be in: normal ACTIVE matching, or HALTED
(circuit breaker fired or operator halt; no matching).

Nothing in ``src/`` uses it. The engine keeps the halt state as
``Engine._halted_symbols`` (a bool per symbol), and the operator guide's
risk-controls chapter shows this enum only as the state model it describes.
"""

from __future__ import annotations

from enum import Enum


class InstrumentState(str, Enum):
    ACTIVE = "ACTIVE"  # normal continuous matching
    HALTED = "HALTED"  # circuit breaker fired; no matching; new quotes rejected
