"""pm-cverifier agrees with the loaders pm-config-deploy compiles with.

The verifier is the gate of ``pm-config-deploy``: a file it passes must
compile, or the operator is told "engine can start" about a file the deploy
then refuses. Each case changes one value of a valid file and checks that the
verifier reports an ERROR exactly when the loaders refuse the file.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from edumatcher.alf_gwy.config import load_alf_gateway_config
from edumatcher.api_gateway.config import load_named_api_gateway_configs
from edumatcher.balf_gwy.config import load_balf_gateway_config
from edumatcher.dc_gateway.config import load_dc_gateway_config
from edumatcher.engine.config_loader import load_engine_config
from edumatcher.log_srv.config import load_log_client_config, load_log_server_config
from edumatcher.md_gateway.config import load_market_data_gateway_config
from edumatcher.monitor.config import load_monitor_config
from edumatcher.ralf_gateway.config import load_ralf_gateway_config
from edumatcher.cverifier.cli import run
from edumatcher.cverifier.models import Severity

_BASE: dict[str, Any] = {
    "sessions_enabled": True,
    "enforce_collars": True,
    "enforce_circuit_breakers": True,
    "require_mm_seed_quotes": True,
    "engine_tuning": {
        "snapshot_interval_sec": 0.5,
        "quote_history_maxlen": 30,
        "drop_copy_buffer_size": 10000,
        "recent_trades_maxlen": 20,
        "depth_snapshot_tolerance_ticks": 100,
    },
    "mm_obligation_defaults": {
        "enforce_mm_obligation": True,
        "mm_max_spread_ticks": 30,
        "mm_min_qty": 100,
    },
    "risk_controls": {
        "default_level": "CORE",
        "levels": {
            "CORE": {"collar": {"static_band_pct": 0.2, "dynamic_band_pct": 0.02}}
        },
    },
    "circuit_breaker_defaults": {
        "reference_window_ns": 300_000_000_000,
        "levels": {
            "L1": {"price_shift_pct": 0.07, "halt_duration_ns": 300_000_000_000}
        },
    },
    "participants": [
        {"id": "TRADER01", "role": "TRADER", "description": "desk one"},
        {"id": "OPS01", "role": "ADMIN", "disconnect_behaviour": "LEAVE_ALL"},
        {"id": "MM01", "role": "MARKET_MAKER"},
    ],
    "dc_gateway": {"heartbeat_interval_sec": 2, "idle_timeout_sec": 20},
    "post_trade_gateway": {"heartbeat_interval_sec": 2, "idle_timeout_sec": 20},
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
                    "tif": "DAY",
                }
            ],
        },
        "MSFT": {
            "tick_decimals": 2,
            "last_buy_price": 200.0,
            "last_sell_price": 200.0,
            "outstanding_shares": 2000,
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
    "market_maker_combos": [
        {
            "combo_id": "C1",
            "combo_type": "AON",
            "tif": "DAY",
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
            "history_file": "data/indexes/OMX_history.jsonl",
            "state_file": "data/indexes/OMX_state.json",
            "constituents": ["AAPL", "MSFT"],
        }
    ],
    "schedule": {
        "weekdays": {
            "pre_open": "09:00",
            "opening_auction_start": "09:25",
            "continuous_start": "09:30",
            "closing_auction_start": "16:00",
            "closing_auction_end": "16:05",
        }
    },
}

_DELETE = object()

# (path, value): one leaf replaced (or deleted) at a time.
_MUTATIONS: list[tuple[tuple[Any, ...], Any]] = [
    # An explicit null the loader refuses.
    (("sessions_enabled",), None),
    (("enforce_collars",), None),
    (("enforce_circuit_breakers",), None),
    (("require_mm_seed_quotes",), None),
    (("engine_tuning", "snapshot_interval_sec"), None),
    (("mm_obligation_defaults", "enforce_mm_obligation"), None),
    (("mm_obligation_defaults", "mm_max_spread_ticks"), None),
    (("mm_obligation_defaults", "mm_min_qty"), None),
    (("symbols", "AAPL", "market_maker_quotes", 0, "bid_price"), None),
    (("symbols", "AAPL", "market_maker_quotes", 0, "ask_price"), None),
    (("symbols", "AAPL", "market_maker_quotes", 0, "bid_qty"), None),
    (("symbols", "AAPL", "market_maker_quotes", 0, "gateway_id"), None),
    (("symbols", "AAPL", "market_maker_quotes", 0, "tif"), None),
    (("risk_controls", "levels", "CORE", "collar", "static_band_pct"), None),
    (("risk_controls", "levels", "CORE", "collar", "dynamic_band_pct"), None),
    (("indices", 0, "history_file"), None),
    (("indices", 0, "constituents"), None),
    (("indices", 0, "constituents"), _DELETE),
    (("participants", 0, "disconnect_behaviour"), None),
    # A nested block that is not a mapping.
    (("risk_controls", "levels", "CORE"), 0),
    (("risk_controls", "levels", "CORE", "collar"), "x"),
    (("circuit_breaker_defaults", "levels", "L1"), 1.5),
    (("schedule", "weekdays"), 0),
    (("engine_tuning",), "x"),
    # Engine fields the hand-written checks never looked at.
    (("engine_tuning", "quote_history_maxlen"), 0),
    (("engine_tuning", "drop_copy_buffer_size"), -1),
    (("engine_tuning", "recent_trades_maxlen"), "x"),
    (("engine_tuning", "depth_snapshot_tolerance_ticks"), 0),
    (("circuit_breaker_defaults", "reference_window_ns"), "x"),
    (("participants", 0, "description"), 1),
    (("market_maker_combos", 0, "legs", 0, "price"), "x"),
    # The loader's type is narrower than the hand-written check's.
    (("dc_gateway", "heartbeat_interval_sec"), 1.5),
    (("dc_gateway", "idle_timeout_sec"), True),
    (("dc_gateway", "port"), None),
    # A name WELCOME cannot carry (DC review C6).
    (("dc_gateway", "name"), "dc|01"),
    # The same for pm-ralf-gwy (RALF review C6), and a role with no channel.
    (("post_trade_gateway", "name"), "ralf|01"),
    (("post_trade_gateway", "allowed_roles"), ["RISK"]),
    # Values the loaders used to read as something else (For-Later L024).
    (("symbols", "AAPL", "tick_decimals"), True),
    (("symbols", "AAPL", "outstanding_shares"), True),
    (("symbols", "AAPL", "order_limits"), {"max_order_qty": 1.5}),
    (("schedule",), "x"),
    (("schedule",), 0),
    (("engine_tuning", "snapshot_interval_sec"), float("nan")),
    (("log_server",), {"enabled": "x"}),
    (("log_server",), {"pubsub_enabled": "x"}),
    (("log_server",), {"name": 5}),
    (("log_server",), {"bind_address": 5}),
    (("log_server",), {"db_path": 5}),
    (("balf_gateway",), {"enabled": "false"}),
    (("alf_gateway",), {"enabled": "false"}),
    (("api_gateways",), {"main": {"enabled": "false"}}),
    (("api_gateways",), {"main": {"swagger_enabled": "x"}}),
]


def _mutate(path: tuple[Any, ...], value: Any) -> dict[str, Any]:
    doc = copy.deepcopy(_BASE)
    node: Any = doc
    for key in path[:-1]:
        node = node[key]
    if value is _DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = value
    return doc


def _loaders_accept(path: Path) -> bool:
    """Whether every loader ``compile_config`` runs accepts *path*."""
    try:
        load_engine_config(path)
        load_alf_gateway_config(path)
        load_balf_gateway_config(path)
        load_market_data_gateway_config(path)
        load_ralf_gateway_config(path)
        load_dc_gateway_config(path)
        load_log_server_config(path)
        load_log_client_config(path)
        load_monitor_config(path)
        load_named_api_gateway_configs(path)
    except Exception:
        return False
    return True


def _errors(path: Path) -> list[str]:
    results, _raw = run(path)
    return [r.code for r in results if r.severity is Severity.ERROR]


def _write(tmp_path: Path, doc: dict[str, Any]) -> Path:
    p = tmp_path / "engine_config.yaml"
    p.write_text(yaml.safe_dump(doc, sort_keys=False))
    return p


def test_base_file_verifies_and_compiles(tmp_path: Path) -> None:
    p = _write(tmp_path, _BASE)
    assert _errors(p) == []
    assert _loaders_accept(p)


@pytest.mark.parametrize(
    ("path", "value"),
    _MUTATIONS,
    ids=[
        ".".join(map(str, p)) + ("=<del>" if v is _DELETE else f"={v!r}")
        for p, v in _MUTATIONS
    ],
)
def test_verifier_error_exactly_when_loaders_refuse(
    tmp_path: Path, path: tuple[Any, ...], value: Any
) -> None:
    p = _write(tmp_path, _mutate(path, value))
    loaders_ok = _loaders_accept(p)
    errors = _errors(p)
    assert not loaders_ok, "the case must be one the loaders refuse"
    assert errors, "the verifier passed a file pm-config-deploy refuses"


def test_backstop_is_quiet_when_an_engine_error_is_already_reported(
    tmp_path: Path,
) -> None:
    # S010 already names the problem; the loader would only restate it.
    p = _write(tmp_path, _mutate(("symbols", "AAPL", "tick_decimals"), 9))
    errors = _errors(p)
    assert "S010" in errors
    assert "S132" not in errors


def test_backstop_reports_the_loader_message(tmp_path: Path) -> None:
    p = _write(tmp_path, _mutate(("engine_tuning", "quote_history_maxlen"), 0))
    results, _raw = run(p)
    backstop = [r for r in results if r.code == "S132"]
    assert len(backstop) == 1
    assert "quote_history_maxlen" in backstop[0].message


def test_dc_backstop_reports_the_loader_message(tmp_path: Path) -> None:
    # No field check looks at an explicit null port; the loader refuses it.
    p = _write(tmp_path, _mutate(("dc_gateway", "port"), None))
    results, _raw = run(p)
    assert [r.code for r in results if r.severity is Severity.ERROR] == ["S133"]


def test_dc_fractional_seconds_are_s094(tmp_path: Path) -> None:
    p = _write(tmp_path, _mutate(("dc_gateway", "heartbeat_interval_sec"), 1.5))
    results, _raw = run(p)
    assert [r.code for r in results if r.severity is Severity.ERROR] == ["S094"]


def test_generated_mm_stub_template_is_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from edumatcher.config_gen.cli import main as gen_main

    out = tmp_path / "engine_config.yaml"
    monkeypatch.setattr(
        "sys.argv",
        [
            "pm-config-gen",
            "--symbols",
            "AAPL",
            "--participants",
            "TRADER01",
            "MM01:MARKET_MAKER",
            "--output",
            str(out),
        ],
    )
    gen_main()
    results, _raw = run(out)
    errors = [r for r in results if r.severity is Severity.ERROR]
    paths = {r.path for r in errors}
    assert "symbols.AAPL.market_maker_quotes[0].bid_price" in paths
    assert "symbols.AAPL.market_maker_quotes[0].ask_price" in paths
    assert not _loaders_accept(out)
