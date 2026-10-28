"""Check families; importing this package registers every check."""

from sim_forensics.checks import (  # noqa: F401
    bookkeeping,
    completeness,
    coverage,
    cumulative,
    derived,
    differential,
    immediate,
    lifecycle,
    matching,
    ops,
    persistence,
    quotes,
    rerun,
    trades,
)
