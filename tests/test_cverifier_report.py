"""The report's counts, codes and messages agree with each other.

The per-layer lines count by severity, so they sum to the verdict; a skipped
layer names the layer that stopped it; a file that did not load gets no Risk
Summary; one defect is one finding under one code.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from edumatcher.config_gen.cli import main as config_gen_main
from edumatcher.cverifier.cli import main, run


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "engine_config.yaml"
    p.write_text(textwrap.dedent(body))
    return p


def _out(tmp_path: Path, capsys: pytest.CaptureFixture[str], body: str) -> str:
    p = _write(tmp_path, body)
    with pytest.raises(SystemExit):
        main([str(p), "--no-color"])
    return capsys.readouterr().out


def _codes(path: Path) -> list[str]:
    results, _raw = run(path)
    return [r.code for r in results]


def test_layer_lines_count_by_severity_and_sum_to_the_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Semantic: M013 (WARN), M004 (INFO). Completeness: C001 (WARN), C003,
    # C004 and C007 (INFO).
    out = _out(
        tmp_path,
        capsys,
        """
        symbols:
          AAPL: {tick_decimals: 2}
        participants:
          - {id: TRADER01, role: TRADER}
        """,
    )
    assert "⚠ Semantic: 1 warning, 1 advisory" in out
    assert "⚠ Completeness: 1 warning, 3 advisories" in out
    assert "2 WARNINGS, 4 ADVISORIES" in out


def test_yaml_error_skips_with_the_right_reason_and_no_risk_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _out(tmp_path, capsys, "key: [unclosed\n")
    assert "Schema: skipped (fix the YAML error first)" in out
    assert "Risk Summary" not in out


def test_missing_file_has_no_risk_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        main([str(tmp_path / "nope.yaml"), "--no-color"])
    assert exc.value.code == 2
    out = capsys.readouterr().out
    assert "Risk Summary" not in out
    assert "Schema: skipped (fix the YAML error first)" in out


def test_schema_error_skip_reason_is_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = _out(tmp_path, capsys, "participants:\n  - {id: OPS01, role: ADMIN}\n")
    assert "Semantic: skipped (fix schema errors first)" in out


def test_locale_country_has_its_own_code(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        symbols:
          AAPL: {tick_decimals: 2}
        participants:
          - {id: OPS01, role: ADMIN}
        locale: {country: 5}
        """,
    )
    codes = _codes(p)
    assert "S134" in codes
    assert "S065" not in codes


def test_prefix_ids_without_alf_gateway_are_one_finding(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        symbols:
          AAPL: {tick_decimals: 2}
        participants:
          - {id: TRADER1, role: TRADER}
          - {id: TRADER10, role: TRADER}
        """,
    )
    codes = _codes(p)
    assert "S084" in codes
    assert "S081" not in codes


def test_broken_alf_gateway_is_still_s081(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        symbols:
          AAPL: {tick_decimals: 2}
        participants:
          - {id: TRADER01, role: TRADER}
        alf_gateway: {heartbeat_interval_sec: 0}
        """,
    )
    assert "S081" in _codes(p)


def test_no_m032_without_api_gateways(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
        symbols:
          AAPL: {tick_decimals: 2}
        participants:
          - {id: OPS01, role: ADMIN}
        """,
    )
    assert "M032" not in _codes(p)


def _generate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *extra: str
) -> list[dict[str, object]]:
    out = tmp_path / "engine_config.yaml"
    monkeypatch.setattr(
        "sys.argv",
        [
            "pm-config-gen",
            "--symbols",
            "AAPL",
            "--participants",
            "TRADER01",
            "OPS01:ADMIN",
            "--api-gateway",
            *extra,
            "--output",
            str(out),
        ],
    )
    config_gen_main()
    cfg = yaml.safe_load(out.read_text())
    credentials: list[dict[str, object]] = cfg["api_gateways"]["default"]["credentials"]
    return credentials


def test_config_gen_api_gateway_writes_a_readonly_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credentials = _generate(tmp_path, monkeypatch)
    assert any(c["gateway_id"] is None for c in credentials)
    assert "M032" not in _codes(tmp_path / "engine_config.yaml")


def test_config_gen_readonly_key_can_be_suppressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credentials = _generate(tmp_path, monkeypatch, "--no-api-gateway-readonly-key")
    assert all(c["gateway_id"] is not None for c in credentials)
