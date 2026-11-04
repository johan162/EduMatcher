"""K13/K14/K15: API-gateway correlation, replace saga, restart and replay.

Findings P1 (raw API key on the engine bus), P2 (a replace whose cancel
succeeded but whose replacement failed is not recoverable), P3 (rebalance
replies resolved by arrival order, not ``command_id``), P4 (no engine
startup-recovery handling) and P5 (a venue-wide sequence compared against a
per-symbol buffer raises a false ``ReplayMiss``).

Every test here fails on the pre-fix tree; see
``docs-design/EduMatcher-Key-Component-Fixes-Workplan.md`` §5 K13-K15.
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.api_gateway.events import envelope
from edumatcher.api_gateway.index_client import IndexClient
from edumatcher.api_gateway.market_cache import MarketDataCache, ReplayMiss
from edumatcher.api_gateway.routers.reference import fetch_reference_bundle
from edumatcher.api_gateway.sessions import Session, correlation_id
from edumatcher.models.generated.index import topic_index_rebalance_ack
from edumatcher.models.generated.system import topic_reference
from edumatcher.models.generated.system import TOPIC_STARTUP_RECOVERY
from edumatcher.models.price import clear_tick_registry, register_tick_decimals
from tests.api_gateway_harness import call, make_app
from tests.test_api_gateway_writes import _ORDER, _Engine  # noqa: F401  (fixtures)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _symbols_loaded() -> Iterator[None]:
    clear_tick_registry()
    register_tick_decimals("AAPL", 2)
    register_tick_decimals("MSFT", 2)
    yield
    clear_tick_registry()


# ---------------------------------------------------------------------------
# K13 / P1 — the API key must never reach the bus
# ---------------------------------------------------------------------------

_SECRET_KEY = "secret-read-only-key-that-must-never-be-published"


class _RecordingEngine:
    """Records the correlation ids handed to engine-bound calls."""

    def __init__(self) -> None:
        self.reference_ids: list[str] = []
        self.awaited_topics: list[str] = []

    def request_reference(self, correlation: str) -> None:
        self.reference_ids.append(correlation)

    async def await_topic(self, topic: str, timeout: float) -> dict[str, Any]:
        self.awaited_topics.append(topic)
        return {"symbols": []}


async def test_p1_reference_bundle_never_puts_the_api_key_on_the_bus() -> None:
    engine = _RecordingEngine()
    session = Session(api_key=_SECRET_KEY, gateway_id=None, description="read-only")
    app = make_app(engine)

    class _Request:
        def __init__(self) -> None:
            self.app = app

    await fetch_reference_bundle(_Request(), session)  # type: ignore[arg-type]

    expected = correlation_id(session)
    assert engine.reference_ids == [expected]
    assert engine.awaited_topics == [topic_reference(expected)]
    assert _SECRET_KEY not in engine.reference_ids[0]
    assert _SECRET_KEY not in engine.awaited_topics[0]


async def test_p1_index_history_request_id_never_carries_the_api_key() -> None:
    """``history.py`` addresses pm-index with the same hashed id.

    pm-index echoes ``request_id`` into a reply topic it publishes to every
    subscriber, so a raw key there is the same leak as on the engine bus.
    """
    import edumatcher.api_gateway.routers.history as history_mod

    seen: list[str] = []

    class _IndexClient:
        async def request_history(self, *, request_id: str, **_: Any) -> dict[str, Any]:
            seen.append(request_id)
            return {"records": []}

    class _Engine:
        async def authenticate(self, gateway_id: str, timeout: float = 3.0) -> Any:
            return True, ""

    app = make_app(_Engine())
    app.state.index_client = _IndexClient()
    session = Session(api_key=_SECRET_KEY, gateway_id=None, description="read-only")

    class _Request:
        def __init__(self) -> None:
            self.app = app

    await history_mod.history_index_events(
        request=_Request(),  # type: ignore[arg-type]
        session=session,
        index_id="EDU100",
    )
    assert seen and _SECRET_KEY.upper() not in seen[0]
    assert seen[0].startswith(correlation_id(session))


def test_p1_no_engine_bound_call_site_uses_the_raw_api_key() -> None:
    """Repo-wide guard: ``session.api_key`` may only be read where it is
    hashed (``sessions.correlation_id``) or used for a purely in-process
    lookup (the rate limiter). Anything else risks putting it on a bus."""
    package = pathlib.Path("src/edumatcher/api_gateway")
    allowed = {
        # (file, enclosing function) -> why it is safe
        ("sessions.py", "correlation_id"): "hashes the key before use",
        ("routers/orders.py", "_check_rate_limit"): "in-process rate-limit key",
        ("routers/admin.py", "_check_rate_limit"): "in-process rate-limit key",
    }
    offenders: list[str] = []
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text(), str(path))
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(func):
                if (
                    isinstance(node, ast.Attribute)
                    and node.attr == "api_key"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "session"
                ):
                    rel = path.relative_to(package).as_posix()
                    if (rel, func.name) in allowed:
                        continue
                    offenders.append(f"{rel}:{node.lineno} in {func.name}()")
    assert not offenders, (
        "session.api_key must not be used as a bus correlation id; "
        f"use sessions.correlation_id(session) instead: {offenders}"
    )


# ---------------------------------------------------------------------------
# K14 / P2 — a replace must be resumable from the step it reached
# ---------------------------------------------------------------------------


class _FlakyEngine(_Engine):
    """Cancels fine; the first ``send_new_order`` blows up."""

    def __init__(self, failures: int = 1) -> None:
        super().__init__()
        self.failures = failures

    def send_new_order(self, order: Any) -> None:
        if self.failures > 0:
            self.failures -= 1
            raise HTTPException(
                status_code=503,
                detail={"error": {"code": "ENGINE_UNAVAILABLE", "message": "down"}},
            )
        super().send_new_order(order)


async def test_p2_retry_after_a_failed_replacement_resumes_the_saga() -> None:
    """The cancel already succeeded, so the retry must only submit the
    replacement -- re-cancelling would ask the engine to cancel an order it
    has already cancelled, and skipping the replacement would leave the
    caller with no order at all."""
    engine = _FlakyEngine()
    app = make_app(engine)
    headers = {"Idempotency-Key": "replace-key-1"}

    first, _, _ = await call(
        app, "POST", "/api/v1/orders/ORD1/replace", body=_ORDER, headers=headers
    )
    assert first == 503
    assert engine.kinds() == ["cancel"]

    status_code, _, body = await call(
        app, "POST", "/api/v1/orders/ORD1/replace", body=_ORDER, headers=headers
    )
    assert status_code == 202, body
    # Exactly one cancel in total, and the replacement did go out.
    assert engine.kinds() == ["cancel", "order"]
    assert body["cancelled_order_id"] == "ORD1"
    assert body["replacement_order_id"]


async def test_p2_retry_after_a_successful_replace_replays_the_first_reply() -> None:
    engine = _Engine()
    app = make_app(engine)
    headers = {"Idempotency-Key": "replace-key-2"}

    _, _, first = await call(
        app, "POST", "/api/v1/orders/ORD1/replace", body=_ORDER, headers=headers
    )
    _, replay_headers, second = await call(
        app, "POST", "/api/v1/orders/ORD1/replace", body=_ORDER, headers=headers
    )
    assert replay_headers.get("idempotent-replayed") == "true"
    assert second == first
    assert engine.kinds() == ["cancel", "order"]


async def test_p2_a_refused_cancel_leaves_nothing_to_resume() -> None:
    """Nothing happened at the engine, so the key is free again and a retry
    makes its own attempt rather than replaying or resuming."""
    engine = _Engine(cancel_accepted=False)
    app = make_app(engine)
    headers = {"Idempotency-Key": "replace-key-3"}

    first, _, _ = await call(
        app, "POST", "/api/v1/orders/ORD1/replace", body=_ORDER, headers=headers
    )
    second, _, _ = await call(
        app, "POST", "/api/v1/orders/ORD1/replace", body=_ORDER, headers=headers
    )
    assert first == second == 409
    assert engine.kinds() == ["cancel", "cancel"]


# ---------------------------------------------------------------------------
# K15 / P3 — rebalance replies belong to their own command_id
# ---------------------------------------------------------------------------


async def test_p3_rebalance_replies_are_matched_by_command_id() -> None:
    """Both rebalances share ``index.rebalance_ack.<gateway_id>``. Reply B
    arrives first; resolving the oldest waiter would hand B's verdict to A."""
    loop = asyncio.get_running_loop()
    with (
        patch("edumatcher.api_gateway.index_client.make_pusher"),
        patch("edumatcher.api_gateway.index_client.make_subscriber"),
    ):
        client = IndexClient("tcp://127.0.0.1:1", "tcp://127.0.0.1:2", loop)

    async def rebalance(command_id: str) -> dict[str, Any]:
        return await client.send_and_await_rebalance(
            gateway_id="GW01",
            index_id="EDU100",
            updates=[{"symbol": "AAPL", "new_shares_outstanding": 1}],
            command_id=command_id,
            timeout=3.0,
        )

    task_a = asyncio.ensure_future(rebalance("cmd-A"))
    task_b = asyncio.ensure_future(rebalance("cmd-B"))
    await asyncio.sleep(0)  # let both register their waiters, A first

    topic = topic_index_rebalance_ack("GW01")
    client._handle_event(topic, {"accepted": True, "command_id": "cmd-B", "level": 2.0})
    client._handle_event(topic, {"accepted": True, "command_id": "cmd-A", "level": 1.0})

    assert (await task_a)["command_id"] == "cmd-A"
    assert (await task_b)["command_id"] == "cmd-B"


# ---------------------------------------------------------------------------
# K15 / P4 — an engine restart de-authenticates every gateway id
# ---------------------------------------------------------------------------


async def test_p4_engine_restart_de_authenticates_every_gateway() -> None:
    """The engine lost its session table; a gateway that still believes it is
    connected sends orders the engine refuses as "not connected" forever."""
    loop = asyncio.get_running_loop()
    with (
        patch("edumatcher.api_gateway.engine_client.make_pusher"),
        patch("edumatcher.api_gateway.engine_client.make_subscriber"),
    ):
        client = EngineClient("tcp://127.0.0.1:1", "tcp://127.0.0.1:2", loop)
    client._authenticated.update({"GW01", "GW02"})

    client._handle_event(TOPIC_STARTUP_RECOVERY, {"ts_ns": 1})

    assert client.active_gateways() == set()


async def test_p4_the_next_request_after_a_restart_re_authenticates() -> None:
    loop = asyncio.get_running_loop()
    with (
        patch("edumatcher.api_gateway.engine_client.make_pusher"),
        patch("edumatcher.api_gateway.engine_client.make_subscriber"),
    ):
        client = EngineClient("tcp://127.0.0.1:1", "tcp://127.0.0.1:2", loop)
    sent: list[list[bytes]] = []
    client._send = lambda frames, **kw: sent.append(frames)
    client._authenticated.add("GW01")

    client._handle_event(TOPIC_STARTUP_RECOVERY, {"ts_ns": 1})

    task = asyncio.ensure_future(client.authenticate("GW01", timeout=3.0))
    await asyncio.sleep(0)
    assert sent, "a gateway_connect must go out again after the restart"
    client._handle_event(
        "system.gateway_auth.GW01", {"gateway_id": "GW01", "accepted": True}
    )
    accepted, _ = await task
    assert accepted


# ---------------------------------------------------------------------------
# K15 / P5 — replay detection is per symbol, not venue-wide
# ---------------------------------------------------------------------------


def _trade(symbol: str, seq: int) -> dict[str, Any]:
    return envelope("trade.executed", {"symbol": symbol, "price": 1.0}, seq=seq)


@pytest.mark.parametrize("symbol", ["AAPL", "MSFT"])
def test_p5_another_symbols_prints_are_not_a_gap(symbol: str) -> None:
    """``seq`` is venue-wide, so a symbol's own buffer is naturally sparse.
    A resume from a seq that belongs to *another* symbol's print has missed
    nothing of this one."""
    other = "MSFT" if symbol == "AAPL" else "AAPL"
    cache = MarketDataCache(window_sec=600)
    cache.record(_trade(other, 1))
    cache.record(_trade(other, 2))
    cache.record(_trade(symbol, 3))
    assert [e["seq"] for e in cache.resume_trades(symbol, 1)] == [3]


def test_p5_interleaved_symbols_replay_only_their_own_prints() -> None:
    cache = MarketDataCache(window_sec=600)
    cache.record(_trade("AAPL", 10))
    cache.record(_trade("MSFT", 11))
    cache.record(_trade("AAPL", 12))
    assert [e["seq"] for e in cache.resume_trades("AAPL", 10)] == [12]
    assert [e["seq"] for e in cache.resume_trades("MSFT", 10)] == [11]


@pytest.mark.parametrize("symbol", ["AAPL", "MSFT"])
def test_p5_a_genuinely_evicted_print_is_still_a_replay_miss(symbol: str) -> None:
    clock = [0.0]
    with patch("edumatcher.api_gateway.market_cache.time.monotonic", lambda: clock[0]):
        cache = MarketDataCache(window_sec=10)
        cache.record(_trade(symbol, 1))
        cache.record(_trade(symbol, 2))
        clock[0] += 100.0
        cache.record(_trade(symbol, 3))
        with pytest.raises(ReplayMiss):
            cache.resume_trades(symbol, 0)
        # The eviction boundary itself is still serviceable.
        assert [e["seq"] for e in cache.resume_trades(symbol, 2)] == [3]
