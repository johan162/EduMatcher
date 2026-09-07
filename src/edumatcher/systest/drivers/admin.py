"""The Admin Driver, for administrative REST ``/admin/*`` verbs.

Implements session transition, instrument halt, circuit-breaker
trigger/resume, kill switch, and reference reload operations over
``pm-api-gwy``'s REST admin endpoints, restricted to the REST transport for
this spec's scope.

See design.md Components §7 (Admin Driver).
"""
