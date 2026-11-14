from __future__ import annotations

import pytest

from edumatcher.config_gen.symbol_spec import parse_symbol_opts


def test_parse_symbol_opts_basic_override() -> None:
    overrides = parse_symbol_opts(
        specs=["AAPL:tick_decimals=4,static_band=0.15,dynamic_band=0.01"],
        allowed_symbols={"AAPL"},
    )
    assert overrides["AAPL"].tick_decimals == 4
    assert overrides["AAPL"].static_band_pct == 0.15
    assert overrides["AAPL"].dynamic_band_pct == 0.01


def test_parse_symbol_opts_merge_same_symbol() -> None:
    overrides = parse_symbol_opts(
        specs=[
            "TSLA:cb_shift_L1=0.10",
            "TSLA:cb_halt_L1=10,mm_spread_ticks=12,mm_min_qty=300",
        ],
        allowed_symbols={"TSLA"},
    )
    assert overrides["TSLA"].cb_shift["L1"] == 0.10
    assert overrides["TSLA"].cb_halt_mins["L1"] == 10
    assert overrides["TSLA"].mm_spread_ticks == 12
    assert overrides["TSLA"].mm_min_qty == 300


def test_parse_symbol_opts_unknown_key_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown key 'unknown_field'"):
        parse_symbol_opts(
            specs=["AAPL:unknown_field=1"],
            allowed_symbols={"AAPL"},
        )


def test_parse_symbol_opts_unknown_symbol_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown symbol 'MSFT'"):
        parse_symbol_opts(
            specs=["MSFT:tick_decimals=4"],
            allowed_symbols={"AAPL"},
        )
