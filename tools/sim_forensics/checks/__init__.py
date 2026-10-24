"""Check families; importing this package registers every check."""

from sim_forensics.checks import (  # noqa: F401
    bookkeeping,
    derived,
    lifecycle,
    matching,
    trades,
)
