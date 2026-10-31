"""WP-API17: pm-alf-console shows each structure cancel's own outcome.

The console subscribes to the engine directly, so it follows the move of
cancel outcomes onto ``oco.cancel_ack``, ``combo.cancel_ack`` and
``quote.cancel_ack``; before, a refusal arrived disguised as a submit ack and
a successful OCO cancel printed nothing at all.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from tests.test_alf_console_quote_ack import _make_gateway


@pytest.mark.parametrize(
    ("topic", "payload", "expected"),
    [
        ("oco.cancel_ack.GW01",
         {"oco_id": "O1", "accepted": True, "cancelled_order_ids": ["a", "b"]},
         "OCO CXL OK"),
        ("combo.cancel_ack.GW01",
         {"combo_id": "C1", "accepted": False, "reason": "Combo not found",
          "reject_code": "ORDER_NOT_FOUND"},
         "COMBO CXL REJ"),
        ("quote.cancel_ack.GW01",
         {"symbol": "AAPL", "quote_id": "Q1", "accepted": True,
          "cancelled_order_ids": ["x", "y"]},
         "QUOTE CXL OK"),
    ],
)  # fmt: skip
def test_cancel_acks_are_rendered(
    topic: str, payload: dict[str, Any], expected: str
) -> None:
    gw, _ = _make_gateway()
    with patch("edumatcher.alf_console.main.console.print") as mock_print:
        gw._handle_event(topic, payload)
    (line,) = [str(c.args[0]) for c in mock_print.call_args_list]
    assert expected in line
