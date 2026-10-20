"""The conftest guard that keeps the suite from beaconing to a real pm-monitor.

Lives apart from ``test_health_reporter.py``, whose module-wide
``real_health_reporter`` marker opts every test there out of the guard.
"""

from __future__ import annotations

from edumatcher.health import HealthReporter


def test_reporters_are_disabled_in_tests_by_default() -> None:
    assert HealthReporter.from_compiled_config("pm-engine") is None
