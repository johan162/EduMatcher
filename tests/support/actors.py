from __future__ import annotations

import pytest

from edumatcher.index.calculator import ConstituentConfig, IndexCalculator


@pytest.fixture
def gateway_ids() -> tuple[str, str]:
    return "GW_BUY", "GW_SELL"


@pytest.fixture
def symbol_ticks() -> dict[str, int]:
    return {"AAPL": 2, "BOND": 4}


@pytest.fixture
def single_constituent_index() -> IndexCalculator:
    return IndexCalculator(
        constituents=[
            ConstituentConfig("AAPL", shares_outstanding=1_000_000, initial_price=100.0)
        ],
        base_value=1000.0,
    )
