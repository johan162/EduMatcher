"""
models/instrument.py — Per-symbol trading-state enum.

Used by the engine to track whether a symbol is in normal ACTIVE matching
or HALTED (circuit breaker fired, no new matching allowed).

Why a separate module?
----------------------
The halt state is a *runtime* classification that crosses module boundaries:
- engine/main.py sets/clears it when a circuit breaker fires or resumes
- engine/collar.py reads it to decide whether to validate prices
- tests can import it without importing the full engine

Having one canonical enum avoids scattered ``"HALTED"`` strings and makes
mypy's exhaustive-match checking work on any future ``match`` statements.
"""

from __future__ import annotations

from enum import Enum


class InstrumentState(str, Enum):
    ACTIVE = "ACTIVE"  # normal continuous matching
    HALTED = "HALTED"  # circuit breaker fired; no matching; new quotes rejected
