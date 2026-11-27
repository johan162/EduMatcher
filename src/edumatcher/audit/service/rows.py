"""Row shapes shared by the worker (which writes them into a generation)
and the API (which serves them): an ``/events`` row and the nanosecond rule."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from edumatcher.audit.replay.facts import Fact
from edumatcher.audit.replay.ordering import pack_sort_key
from edumatcher.audit.service.market import epoch_ns


def event_row(f: Fact) -> dict[str, Any]:
    """One fact as an ``/events`` row: canonical key, both clocks' raw values,
    every price with its scale, and where it was read."""
    return {
        "key": pack_sort_key(f).replace("\x1f", "|"),
        "run": f.publisher_run,
        "eseq": f.eseq,
        "topic_seq": f.topic_seq,
        "receipt_ts": f.receipt_raw,
        "receipt_ns": str(epoch_ns(f.receipt_ts)),
        "topic": f.topic,
        "kind": f.kind,
        "symbol": f.symbol,
        "actor": f.actor,
        "msg_id": f.msg_id,
        "causation_id": f.causation_id,
        "correlation_id": f.correlation_id,
        "late": f.late,
        "fields": ns_as_strings(f.payload),
        "prices": [
            {
                "name": p.name,
                "raw": p.raw,
                "display": p.display,
                "tick_decimals": p.tick_decimals,
            }
            for p in f.prices.values()
        ],
        "source": {"file": f.file, "line": f.line_no},
    }


def ns_as_strings(value: Any, key: str = "") -> Any:
    """*value* with every integer under a ``*_ns`` key as a decimal string:
    nanosecond epochs exceed JavaScript's exact integers (design §3.2)."""
    if isinstance(value, Mapping):
        return {k: ns_as_strings(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [ns_as_strings(v, key) for v in value]
    if key.endswith("_ns") and isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return value
