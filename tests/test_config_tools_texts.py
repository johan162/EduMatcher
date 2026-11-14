"""Help texts, pm-help entries and generated comments say what the code does.

Each assertion pins a text the 2026-11 review found wrong (§5, D2-D16).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from edumatcher.config_gen import defaults
from edumatcher.config_gen.cli import main as config_gen_main
from edumatcher.config_gen.cli_parser import build_parser
from edumatcher.cverifier.cli import run
from edumatcher.pm_help.registry import get_command


def _help() -> str:
    return " ".join(build_parser().format_help().split())


def _generate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
) -> tuple[str, str]:
    out = tmp_path / "engine_config.yaml"
    monkeypatch.setattr("sys.argv", ["pm-config-gen", *argv, "--output", str(out)])
    config_gen_main()
    return out.read_text(), capsys.readouterr().err


def test_cverifier_pm_help_states_the_exit_codes() -> None:
    cmd = get_command("pm-cverifier")
    assert cmd is not None
    notes = " ".join(cmd.notes)
    assert "Exit 1: warnings" in notes
    assert "Exit 2:" in notes
    assert "--level only filters" in notes


def test_config_gen_pm_help_cb_levels_has_no_mode() -> None:
    cmd = get_command("pm-config-gen")
    assert cmd is not None
    flags = [o.flags for o in cmd.options]
    assert "--cb-levels NAME:SHIFT[:HALT_MINS]" in flags
    sessions = next(o for o in cmd.options if o.flags == "--sessions-enabled")
    assert "absent key means enabled" in sessions.help
    schedule = next(o for o in cmd.options if o.flags.startswith("--schedule"))
    assert "Force" not in schedule.help


def test_unused_cb_ladder_default_is_gone() -> None:
    assert not hasattr(defaults, "DEFAULT_CB_LEVEL_SPECS")


def test_config_gen_help_texts() -> None:
    text = _help()
    assert "Force emit schedule section" not in text
    assert "needs --sessions-enabled" in text
    assert "writes sessions_enabled: false" in text
    assert "HALT_MINS > 0" in text
    for key in ("tick_decimals", "cb_halt_l1", "ace_random_end_ns", "level"):
        assert key in text.split("--symbol-opts SYMBOL:KEY=VALUE[,KEY=VALUE]", 2)[2]
    assert "api_gateway.port" not in text
    assert "api_gateways.<name>.port" in text
    assert "each configured ALF gateway" not in text
    assert "same as omitting the field with retention disabled" not in text
    assert "a null is no reference price" in text


def test_null_last_price_is_not_called_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    yaml_text, err = _generate(
        tmp_path,
        monkeypatch,
        capsys,
        "--symbols",
        "AAPL",
        "--participants",
        "TRADER01",
        "MM01:MARKET_MAKER",
        "--seed-last-prices",
    )
    assert "REQUIRED: set last buy" not in yaml_text
    assert "optional" in yaml_text
    assert "required for collar initialization" not in err


def test_every_section_has_a_heading_and_no_repo_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    yaml_text, _err = _generate(
        tmp_path,
        monkeypatch,
        capsys,
        "--symbols",
        "AAPL",
        "--participants",
        "TRADER01",
        "OPS01:ADMIN",
        "--alf-gateway",
        "--balf-gateway",
        "--log-server",
        "--monitor",
        "--comment-default-config-fields",
    )
    assert "# -- Additional fields --" not in yaml_text
    for heading in (
        "# -- ALF order-entry gateway --",
        "# -- BALF binary order-entry gateway --",
        "# -- Log server --",
        "# -- Health monitor --",
    ):
        assert heading in yaml_text
    assert "../../../docs" not in yaml_text


def test_schedule_diagnostic_states_the_written_times(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _yaml, err = _generate(
        tmp_path,
        monkeypatch,
        capsys,
        "--symbols",
        "AAPL",
        "--participants",
        "TRADER01",
        "OPS01:ADMIN",
        "--sessions-enabled",
        "--pre-open",
        "08:00",
    )
    assert "(08:00-16:05)" in err
    assert "default schedule (09:00-16:05)" not in err


def _verify(tmp_path: Path, body: str) -> dict[str, str]:
    p = tmp_path / "engine_config.yaml"
    p.write_text(textwrap.dedent(body))
    results, _raw = run(p)
    return {r.code: r.suggestion for r in results}


def test_m001_names_a_real_flag(tmp_path: Path) -> None:
    suggestions = _verify(
        tmp_path,
        """
        symbols:
          AAPL: {tick_decimals: 2}
        participants:
          - {id: MM01, role: MARKET_MAKER}
        """,
    )
    assert "--seed-mm-mid-range" in suggestions["M001"]
    assert "--seed-mm " not in suggestions["M001"]


def test_m003_does_not_claim_the_seed_is_rejected(tmp_path: Path) -> None:
    suggestions = _verify(
        tmp_path,
        """
        mm_obligation_defaults: {enforce_mm_obligation: true, mm_max_spread_ticks: 5}
        symbols:
          AAPL:
            tick_decimals: 2
            market_maker_quotes:
              - {gateway_id: MM01, bid_price: 99.0, ask_price: 101.0, bid_qty: 100, ask_qty: 100}
        participants:
          - {id: MM01, role: MARKET_MAKER}
        """,
    )
    assert "immediately rejected" not in suggestions["M003"]
    assert "injects" in suggestions["M003"]
