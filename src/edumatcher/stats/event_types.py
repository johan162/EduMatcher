"""The ``order_events.event_type`` vocabulary.

Kept in its own module because both sides need it: ``stats/main.py`` produces
these values, while ``stats/cli.py`` and the API gateway validate filters
against them. Importing the writer from a reader would drag pyzmq and the whole
recorder into a read-only query path.
"""

from __future__ import annotations

#: Recorded when an ack-style event arrives without its ``accepted`` flag.
#: Deliberately *not* REJECT — asserting a rejection the engine never sent
#: would fabricate an audit record. Missing information is recoverable; wrong
#: information is not.
UNKNOWN_EVENT_TYPE = "UNKNOWN"

#: Every value ``_event_type_from_topic`` can produce.
#:
#: Combo, OCO and quote events carry their own accept / reject / cancel /
#: status values rather than collapsing to a bare family name: a rejected
#: combo recorded as plain ``COMBO`` is indistinguishable from an accepted
#: one, and an ``oco.cancelled`` recorded as ``OCO`` cannot be found by any
#: cancel-oriented filter.
EVENT_TYPES = (
    "ACK",
    "REJECT",
    "FILL",
    "AMEND",
    "CANCEL",
    "EXPIRE",
    "COMBO_ACK",
    "COMBO_REJECT",
    "COMBO_STATUS",
    "OCO_ACK",
    "OCO_REJECT",
    "OCO_CANCEL",
    "QUOTE_ACK",
    "QUOTE_REJECT",
    "QUOTE_STATUS",
    UNKNOWN_EVENT_TYPE,
    "EVENT",
)
