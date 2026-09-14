"""The four live models (tasks AR-2.1, AR-2.2).

Two properties carry most of the weight here.

**Nothing raises.** This is the tool someone reaches for when the exchange is
already misbehaving, so every malformed thing the log can contain -- a status
that skips the ladder, a fill after the order ended, a resume with no halt --
has to come out as a finding rather than a traceback. Every illegal case below
asserts the anomaly *and* that the call returned.

**A halt is remembered well enough to explain a rejection.** That is the whole
reason the market model exists: ``reject_code=CIRCUIT_BREAKER_ACTIVE`` says an
order was refused, and only the model can say since when, by whom, and through
which corridor.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.audit.query import AuditEntry
from edumatcher.audit.replay.anomalies import (
    ACK_DUPLICATE,
    FILL_AFTER_TERMINAL,
    ILLEGAL_STATUS_TRANSITION,
    QTY_MISMATCH,
    REMAINING_NOT_MONOTONIC,
    RESUME_WITHOUT_HALT,
    RUN_SEQ_CHANGE,
)
from edumatcher.audit.replay.facts import to_fact
from edumatcher.audit.replay.state import (
    HALT_SOURCE_ADMIN,
    HALT_SOURCE_BREAKER,
    STATUS_CANCELLED,
    STATUS_EXPIRED,
    STATUS_FILLED,
    STATUS_NEW,
    STATUS_PARTIAL,
    STATUS_REJECTED,
    TERMINAL_STATUSES,
    StateModel,
)

_TS = "2026-09-08T09:31:02.118+00:00"
ORDER = "4f2c9a1e6d8b47c3a5f09e21b7d4c6a8"


def fact(topic: str, payload: dict[str, Any], ordinal: int = 0) -> Any:
    return to_fact(
        AuditEntry(_TS, topic, payload, {}, file="audit.log", line_no=ordinal + 1),
        ordinal,
    )


def codes(anomalies: Any) -> list[str]:
    return [a.code for a in anomalies]


def submitted(**overrides: Any) -> dict[str, Any]:
    payload = {
        "id": ORDER,
        "symbol": "AAPL",
        "side": "BUY",
        "order_type": "LIMIT",
        "tif": "DAY",
        "quantity": 200,
        "remaining_qty": 200,
        "gateway_id": "TRADER01",
        "tick_decimals": 2,
        "price_ticks": 7569,
        "status": STATUS_NEW,
        "arrival_seq": 8814,
        "origin": "ORDER",
        "client_tag": "blotter-88",
    }
    payload.update(overrides)
    return payload


def filled(**overrides: Any) -> dict[str, Any]:
    payload = {
        "gateway_id": "TRADER01",
        "order_id": ORDER,
        "symbol": "AAPL",
        "fill_qty": 150,
        "fill_price": 74.8,
        "remaining_qty": 50,
        "status": STATUS_PARTIAL,
        "qty": 200,
        "trade_ids": ["000042-000001873"],
        "liquidity_flag": "TAKER",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# The order model and its ladder
# ---------------------------------------------------------------------------


class TestTheOrderModel:
    def test_a_submission_is_recorded_in_full(self) -> None:
        model = StateModel()
        assert model.apply(fact("order.new", submitted())) == ()
        order = model.orders[ORDER]
        assert (order.symbol, order.side, order.order_type) == ("AAPL", "BUY", "LIMIT")
        assert (order.quantity, order.remaining_qty) == (200, 200)
        assert order.gateway_id == "TRADER01"
        assert order.arrival_seq == 8814
        assert order.status == STATUS_NEW
        assert order.terminal is False

    def test_a_fill_moves_the_tally_and_the_status(self) -> None:
        model = StateModel()
        model.apply(fact("order.new", submitted()))
        assert model.apply(fact("order.fill.TRADER01", filled())) == ()
        order = model.orders[ORDER]
        assert (order.filled_qty, order.remaining_qty, order.fills) == (150, 50, 1)
        assert order.status == STATUS_PARTIAL

    def test_two_fills_complete_it(self) -> None:
        model = StateModel()
        model.apply(fact("order.new", submitted()))
        model.apply(fact("order.fill.TRADER01", filled()))
        found = model.apply(
            fact(
                "order.fill.TRADER01",
                filled(fill_qty=50, remaining_qty=0, status=STATUS_FILLED),
            )
        )
        assert codes(found) == []
        order = model.orders[ORDER]
        assert (order.filled_qty, order.remaining_qty) == (200, 0)
        assert order.terminal is True
        assert order.closed_ts is not None

    def test_a_rejection_ends_the_order_and_says_why(self) -> None:
        model = StateModel()
        model.apply(fact("order.new", submitted()))
        model.apply(
            fact(
                "order.ack.TRADER01",
                {
                    "gateway_id": "TRADER01",
                    "order_id": ORDER,
                    "accepted": False,
                    "reject_code": "CIRCUIT_BREAKER_ACTIVE",
                    "symbol": "AAPL",
                },
            )
        )
        order = model.orders[ORDER]
        assert order.status == STATUS_REJECTED
        assert order.ended_because == "CIRCUIT_BREAKER_ACTIVE"

    def test_a_cancellation_records_its_reason(self) -> None:
        model = StateModel()
        model.apply(fact("order.new", submitted()))
        model.apply(
            fact(
                "order.cancelled.TRADER01",
                {
                    "gateway_id": "TRADER01",
                    "order_id": ORDER,
                    "symbol": "AAPL",
                    "cancel_reason": "KILL_SWITCH",
                },
            )
        )
        assert model.orders[ORDER].status == STATUS_CANCELLED
        assert model.orders[ORDER].ended_because == "KILL_SWITCH"

    def test_an_amend_moves_the_size_the_tally_is_checked_against(self) -> None:
        """Without this every fill after an amend would look like a mismatch."""
        model = StateModel()
        model.apply(fact("order.new", submitted()))
        model.apply(
            fact(
                "order.amended.TRADER01",
                {
                    "gateway_id": "TRADER01",
                    "order_id": ORDER,
                    "symbol": "AAPL",
                    "qty": 100,
                    "remaining_qty": 100,
                },
            )
        )
        found = model.apply(
            fact(
                "order.fill.TRADER01",
                filled(fill_qty=100, remaining_qty=0, status=STATUS_FILLED, qty=100),
            )
        )
        assert codes(found) == []


class TestTheStatusLadder:
    @pytest.mark.parametrize("terminal", sorted(TERMINAL_STATUSES - {STATUS_REJECTED}))
    def test_new_may_go_straight_to_any_terminal(self, terminal: str) -> None:
        model = StateModel()
        model.apply(fact("order.new", submitted()))
        found = model.apply(
            fact(
                "order.fill.TRADER01",
                filled(fill_qty=200, remaining_qty=0, status=terminal),
            )
        )
        assert ILLEGAL_STATUS_TRANSITION not in codes(found)
        assert model.orders[ORDER].status == terminal

    def test_partial_may_not_go_back_to_new(self) -> None:
        model = StateModel()
        model.apply(fact("order.new", submitted()))
        model.apply(fact("order.fill.TRADER01", filled()))
        found = model.apply(
            fact(
                "order.fill.TRADER01",
                filled(fill_qty=0, remaining_qty=50, status=STATUS_NEW),
            )
        )
        assert ILLEGAL_STATUS_TRANSITION in codes(found)

    def test_a_repeated_status_is_legal(self) -> None:
        """Two fills of one order both say PARTIAL; that is not a violation."""
        model = StateModel()
        model.apply(fact("order.new", submitted()))
        model.apply(
            fact("order.fill.TRADER01", filled(fill_qty=100, remaining_qty=100))
        )
        found = model.apply(
            fact("order.fill.TRADER01", filled(fill_qty=50, remaining_qty=50))
        )
        assert ILLEGAL_STATUS_TRANSITION not in codes(found)

    def test_an_illegal_transition_is_still_applied(self) -> None:
        """Recorded, then applied. Refusing it would leave the model
        describing a world the log does not."""
        model = StateModel()
        model.apply(fact("order.new", submitted()))
        model.apply(
            fact(
                "order.cancelled.TRADER01",
                {"gateway_id": "TRADER01", "order_id": ORDER, "symbol": "AAPL"},
            )
        )
        found = model.apply(
            fact(
                "order.fill.TRADER01",
                filled(fill_qty=200, remaining_qty=0, status=STATUS_FILLED),
            )
        )
        assert ILLEGAL_STATUS_TRANSITION in codes(found)
        assert model.orders[ORDER].status == STATUS_FILLED

    def test_an_expiry_after_a_cancel_is_illegal(self) -> None:
        model = StateModel()
        model.apply(fact("order.new", submitted()))
        model.apply(
            fact(
                "order.cancelled.TRADER01",
                {"gateway_id": "TRADER01", "order_id": ORDER, "symbol": "AAPL"},
            )
        )
        found = model.apply(
            fact(
                "order.expired.TRADER01",
                {"gateway_id": "TRADER01", "order_id": ORDER, "symbol": "AAPL"},
            )
        )
        assert ILLEGAL_STATUS_TRANSITION in codes(found)
        assert model.orders[ORDER].status == STATUS_EXPIRED


class TestTheWireVocabulary:
    """One state, two spellings on the wire.

    ``order.new.status`` is an enum declaring PARTIAL; ``order.fill.status`` is
    an unconstrained string and the engine publishes PARTIAL_FILL into it. Both
    mean remaining_qty > 0. The ladder works in one vocabulary; the model maps
    the other onto it.
    """

    def test_partial_fill_is_the_same_state_as_partial(self) -> None:
        model = StateModel()
        model.apply(fact("order.new", submitted()))
        found = model.apply(fact("order.fill.TRADER01", filled(status="PARTIAL_FILL")))
        assert ILLEGAL_STATUS_TRANSITION not in codes(found)
        assert model.orders[ORDER].status == STATUS_PARTIAL

    def test_a_second_partial_fill_is_still_legal(self) -> None:
        model = StateModel()
        model.apply(fact("order.new", submitted()))
        model.apply(
            fact(
                "order.fill.TRADER01",
                filled(fill_qty=100, remaining_qty=100, status="PARTIAL_FILL"),
            )
        )
        found = model.apply(
            fact(
                "order.fill.TRADER01",
                filled(fill_qty=50, remaining_qty=50, status="PARTIAL_FILL"),
            )
        )
        assert ILLEGAL_STATUS_TRANSITION not in codes(found)

    def test_a_status_in_neither_vocabulary_is_still_reported(self) -> None:
        """Normalising a known divergence must not become tolerating anything."""
        model = StateModel()
        model.apply(fact("order.new", submitted()))
        model.apply(fact("order.fill.TRADER01", filled()))
        found = model.apply(fact("order.fill.TRADER01", filled(status="HALF_DONE")))
        assert ILLEGAL_STATUS_TRANSITION in codes(found)


class TestLifecycleFindings:
    def test_a_fill_after_a_terminal_status_is_reported(self) -> None:
        model = StateModel()
        model.apply(fact("order.new", submitted()))
        model.apply(
            fact(
                "order.expired.TRADER01",
                {"gateway_id": "TRADER01", "order_id": ORDER, "symbol": "AAPL"},
            )
        )
        assert FILL_AFTER_TERMINAL in codes(
            model.apply(fact("order.fill.TRADER01", filled()))
        )

    def test_a_second_ack_is_reported(self) -> None:
        ack = {
            "gateway_id": "TRADER01",
            "order_id": ORDER,
            "accepted": True,
            "symbol": "AAPL",
            "qty": 200,
        }
        model = StateModel()
        model.apply(fact("order.new", submitted()))
        assert codes(model.apply(fact("order.ack.TRADER01", ack))) == []
        assert ACK_DUPLICATE in codes(model.apply(fact("order.ack.TRADER01", ack)))

    def test_remaining_qty_rising_is_reported(self) -> None:
        model = StateModel()
        model.apply(fact("order.new", submitted()))
        model.apply(fact("order.fill.TRADER01", filled()))
        found = model.apply(
            fact("order.fill.TRADER01", filled(fill_qty=10, remaining_qty=120))
        )
        assert REMAINING_NOT_MONOTONIC in codes(found)

    def test_a_tally_disagreeing_with_the_engine_is_reported(self) -> None:
        """The tool's own sum against the engine's arithmetic -- which is why
        the model keeps both numbers rather than one."""
        model = StateModel()
        model.apply(fact("order.new", submitted()))
        found = model.apply(fact("order.fill.TRADER01", filled(fill_qty=140)))
        assert QTY_MISMATCH in codes(found)

    def test_a_malformed_payload_produces_no_traceback(self) -> None:
        model = StateModel()
        for payload in ({}, {"order_id": None}, {"order_id": 17}, {"id": ""}):
            for topic in (
                "order.new",
                "order.ack.TRADER01",
                "order.fill.TRADER01",
                "order.cancelled.TRADER01",
                "order.amended.TRADER01",
            ):
                assert model.apply(fact(topic, dict(payload))) == ()


# ---------------------------------------------------------------------------
# The market model (AR-2.2)
# ---------------------------------------------------------------------------


HALT = {
    "symbol": "AAPL",
    "trigger_price": 78.90,
    "reference_price": 75.00,
    "resume_at_ns": 1788860710000000000,
    "halt_source": HALT_SOURCE_BREAKER,
    "level": "L1",
    "corridor_low": 71.25,
    "corridor_high": 78.75,
    "expansion": 0,
}


class TestTheMarketModel:
    def test_a_halt_is_remembered_with_its_corridor(self) -> None:
        model = StateModel()
        model.apply(fact("circuit_breaker.halt.AAPL", dict(HALT)))
        state = model.symbols["AAPL"]
        assert state.halted is True
        assert state.halt_source == HALT_SOURCE_BREAKER
        assert state.halt_level == "L1"
        assert (state.corridor_low, state.corridor_high) == (71.25, 78.75)
        assert state.resume_at is not None
        assert state.halted_since is not None

    def test_the_halt_explains_a_rejection(self) -> None:
        """AR-2.2's checkpoint: a halt spanning a CIRCUIT_BREAKER_ACTIVE
        rejection lets the tool state *why* the symbol was halted, with the
        corridor figures from the original halt."""
        model = StateModel()
        model.apply(fact("circuit_breaker.halt.AAPL", dict(HALT)))
        described = model.symbols["AAPL"].describe_halt()
        assert "circuit breaker" in described
        assert "L1" in described
        assert "71.25" in described and "78.75" in described

    def test_an_admin_halt_is_named_as_one(self) -> None:
        model = StateModel()
        model.apply(
            fact(
                "circuit_breaker.halt.AAPL",
                dict(HALT, halt_source=HALT_SOURCE_ADMIN, level=""),
            )
        )
        assert "admin" in model.symbols["AAPL"].describe_halt()

    def test_an_extension_moves_the_corridor(self) -> None:
        model = StateModel()
        model.apply(fact("circuit_breaker.halt.AAPL", dict(HALT)))
        model.apply(
            fact(
                "circuit_breaker.extend.AAPL",
                {
                    "symbol": "AAPL",
                    "corridor_low": 70.00,
                    "corridor_high": 80.00,
                    "resume_at_ns": 1788860999000000000,
                    "expansion": 1,
                },
            )
        )
        state = model.symbols["AAPL"]
        assert (state.corridor_low, state.corridor_high) == (70.00, 80.00)
        assert state.halted is True

    def test_a_resume_clears_the_halt(self) -> None:
        model = StateModel()
        model.apply(fact("circuit_breaker.halt.AAPL", dict(HALT)))
        found = model.apply(
            fact(
                "circuit_breaker.resume.AAPL",
                {
                    "symbol": "AAPL",
                    "halt_source": HALT_SOURCE_BREAKER,
                    "reason": "corridor expired",
                    "clamped": False,
                    "print_price": 76.10,
                },
            )
        )
        assert codes(found) == []
        state = model.symbols["AAPL"]
        assert state.halted is False
        assert state.corridor_low is None
        assert state.last_price == pytest.approx(76.10)
        assert state.describe_halt() == "not halted"

    def test_a_resume_with_no_halt_is_reported(self) -> None:
        model = StateModel()
        found = model.apply(
            fact(
                "circuit_breaker.resume.AAPL",
                {"symbol": "AAPL", "halt_source": HALT_SOURCE_BREAKER},
            )
        )
        assert RESUME_WITHOUT_HALT in codes(found)

    def test_a_session_transition_reaches_symbols_met_later(self) -> None:
        model = StateModel()
        model.apply(
            fact("session.state", {"state": "CONTINUOUS", "prev_state": "OPEN"})
        )
        model.apply(fact("circuit_breaker.halt.AAPL", dict(HALT)))
        assert model.symbols["AAPL"].session_state == "CONTINUOUS"

    def test_a_trade_moves_the_last_price(self) -> None:
        model = StateModel()
        model.apply(
            fact(
                "trade.executed",
                {
                    "id": "000042-000001873",
                    "run_seq": 42,
                    "symbol": "AAPL",
                    "price": 74.8,
                    "quantity": 150,
                    "tick_decimals": 2,
                },
            )
        )
        assert model.symbols["AAPL"].last_price == pytest.approx(74.8)


# ---------------------------------------------------------------------------
# Gateways and runs
# ---------------------------------------------------------------------------


class TestTheGatewayModel:
    def test_the_description_is_what_makes_an_actor_readable(self) -> None:
        model = StateModel()
        model.apply(
            fact(
                "system.gateway_auth.TRADER01",
                {
                    "gateway_id": "TRADER01",
                    "accepted": True,
                    "description": "Nordic Equities desk",
                    "reason": "",
                },
            )
        )
        gateway = model.gateways["TRADER01"]
        assert gateway.label == "TRADER01 (Nordic Equities desk)"
        assert gateway.auth_accepted is True
        assert gateway.connected_at is not None

    def test_an_unnamed_gateway_is_just_its_id(self) -> None:
        assert StateModel().gateway("MM01").label == "MM01"

    def test_a_disconnect_closes_the_span(self) -> None:
        model = StateModel()
        model.apply(fact("system.gateway_connect", {"gateway_id": "MM01"}))
        model.apply(
            fact("system.gateway_disconnect", {"gateway_id": "MM01", "reason": "bye"})
        )
        gateway = model.gateways["MM01"]
        assert gateway.disconnected_at is not None
        assert gateway.disconnect_reason == "bye"

    def test_orders_and_trades_are_counted_per_gateway(self) -> None:
        model = StateModel()
        model.apply(fact("order.new", submitted()))
        model.apply(fact("order.fill.TRADER01", filled()))
        assert model.gateways["TRADER01"].orders == 1
        assert model.gateways["TRADER01"].trades == 1


class TestTheRunModel:
    def test_the_first_run_seq_is_adopted_quietly(self) -> None:
        model = StateModel()
        found = model.apply(
            fact("trade.executed", {"id": "a", "run_seq": 42, "symbol": "AAPL"})
        )
        assert codes(found) == []
        assert model.run.run_seq == 42

    def test_a_restart_is_reported(self) -> None:
        """Not a fault -- but arrival_seq and the trade counter restart with
        it, so nothing may be compared across the boundary."""
        model = StateModel()
        model.apply(
            fact("trade.executed", {"id": "a", "run_seq": 42, "symbol": "AAPL"})
        )
        found = model.apply(
            fact("trade.executed", {"id": "b", "run_seq": 43, "symbol": "AAPL"})
        )
        assert RUN_SEQ_CHANGE in codes(found)
        assert model.run.run_seq == 43

    def test_recovery_counts_are_kept(self) -> None:
        model = StateModel()
        model.apply(
            fact(
                "system.startup_recovery",
                {
                    "restored_orders": 118,
                    "discarded_stale_day_orders": 6,
                    "failed_orders": 1,
                    "rebuilt_quotes": 4,
                },
            )
        )
        assert model.run.recovery_seen is True
        assert model.run.recovery_counts["restored_orders"] == 118
        assert model.run.recovery_counts["failed_orders"] == 1

    def test_a_failed_recovery_item_names_the_entity(self) -> None:
        """AR-0.5's point: "which order failed to restore?" was unanswerable
        while the trail carried only the counts."""
        model = StateModel()
        model.apply(
            fact(
                "system.recovery_item",
                {
                    "entity_id": ORDER,
                    "kind": "order",
                    "outcome": "FAILED",
                    "symbol": "AAPL",
                    "detail": "unparseable",
                },
            )
        )
        assert model.run.recovery_failures == [ORDER]

    def test_a_restart_clears_the_previous_runs_recovery(self) -> None:
        model = StateModel()
        model.apply(
            fact("trade.executed", {"id": "a", "run_seq": 42, "symbol": "AAPL"})
        )
        model.apply(fact("system.startup_recovery", {"restored_orders": 5}))
        model.apply(
            fact("trade.executed", {"id": "b", "run_seq": 43, "symbol": "AAPL"})
        )
        assert model.run.recovery_seen is False
        assert model.run.recovery_counts == {}


class TestNothingUnknownCrashes:
    def test_an_unmodelled_topic_is_ignored_without_complaint(self) -> None:
        model = StateModel()
        assert model.apply(fact("depth.AAPL", {"symbol": "AAPL"})) == ()

    def test_an_unknown_topic_is_ignored_without_complaint(self) -> None:
        model = StateModel()
        assert model.apply(fact("future.family.thing", {"anything": 1})) == ()
