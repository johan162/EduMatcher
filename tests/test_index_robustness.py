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
        self.options: list[tuple[int, bytes]] = []
        self.sent: list[list[bytes]] = []

    def poll(self, timeout: int = 0) -> bool:
        return False

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        pass

    def setsockopt(self, option: int, value: bytes) -> None:
        self.options.append((option, value))


@pytest.fixture()
def proc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[index_main.IndexProcess, None, None]:
    pub = _Sock()
    monkeypatch.setattr(index_main, "make_subscriber", lambda *_a, **_k: _Sock())
    monkeypatch.setattr(index_main, "make_pusher", lambda *_a, **_k: _Sock())
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
        tradeable_symbols=frozenset({"AAPL", "MSFT", "GOOG", "AMZN"}),
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
    "_handle_corp_action": [
        "dividend_per_share",
        "new_shares_outstanding",
        "shares_delta",
    ],
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


# --- K1-K10 review #9 ---------------------------------------------------------


def _rebalance(proc: index_main.IndexProcess, *updates: dict[str, Any]) -> None:
    proc._handle_rebalance({**_BASE["_handle_rebalance"], "updates": list(updates)})


@pytest.mark.parametrize("bad", [9_000.5, True, float("nan"), "9000.0"])
def test_rebalance_rejects_a_non_integral_share_count(
    proc: index_main.IndexProcess, bad: Any
) -> None:
    """Same strictness as the other commands' typed parse (K8): truncating
    9000.5 to 9000, or reading True as 1, is not a share count."""
    _rebalance(proc, {"symbol": "AAPL", "new_shares_outstanding": bad})

    assert proc._indices["EDU100"].calc.shares_outstanding("AAPL") == 10_000
    (ack,) = [p for t, p in _published(proc) if t.startswith("index.rebalance_ack")]
    assert ack["accepted"] is False


def test_a_rebalance_that_fails_part_way_applies_none_of_it(
    proc: index_main.IndexProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WP-IDX01: the batch is applied to a copy, so a failure on its second
    entry leaves the first unapplied in memory and in the state file."""
    idx = proc._indices["EDU100"]
    original = IndexCalculator.apply_shares_issuance

    def fail_on_msft(
        self: IndexCalculator, symbol: str, new_shares_outstanding: int
    ) -> None:
        if symbol == "MSFT":
            raise ValueError("aggregate cap would be non-positive")
        original(self, symbol, new_shares_outstanding)

    monkeypatch.setattr(IndexCalculator, "apply_shares_issuance", fail_on_msft)
    _rebalance(
        proc,
        {"symbol": "AAPL", "new_shares_outstanding": 9_000},
        {"symbol": "MSFT", "new_shares_outstanding": 1},
    )

    (ack,) = [p for t, p in _published(proc) if t.startswith("index.rebalance_ack")]
    assert ack["accepted"] is False
    assert idx.calc.shares_outstanding("AAPL") == 10_000
    assert _state(proc)["outstanding_shares"]["AAPL"] == 10_000


# --- WP-IDX01 (C5, C7): a command is applied, persisted and acked together --


def _state(proc: index_main.IndexProcess) -> dict[str, Any]:
    import json

    idx = proc._indices["EDU100"]
    loaded: dict[str, Any] = json.loads(
        Path(idx.cfg.state_file).read_text(encoding="utf-8")
    )
    loaded.pop("last_updated")
    return loaded


def _snapshot(proc: index_main.IndexProcess) -> tuple[Any, ...]:
    calc = proc._indices["EDU100"].calc
    symbols = calc.constituent_symbols()
    return (
        calc.divisor,
        symbols,
        {s: calc.shares_outstanding(s) for s in symbols},
        {s: calc.last_price(s) for s in symbols},
    )


_COMMANDS: dict[str, tuple[str, dict[str, Any]]] = {
    "SPLIT": ("_handle_corp_action", _BASE["_handle_corp_action"]),
    "SHARES_ISSUANCE": (
        "_handle_corp_action",
        {
            **_BASE["_handle_corp_action"],
            "action": "SHARES_ISSUANCE",
            "new_shares_outstanding": 15_000,
        },
    ),
    "ADD": ("_handle_constituent_change", _BASE["_handle_constituent_change"]),
    "DELIST": (
        "_handle_constituent_change",
        {
            **_BASE["_handle_constituent_change"],
            "change_type": "DELIST",
            "symbol": "MSFT",
        },
    ),
    "REBALANCE": ("_handle_rebalance", _BASE["_handle_rebalance"]),
}


def _fail_history(
    proc: index_main.IndexProcess, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_record: dict[str, Any]) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(proc._indices["EDU100"].history, "append", boom)


def _fail_state(proc: index_main.IndexProcess, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(index_main, "atomic_write_text", boom)


@pytest.mark.parametrize("fail", [_fail_history, _fail_state], ids=["history", "state"])
@pytest.mark.parametrize("command", sorted(_COMMANDS))
def test_a_command_whose_write_fails_is_rejected_and_changes_nothing(
    proc: index_main.IndexProcess,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    fail: Any,
) -> None:
    handler, payload = _COMMANDS[command]
    before, state_before = _snapshot(proc), _state(proc)
    proc._test_pub.sent.clear()  # type: ignore[attr-defined]
    fail(proc, monkeypatch)

    getattr(proc, handler)(dict(payload))

    published = _published(proc)
    assert [t for t, _ in published if t == "index.update"] == []
    ((topic, ack),) = published
    assert "_ack." in topic
    assert ack["accepted"] is False
    assert "No space left on device" in ack["reason"]
    assert _snapshot(proc) == before
    assert _state(proc) == state_before
    assert proc._constituent_to_indices.get("GOOG", set()) == set()
    assert "EDU100" in proc._constituent_to_indices["MSFT"]


@pytest.mark.parametrize("command", sorted(_COMMANDS))
def test_a_rejected_command_retried_is_applied_once_and_survives_a_restart(
    proc: index_main.IndexProcess,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    handler, payload = _COMMANDS[command]
    with monkeypatch.context() as m:
        _fail_history(proc, m)
        getattr(proc, handler)(dict(payload))
    proc._test_pub.sent.clear()  # type: ignore[attr-defined]

    getattr(proc, handler)(dict(payload))

    (ack,) = [p for t, p in _published(proc) if "_ack." in t]
    assert ack["accepted"] is True
    applied = _snapshot(proc)
    level = proc._indices["EDU100"].calc.recalculate()
    assert _state(proc)["divisor"] == applied[0]

    cfg = proc._indices["EDU100"].cfg
    monkeypatch.setattr(index_main, "load_index_runtime_configs", lambda _p: [cfg])
    restarted = index_main.IndexProcess(
        config_path=Path(cfg.state_file).parent / "e.yaml"
    )
    try:
        restarted._initialise()
        assert _snapshot(restarted) == applied
        assert restarted._indices["EDU100"].calc.recalculate() == pytest.approx(level)
    finally:
        restarted.close()


def test_a_reverse_split_that_rounds_a_holding_to_zero_is_refused(
    proc: index_main.IndexProcess,
) -> None:
    proc._handle_rebalance(
        {
            **_BASE["_handle_rebalance"],
            "updates": [{"symbol": "AAPL", "new_shares_outstanding": 4}],
        }
    )
    before = _snapshot(proc)
    proc._test_pub.sent.clear()  # type: ignore[attr-defined]

    proc._handle_corp_action(
        {**_BASE["_handle_corp_action"], "ratio_numerator": 1, "ratio_denominator": 10}
    )

    (ack,) = [p for t, p in _published(proc) if "_ack." in t]
    assert ack["accepted"] is False
    assert "would leave AAPL with 0 shares" in ack["reason"]
    assert _snapshot(proc) == before


def test_a_reverse_split_that_keeps_one_share_or_more_is_accepted() -> None:
    calc = IndexCalculator(
        [ConstituentConfig("AAPL", 3, 100.0), ConstituentConfig("MSFT", 10, 50.0)],
        base_value=1000.0,
    )
    calc.apply_split("AAPL", ratio_numerator=1, ratio_denominator=2)
    assert calc.shares_outstanding("AAPL") == 2


# --- WP-IDX05 (C12): ADD names a configured symbol ---------------------------


def test_add_of_a_symbol_the_exchange_does_not_trade_is_rejected(
    proc: index_main.IndexProcess,
) -> None:
    before = _snapshot(proc)
    proc._test_pub.sent.clear()  # type: ignore[attr-defined]

    proc._handle_constituent_change(
        {**_BASE["_handle_constituent_change"], "symbol": "APPL"}
    )

    ((_, ack),) = _published(proc)
    assert ack["accepted"] is False
    assert ack["reason"] == "APPL is not a configured symbol"
    assert _snapshot(proc) == before
    assert "APPL" not in proc._constituent_to_indices


def test_add_of_a_configured_symbol_is_accepted(
    proc: index_main.IndexProcess,
) -> None:
    proc._handle_constituent_change(dict(_BASE["_handle_constituent_change"]))

    (ack,) = [p for t, p in _published(proc) if "_ack." in t]
    assert ack["accepted"] is True
    assert "GOOG" in proc._indices["EDU100"].calc.constituent_symbols()


# --- WP-IDX08 (C6): share deltas are resolved by pm-index --------------------


def _shares(proc: index_main.IndexProcess, **fields: Any) -> dict[str, Any]:
    proc._test_pub.sent.clear()  # type: ignore[attr-defined]
    proc._handle_corp_action(
        {
            "gateway_id": "GW1",
            "index_id": "EDU100",
            "command_id": "c1",
            "action": "SHARES_ISSUANCE",
            "symbol": "AAPL",
            **fields,
        }
    )
    ((_, ack),) = _published_acks(proc)
    return ack


def _published_acks(
    proc: index_main.IndexProcess,
) -> list[tuple[str, dict[str, Any]]]:
    return [(t, p) for t, p in _published(proc) if "_ack." in t]


def test_a_share_delta_applies_to_the_live_count_after_a_split(
    proc: index_main.IndexProcess,
) -> None:
    proc._handle_corp_action(dict(_BASE["_handle_corp_action"]))  # 2:1 → 20 000
    ack = _shares(proc, shares_delta=-100)

    assert ack["accepted"] is True
    assert ack["shares_outstanding"] == 19_900
    assert proc._indices["EDU100"].calc.shares_outstanding("AAPL") == 19_900


def test_every_accepted_corp_action_ack_carries_the_resulting_count(
    proc: index_main.IndexProcess,
) -> None:
    ack = _shares(proc, new_shares_outstanding=12_345)
    assert ack["shares_outstanding"] == 12_345


@pytest.mark.parametrize(
    "fields",
    [{}, {"new_shares_outstanding": 12_000, "shares_delta": 100}],
    ids=["neither", "both"],
)
def test_exactly_one_of_new_shares_and_delta_is_required(
    proc: index_main.IndexProcess, fields: dict[str, Any]
) -> None:
    before = _snapshot(proc)
    ack = _shares(proc, **fields)

    assert ack["accepted"] is False
    assert "exactly one of new_shares_outstanding and shares_delta" in ack["reason"]
    assert _snapshot(proc) == before


@pytest.mark.parametrize("delta", [-10_000, -20_000])
def test_a_delta_that_leaves_no_shares_is_rejected(
    proc: index_main.IndexProcess, delta: int
) -> None:
    before = _snapshot(proc)
    ack = _shares(proc, shares_delta=delta)

    assert ack["accepted"] is False
    assert "would leave AAPL with" in ack["reason"]
    assert _snapshot(proc) == before


def test_a_rebalance_record_lists_each_symbols_new_count(
    proc: index_main.IndexProcess,
) -> None:
    _rebalance(
        proc,
        {"symbol": "AAPL", "new_shares_outstanding": 9_000},
        {"symbol": "MSFT", "new_shares_outstanding": 21_000},
    )
    history = proc._indices["EDU100"].history
    history.flush()
    (record,), _ = history.query(0, 2**63, {"REBALANCE"})

    assert record["updates"] == [
        {"symbol": "AAPL", "new_shares_outstanding": 9_000},
        {"symbol": "MSFT", "new_shares_outstanding": 21_000},
    ]
