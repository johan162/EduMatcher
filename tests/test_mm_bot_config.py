"""Tests for mm_bot/config.py and main()'s validation of the settings it loads."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from edumatcher.mm_bot import main as mm_main
from edumatcher.mm_bot.config import load_bot_config


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot read config file"):
        load_bot_config(tmp_path / "missing.yaml")


def test_load_empty_file_configures_nothing(tmp_path: Path) -> None:
    p = tmp_path / "empty.yaml"
    p.write_text("")
    loaded = load_bot_config(p)
    assert loaded.symbols == {} and loaded.defaults == {}


def test_load_not_a_mapping_raises(tmp_path: Path) -> None:
    p = tmp_path / "list.yaml"
    p.write_text("- AAPL\n- MSFT\n")
    with pytest.raises(ValueError, match="must contain a YAML mapping"):
        load_bot_config(p)


def test_load_invalid_yaml_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("symbols: [unclosed\n")
    with pytest.raises(ValueError, match="not valid YAML"):
        load_bot_config(p)


# ------------------------------------------------------------------------
# The flat (pre-version-1) layout is no longer read (review C8, Q5)
# ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, message",
    [
        pytest.param(
            "symbol: AAPL\n", "list the symbols under 'symbols:'", id="symbol"
        ),
        pytest.param(
            "symbols: [AAPL]\ngap: 0.08\n",
            "'gap' is a per-symbol setting; move it under 'defaults:'",
            id="tier2-at-top",
        ),
        pytest.param(
            "symbols: [AAPL]\nid_suffix: 01\n",
            "'id_suffix' is a gateway-wide setting; move it under 'gateway:'",
            id="gateway-key-at-top",
        ),
        pytest.param(
            "symbols: AAPL,MSFT\n",
            "'symbols' must be a mapping of symbol blocks or a list",
            id="comma-string",
        ),
    ],
)
def test_a_flat_file_is_refused_with_a_pointer(
    tmp_path: Path, text: str, message: str
) -> None:
    p = tmp_path / "flat.yaml"
    p.write_text(text)
    with pytest.raises(ValueError, match=message):
        load_bot_config(p)


# ------------------------------------------------------------------------
# main(): gateway-wide and logging values are validated (review C7)
# ------------------------------------------------------------------------


def _run_main(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> tuple[int, Any]:
    started: list[dict[str, Any]] = []

    class FakeBot:
        def __init__(self, **kwargs: Any) -> None:
            started.append(kwargs)

        def run(self) -> int:
            return 0

        def shutdown(self) -> None:
            pass

    monkeypatch.setattr("edumatcher.mm_bot.bot.MMBot", FakeBot)
    monkeypatch.setattr(mm_main, "_configure_logging", lambda args: logging.WARNING)
    with pytest.raises(SystemExit) as exc_info:
        mm_main.main(argv)
    code = exc_info.value.code
    return (code if isinstance(code, int) else 1), (started[0] if started else None)


def _config(tmp_path: Path, text: str) -> str:
    p = tmp_path / "mm.yaml"
    p.write_text(text)
    return str(p)


@pytest.mark.parametrize(
    "block, message",
    [
        pytest.param(
            'gateway:\n  startup_session_timeout_sec: "5"\n',
            "startup_session_timeout_sec must be a number",
            id="quoted-number",
        ),
        pytest.param(
            "gateway:\n  shutdown_timeout_sec: 0\n",
            "shutdown_timeout_sec must be positive",
            id="zero-timeout",
        ),
        pytest.param(
            "logging:\n  level: verbose\n", "level must be one of", id="log-level"
        ),
        pytest.param(
            "logging:\n  target: syslog\n", "target must be one of", id="log-target"
        ),
        pytest.param(
            "gateway:\n  label: 7\n", "label must be a non-empty string", id="label"
        ),
        pytest.param(
            "gateway:\n  engine_pull: 5555\n",
            "engine_pull must be a non-empty string",
            id="engine-pull",
        ),
    ],
)
def test_a_bad_gateway_or_logging_value_stops_the_bot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    block: str,
    message: str,
) -> None:
    path = _config(tmp_path, f"version: 1\n{block}symbols: [AAPL]\n")
    caplog.set_level(logging.CRITICAL)
    code, bot = _run_main(["--config", path], monkeypatch)
    assert code == 1
    assert bot is None
    assert any(message in r.getMessage() for r in caplog.records)


def test_a_lower_case_log_level_in_the_file_is_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _config(tmp_path, "version: 1\nlogging:\n  level: debug\nsymbols: [AAPL]\n")
    code, bot = _run_main(["--config", path], monkeypatch)
    assert code == 0
    assert bot is not None


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["--gap", "nan"], id="gap-nan"),
        pytest.param(["--gap", "inf"], id="gap-inf"),
        pytest.param(["--fade-sec", "nan"], id="fade-nan"),
        pytest.param(["--heartbeat-interval-sec", "inf"], id="heartbeat-inf"),
        pytest.param(["--startup-session-timeout-sec", "nan"], id="session-nan"),
    ],
)
def test_a_non_finite_number_stops_the_bot(
    monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    code, bot = _run_main(["--symbol", "AAPL", *argv], monkeypatch)
    assert code == 1
    assert bot is None
