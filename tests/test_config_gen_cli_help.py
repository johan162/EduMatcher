from __future__ import annotations

import subprocess


def test_pm_config_gen_help_runs() -> None:
    result = subprocess.run(
        ["poetry", "run", "pm-config-gen", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "pm-config-gen" in result.stdout
    assert "--symbols" in result.stdout
    assert "--seed-mm-mid-range" in result.stdout
    assert "--seed-last-prices-from-mm" in result.stdout
    assert "--comment-default-config-fields" in result.stdout
    assert "--symbol-static-band" in result.stdout
    assert "--symbol-dynamic-band" in result.stdout
    assert "--symbol-risk-level" in result.stdout
    assert "--api-gateway" in result.stdout
    assert "--api-gateway-name" in result.stdout
    assert "--api-gateway-instance" in result.stdout
    assert "--api-key" in result.stdout
    assert "--api-gateway-readonly-key" in result.stdout
    assert "--index" in result.stdout
    assert "--index-constituents" in result.stdout
