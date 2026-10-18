"""Constructors for the application metrics a process puts in its beacon.

Two functions, not a metrics framework: a process keeps its counters however
it already does (a dict, an attribute) and turns them into samples once per
beacon interval with these. The returned records are the generated
``MetricSample`` of ``spec/messages/health.yaml``; they are validated in the
reporter's sampler thread, where an invalid one is dropped and counted rather
than allowed to stop the beacon.
"""

from __future__ import annotations

from edumatcher.models.generated.health import MetricSample


def counter(name: str, value: float, label: str = "") -> MetricSample:
    """A monotonic count since process start, e.g. ``engine.orders_in``."""
    return MetricSample(name=name, kind="COUNTER", label=label, value=float(value))


def gauge(name: str, value: float, label: str = "") -> MetricSample:
    """A level at the time of sampling, e.g. ``md.clients``."""
    return MetricSample(name=name, kind="GAUGE", label=label, value=float(value))
