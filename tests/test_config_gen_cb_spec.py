from __future__ import annotations

import pytest

from edumatcher.config_gen.cb_spec import parse_cb_spec


def test_parse_cb_spec_with_halt() -> None:
    parsed = parse_cb_spec("L1:0.07:5")
    assert parsed.name == "L1"
    assert parsed.shift_pct == pytest.approx(0.07)
    assert parsed.halt_mins == 5


def test_parse_cb_spec_rest_of_day() -> None:
    parsed = parse_cb_spec("L3:0.20")
    assert parsed.name == "L3"
    assert parsed.halt_mins is None


def test_parse_cb_spec_invalid_shift() -> None:
    with pytest.raises(ValueError, match=r"in \(0, 1\)"):
        parse_cb_spec("L1:1.2:5")


def test_parse_cb_spec_invalid_halt() -> None:
    with pytest.raises(ValueError, match="halt_mins"):
        parse_cb_spec("L1:0.07:-1")
