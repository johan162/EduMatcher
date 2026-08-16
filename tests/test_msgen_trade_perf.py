"""Hot-path cost of the generated trade constructor.

Phase 2 put ``make_trade_executed_unchecked`` on ``engine/main.py::
_publish_trade``, which runs once per match. ``docs-design/perf-notes.md``
records publication optimisations worth 0.2-1.0 us each, so a regression here
would quietly undo them.

Marked ``perf`` and deselected by default (``pytest -m perf`` to run), matching
the existing convention. The bound is deliberately loose: this is a guard
against an order-of-magnitude regression - the shape the constructor had before
design section 8.2 reshaped it, which measured 4x the hand-written literal - not
a benchmark. Timing on shared CI is far too noisy for a tight threshold.
"""

from __future__ import annotations

import timeit
from typing import Any

import pytest

from edumatcher.models.generated.trade import make_trade_executed_unchecked
from edumatcher.models.message import dumps

pytestmark = pytest.mark.perf

_SAMPLE: dict[str, Any] = {
    "id": "42",
    "symbol": "ACME",
    "buy_order_id": "b-1",
    "sell_order_id": "s-1",
    "buy_gateway_id": "GW1",
    "sell_gateway_id": "GW2",
    "price": 101.5,
    "quantity": 300,
    "aggressor_side": "BUY",
    "timestamp": 1_700_000_000.0,
    "tick_decimals": 2,
}

_TOPIC = b"trade.executed"

#: How many times slower than the hand-written literal the generated
#: constructor may be. Measured at ~1.5x on a quiet machine; the pre-8.2 shape
#: measured ~4.2x, so this catches a reversion to it while tolerating a very
#: noisy runner.
_MAX_RATIO = 3.0

_ITERATIONS = 20_000


def _hand_written_baseline() -> list[bytes]:
    """The dict literal ``_publish_trade`` used before Phase 2 adopted the spec."""
    return [
        _TOPIC,
        dumps(
            {
                "id": _SAMPLE["id"],
                "symbol": _SAMPLE["symbol"],
                "buy_order_id": _SAMPLE["buy_order_id"],
                "sell_order_id": _SAMPLE["sell_order_id"],
                "buy_gateway_id": _SAMPLE["buy_gateway_id"],
                "sell_gateway_id": _SAMPLE["sell_gateway_id"],
                "price": _SAMPLE["price"],
                "tick_decimals": _SAMPLE["tick_decimals"],
                "quantity": _SAMPLE["quantity"],
                "aggressor_side": _SAMPLE["aggressor_side"],
                "timestamp": _SAMPLE["timestamp"],
            }
        ),
    ]


def _generated() -> list[bytes]:
    return make_trade_executed_unchecked(**_SAMPLE)


def _best_of_three(fn: Any) -> float:
    """Return the fastest of three runs, in microseconds per call.

    Best-of, not mean: a slow run means the machine was busy, which says
    nothing about the code. The fastest observation is the least contaminated.
    """
    return (
        min(timeit.repeat(fn, repeat=3, number=_ITERATIONS)) / _ITERATIONS * 1_000_000
    )


def test_generated_constructor_is_within_budget() -> None:
    baseline = _best_of_three(_hand_written_baseline)
    generated = _best_of_three(_generated)
    ratio = generated / baseline
    assert ratio < _MAX_RATIO, (
        f"generated constructor is {ratio:.1f}x the hand-written literal "
        f"({generated:.2f} us vs {baseline:.2f} us), over the {_MAX_RATIO}x "
        "budget. If this is the from_dict/dataclass/to_dict route returning, "
        "see design section 8.2."
    )


def test_the_baseline_and_the_generated_form_agree() -> None:
    """A perf comparison is meaningless if the two do different work."""
    import json

    hand = json.loads(_hand_written_baseline()[1])
    generated = json.loads(_generated()[1])
    assert hand == generated
