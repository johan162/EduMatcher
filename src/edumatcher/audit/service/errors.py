"""Typed failures of the Audit GUI's read models; the router maps each to a
status (design §8.1). Nothing here knows HTTP."""

from __future__ import annotations

from edumatcher.audit.service.capabilities import Reason


class UnknownEntity(LookupError):
    """The snapshot holds no record of this entity (order, symbol, ...)."""


class CapabilityUnavailable(Exception):
    """The snapshot's evidence cannot support this analysis."""

    def __init__(self, reason: Reason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class EmptyWindow(ValueError):
    """The requested time window holds no time: ``from`` is not before ``to``."""
