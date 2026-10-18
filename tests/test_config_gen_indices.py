"""pm-config-gen --index* flags: what they emit, and what they refuse.

Every refusal here used to be accepted, and each one produced a config that
either failed validation or that pm-index could not start on -- while
pm-config-gen still exited 0.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from edumatcher.config_gen.cli import main as config_gen_main
from edumatcher.index.config_loader import load_index_runtime_configs

_SHARES = [
    "--outstanding-shares",
    "AAPL:15400000000",
    "--outstanding-shares",
    "MSFT:7430000000",
    "--outstanding-shares",
    "JPM:2800000000",
]
# The only way pm-config-gen emits real last prices, which pm-index needs to
# compute an index's initial divisor.
_PRICES = ["--seed-mm-mid-range", "20:300", "--seed-last-prices-from-mm"]


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *extra: str) -> Path:
    out = tmp_path / "engine_config.yaml"
    monkeypatch.setattr(
        "sys.argv",
        [
            "pm-config-gen",
            "--symbols",
            "AAPL",
            "MSFT",
            "JPM",
            "--participants",
            "TRADER01:TRADER",
            "OPS01:ADMIN",
            "MM01:MARKET_MAKER",
            "--seed",
            "1",
            "--output",
            str(out),
            *extra,
        ],
    )
    config_gen_main()
    return out


def _refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *extra: str,
) -> str:
    with pytest.raises(SystemExit) as exc:
        _run(tmp_path, monkeypatch, *extra)
    assert exc.value.code == 2
    assert not (tmp_path / "engine_config.yaml").exists()
    return capsys.readouterr().err


def test_every_index_flag_reaches_the_config_and_pm_index_loads_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = _run(
        tmp_path,
        monkeypatch,
        *_SHARES,
        *_PRICES,
        "--index",
        "edu100:Tech: large caps",
        "--index-constituents",
        "EDU100:aapl,MSFT",
        "--index-base-value",
        "EDU100:500",
        "--index",
        "FIN",
        "--index-constituents",
        "FIN:JPM",
        "--index-interval",
        "FIN:2.5",
        "--index-history-file",
        "FIN:data/x/fin_history.jsonl",
        "--index-state-file",
        "FIN:data/x/fin_state.json",
    )

    indices = yaml.safe_load(out.read_text())["indices"]
    assert indices == [
        {
            "id": "EDU100",
            "description": "Tech: large caps",
            "base_value": 500.0,
            "publish_interval_sec": 1.0,
            "history_file": "data/indexes/EDU100_history.jsonl",
            "state_file": "data/indexes/EDU100_state.json",
            "constituents": ["AAPL", "MSFT"],
        },
        {
            "id": "FIN",
            "description": "Index FIN",
            "base_value": 1000.0,
            "publish_interval_sec": 2.5,
            "history_file": "data/x/fin_history.jsonl",
            "state_file": "data/x/fin_state.json",
            "constituents": ["JPM"],
        },
    ]
    loaded = load_index_runtime_configs(out)
    assert [(c.id, c.base_value) for c in loaded] == [
        ("EDU100", 500.0),
        ("FIN", 1000.0),
    ]


@pytest.mark.parametrize(
    "prices",
    [[], ["--seed-last-prices"]],
    ids=["no-prices", "null-placeholders"],
)
def test_constituents_without_a_reference_price_are_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    prices: list[str],
) -> None:
    err = _refused(
        tmp_path,
        monkeypatch,
        capsys,
        *_SHARES,
        *prices,
        "--index",
        "EDU100",
        "--index-constituents",
        "EDU100:AAPL,MSFT",
    )
    assert "constituent(s) AAPL, MSFT have no reference price" in err
    assert "--seed-last-prices-from-mm" in err


@pytest.mark.parametrize("index_id", ["EDU-100", "EDU_100", "ÉDU100"])
def test_index_ids_must_be_letters_and_digits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    index_id: str,
) -> None:
    err = _refused(
        tmp_path,
        monkeypatch,
        capsys,
        *_SHARES,
        *_PRICES,
        "--index",
        index_id,
        "--index-constituents",
        f"{index_id}:AAPL",
    )
    assert "id must contain only letters and digits" in err


def test_index_detail_flags_without_index_are_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    err = _refused(
        tmp_path,
        monkeypatch,
        capsys,
        *_SHARES,
        *_PRICES,
        "--index-constituents",
        "EDU100:AAPL",
        "--index-interval",
        "EDU100:2",
    )
    assert "--index-constituents, --index-interval given without --index" in err


@pytest.mark.parametrize(
    "flag, first, second",
    [
        ("--index-constituents", "EDU100:AAPL", "EDU100:MSFT"),
        ("--index-base-value", "EDU100:100", "edu100:200"),
        ("--index-interval", "EDU100:1", "EDU100:2"),
        ("--index-history-file", "EDU100:a.jsonl", "EDU100:b.jsonl"),
        ("--index-state-file", "EDU100:a.json", "EDU100:b.json"),
    ],
)
def test_repeating_a_per_index_flag_for_the_same_index_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flag: str,
    first: str,
    second: str,
) -> None:
    base = ["--index", "EDU100"]
    if flag != "--index-constituents":
        base += ["--index-constituents", "EDU100:AAPL"]
    err = _refused(
        tmp_path,
        monkeypatch,
        capsys,
        *_SHARES,
        *_PRICES,
        *base,
        flag,
        first,
        flag,
        second,
    )
    assert f"{flag} given more than once for index 'EDU100'" in err


def test_duplicate_constituents_are_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    err = _refused(
        tmp_path,
        monkeypatch,
        capsys,
        *_SHARES,
        *_PRICES,
        "--index",
        "EDU100",
        "--index-constituents",
        "EDU100:AAPL,MSFT,aapl",
    )
    assert "duplicate symbol(s) AAPL" in err


def test_constituents_without_outstanding_shares_are_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    err = _refused(
        tmp_path,
        monkeypatch,
        capsys,
        "--outstanding-shares",
        "AAPL:100",
        *_PRICES,
        "--index",
        "EDU100",
        "--index-constituents",
        "EDU100:AAPL,MSFT",
    )
    assert "symbol 'MSFT' has no outstanding shares" in err
    assert "--outstanding-shares MSFT:N" in err
