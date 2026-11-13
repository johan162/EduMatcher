"""Every halt treats a market maker's quotes alike (WP-ENG06).

C10 (engine review 2026-11): with ``INACTIVATE_ON_ANY_FILL`` a quote hit on
one side leaves the ``QuoteIndex``, but its remainder keeps resting. Cancel-
symbol and the kill switches swept that remainder; a breaker trip, halt-all
and the per-symbol halt did not, so a halt pulled the quotes but not the leg.
A halted quote was also always refused as a "circuit breaker halt".
C11 / Q3: an operator halt without a resume time is the operator's to lift;
the close does not lift it, breaker configured or not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import edumatcher.engine.main as engine_main
from edumatcher.engine.circuit_breaker import CircuitBreakerConfig, CircuitBreakerLevel
from edumatcher.engine.config_loader import SymbolConfig
from edumatcher.engine.main import Engine
from edumatcher.models.clock import now_ns
from edumatcher.models.order import OrderType, Side
from tests.engine_harness import (
    SYMBOL,
    FakeSock,
    assert_engine_links,
    connect,
    make_engine,
    msgs,
    order_payload,
    submit_quote,
)

ADMIN = "ADM01"
MM = "GW03"
SELLER = "GW01"
MIN = 60_000_000_000


def _engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, breaker: bool = True
) -> tuple[Engine, FakeSock]:
    monkeypatch.setattr(engine_main, "DATA_DIR", tmp_path)
    cb = CircuitBreakerConfig(
        symbol=SYMBOL,
        levels=[
            CircuitBreakerLevel("L1", 0.05, 5 * MIN),
            CircuitBreakerLevel("L3", 0.20, None),  # rest of day
        ],
    )
    engine, pub = make_engine(
        monkeypatch,
        tmp_path,
        gateways=(SELLER, "GW02", MM, ADMIN),
        mm_gateways=(MM,),
        admin_gateways=(ADMIN,),
        symbol_configs={
            SYMBOL: SymbolConfig(
                name=SYMBOL,
                last_buy_price=100.0,
                circuit_breaker=cb if breaker else None,
            )
        },
        sessions_enabled=True,
    )
    engine._load_config()
    connect(engine, SELLER, "GW02", MM, ADMIN)
    for state in ("PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS"):
        engine._handle_session_transition({"to_state": state})
    return engine, pub


def _half_filled_quote(engine: Engine, pub: FakeSock) -> str:
    """The 40 sold hit the bid: the quote is inactive, 60 of the bid rests."""
    engine._handle_new_order(
        order_payload(
            gateway_id=SELLER, symbol=SYMBOL, side=Side.SELL,
            order_type=OrderType.LIMIT, price=100.0, qty=40,
        )
    )  # fmt: skip
    submit_quote(engine, MM, 100.0, 101.0)
    assert engine._quote_index.get(MM, SYMBOL) is None
    (leg,) = engine.books[SYMBOL].resting_orders()
    assert leg.remaining_qty == 60
    pub.sent.clear()
    return leg.id


def _halt_by_breaker(engine: Engine) -> None:
    engine._check_circuit_breaker(SYMBOL, 12000, now_ns())


def _halt_all(engine: Engine) -> None:
    engine._handle_circuit_breaker_halt_all({"gateway_id": ADMIN})


def _halt_symbol(engine: Engine, level: str | None = None) -> None:
    payload: dict[str, Any] = {"gateway_id": ADMIN, "symbol": SYMBOL}
    if level is not None:
        payload["level"] = level
    engine._handle_symbol_halt(payload)


# --- C10: the leg of an inactivated quote ---------------------------------------


@pytest.mark.parametrize("halt", [_halt_by_breaker, _halt_all, _halt_symbol])
def test_a_halt_cancels_the_leg_of_an_inactivated_quote(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, halt: Any
) -> None:
    engine, pub = _engine(monkeypatch, tmp_path)
    leg = _half_filled_quote(engine, pub)

    halt(engine)

    assert engine._halted_symbols[SYMBOL] is True
    assert list(engine.books[SYMBOL].resting_orders()) == []
    (cancelled,) = msgs(pub, f"order.cancelled.{MM}")
    assert (cancelled["order_id"], cancelled["cancel_reason"]) == (
        leg,
        "CIRCUIT_BREAKER_HALT",
    )
    assert_engine_links(engine)


@pytest.mark.parametrize(
    ("halt", "ack_topic"),
    [
        (_halt_all, f"risk.circuit_breaker_halt_all_ack.{ADMIN}"),
        (_halt_symbol, f"risk.symbol_halt_ack.{ADMIN}"),
    ],
)
def test_the_halt_ack_names_the_leg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, halt: Any, ack_topic: str
) -> None:
    engine, pub = _engine(monkeypatch, tmp_path)
    leg = _half_filled_quote(engine, pub)

    halt(engine)

    (ack,) = msgs(pub, ack_topic)
    assert (ack["cancelled_quotes"], ack["cancelled_quote_order_ids"]) == (1, [leg])


# --- C10: the reason a halted quote is refused with -----------------------------


@pytest.mark.parametrize(
    ("halt", "trigger"),
    [(_halt_symbol, "trading halt"), (_halt_by_breaker, "circuit breaker halt")],
)
def test_a_halted_quote_is_refused_for_the_halt_it_meets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, halt: Any, trigger: str
) -> None:
    engine, pub = _engine(monkeypatch, tmp_path)
    halt(engine)

    submit_quote(engine, MM, 99.0, 101.0)

    (ack,) = msgs(pub, f"quote.ack.{MM}")
    assert ack["accepted"] is False
    assert ack["reason"] == f"{SYMBOL} is halted — quotes rejected during {trigger}"


# --- C11 / Q3: what the close lifts ---------------------------------------------


def _close(engine: Engine) -> None:
    for state in ("CLOSING_AUCTION", "CLOSED"):
        engine._handle_session_transition({"to_state": state})
    assert engine._session_state.value == "CLOSED"


def _halt_status(engine: Engine, pub: FakeSock) -> list[dict[str, Any]]:
    engine._handle_halt_status_request({"gateway_id": ADMIN})
    return list(msgs(pub, f"system.halt_status.{ADMIN}")[-1]["halted"])


@pytest.mark.parametrize("breaker", [False, True])
@pytest.mark.parametrize("halt", [_halt_symbol, _halt_all])
def test_an_operator_halt_outlasts_the_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, halt: Any, breaker: bool
) -> None:
    engine, pub = _engine(monkeypatch, tmp_path, breaker=breaker)
    halt(engine)

    _close(engine)

    assert engine._halted_symbols[SYMBOL] is True
    assert msgs(pub, f"circuit_breaker.resume.{SYMBOL}") == []
    (entry,) = _halt_status(engine, pub)
    assert (entry["symbol"], entry["halt_source"]) == (SYMBOL, "ADMIN")


@pytest.mark.parametrize(
    "halt",
    [
        _halt_by_breaker,
        lambda engine: _halt_symbol(engine, "L1"),
        lambda engine: _halt_symbol(engine, "L3"),  # rest of day: ends at close
    ],
)
def test_the_close_reopens_a_breaker_level_halt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, halt: Any
) -> None:
    engine, pub = _engine(monkeypatch, tmp_path)
    halt(engine)

    _close(engine)

    assert engine._halted_symbols[SYMBOL] is False
    assert _halt_status(engine, pub) == []
