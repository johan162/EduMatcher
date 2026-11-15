"""Checks whose failure stops a process from starting are ERRORs.

pm-scheduler exits at start-up on schedule times that are not strictly
increasing, and pm-index raises for a constituent without a reference
price. pm-config-deploy is the last place to stop such a file, and it blocks
on ERROR only.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from edumatcher.config_deploy import CompileError, compile_config
from edumatcher.cverifier.cli import main, run
from edumatcher.cverifier.models import Severity

_PARTICIPANTS = """
participants:
  - {id: TRADER01, role: TRADER}
  - {id: OPS01, role: ADMIN, disconnect_behaviour: LEAVE_ALL}
"""


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "engine_config.yaml"
    p.write_text(textwrap.dedent(body) + _PARTICIPANTS)
    return p


def _schedule(continuous: str) -> str:
    return f"""
        sessions_enabled: true
        symbols:
          AAPL: {{tick_decimals: 2, last_buy_price: 100.0}}
        schedule:
          weekdays:
            pre_open: "09:00"
            opening_auction_start: "09:25"
            continuous_start: "{continuous}"
            closing_auction_start: "16:00"
            closing_auction_end: "16:05"
        """


def _index(price_line: str) -> str:
    return f"""
        sessions_enabled: false
        symbols:
          AAPL: {{tick_decimals: 2, outstanding_shares: 1000{price_line}}}
        indices:
          - {{id: OMX, description: Test, constituents: [AAPL]}}
        """


def _severity(path: Path, code: str) -> Severity | None:
    results, _raw = run(path)
    found = [r.severity for r in results if r.code == code]
    return found[0] if found else None


def test_out_of_order_schedule_is_an_error_and_is_not_deployed(
    tmp_path: Path,
) -> None:
    p = _write(tmp_path, _schedule("16:30"))
    assert _severity(p, "M006") is Severity.ERROR
    with pytest.raises(SystemExit) as exc:
        main([str(p), "--no-color"])
    assert exc.value.code == 2
    with pytest.raises(CompileError):
        compile_config(p)


def test_ordered_schedule_is_unchanged(tmp_path: Path) -> None:
    p = _write(tmp_path, _schedule("09:30"))
    assert _severity(p, "M006") is None
    compile_config(p)


def test_constituent_without_reference_price_is_an_error(tmp_path: Path) -> None:
    p = _write(tmp_path, _index(""))
    assert _severity(p, "C008") is Severity.ERROR
    with pytest.raises(CompileError):
        compile_config(p)


def test_priced_constituent_is_unchanged(tmp_path: Path) -> None:
    p = _write(tmp_path, _index(", last_buy_price: 100.0"))
    assert _severity(p, "C008") is None
    compile_config(p)
