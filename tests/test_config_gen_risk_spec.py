from __future__ import annotations

import pytest

from edumatcher.config_gen.risk_spec import parse_risk_level_spec


def test_parse_risk_level_spec_full() -> None:
    parsed = parse_risk_level_spec("STRICT:0.12:0.01")
    assert parsed.name == "STRICT"
    assert parsed.static_pct == pytest.approx(0.12)
    assert parsed.dynamic_pct == pytest.approx(0.01)


def test_parse_risk_level_spec_default_dynamic() -> None:
    parsed = parse_risk_level_spec("WIDE:0.40")
    assert parsed.name == "WIDE"
    assert parsed.static_pct == pytest.approx(0.40)
    assert parsed.dynamic_pct == pytest.approx(0.02)


def test_parse_risk_level_invalid_static() -> None:
    with pytest.raises(ValueError, match="static_pct"):
        parse_risk_level_spec("BAD:2.0:0.01")


def test_parse_risk_level_invalid_dynamic() -> None:
    with pytest.raises(ValueError, match="dynamic_pct"):
        parse_risk_level_spec("BAD:0.2:2.0")
