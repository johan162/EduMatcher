"""pm-config-gen refuses NaN and infinity in every numeric option.

``float()`` accepts "nan" and "inf", and NaN passes every ``x <= 0`` check, so
without an explicit test pm-config-gen writes ``.nan`` into the file (or ends
in a traceback when a later step converts it to an integer).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edumatcher.config_gen.cli import main as config_gen_main

_BASE = ["--symbols", "AAPL", "--participants", "TRADER01", "OPS01:ADMIN"]
_MM = ["--symbols", "AAPL", "--participants", "TRADER01", "MM01:MARKET_MAKER"]
_INDEX = [
    "--symbols",
    "AAPL",
    "--participants",
    "TRADER01",
    "MM01:MARKET_MAKER",
    "--seed-mm-mid-range",
    "10:20",
    "--seed-last-prices-from-mm",
    "--outstanding-shares",
    "AAPL:1000",
    "--index",
    "OMX",
    "--index-constituents",
    "OMX:AAPL",
]

_CASES = [
    (_BASE + ["--snapshot-interval", "nan"], "--snapshot-interval"),
    (_BASE + ["--snapshot-interval", "inf"], "--snapshot-interval"),
    (
        _BASE + ["--api-gateway", "--api-gateway-wait-ack-sec", "nan"],
        "--api-gateway-wait-ack-sec",
    ),
    (
        _BASE + ["--monitor", "--monitor-beacon-interval-sec", "inf"],
        "--monitor-beacon-interval-sec",
    ),
    (_INDEX + ["--index-base-value", "OMX:nan"], "--index-base-value"),
    (_INDEX + ["--index-base-value", "OMX:inf"], "--index-base-value"),
    (_INDEX + ["--index-interval", "OMX:nan"], "--index-interval"),
    (_MM + ["--seed-mm-mid-range", "10:inf"], "--seed-mm-mid-range"),
    (_MM + ["--seed-mm-mid-range", "nan:20"], "--seed-mm-mid-range"),
    (_BASE + ["--symbol-max-order-value", "AAPL:inf"], "--symbol-max-order-value"),
    (_BASE + ["--monitor-threshold", "host_cpu_pct:nan:90"], "--monitor-threshold"),
    (
        [
            "--symbols",
            "AAPL",
            "MSFT",
            "--participants",
            "TRADER01",
            "OPS01:ADMIN",
            "--combo",
            "C1:AON:DAY:AAPL/BUY/LIMIT/1/inf,MSFT/SELL/LIMIT/1/10.00",
        ],
        "--combo",
    ),
]


@pytest.mark.parametrize(
    ("argv", "flag"), _CASES, ids=[" ".join(a[-2:]) for a, _f in _CASES]
)
def test_non_finite_option_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    flag: str,
) -> None:
    out = tmp_path / "engine_config.yaml"
    monkeypatch.setattr("sys.argv", ["pm-config-gen", *argv, "--output", str(out)])
    with pytest.raises(SystemExit) as exc:
        config_gen_main()
    assert exc.value.code == 2
    assert flag in capsys.readouterr().err
    assert not out.exists()
