"""Order scans cost what is live; replies reach only their waiter (review P1-P3).

Every process caches every gateway's orders, terminal ones included for
``order_retention_sec`` (about 200 000 at the s300 open). The admin monitor's
opening snapshot sent all of them (1.5 s on the loop, a 77 MiB frame), and
each status-filtered scan read all of them. Request/reply topics were tested
against every market-data filter and queued on every admin monitor.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from edumatcher.api_gateway.caches import TERMINAL_ORDER_STATUSES
from edumatcher.api_gateway.config import ApiGatewayConfig, TimeoutConfig
from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.api_gateway.routers import bootstrap, ws
from edumatcher.models.message import (
    decode,
    make_ack_msg,
    make_cancelled_msg,
    make_fill_msg,
    make_symbols_msg,
)

WORKING = {"PENDING", "NEW", "PARTIAL", "AMENDED"}


def _engine(loop: asyncio.AbstractEventLoop | None = None) -> EngineClient:
    with (
        patch(
            "edumatcher.api_gateway.engine_client.make_pusher",
            return_value=MagicMock(closed=False),
        ),
        patch(
            "edumatcher.api_gateway.engine_client.make_subscriber",
            return_value=MagicMock(),
        ),
    ):
        return EngineClient(
            "tcp://127.0.0.1:1",
            "tcp://127.0.0.1:2",
            loop or asyncio.new_event_loop(),
        )


def _feed_mixed(engine: EngineClient) -> None:
    """Orders in every status, over two gateways, through real events."""
    for gw in ("GW01", "GW02"):
        for n in range(4):
            engine._handle_event(
                *decode(make_ack_msg(gw, f"{gw}-A{n}", True, request="NEW"))
            )
        engine._handle_event(
            *decode(make_fill_msg(gw, f"{gw}-A1", 5, 20.0, 5, "PARTIAL"))
        )
        engine._handle_event(
            *decode(make_fill_msg(gw, f"{gw}-A2", 10, 20.0, 0, "FILLED"))
        )
        engine._handle_event(*decode(make_cancelled_msg(gw, f"{gw}-A3")))
        engine._handle_event(
            *decode(make_ack_msg(gw, f"{gw}-R", False, "no", request="NEW"))
        )
        engine.get_caches(gw).submitted(f"{gw}-P", {"order_id": f"{gw}-P"})


@pytest.mark.anyio
async def test_the_monitor_snapshot_carries_working_orders_only() -> None:
    engine = _engine(asyncio.get_running_loop())
    _feed_mixed(engine)
    config = ApiGatewayConfig(timeouts=TimeoutConfig(engine_reply_sec=0.01))
    socket = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(engine=engine, config=config))
    )

    snapshot = await ws._monitor_snapshot(socket, "ADMIN")  # type: ignore[arg-type]

    orders = snapshot["data"]["orders"]
    assert {o["status"] for o in orders} == {"NEW", "PARTIAL", "PENDING"}
    assert len(orders) == 6
    assert {o["gateway_id"] for o in orders} == {"GW01", "GW02"}


class _NoScan(dict[str, dict[str, Any]]):
    """An order dict that refuses to be iterated: a status filter for a live
    status must reach its orders by id."""

    def values(self) -> Any:
        raise AssertionError("scanned every cached order")

    def items(self) -> Any:
        raise AssertionError("scanned every cached order")

    def __iter__(self) -> Any:
        raise AssertionError("scanned every cached order")


def test_a_live_status_filter_reads_only_live_orders() -> None:
    engine = _engine()
    cache = engine.get_caches("GW01")
    for n in range(1000):
        engine._handle_event(
            *decode(make_ack_msg("GW01", f"T{n}", False, "x", request="NEW"))
        )
    for n in range(10):
        engine._handle_event(
            *decode(make_ack_msg("GW01", f"L{n}", True, request="NEW"))
        )
    cache.orders = _NoScan(cache.orders)

    found = engine.all_orders(status="new")

    assert sorted(o["order_id"] for o in found) == [f"L{n}" for n in range(10)]


def test_active_counts_match_a_full_scan() -> None:
    engine = _engine()
    _feed_mixed(engine)
    engine._authenticated.update({"GW01", "GW03"})
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=engine)))

    counts = bootstrap._active_order_counts(request)  # type: ignore[arg-type]

    expected: dict[str, int] = {"GW01": 0, "GW03": 0}
    for gid, cache in engine._caches.items():
        for order in cache.orders.values():
            if order["status"] not in TERMINAL_ORDER_STATUSES:
                expected[gid] = expected.get(gid, 0) + 1
    assert counts == expected == {"GW01": 3, "GW02": 3, "GW03": 0}


def test_evicted_and_finished_orders_leave_the_live_index() -> None:
    engine = _engine()
    _feed_mixed(engine)
    cache = engine.get_caches("GW01")
    assert set(cache.live) == {"GW01-A0", "GW01-A1", "GW01-P"}
    engine._handle_event(*decode(make_cancelled_msg("GW01", "GW01-A0")))
    assert "GW01-A0" not in cache.live
    cache.evict_terminal_orders(1, now=float("inf"))
    assert set(cache.live) <= set(cache.orders)


@pytest.mark.anyio
async def test_a_reply_reaches_its_waiter_and_no_fan_out() -> None:
    engine = _engine(asyncio.get_running_loop())
    admin: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    market: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    tested: list[dict[str, Any]] = []
    engine.add_admin_sink(admin)

    def _accepts(event: dict[str, Any]) -> bool:
        tested.append(event)
        return True

    engine.add_market_data_sink(market, _accepts)
    topic = "system.reference.RO0123456789ABCDEF"
    waiter = asyncio.create_task(engine.await_topic(topic, 1.0))
    await asyncio.sleep(0)

    engine._handle_event(topic, {"symbols": []})

    assert (await waiter) == {"symbols": []}
    assert admin.empty() and market.empty()
    assert tested == []


@pytest.mark.anyio
async def test_a_private_reply_still_reaches_its_gateway() -> None:
    engine = _engine(asyncio.get_running_loop())
    private: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    engine.add_sink("GW01", private)

    engine._handle_event(*decode(make_symbols_msg("GW01", [])))

    assert private.get_nowait()["type"] == "system.symbols"
