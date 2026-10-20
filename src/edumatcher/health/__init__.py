"""Health beacons: how every long-running process reports itself to pm-monitor.

See docs-design/EduMatcher-Operator-Dashboard.md §7.
"""

from edumatcher.health.reporter import HealthReporter
from edumatcher.health.samples import counter, gauge

__all__ = ["HealthReporter", "counter", "gauge"]
