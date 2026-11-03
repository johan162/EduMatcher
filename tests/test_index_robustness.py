"""K8 (I2, I3, I4): index value-domain and handler robustness.

I2: delisting the last constituent deleted it from every map and only then
    raised, leaving a calculator with no constituents and a rejected command.
I3: command handlers did ``int(payload.get(...))`` on decoded payloads, so a
    well-formed message with ``None`` in a field raised TypeError out of a
    dispatch loop that guards only decoding.
I4: ``price <= 0.0`` lets NaN and +inf through, and the poisoned value was
    stored and published.
See docs-design/EduMatcher-Key-Component-Fixes-Workplan.md K8.
"""

from __future__ import annotations

import math
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

import edumatcher.index.main as index_main
from edumatcher.index.calculator import ConstituentConfig, IndexCalculator
from edumatcher.index.config_loader import IndexRuntimeConfig
from edumatcher.models.message import decode, encode

from tests.support.badvalues import ABSENT, BAD_VALUES


class _Sock:
    def __init__(self) -> None:
        self.sent: list[list[bytes]] = []

    def poll(self, timeout: int = 0) -> bool:
        return False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        pass


@pytest.fixture()
def proc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[index_main.IndexProcess, None, None]:
    pub = _Sock()
    monkeypatch.setattr(index_main, "make_subscriber", lambda *_a, **_k: _Sock())
    monkeypatch.setattr(index_main, "make_puller", lambda *_a, **_k: _Sock())
    monkeypatch.setattr(index_main, "make_publisher", lambda *_a, **_k: pub)
    monkeypatch.setattr(index_main, "make_replier", lambda *_a, **_k: _Sock())
    cfg = IndexRuntimeConfig(
        id="EDU100",
        description="Education 100",
        base_value=1000.0,
        publish_interval_sec=0.0,
        history_file=str(tmp_path / "history.jsonl"),
        state_file=str(tmp_path / "state.json"),
        constituents=["AAPL", "MSFT"],
        outstanding_shares={"AAPL": 10_000, "MSFT": 20_000},
        reference_prices={"AAPL": 100.0, "MSFT": 50.0},
    )
    monkeypatch.setattr(index_main, "load_index_runtime_configs", lambda _p: [cfg])
    p = index_main.IndexProcess(config_path=tmp_path / "engine.yaml")
    p._initialise()
    p._test_pub = pub  # type: ignore[attr-defined]
    yield p
    p.close()


def assert_index_levels_finite(proc: index_main.IndexProcess) -> None:
    """Index invariant: every live level, cap and divisor is a finite number."""
    for idx in proc._indices.values():
        assert math.isfinite(idx.calc.recalculate())
        assert math.isfinite(idx.calc.aggregate_cap())
        assert math.isfinite(idx.calc.divisor) and idx.calc.divisor > 0


def _published(proc: index_main.IndexProcess) -> list[tuple[str, dict[str, Any]]]:
    return [decode(f) for f in proc._test_pub.sent]  # type: ignore[attr-defined]


# --- I2 ---------------------------------------------------------------------


def test_delisting_the_last_constituent_leaves_the_index_intact() -> None:
    calc = IndexCalculator([ConstituentConfig("AAPL", 1_000, 100.0)], base_value=1000.0)
    level, divisor = calc.recalculate(), calc.divisor

    with pytest.raises(ValueError):
        calc.delist_symbol("AAPL")

    assert calc.constituent_symbols() == ["AAPL"]
    assert calc.shares_outstanding("AAPL") == 1_000
    assert calc.last_price("AAPL") == 100.0
    assert (calc.recalculate(), calc.divisor) == (level, divisor)


# --- I4 ---------------------------------------------------------------------


@pytest.mark.parametrize("price", ["nan", "inf", "-inf", float("nan"), float("inf")])
def test_non_finite_trade_price_is_not_stored_or_published(
    proc: index_main.IndexProcess, price: Any
) -> None:
    before = proc._indices["EDU100"].calc.last_price("AAPL")
    proc._test_pub.sent.clear()  # type: ignore[attr-defined]

    proc._handle_trade({"symbol": "AAPL", "price": price})

    assert proc._indices["EDU100"].calc.last_price("AAPL") == before
    assert _published(proc) == []
    assert_index_levels_finite(proc)


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_calculator_rejects_non_finite_prices(value: float) -> None:
    calc = IndexCalculator([ConstituentConfig("AAPL", 1_000, 100.0)], 1000.0)
    with pytest.raises(ValueError):
        calc.update_price("AAPL", value)
    with pytest.raises(ValueError):
        calc.apply_cash_dividend("AAPL", value)
    with pytest.raises(ValueError):
        calc.add_constituent("MSFT", 10, value)
    with pytest.raises(ValueError):
        IndexCalculator([ConstituentConfig("AAPL", 1_000, value)], 1000.0)
    assert calc.last_price("AAPL") == 100.0


# --- I3 ---------------------------------------------------------------------

_BASE: dict[str, dict[str, Any]] = {
    "_handle_trade": {"symbol": "AAPL", "price": 101.0},
    "_handle_session_state": {"state": "CONTINUOUS"},
    "_handle_history_request": {
        "gateway_id": "GW1",
        "index_id": "EDU100",
        "from_ts_ns": 0,
        "to_ts_ns": 10**19,
        "max_records": 10,
        "types": ["INIT"],
    },
    "_handle_corp_action": {
        "gateway_id": "GW1",
        "index_id": "EDU100",
        "command_id": "c1",
        "action": "SPLIT",
        "symbol": "AAPL",
        "ratio_numerator": 2,
        "ratio_denominator": 1,
    },
    "_handle_constituent_change": {
        "gateway_id": "GW1",
        "index_id": "EDU100",
        "command_id": "c1",
        "change_type": "ADD",
        "symbol": "GOOG",
        "shares_outstanding": 100,
        "initial_price": 10.0,
    },
    "_handle_rebalance": {
        "gateway_id": "GW1",
        "index_id": "EDU100",
        "command_id": "c1",
        "updates": [{"symbol": "AAPL", "new_shares_outstanding": 9_000}],
    },
}
_EXTRA_FIELDS = {
    "_handle_corp_action": ["dividend_per_share", "new_shares_outstanding"],
}


def _cases() -> list[tuple[str, str]]:
    out = []
    for handler, base in _BASE.items():
        for field in [*base, *_EXTRA_FIELDS.get(handler, [])]:
            out.append((handler, field))
    return out


@pytest.mark.parametrize("bad", BAD_VALUES)
@pytest.mark.parametrize(("handler", "field"), _cases())
def test_no_handler_raises_on_a_bad_field_value(
    proc: index_main.IndexProcess, handler: str, field: str, bad: Any
) -> None:
    payload = dict(_BASE[handler])
    if bad is ABSENT:
        payload.pop(field, None)
    else:
        payload[field] = bad
    if handler == "_handle_corp_action" and field in _EXTRA_FIELDS[handler]:
        payload["action"] = (
            "CASH_DIVIDEND" if field == "dividend_per_share" else "SHARES_ISSUANCE"
        )

    getattr(proc, handler)(payload)  # a reject reply at worst, never an exception

    assert_index_levels_finite(proc)


def test_history_request_with_a_null_bound_is_answered_and_the_next_one_served(
    proc: index_main.IndexProcess,
) -> None:
    proc._test_pub.sent.clear()  # type: ignore[attr-defined]
    proc._handle_history_request(
        {"gateway_id": "GW1", "index_id": "EDU100", "from_ts_ns": None}
    )
    proc._handle_history_request(
        {"gateway_id": "GW1", "index_id": "EDU100", "types": ["INIT"]}
    )

    topics = [t for t, _ in _published(proc)]
    assert topics == ["index.error.GW1", "index.history.GW1"]


def test_a_handler_that_raises_does_not_end_the_loop(
    proc: index_main.IndexProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def boom(_payload: dict[str, Any]) -> None:
        raise RuntimeError("handler bug")

    monkeypatch.setattr(proc, "_handle_corp_action", boom)
    monkeypatch.setattr(proc, "_handle_trade", lambda p: calls.append("trade"))

    proc._handle_pull_message(encode("index.corp_action", {"gateway_id": "GW1"}))
    proc._handle_sub_message(encode("trade.executed", {"symbol": "AAPL"}))

    assert calls == ["trade"]
