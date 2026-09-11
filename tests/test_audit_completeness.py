"""Coverage for the audit-completeness pass (see docs/user-guide/190-audit.md).

pm-audit is a bare, empty-prefix ZMQ SUB on the engine's PUB :5556 socket — it
can only ever see what gets published there. Before this pass, several
engine-initiated decisions produced an outcome on the wire with no reason
(a kill switch, an admin mass-cancel, a circuit-breaker halt, a gateway
disconnect, a quote replacement, a quote leg cancelled because its sibling
filled all published order.cancelled with cancel_reason absent), one
decision produced no outcome at all (a combo child leg's acceptance), and a
few decision points reached only the process log (GTC-restore counts, an
absorbed maintenance-flush exception, a dispatch-handler crash, an
undecodable inbound message). This module tests that each of those now
reaches the wire.
"""

from __future__ import annotations

from typing import Any

import pytest

from edumatcher.models.combo import ComboLeg
from edumatcher.engine.config_loader import MMQuoteSeed, SymbolConfig
from edumatcher.models.combo import ComboType
from edumatcher.models.order import Order, OrderType, Side, TIF
from tests.engine_harness import (
    SYMBOL,
    connect,
    make_engine,
    msgs,
    order_payload,
)


def _cancelled(pub_sock: Any, gateway_id: str = "GW01") -> list[dict[str, Any]]:
    return msgs(pub_sock, f"order.cancelled.{gateway_id}")


def _quote_status(pub_sock: Any, gateway_id: str = "GW01") -> list[dict[str, Any]]:
    return msgs(pub_sock, f"quote.status.{gateway_id}")


class TestCancelReasonCoverage:
    """Every engine-initiated cancel now says why, and (when one exists)
    which admin/kill-switch command caused it."""

    def test_self_kill_switch_sets_reason_and_command_id(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")
        payload = order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.00)
        engine._handle_new_order(payload)

        engine._handle_kill_switch({"gateway_id": "GW01", "command_id": "CMD-1"})

        cancelled = _cancelled(pub, "GW01")
        assert len(cancelled) == 1
        assert cancelled[0]["cancel_reason"] == "KILL_SWITCH"
        assert cancelled[0]["command_id"] == "CMD-1"

    def test_admin_cancel_symbol_sets_reason_and_command_id(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        engine, pub = make_engine(
            monkeypatch,
            tmp_path,
            gateways=("GW01", "ADMIN01"),
            admin_gateways=("ADMIN01",),
        )
        connect(engine, "GW01", "ADMIN01")
        payload = order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.00)
        engine._handle_new_order(payload)

        engine._handle_cancel_symbol(
            {"gateway_id": "ADMIN01", "symbol": SYMBOL, "command_id": "CMD-2"}
        )

        cancelled = _cancelled(pub, "GW01")
        assert len(cancelled) == 1
        assert cancelled[0]["cancel_reason"] == "ADMIN_CANCEL_SYMBOL"
        assert cancelled[0]["command_id"] == "CMD-2"

    def test_admin_kill_switch_gateway_sets_reason_and_command_id(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        engine, pub = make_engine(
            monkeypatch,
            tmp_path,
            gateways=("GW01", "ADMIN01"),
            admin_gateways=("ADMIN01",),
        )
        connect(engine, "GW01", "ADMIN01")
        payload = order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.00)
        engine._handle_new_order(payload)

        engine._handle_kill_switch_gateway(
            {
                "gateway_id": "ADMIN01",
                "target_gateway_id": "GW01",
                "command_id": "CMD-3",
            }
        )

        cancelled = _cancelled(pub, "GW01")
        assert len(cancelled) == 1
        assert cancelled[0]["cancel_reason"] == "KILL_SWITCH"
        assert cancelled[0]["command_id"] == "CMD-3"

    def test_gateway_disconnect_cancels_quote_with_reason(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """Default disconnect_behaviour is CANCEL_QUOTES_ONLY, so this
        exercises the quote-cancel path; no command_id exists for a
        disconnect, so it stays absent."""
        engine, pub = make_engine(monkeypatch, tmp_path, mm_gateways=("GW01",))
        connect(engine, "GW01")
        engine._handle_quote_new(
            {
                "gateway_id": "GW01",
                "symbol": SYMBOL,
                "quote_id": "Q1",
                "bid_price": 9900,
                "ask_price": 10100,
                "bid_qty": 100,
                "ask_qty": 100,
                "tif": "DAY",
            }
        )

        engine._handle_gateway_disconnect({"gateway_id": "GW01"})

        cancelled = _cancelled(pub, "GW01")
        assert len(cancelled) == 2  # bid + ask leg
        for c in cancelled:
            assert c["cancel_reason"] == "GATEWAY_DISCONNECT"
            assert "command_id" not in c

    def test_quote_replace_cancels_previous_legs_as_replaced(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path, mm_gateways=("GW01",))
        connect(engine, "GW01")
        new_quote = {
            "gateway_id": "GW01",
            "symbol": SYMBOL,
            "quote_id": "Q1",
            "bid_price": 9900,
            "ask_price": 10100,
            "bid_qty": 100,
            "ask_qty": 100,
            "tif": "DAY",
        }
        engine._handle_quote_new(new_quote)
        engine._handle_quote_new({**new_quote, "bid_price": 9800, "quote_id": "Q2"})

        cancelled = _cancelled(pub, "GW01")
        assert len(cancelled) == 2
        for c in cancelled:
            assert c["cancel_reason"] == "QUOTE_REPLACED"

    def test_quote_leg_filled_cancels_sibling_as_quote_leg_filled(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path, mm_gateways=("GW01",))
        connect(engine, "GW01", "GW02")
        engine._handle_quote_new(
            {
                "gateway_id": "GW01",
                "symbol": SYMBOL,
                "quote_id": "Q1",
                "bid_price": 10000,
                "ask_price": 10100,
                "bid_qty": 100,
                "ask_qty": 100,
                "tif": "DAY",
            }
        )
        # Aggressively sell into the bid so it fully fills, inactivating the
        # quote and (under the default INACTIVATE_ON_ANY_FILL policy)
        # cancelling the untouched ask leg as its sibling.
        engine._handle_new_order(
            order_payload(Side.SELL, OrderType.LIMIT, 100, "GW02", price=100.00)
        )

        cancelled = _cancelled(pub, "GW01")
        assert len(cancelled) == 1
        assert cancelled[0]["cancel_reason"] == "QUOTE_LEG_FILLED"

    def test_client_requested_quote_cancel_has_no_reason(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path, mm_gateways=("GW01",))
        connect(engine, "GW01")
        engine._handle_quote_new(
            {
                "gateway_id": "GW01",
                "symbol": SYMBOL,
                "quote_id": "Q1",
                "bid_price": 9900,
                "ask_price": 10100,
                "bid_qty": 100,
                "ask_qty": 100,
                "tif": "DAY",
            }
        )
        engine._handle_quote_cancel({"gateway_id": "GW01", "symbol": SYMBOL})

        cancelled = _cancelled(pub, "GW01")
        assert len(cancelled) == 2
        for c in cancelled:
            assert "cancel_reason" not in c
            assert "command_id" not in c


class TestComboLegAck:
    """Every combo child leg gets its own order.ack -- previously none did."""

    def test_live_combo_legs_are_acked_before_the_combo_ack(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        # Two symbols: _validate_combo rejects a combo whose legs repeat a
        # symbol, so a same-symbol pair (as in most of this module's other
        # tests) would never reach the leg-acceptance loop this test targets.
        engine, pub = make_engine(monkeypatch, tmp_path, symbols=(SYMBOL, "MSFT"))
        connect(engine, "GW01")
        from edumatcher.models.combo import ComboOrder

        combo = ComboOrder.create(
            combo_id="C1",
            gateway_id="GW01",
            combo_type=ComboType.AON,
            tif=TIF.DAY,
            legs=[
                ComboLeg(
                    symbol=SYMBOL,
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    price=10000,
                ),
                ComboLeg(
                    symbol="MSFT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=10,
                    price=10500,
                ),
            ],
        )
        engine._handle_combo_order(combo.to_dict())

        acks = msgs(pub, "order.ack.GW01")
        assert len(acks) == 2
        assert all(a["accepted"] is True for a in acks)
        combo_acks = msgs(pub, "combo.ack.GW01")
        assert len(combo_acks) == 1


class TestIsSeed:
    """A config-bootstrapped order/quote leg is marked is_seed=True; a live
    one is not -- purely observational, origin still governs routing."""

    def test_order_round_trips_is_seed(self) -> None:
        o = Order.create(
            symbol=SYMBOL,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW01",
            price=10000,
            is_seed=True,
        )
        assert o.is_seed is True
        restored = Order.from_dict(o.to_dict())
        assert restored.is_seed is True

        live = Order.create(
            symbol=SYMBOL,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW01",
            price=10000,
        )
        assert live.is_seed is False
        assert Order.from_dict(live.to_dict()).is_seed is False

    def test_seeded_mm_quote_legs_are_marked_is_seed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        engine, pub = make_engine(
            monkeypatch,
            tmp_path,
            mm_gateways=("MM01",),
            symbol_configs={
                SYMBOL: SymbolConfig(
                    name=SYMBOL,
                    market_maker_quotes=[
                        MMQuoteSeed(
                            gateway_id="MM01",
                            bid_price=99.0,
                            ask_price=101.0,
                            bid_qty=100,
                            ask_qty=100,
                        )
                    ],
                )
            },
        )
        engine._restore_gtc()
        engine._load_config()

        acks = msgs(pub, "order.ack.MM01")
        assert len(acks) == 2
        assert all(a["is_seed"] is True for a in acks)

    def test_live_order_is_not_marked_is_seed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")
        engine._handle_new_order(
            order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.00)
        )
        acks = msgs(pub, "order.ack.GW01")
        assert len(acks) == 1
        assert acks[0].get("is_seed", False) is False


class TestStartupRecovery:
    """_restore_gtc() announces its summary once, on the wire."""

    def test_restore_gtc_publishes_a_summary_with_real_counts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        gtc_order = Order.create(
            symbol=SYMBOL,
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            gateway_id="GW01",
            tif=TIF.GTC,
            price=10000,
        )
        engine, pub = make_engine(monkeypatch, tmp_path, gtc_orders=[gtc_order])

        engine._restore_gtc()

        recoveries = msgs(pub, "system.startup_recovery")
        assert len(recoveries) == 1
        assert recoveries[0]["restored_orders"] == 1
        assert recoveries[0]["failed_orders"] == 0
        assert recoveries[0]["discarded_stale_day_orders"] == 0
        assert recoveries[0]["restored_combos"] == 0

    def test_restore_gtc_publishes_a_summary_even_with_nothing_to_restore(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """Worth a record even when every count is zero -- an empty restart
        is still a fact about what happened."""
        engine, pub = make_engine(monkeypatch, tmp_path)

        engine._restore_gtc()

        recoveries = msgs(pub, "system.startup_recovery")
        assert len(recoveries) == 1
        assert recoveries[0]["restored_orders"] == 0


class TestAr05KillSwitchIdLists:
    """AR-0.5: risk.kill_switch_ack's cancelled_order_ids lists exactly the
    order ids cancelled_orders counts -- not just how many, but which."""

    def test_cancelled_order_ids_match_the_orders_actually_cancelled(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path, symbols=(SYMBOL, "MSFT"))
        connect(engine, "GW01")

        submitted_ids = []
        for symbol, price in (
            (SYMBOL, 100.00),
            (SYMBOL, 101.00),
            ("MSFT", 200.00),
        ):
            payload = order_payload(
                Side.BUY, OrderType.LIMIT, 100, "GW01", price=price, symbol=symbol
            )
            engine._handle_new_order(payload)
            submitted_ids.append(payload["id"])

        engine._handle_kill_switch({"gateway_id": "GW01", "command_id": "CMD-AR05"})

        acks = msgs(pub, "risk.kill_switch_ack.GW01")
        assert len(acks) == 1
        ack = acks[0]
        assert ack["cancelled_orders"] == 3
        assert set(ack["cancelled_order_ids"]) == set(submitted_ids)
        assert len(ack["cancelled_order_ids"]) == ack["cancelled_orders"]


class TestDiagnostic:
    """Internal failures the engine absorbs and keeps running past are now
    on the wire, not just in the process log."""

    def test_maintenance_flush_failure_publishes_a_diagnostic(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path)

        def _boom() -> None:
            raise RuntimeError("disk full")

        # _run_maintenance reports getattr(flush, "__name__", "?"); a plain
        # lambda would report "<lambda>" instead of the flush it replaces, so
        # name this the way the real bound method would report itself.
        _boom.__name__ = "_flush_snapshots"
        monkeypatch.setattr(engine, "_flush_snapshots", _boom)

        engine._run_maintenance()

        diags = msgs(pub, "system.diagnostic")
        assert len(diags) == 1
        assert diags[0]["component"] == "MAINTENANCE_FLUSH"
        assert diags[0]["detail"] == "_flush_snapshots"
        assert diags[0]["error"] == "disk full"
        assert diags[0]["count"] == 1

    def test_undecodable_message_publishes_a_diagnostic(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        # Drives the actual receive-decode-dispatch step via the shared
        # helper test_engine_durability.py keeps in sync with run()'s body
        # (including its diagnostic publish), rather than re-deriving that
        # guarded block inline here where it could drift from the real one.
        from tests.engine_harness import FakeSock
        from tests.test_engine_durability import _run_one_receive_iteration

        engine, pub = make_engine(monkeypatch, tmp_path)
        engine.pull_sock = FakeSock()
        engine.pull_sock.recv_multipart = lambda: [b"order.new"]  # single frame

        _run_one_receive_iteration(engine)

        assert engine._undecodable_count == 1
        diags = msgs(pub, "system.diagnostic")
        assert len(diags) == 1
        assert diags[0]["component"] == "UNDECODABLE_MESSAGE"
        assert diags[0]["count"] == 1


class TestAmendOldValues:
    """order.amended carries old_price/old_qty alongside the new values."""

    def test_amend_reports_old_and_new_price_and_qty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        engine, pub = make_engine(monkeypatch, tmp_path)
        connect(engine, "GW01")
        payload = order_payload(Side.BUY, OrderType.LIMIT, 100, "GW01", price=100.00)
        engine._handle_new_order(payload)

        engine._handle_amend(
            {
                "order_id": payload["id"],
                "gateway_id": "GW01",
                "price": 101.00,
                "qty": 150,
            }
        )

        amended = msgs(pub, "order.amended.GW01")
        assert len(amended) == 1
        assert amended[0]["old_price"] == pytest.approx(100.00)
        assert amended[0]["old_qty"] == 100
        assert amended[0]["price"] == pytest.approx(101.00)
        assert amended[0]["qty"] == 150
