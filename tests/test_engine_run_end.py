"""A subscriber can tell whether it received the whole of an engine run
(For-Later L022, WP-FL04).

Trade ids are ``{run_seq}-{seq}`` and ``seq`` restarts every run, so a
subscriber found a lost trade only when a later trade of the same run
arrived. Trades lost just before the engine stopped looked like a clean run
boundary. ``system.eod`` (and the session-status reply, for "so far") now
name the run's last trade id.
"""

from __future__ import annotations

from typing import Any

from edumatcher.models.generated import system as gen_system
from edumatcher.models.message import decode, make_eod_msg, make_session_status_msg
from edumatcher.models.order import OrderType, Side
from edumatcher.models.trade import last_trade_id
from tests.engine_harness import connect, make_engine, msgs, order_payload


def trade(engine: Any, price: float = 100.0) -> None:
    engine._handle_new_order(order_payload(Side.SELL, OrderType.LIMIT, 5, "GW01", price=price))  # fmt: skip
    engine._handle_new_order(order_payload(Side.BUY, OrderType.LIMIT, 5, "GW02", price=price))  # fmt: skip


def test_the_generated_messages_carry_the_last_trade_id() -> None:
    _, eod = decode(make_eod_msg([], last_trade_id="000003-000000042"))
    assert gen_system.Eod.from_dict(eod).last_trade_id == "000003-000000042"
    _, status = decode(
        make_session_status_msg(
            "GW01", "CONTINUOUS", "2024-01-09T06:00:00.000Z", True, last_trade_id=None
        )
    )
    assert gen_system.SessionStatus.from_dict(status).last_trade_id is None


def test_last_trade_id_follows_the_trades_of_the_run(monkeypatch, tmp_path) -> None:
    engine, _pub = make_engine(monkeypatch, tmp_path, run_seq=3)
    connect(engine)
    assert last_trade_id() is None
    for _ in range(3):
        trade(engine)
    assert last_trade_id() == "000003-000000003"


def test_the_session_status_names_the_last_trade_so_far(monkeypatch, tmp_path) -> None:
    engine, pub = make_engine(monkeypatch, tmp_path, run_seq=3)
    connect(engine)
    engine._handle_session_state_request({"gateway_id": "GW01"})
    trade(engine)
    trade(engine)
    engine._handle_session_state_request({"gateway_id": "GW01"})
    first, second = msgs(pub, "system.session_status.GW01")
    assert first["last_trade_id"] is None
    assert second["last_trade_id"] == "000003-000000002"


def test_system_eod_names_the_runs_last_trade(monkeypatch, tmp_path) -> None:
    import edumatcher.engine.main as engine_main

    for name in ("GTC_ORDERS_FILE", "GTC_COMBOS_FILE", "BOOK_STATS_FILE"):
        monkeypatch.setattr(engine_main, name, tmp_path / f"{name.lower()}.json")
    engine, pub = make_engine(monkeypatch, tmp_path, run_seq=3)
    connect(engine)
    for _ in range(3):
        trade(engine)
    engine._shutdown()
    (eod,) = msgs(pub, "system.eod")
    assert eod["last_trade_id"] == "000003-000000003"


def test_system_eod_of_a_run_without_trades_names_none(monkeypatch, tmp_path) -> None:
    import edumatcher.engine.main as engine_main

    for name in ("GTC_ORDERS_FILE", "GTC_COMBOS_FILE", "BOOK_STATS_FILE"):
        monkeypatch.setattr(engine_main, name, tmp_path / f"{name.lower()}.json")
    engine, pub = make_engine(monkeypatch, tmp_path, run_seq=3)
    engine._shutdown()
    (eod,) = msgs(pub, "system.eod")
    assert eod["last_trade_id"] is None
