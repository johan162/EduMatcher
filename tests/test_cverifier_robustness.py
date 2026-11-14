"""pm-cverifier never crashes, and refuses numbers no process can use.

A traceback ends the verifier with exit 1, the code it documents as
"warnings only", so a CI step that accepts warnings would accept a verifier
that crashed. YAML's ``.inf`` and ``.nan`` are floats, and NaN passes every
``x <= 0`` check.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from edumatcher.cverifier import layer3_semantic
from edumatcher.cverifier.cli import main, run
from edumatcher.cverifier.models import Severity

_BASE: dict[str, Any] = {
    "sessions_enabled": False,
    "symbols": {
        "AAPL": {
            "tick_decimals": 2,
            "last_buy_price": 100.0,
            "last_sell_price": 100.0,
            "outstanding_shares": 1000,
            "market_maker_quotes": [
                {
                    "gateway_id": "MM01",
                    "bid_price": 99.9,
                    "ask_price": 100.1,
                    "bid_qty": 100,
                    "ask_qty": 100,
                }
            ],
            "circuit_breaker": {
                "levels": {
                    "L1": {"price_shift_pct": 0.05, "halt_duration_ns": 60_000_000_000}
                }
            },
        },
        "MSFT": {
            "tick_decimals": 2,
            "last_buy_price": 200.0,
            "market_maker_quotes": [
                {
                    "gateway_id": "MM01",
                    "bid_price": 199.9,
                    "ask_price": 200.1,
                    "bid_qty": 100,
                    "ask_qty": 100,
                }
            ],
        },
    },
    "participants": [
        {"id": "TRADER01", "role": "TRADER"},
        {"id": "OPS01", "role": "ADMIN", "disconnect_behaviour": "LEAVE_ALL"},
        {"id": "MM01", "role": "MARKET_MAKER"},
    ],
    "market_maker_combos": [
        {
            "combo_id": "C1",
            "legs": [
                {
                    "symbol": "AAPL",
                    "side": "BUY",
                    "order_type": "LIMIT",
                    "quantity": 1,
                    "price": 100.0,
                },
                {
                    "symbol": "MSFT",
                    "side": "SELL",
                    "order_type": "LIMIT",
                    "quantity": 1,
                    "price": 200.0,
                },
            ],
        }
    ],
    "indices": [
        {
            "id": "OMX",
            "description": "Test",
            "base_value": 1000.0,
            "publish_interval_sec": 1.0,
            "constituents": ["AAPL"],
        }
    ],
}

_INF = float("inf")
_NAN = float("nan")


def _write(tmp_path: Path, path: tuple[Any, ...], value: Any) -> Path:
    doc = copy.deepcopy(_BASE)
    node: Any = doc
    for key in path[:-1]:
        node = node.setdefault(key, {}) if isinstance(node, dict) else node[key]
    node[path[-1]] = value
    p = tmp_path / "engine_config.yaml"
    p.write_text(yaml.safe_dump(doc, sort_keys=False))
    return p


def test_base_file_has_no_error(tmp_path: Path) -> None:
    p = tmp_path / "engine_config.yaml"
    p.write_text(yaml.safe_dump(_BASE, sort_keys=False))
    results, _raw = run(p)
    assert [r.code for r in results if r.severity is Severity.ERROR] == []


_NON_FINITE = [
    (("symbols", "AAPL", "last_buy_price"), _INF, "symbols.AAPL.last_buy_price"),
    (("symbols", "AAPL", "last_buy_price"), _NAN, "symbols.AAPL.last_buy_price"),
    (
        ("symbols", "AAPL", "market_maker_quotes", 0, "bid_price"),
        _NAN,
        "symbols.AAPL.market_maker_quotes[0]",
    ),
    (
        ("symbols", "AAPL", "market_maker_quotes", 0, "bid_qty"),
        _INF,
        "symbols.AAPL.market_maker_quotes[0]",
    ),
    (
        ("symbols", "AAPL", "circuit_breaker", "levels", "L1", "halt_duration_ns"),
        _INF,
        "symbols.AAPL.circuit_breaker.levels.L1.halt_duration_ns",
    ),
    (("symbols", "AAPL", "tick_decimals"), _INF, "symbols.AAPL.tick_decimals"),
    (
        ("symbols", "AAPL", "outstanding_shares"),
        _INF,
        "symbols.AAPL.outstanding_shares",
    ),
    (
        ("market_maker_combos", 0, "legs", 0, "price"),
        _NAN,
        "market_maker_combos[0].legs[0].price",
    ),
    (
        ("engine_tuning", "snapshot_interval_sec"),
        _NAN,
        "engine_tuning.snapshot_interval_sec",
    ),
    (("indices", 0, "base_value"), _NAN, "indices[0].base_value"),
    (("indices", 0, "publish_interval_sec"), _NAN, "indices[0].publish_interval_sec"),
    (("indices", 0, "base_value"), _INF, "indices[0].base_value"),
]


@pytest.mark.parametrize(
    ("path", "value", "where"),
    _NON_FINITE,
    ids=[f"{w}={v}" for _p, v, w in _NON_FINITE],
)
def test_non_finite_number_is_an_error_not_a_crash(
    tmp_path: Path, path: tuple[Any, ...], value: float, where: str
) -> None:
    p = _write(tmp_path, path, value)
    results, _raw = run(p)
    errors = [r for r in results if r.severity is Severity.ERROR]
    assert any(r.path == where for r in errors), [(r.code, r.path) for r in errors]


def test_non_finite_exits_2(tmp_path: Path) -> None:
    p = _write(tmp_path, ("symbols", "AAPL", "last_buy_price"), _INF)
    with pytest.raises(SystemExit) as exc:
        main([str(p), "--no-color"])
    assert exc.value.code == 2


def test_non_utf8_file_is_y002(tmp_path: Path) -> None:
    p = tmp_path / "engine_config.yaml"
    p.write_bytes(yaml.safe_dump(_BASE).encode() + b"# \xff\xfe\n")
    results, _raw = run(p)
    assert [r.code for r in results] == ["Y002"]
    assert "UTF-8" in results[0].message
    with pytest.raises(SystemExit) as exc:
        main([str(p), "--no-color"])
    assert exc.value.code == 2


def test_non_string_constituent_is_an_error(tmp_path: Path) -> None:
    p = _write(tmp_path, ("indices", 0, "constituents"), [[]])
    results, _raw = run(p)
    assert any(r.severity is Severity.ERROR for r in results)


def test_unexpected_exception_exits_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    p = tmp_path / "engine_config.yaml"
    p.write_text(yaml.safe_dump(_BASE))

    def boom(raw: object, path: object) -> list[object]:
        raise RuntimeError("boom")

    monkeypatch.setattr(layer3_semantic, "check", boom)
    with pytest.raises(SystemExit) as exc:
        main([str(p), "--no-color"])
    assert exc.value.code == 2
    assert "cannot verify" in capsys.readouterr().err
