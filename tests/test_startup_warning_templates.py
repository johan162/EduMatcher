"""pm-board / pm-orders replay their import-time warnings with constant templates.

The log ledger keys a row on its unformatted template (record.msg), so a
warning collected before logging is configured must keep the format string
and its arguments apart (docs-design/EduMatcher-Log-Ledger.md §2.2).
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "module_name", ["edumatcher.board.main", "edumatcher.orders.main"]
)
def test_missing_engine_config_is_logged_with_a_constant_template(
    module_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mod = importlib.import_module(module_name)
    missing = tmp_path / "nowhere" / "engine_config.json"
    monkeypatch.setattr(mod, "COMPILED_CONFIG_FILE", missing)
    monkeypatch.chdir(tmp_path)

    decimals, warnings = mod._load_tick_decimals()
    assert decimals == {}
    assert len(warnings) == 1

    with caplog.at_level(logging.WARNING, logger=module_name):
        mod._log_startup_warnings(warnings)

    (record,) = caplog.records
    assert "%s" in record.msg  # the template, not the formatted text
    assert str(missing) not in record.msg
    assert str(missing) in record.getMessage()
