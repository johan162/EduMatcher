from __future__ import annotations

from edumatcher.config_gen.symbol_spec import parse_symbol_opts


def test_parse_symbol_opts_basic_override() -> None:
    overrides, warnings = parse_symbol_opts(
        specs=["AAPL:tick_decimals=4,static_band=0.15,dynamic_band=0.01"],
        allowed_symbols={"AAPL"},
    )
    assert warnings == []
    assert overrides["AAPL"].tick_decimals == 4
    assert overrides["AAPL"].static_band_pct == 0.15
    assert overrides["AAPL"].dynamic_band_pct == 0.01


def test_parse_symbol_opts_merge_same_symbol() -> None:
    overrides, warnings = parse_symbol_opts(
        specs=[
            "TSLA:cb_shift_L1=0.10",
            "TSLA:cb_halt_L1=10,mm_spread_ticks=12,mm_min_qty=300",
        ],
        allowed_symbols={"TSLA"},
    )
    assert warnings == []
    assert overrides["TSLA"].cb_shift["L1"] == 0.10
    assert overrides["TSLA"].cb_halt_mins["L1"] == 10
    assert overrides["TSLA"].mm_spread_ticks == 12
    assert overrides["TSLA"].mm_min_qty == 300


def test_parse_symbol_opts_unknown_key_warns() -> None:
    _, warnings = parse_symbol_opts(
        specs=["AAPL:unknown_field=1"],
        allowed_symbols={"AAPL"},
    )
    assert any("Unknown --symbol-opts key" in msg for msg in warnings)


def test_parse_symbol_opts_unknown_symbol_warns() -> None:
    overrides, warnings = parse_symbol_opts(
        specs=["MSFT:tick_decimals=4"],
        allowed_symbols={"AAPL"},
    )
    assert overrides == {}
    assert any("unknown symbol" in msg.lower() for msg in warnings)
