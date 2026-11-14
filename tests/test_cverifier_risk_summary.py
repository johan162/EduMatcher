"""The Risk Summary states what the engine will enforce.

It is built from the EngineConfig the engine loader produces, so an inline
collar, a symbol-only circuit breaker and a participant's own MM enforcement
are reported as the engine applies them, per symbol.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from edumatcher.cverifier.cli import main

_PARTICIPANTS = """
participants:
  - {id: TRADER01, role: TRADER}
  - {id: OPS01, role: ADMIN, disconnect_behaviour: LEAVE_ALL}
  - {id: MM01, role: MARKET_MAKER, enforce_mm_obligation: true, mm_max_spread_ticks: 30, mm_min_qty: 50}
"""

_QUOTE = (
    "market_maker_quotes: [{gateway_id: MM01, bid_price: %s, ask_price: %s, "
    "bid_qty: 100, ask_qty: 100}]"
)

_SYMBOL_ONLY = """
sessions_enabled: false
symbols:
  AAPL:
    tick_decimals: 2
    last_buy_price: 100.0
    collar: {static_band_pct: 0.1, dynamic_band_pct: 0.02}
    circuit_breaker: {levels: {L1: {price_shift_pct: 0.05, halt_duration_ns: 60000000000}}}
    %s
  MSFT:
    tick_decimals: 2
    last_buy_price: 200.0
    %s
""" % (_QUOTE % ("99.9", "100.1"), _QUOTE % ("199.9", "200.1")) + _PARTICIPANTS

_DEFAULTS = """
sessions_enabled: false
risk_controls:
  default_level: CORE
  levels:
    CORE: {collar: {static_band_pct: 0.2, dynamic_band_pct: 0.025}}
circuit_breaker_defaults:
  levels:
    L1: {price_shift_pct: 0.07, halt_duration_ns: 90000000000}
    L2: {price_shift_pct: 0.13}
symbols:
  AAPL: {tick_decimals: 2, last_buy_price: 100.0, %s}
  MSFT: {tick_decimals: 2, last_buy_price: 200.0, %s}
""" % (_QUOTE % ("99.9", "100.1"), _QUOTE % ("199.9", "200.1")) + _PARTICIPANTS


def _text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], body: str, *extra: str
) -> str:
    p = tmp_path / "engine_config.yaml"
    p.write_text(textwrap.dedent(body))
    with pytest.raises(SystemExit):
        main([str(p), "--no-color", *extra])
    return capsys.readouterr().out


def _line(text: str, label: str) -> str:
    return next(line for line in text.splitlines() if line.startswith(label))


def test_symbol_level_controls_are_reported_per_symbol(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _text(tmp_path, capsys, _SYMBOL_ONLY)
    assert _line(out, "Collars") == (
        "Collars          enabled — 1 of 2 symbols (AAPL: static 10%, dynamic 2%)"
    )
    assert _line(out, "Circuit breakers") == (
        "Circuit breakers enabled — 1 of 2 symbols (AAPL: L1=5% (1 min))"
    )
    assert _line(out, "MM obligations") == "MM obligations   enforced — MM01"


def test_defaults_cover_every_symbol(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _text(tmp_path, capsys, _DEFAULTS)
    assert _line(out, "Collars") == (
        "Collars          enabled — 2 of 2 symbols "
        "(AAPL, MSFT: static 20%, dynamic 2.5%)"
    )
    assert _line(out, "Circuit breakers") == (
        "Circuit breakers enabled — 2 of 2 symbols "
        "(AAPL, MSFT: L1=7% (90 s), L2=13% (rest-of-day))"
    )


def test_file_that_does_not_load_is_marked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    body = _SYMBOL_ONLY.replace("sessions_enabled: false", "engine_tuning: x")
    out = _text(tmp_path, capsys, body)
    assert "Risk Summary (from the file as written; it does not load)" in out


def test_json_carries_the_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _text(tmp_path, capsys, _SYMBOL_ONLY, "--format", "json")
    rs = json.loads(out)["risk_summary"]
    assert rs["collared_symbols"] == ["AAPL"]
    assert rs["circuit_breaker_symbols"] == ["AAPL"]
    assert rs["mm_obligation_gateways"] == ["MM01"]
    assert rs["mm_obligations_enforced"] is True
    assert rs["collars_configured"] is True
    assert rs["circuit_breakers_configured"] is True
    assert rs["loaded"] is True


def test_summary_uses_the_loaded_config_despite_another_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # S121 (an unknown key) is an ERROR the loader does not share: the file
    # still loads, so the summary is the engine's, not the raw reading.
    body = _SYMBOL_ONLY.replace("sessions_enabled: false", "sesions_enabled: false")
    out = _text(tmp_path, capsys, body)
    assert "[S121]" in out
    assert "it does not load" not in out
    assert _line(out, "Collars").startswith("Collars          enabled — 1 of 2 symbols")


def test_collar_without_a_reference_price_is_marked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The engine registers a collar only when it starts with a reference
    # price (engine/main.py, collar wiring); the file gives MSFT none.
    body = _DEFAULTS.replace(
        "MSFT: {tick_decimals: 2, last_buy_price: 200.0,", "MSFT: {tick_decimals: 2,"
    )
    out = _text(tmp_path, capsys, body)
    assert _line(out, "Collars") == (
        "Collars          enabled — 2 of 2 symbols (AAPL: static 20%, "
        "dynamic 2.5%; MSFT: static 20%, dynamic 2.5%, no reference price "
        "in the file)"
    )
