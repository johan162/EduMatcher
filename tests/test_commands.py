"""
Tests for edumatcher.commands.ExchangeCommandClient.

Strategy
--------
Each test injects two fake objects:

    _push_sock  — a _FakePush that captures send_multipart() calls.
    _recv_queue — a deque[list[bytes]] pre-loaded with engine responses.

The client's _recv() drains the queue without any ZMQ polling, so tests
run without a live engine.

The send-side assertions verify that the correct (topic, payload) frames
were placed on the push socket — i.e. the command mapped to the right message.
The return-value assertions verify that the payload from the queue is
correctly parsed and returned.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import pytest

from edumatcher.commands import CommandTimeoutError, ExchangeCommandClient
from edumatcher.models.message import (
    decode,
    encode,
    make_book_msg,
    make_cancel_symbol_ack_msg,
    make_circuit_breaker_halt_all_ack_msg,
    make_circuit_breaker_resume_all_ack_msg,
    make_gateway_auth_msg,
    make_gateways_msg,
    make_kill_switch_ack_msg,
    make_orders_msg,
    make_quote_ack_msg,
    make_quote_bootstrap_msg,
    make_index_history_msg,
    make_index_corp_action_ack_msg,
    make_index_constituent_change_ack_msg,
    make_session_schedule_msg,
    make_session_status_msg,
    make_symbol_halt_ack_msg,
    make_symbol_resume_ack_msg,
    make_symbols_msg,
    make_volume_msg,
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakePush:
    sent: list[list[bytes]] = field(default_factory=list)

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        pass


def _q(*frames_list: list[bytes]) -> deque[list[bytes]]:
    """Build a _recv_queue from pre-encoded frame lists."""
    return deque(frames_list)


def _client(
    gw_id: str = "GW_ADMIN", recv_queue: deque[list[bytes]] | None = None
) -> tuple[ExchangeCommandClient, _FakePush]:
    push = _FakePush()
    client = ExchangeCommandClient(
        gw_id,
        _push_sock=push,
        _sub_sock=None,
        _recv_queue=recv_queue or deque(),
    )
    return client, push


def _last_sent(push: _FakePush) -> tuple[str, dict]:
    """Decode the most recently sent frames."""
    return decode(push.sent[-1])


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_connect_sends_correct_frames(self) -> None:
        client, push = _client(
            recv_queue=_q(make_gateway_auth_msg("GW_ADMIN", True, description="Ops"))
        )
        result = client.connect()

        topic, payload = _last_sent(push)
        assert topic == "system.gateway_connect"
        assert payload["gateway_id"] == "GW_ADMIN"

        assert result["accepted"] is True
        assert result["description"] == "Ops"

    def test_connect_gw_id_uppercased(self) -> None:
        client, push = _client(
            "gw_admin",
            recv_queue=_q(make_gateway_auth_msg("GW_ADMIN", True)),
        )
        client.connect()
        _, payload = _last_sent(push)
        assert payload["gateway_id"] == "GW_ADMIN"

    def test_disconnect_sends_correct_frames_no_recv(self) -> None:
        client, push = _client()
        client.disconnect()

        topic, payload = _last_sent(push)
        assert topic == "system.gateway_disconnect"
        assert payload["gateway_id"] == "GW_ADMIN"
        assert payload["reason"] == ""

    def test_context_manager_calls_close(self, monkeypatch) -> None:
        push = _FakePush()
        closed = []

        class _CloseSpy:
            def close(self):
                closed.append(True)

        client = ExchangeCommandClient(
            "GW_ADMIN",
            _push_sock=push,
            _sub_sock=_CloseSpy(),
            _recv_queue=deque(),
        )
        # Manually set _owns_sockets to True to exercise close path
        client._owns_sockets = True
        with client:
            pass
        # push.close() was called (no-op in _FakePush); sub close was called
        assert closed  # _CloseSpy.close() ran


# ---------------------------------------------------------------------------
# ADMIN risk controls
# ---------------------------------------------------------------------------


class TestAdminRiskControls:
    def test_halt_all_sends_correct_frames(self) -> None:
        client, push = _client(
            recv_queue=_q(
                make_circuit_breaker_halt_all_ack_msg(
                    "GW_ADMIN", True, halted_symbols=3, cancelled_quotes=6
                )
            )
        )
        result = client.halt_all()

        topic, payload = _last_sent(push)
        assert topic == "risk.circuit_breaker_halt_all"
        assert payload["gateway_id"] == "GW_ADMIN"

        assert result["accepted"] is True
        assert result["halted_symbols"] == 3
        assert result["cancelled_quotes"] == 6

    def test_halt_all_rejected(self) -> None:
        client, push = _client(
            recv_queue=_q(
                make_circuit_breaker_halt_all_ack_msg(
                    "GW_ADMIN", False, reason="Not ADMIN"
                )
            )
        )
        result = client.halt_all()
        assert result["accepted"] is False
        assert "ADMIN" in result["reason"]

    def test_resume_all_sends_correct_frames(self) -> None:
        client, push = _client(
            recv_queue=_q(
                make_circuit_breaker_resume_all_ack_msg(
                    "GW_ADMIN", True, resumed_symbols=3
                )
            )
        )
        result = client.resume_all()

        topic, payload = _last_sent(push)
        assert topic == "risk.circuit_breaker_resume_all"
        assert payload["gateway_id"] == "GW_ADMIN"

        assert result["accepted"] is True
        assert result["resumed_symbols"] == 3

    def test_resume_all_zero_when_nothing_halted(self) -> None:
        client, push = _client(
            recv_queue=_q(
                make_circuit_breaker_resume_all_ack_msg(
                    "GW_ADMIN", True, resumed_symbols=0
                )
            )
        )
        result = client.resume_all()
        assert result["accepted"] is True
        assert result["resumed_symbols"] == 0


# ---------------------------------------------------------------------------
# Risk controls available to any gateway
# ---------------------------------------------------------------------------


class TestRiskControls:
    def test_kill_switch_all_symbols(self) -> None:
        client, push = _client(
            recv_queue=_q(
                make_kill_switch_ack_msg("TRADER01", True, cancelled_orders=5)
            )
        )
        result = client.kill_switch("TRADER01")

        topic, payload = _last_sent(push)
        assert topic == "risk.kill_switch"
        assert payload["gateway_id"] == "TRADER01"
        assert payload["symbol"] == ""

        assert result["accepted"] is True
        assert result["cancelled_orders"] == 5

    def test_kill_switch_scoped_to_symbol(self) -> None:
        client, push = _client(
            recv_queue=_q(
                make_kill_switch_ack_msg("TRADER01", True, cancelled_orders=2)
            )
        )
        client.kill_switch("TRADER01", symbol="aapl")  # lowercase input

        _, payload = _last_sent(push)
        assert payload["gateway_id"] == "TRADER01"
        assert payload["symbol"] == "AAPL"  # uppercased by client

    def test_mass_cancel_delegates_to_kill_switch(self) -> None:
        client, push = _client(
            recv_queue=_q(
                make_kill_switch_ack_msg(
                    "MM01", True, cancelled_orders=1, cancelled_quotes=2
                )
            )
        )
        result = client.mass_cancel("MM01", "MSFT")

        topic, payload = _last_sent(push)
        assert topic == "risk.kill_switch"
        assert payload["gateway_id"] == "MM01"
        assert payload["symbol"] == "MSFT"
        assert result["cancelled_quotes"] == 2

    def test_quote_cancel_sends_correct_frames(self) -> None:
        client, push = _client(recv_queue=_q(make_quote_ack_msg("MM01", "Q001", True)))
        result = client.quote_cancel("mm01", "aapl")  # lowercase input

        topic, payload = _last_sent(push)
        assert topic == "quote.cancel"
        assert payload["gateway_id"] == "MM01"  # uppercased
        assert payload["symbol"] == "AAPL"  # uppercased

        assert result["accepted"] is True

    def test_gateway_kick_sends_disconnect_for_target(self) -> None:
        client, push = _client()
        client.gateway_kick("TRADER01", reason="Compliance hold")

        topic, payload = _last_sent(push)
        assert topic == "system.gateway_disconnect"
        assert payload["gateway_id"] == "TRADER01"
        assert payload["reason"] == "Compliance hold"

    def test_gateway_kick_no_reason(self) -> None:
        client, push = _client()
        client.gateway_kick("TRADER01")

        _, payload = _last_sent(push)
        assert payload["reason"] == ""


# ---------------------------------------------------------------------------
# Data queries
# ---------------------------------------------------------------------------


class TestDataQueries:
    def test_book_depth_sends_snapshot_request(self) -> None:
        book_payload = {
            "symbol": "AAPL",
            "bids": [{"price": 150.0, "qty": 100, "count": 1}],
            "asks": [{"price": 150.5, "qty": 200, "count": 2}],
            "last_price": 150.25,
            "last_qty": 50,
            "recent_trades": [],
        }
        client, push = _client(recv_queue=_q(make_book_msg("AAPL", book_payload)))
        result = client.book_depth("aapl")  # lowercase input

        topic, payload = _last_sent(push)
        assert topic == "book.snapshot_request"
        assert payload["symbol"] == "AAPL"  # uppercased

        assert result["symbol"] == "AAPL"
        assert result["bids"][0]["price"] == 150.0
        assert result["last_price"] == 150.25

    def test_order_list_returns_orders_array(self) -> None:
        orders = [{"id": "abc", "symbol": "AAPL", "side": "BUY", "remaining_qty": 100}]
        client, push = _client(recv_queue=_q(make_orders_msg("TRADER01", orders)))
        result = client.order_list("TRADER01")

        topic, payload = _last_sent(push)
        assert topic == "order.orders_request"
        assert payload["gateway_id"] == "TRADER01"

        assert len(result) == 1
        assert result[0]["id"] == "abc"

    def test_order_list_empty_when_no_orders(self) -> None:
        client, push = _client(recv_queue=_q(make_orders_msg("TRADER01", [])))
        result = client.order_list("TRADER01")
        assert result == []

    def test_symbol_list_returns_symbols(self) -> None:
        client, push = _client(
            recv_queue=_q(make_symbols_msg("GW_ADMIN", ["AAPL", "MSFT", "TSLA"]))
        )
        result = client.symbol_list()

        topic, payload = _last_sent(push)
        assert topic == "system.symbols_request"
        assert payload["gateway_id"] == "GW_ADMIN"

        assert result == ["AAPL", "MSFT", "TSLA"]

    def test_quote_bootstrap_returns_quotes(self) -> None:
        quotes = [
            {
                "quote_id": "SEED-MM_AAPL_01-AAPL-1",
                "gateway_id": "MM_AAPL_01",
                "symbol": "AAPL",
                "state": "ACTIVE",
                "bid_order_id": "bid-1",
                "ask_order_id": "ask-1",
                "bid_price": 100.0,
                "ask_price": 101.0,
                "bid_qty": 500,
                "ask_qty": 500,
                "bid_remaining_qty": 500,
                "ask_remaining_qty": 500,
                "bid_status": "NEW",
                "ask_status": "NEW",
            }
        ]
        client, push = _client(
            recv_queue=_q(make_quote_bootstrap_msg("MM_AAPL_01", quotes))
        )
        result = client.quote_bootstrap("mm_aapl_01", symbol="aapl")

        topic, payload = _last_sent(push)
        assert topic == "system.quote_bootstrap_request"
        assert payload["gateway_id"] == "MM_AAPL_01"
        assert payload["symbol"] == "AAPL"

        assert len(result) == 1
        assert result[0]["symbol"] == "AAPL"
        assert result[0]["quote_id"] == "SEED-MM_AAPL_01-AAPL-1"


class TestIndexCommands:
    def test_index_history_sends_request_to_index_channel(self) -> None:
        client, push = _client(
            recv_queue=_q(
                make_index_history_msg(
                    gateway_id="GW_ADMIN",
                    index_id="EDU100",
                    records=[{"type": "CORP_ACTION", "timestamp": 1.0}],
                )
            )
        )

        result = client.index_history("edu100", from_ts=0.0, to_ts=10.0)

        topic, payload = _last_sent(push)
        assert topic == "index.history_request"
        assert payload["gateway_id"] == "GW_ADMIN"
        assert payload["index_id"] == "EDU100"
        assert len(result["records"]) == 1

    def test_index_corp_action_sends_and_receives_ack(self) -> None:
        client, push = _client(
            recv_queue=_q(
                make_index_corp_action_ack_msg(
                    gateway_id="GW_ADMIN",
                    accepted=True,
                    index_id="EDU100",
                    level=1001.0,
                    divisor=99.0,
                )
            )
        )

        result = client.index_corp_action(
            "edu100",
            action="split",
            symbol="aapl",
            ratio_numerator=2,
            ratio_denominator=1,
        )

        topic, payload = _last_sent(push)
        assert topic == "index.corp_action"
        assert payload["index_id"] == "EDU100"
        assert payload["symbol"] == "AAPL"
        assert payload["action"] == "SPLIT"
        assert result["accepted"] is True

    def test_index_add_and_delist_constituent(self) -> None:
        client, push = _client(
            recv_queue=_q(
                make_index_constituent_change_ack_msg(
                    gateway_id="GW_ADMIN",
                    accepted=True,
                    index_id="EDU100",
                ),
                make_index_constituent_change_ack_msg(
                    gateway_id="GW_ADMIN",
                    accepted=True,
                    index_id="EDU100",
                ),
            )
        )

        add_result = client.index_add_constituent(
            "edu100",
            "amzn",
            shares_outstanding=10,
            initial_price=195.0,
        )
        add_topic, add_payload = decode(push.sent[-1])
        assert add_topic == "index.constituent_change"
        assert add_payload["change_type"] == "ADD"
        assert add_payload["symbol"] == "AMZN"
        assert add_result["accepted"] is True

        delist_result = client.index_delist("edu100", "amzn")
        delist_topic, delist_payload = decode(push.sent[-1])
        assert delist_topic == "index.constituent_change"
        assert delist_payload["change_type"] == "DELIST"
        assert delist_result["accepted"] is True


# ---------------------------------------------------------------------------
# Session control
# ---------------------------------------------------------------------------


class TestSessionControl:
    def test_session_advance_sends_transition(self) -> None:
        state_msg = encode(
            "session.state", {"state": "CONTINUOUS", "prev_state": "OPENING_AUCTION"}
        )
        client, push = _client(recv_queue=_q(state_msg))
        result = client.session_advance("continuous")  # lowercase input

        topic, payload = _last_sent(push)
        assert topic == "session.transition"
        assert payload["to_state"] == "CONTINUOUS"  # uppercased

        assert result["state"] == "CONTINUOUS"
        assert result["prev_state"] == "OPENING_AUCTION"


# ---------------------------------------------------------------------------
# _recv behaviour
# ---------------------------------------------------------------------------


class TestRecvBehaviour:
    def test_recv_skips_unrelated_messages_before_matching(self) -> None:
        """Messages that don't match the prefix are silently discarded."""
        unrelated = encode("order.ack.TRADER01", {"order_id": "x", "accepted": True})
        halt_ack = make_circuit_breaker_halt_all_ack_msg(
            "GW_ADMIN", True, halted_symbols=1
        )

        client, _ = _client(recv_queue=_q(unrelated, halt_ack))
        result = client.halt_all()

        assert result["accepted"] is True
        assert result["halted_symbols"] == 1

    def test_recv_raises_timeout_when_queue_exhausted(self) -> None:
        """An empty queue raises CommandTimeoutError."""
        client, push = _client(recv_queue=deque())  # empty — nothing to receive
        with pytest.raises(CommandTimeoutError, match="exhausted"):
            client.halt_all()

    def test_recv_raises_timeout_when_no_prefix_match(self) -> None:
        """Queue has messages but none match the expected prefix."""
        unrelated1 = encode("order.ack.X", {"accepted": True})
        unrelated2 = encode("trade.executed", {"price": 100})
        client, _ = _client(recv_queue=_q(unrelated1, unrelated2))
        with pytest.raises(CommandTimeoutError):
            client.halt_all()

    def test_multiple_commands_in_sequence(self) -> None:
        """Each command consumes exactly its own ack from the queue."""
        halt_ack = make_circuit_breaker_halt_all_ack_msg(
            "GW_ADMIN", True, halted_symbols=2
        )
        resume_ack = make_circuit_breaker_resume_all_ack_msg(
            "GW_ADMIN", True, resumed_symbols=2
        )

        client, push = _client(recv_queue=_q(halt_ack, resume_ack))

        r1 = client.halt_all()
        r2 = client.resume_all()

        assert r1["halted_symbols"] == 2
        assert r2["resumed_symbols"] == 2
        assert len(push.sent) == 2

        topic0, _ = decode(push.sent[0])
        topic1, _ = decode(push.sent[1])
        assert topic0 == "risk.circuit_breaker_halt_all"
        assert topic1 == "risk.circuit_breaker_resume_all"


# ---------------------------------------------------------------------------
# New read-only query commands
# ---------------------------------------------------------------------------


class TestSessionStatus:
    def test_returns_state_and_sessions_enabled(self) -> None:
        ack = make_session_status_msg("GW_ADMIN", "CONTINUOUS", True)
        client, push = _client(recv_queue=_q(ack))
        result = client.session_status()
        assert result["state"] == "CONTINUOUS"
        assert result["sessions_enabled"] is True

    def test_sends_correct_topic(self) -> None:
        ack = make_session_status_msg("GW_ADMIN", "CLOSED", False)
        client, push = _client(recv_queue=_q(ack))
        client.session_status()
        topic, payload = _last_sent(push)
        assert topic == "system.session_state_request"
        assert payload["gateway_id"] == "GW_ADMIN"

    def test_sessions_disabled(self) -> None:
        ack = make_session_status_msg("GW_ADMIN", "PRE_OPEN", False)
        client, push = _client(recv_queue=_q(ack))
        result = client.session_status()
        assert result["sessions_enabled"] is False


class TestSessionSchedule:
    def test_returns_schedule_fields(self) -> None:
        sched = {
            "pre_open": "08:00",
            "opening_auction_start": "09:00",
            "continuous_start": "09:30",
            "closing_auction_start": "16:00",
            "closing_auction_end": "16:15",
        }
        ack = make_session_schedule_msg("GW_ADMIN", True, sched)
        client, push = _client(recv_queue=_q(ack))
        result = client.session_schedule()
        assert result["sessions_enabled"] is True
        assert result["schedule"]["continuous_start"] == "09:30"

    def test_sends_correct_topic(self) -> None:
        ack = make_session_schedule_msg("GW_ADMIN", False, None)
        client, push = _client(recv_queue=_q(ack))
        client.session_schedule()
        topic, payload = _last_sent(push)
        assert topic == "system.session_schedule_request"
        assert payload["gateway_id"] == "GW_ADMIN"

    def test_no_schedule_returns_empty_dict(self) -> None:
        ack = make_session_schedule_msg("GW_ADMIN", False, None)
        client, push = _client(recv_queue=_q(ack))
        result = client.session_schedule()
        assert result["sessions_enabled"] is False
        # make_session_schedule_msg encodes None as {}
        assert result["schedule"] == {}


class TestGatewayList:
    def test_returns_list_of_gateways(self) -> None:
        gateways = [
            {
                "id": "GW_ADMIN",
                "role": "ADMIN",
                "description": "Admin gateway",
                "connected": True,
            },
            {
                "id": "TRADER01",
                "role": "TRADER",
                "description": "Trader 1",
                "connected": False,
            },
        ]
        ack = make_gateways_msg("GW_ADMIN", gateways)
        client, push = _client(recv_queue=_q(ack))
        result = client.gateway_list()
        assert len(result) == 2
        assert result[0]["id"] == "GW_ADMIN"
        assert result[0]["connected"] is True
        assert result[1]["connected"] is False

    def test_sends_correct_topic(self) -> None:
        ack = make_gateways_msg("GW_ADMIN", [])
        client, push = _client(recv_queue=_q(ack))
        client.gateway_list()
        topic, payload = _last_sent(push)
        assert topic == "system.gateways_request"
        assert payload["gateway_id"] == "GW_ADMIN"

    def test_empty_gateways(self) -> None:
        ack = make_gateways_msg("GW_ADMIN", [])
        client, push = _client(recv_queue=_q(ack))
        assert client.gateway_list() == []


class TestVolume:
    def test_returns_symbol_and_total_data(self) -> None:
        symbols_vol = {
            "AAPL": {"qty": 500, "value": 75000.0, "trades": 10},
            "GOOG": {"qty": 200, "value": 50000.0, "trades": 5},
        }
        ack = make_volume_msg("GW_ADMIN", symbols_vol, 700, 125000.0, 15)
        client, push = _client(recv_queue=_q(ack))
        result = client.volume()
        assert result["total_qty"] == 700
        assert result["total_value"] == 125000.0
        assert result["total_trades"] == 15
        assert result["symbols"]["AAPL"]["qty"] == 500
        assert result["symbols"]["GOOG"]["trades"] == 5

    def test_sends_correct_topic(self) -> None:
        ack = make_volume_msg("GW_ADMIN", {}, 0, 0.0, 0)
        client, push = _client(recv_queue=_q(ack))
        client.volume()
        topic, payload = _last_sent(push)
        assert topic == "system.volume_request"
        assert payload["gateway_id"] == "GW_ADMIN"

    def test_zero_volume(self) -> None:
        ack = make_volume_msg("GW_ADMIN", {}, 0, 0.0, 0)
        client, push = _client(recv_queue=_q(ack))
        result = client.volume()
        assert result["total_qty"] == 0
        assert result["symbols"] == {}


# ---------------------------------------------------------------------------
# Per-symbol halt / resume / cancel
# ---------------------------------------------------------------------------


class TestSymbolHalt:
    def test_sends_correct_topic_and_payload(self) -> None:
        ack = make_symbol_halt_ack_msg("GW_ADMIN", "AAPL", True, cancelled_quotes=2)
        client, push = _client(recv_queue=_q(ack))
        result = client.symbol_halt("aapl")  # lowercase input

        topic, payload = _last_sent(push)
        assert topic == "risk.symbol_halt"
        assert payload["gateway_id"] == "GW_ADMIN"
        assert payload["symbol"] == "AAPL"  # uppercased by client

        assert result["accepted"] is True
        assert result["symbol"] == "AAPL"
        assert result["cancelled_quotes"] == 2

    def test_rejected_when_not_admin(self) -> None:
        ack = make_symbol_halt_ack_msg("GW_ADMIN", "AAPL", False, reason="Not ADMIN")
        client, push = _client(recv_queue=_q(ack))
        result = client.symbol_halt("AAPL")
        assert result["accepted"] is False
        assert "ADMIN" in result["reason"]

    def test_no_quotes_cancelled_when_none_active(self) -> None:
        ack = make_symbol_halt_ack_msg("GW_ADMIN", "MSFT", True, cancelled_quotes=0)
        client, push = _client(recv_queue=_q(ack))
        result = client.symbol_halt("MSFT")
        assert result["accepted"] is True
        assert result["cancelled_quotes"] == 0


class TestSymbolResume:
    def test_sends_correct_topic_and_payload(self) -> None:
        ack = make_symbol_resume_ack_msg("GW_ADMIN", "AAPL", True)
        client, push = _client(recv_queue=_q(ack))
        result = client.symbol_resume("aapl")  # lowercase input

        topic, payload = _last_sent(push)
        assert topic == "risk.symbol_resume"
        assert payload["gateway_id"] == "GW_ADMIN"
        assert payload["symbol"] == "AAPL"

        assert result["accepted"] is True
        assert result["symbol"] == "AAPL"

    def test_rejected_when_symbol_not_halted(self) -> None:
        ack = make_symbol_resume_ack_msg(
            "GW_ADMIN", "AAPL", False, reason="AAPL is not halted"
        )
        client, push = _client(recv_queue=_q(ack))
        result = client.symbol_resume("AAPL")
        assert result["accepted"] is False
        assert "not halted" in result["reason"]


class TestCancelSymbol:
    def test_sends_correct_topic_and_payload(self) -> None:
        ack = make_cancel_symbol_ack_msg(
            "GW_ADMIN", "AAPL", True, cancelled_orders=12, cancelled_quotes=2
        )
        client, push = _client(recv_queue=_q(ack))
        result = client.cancel_symbol("aapl")  # lowercase input

        topic, payload = _last_sent(push)
        assert topic == "risk.cancel_symbol"
        assert payload["gateway_id"] == "GW_ADMIN"
        assert payload["symbol"] == "AAPL"

        assert result["accepted"] is True
        assert result["symbol"] == "AAPL"
        assert result["cancelled_orders"] == 12
        assert result["cancelled_quotes"] == 2

    def test_rejected_when_not_admin(self) -> None:
        ack = make_cancel_symbol_ack_msg("GW_ADMIN", "AAPL", False, reason="ADMIN only")
        client, push = _client(recv_queue=_q(ack))
        result = client.cancel_symbol("AAPL")
        assert result["accepted"] is False

    def test_empty_book_returns_zero_counts(self) -> None:
        ack = make_cancel_symbol_ack_msg(
            "GW_ADMIN", "TSLA", True, cancelled_orders=0, cancelled_quotes=0
        )
        client, push = _client(recv_queue=_q(ack))
        result = client.cancel_symbol("TSLA")
        assert result["cancelled_orders"] == 0
        assert result["cancelled_quotes"] == 0
