"""WP-API02: asynchronous writes a client can trust and safely retry.

Driven through the real app (tests/api_gateway_harness.py) because what is
under test is what the client sees: status codes, the reply after an ack
timeout, and whether a retried request reaches the engine a second time.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import HTTPException

from edumatcher.api_gateway.caches import SessionCaches
from edumatcher.models.price import clear_tick_registry, register_tick_decimals
from tests.api_gateway_harness import call, make_app


class _Engine:
    """EngineClient double: records sends, answers or times out acks."""

    def __init__(
        self,
        *,
        timeout_prefixes: tuple[str, ...] = (),
        delay: float = 0.0,
        cancel_accepted: bool = True,
        unavailable: bool = False,
    ) -> None:
        self.cache = SessionCaches()
        self.sent: list[tuple[str, Any]] = []
        self.timeout_prefixes = timeout_prefixes
        self.delay = delay
        self.cancel_accepted = cancel_accepted
        self.unavailable = unavailable

    async def authenticate(
        self, gateway_id: str, timeout: float = 3.0
    ) -> tuple[bool, str]:
        return True, ""

    def get_caches(self, gateway_id: str) -> SessionCaches:
        return self.cache

    def _send(self, kind: str, payload: Any) -> None:
        if self.unavailable:
            raise HTTPException(
                status_code=503,
                detail={"error": {"code": "ENGINE_UNAVAILABLE", "message": "down"}},
            )
        self.sent.append((kind, payload))

    def send_new_order(self, order: Any) -> None:
        self._send("order", order)

    def send_cancel(
        self, order_id: str, gateway_id: str, request_tag: str | None = None
    ) -> None:
        self._send("cancel", (order_id, request_tag))

    def send_amend(self, order_id: str, gateway_id: str, *args: Any, **kw: Any) -> None:
        self._send("amend", order_id)

    def send_oco(self, payload: dict[str, Any]) -> None:
        self._send("oco", payload)

    def send_combo(self, payload: dict[str, Any]) -> None:
        self._send("combo", payload)

    def send_quote(self, payload: dict[str, Any]) -> None:
        self._send("quote", payload)

    def send_oco_cancel(
        self, oco_id: str, gateway_id: str, request_tag: str = ""
    ) -> None:
        self._send("oco_cancel", (oco_id, request_tag))

    def send_combo_cancel(
        self, combo_id: str, gateway_id: str, request_tag: str = ""
    ) -> None:
        self._send("combo_cancel", (combo_id, request_tag))

    def send_quote_cancel(
        self, gateway_id: str, symbol: str, request_tag: str = ""
    ) -> None:
        self._send("quote_cancel", (symbol, request_tag))

    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.sent]

    async def await_event(
        self, topic: str, match: dict[str, str] | None, timeout: float
    ) -> dict[str, Any]:
        if self.delay:
            await asyncio.sleep(self.delay)
        if topic.startswith(self.timeout_prefixes):
            raise TimeoutError(f"Timed out waiting for {topic}")
        if ".cancel_ack." in topic and not self.cancel_accepted:
            return {
                "accepted": False,
                "reason": "OCO not found",
                "reject_code": "ORDER_NOT_FOUND",
                "cancelled_order_ids": [],
                **(match or {}),
            }
        return {"accepted": True, "reason": "", **(match or {})}

    async def await_cancel_or_amend_outcome(
        self,
        *,
        success_topic: str,
        gateway_id: str,
        order_id: str,
        request_tag: str,
        timeout: float,
    ) -> dict[str, Any]:
        if self.delay:
            await asyncio.sleep(self.delay)
        if success_topic.startswith(self.timeout_prefixes):
            raise TimeoutError(f"Timed out waiting for {success_topic}")
        if not self.cancel_accepted:
            return {
                "order_id": order_id,
                "accepted": False,
                "reason": "Order already filled",
                "reject_code": "ORDER_ALREADY_TERMINAL",
                "request_tag": request_tag,
            }
        return {"order_id": order_id, "accepted": True, "request_tag": request_tag}


_ORDER = {
    "symbol": "AAPL",
    "side": "BUY",
    "order_type": "LIMIT",
    "quantity": 10,
    "price": 150.0,
}
_OCO = {
    "oco_id": "oco-1",
    "symbol": "AAPL",
    "quantity": 10,
    # REST bodies carry display prices (D8); the gateway converts to ticks.
    "leg1": {
        "side": "SELL",
        "order_type": "LIMIT",
        "price": 155.0,
    },
    "leg2": {
        "side": "SELL",
        "order_type": "STOP",
        "stop_price": 145.0,
    },
}
_COMBO = {
    "combo_id": "combo-1",
    "legs": [
        {"symbol": "AAPL", "side": "BUY", "quantity": 10, "price": 150.0},
        {"symbol": "MSFT", "side": "SELL", "quantity": 5, "price": 410.0},
    ],
}
_QUOTE = {
    "symbol": "AAPL",
    "bid_price": 149.9,
    "bid_qty": 10,
    "ask_price": 150.1,
    "ask_qty": 10,
}


@pytest.fixture(autouse=True)
def _symbols_loaded() -> Iterator[None]:
    clear_tick_registry()
    register_tick_decimals("AAPL", 2)
    register_tick_decimals("MSFT", 2)
    yield
    clear_tick_registry()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# --- E7: an ack timeout keeps the order id -------------------------------------


@pytest.mark.anyio
async def test_submit_ack_timeout_is_202_with_the_order_id() -> None:
    """The order was sent; a 503 here used to lose its id, so the client could
    neither cancel nor track it, and its retry made a second order."""
    engine = _Engine(timeout_prefixes=("order.ack.",))
    status, _, body = await call(
        make_app(engine), "POST", "/api/v1/orders?wait=ack", body=_ORDER
    )
    assert status == 202
    assert body["status"] == "PENDING" and body["ack_timeout"] is True
    assert body["order_id"] and engine.kinds() == ["order"]


@pytest.mark.anyio
async def test_cancel_and_amend_ack_timeouts_are_202() -> None:
    engine = _Engine(timeout_prefixes=("order.cancelled.", "order.amended."))
    app = make_app(engine)
    cancel = await call(app, "DELETE", "/api/v1/orders/ORD1?wait=ack&request_tag=c1")
    amend = await call(
        app,
        "PATCH",
        "/api/v1/orders/ORD1?wait=ack",
        body={"price": 151.0, "request_tag": "a1"},
    )
    assert (cancel[0], cancel[2]["status"], cancel[2]["ack_timeout"]) == (
        202,
        "PENDING_CANCEL",
        True,
    )
    assert (amend[0], amend[2]["status"], amend[2]["ack_timeout"]) == (
        202,
        "PENDING_AMEND",
        True,
    )


@pytest.mark.anyio
async def test_a_prompt_ack_says_no_timeout() -> None:
    status, _, body = await call(
        make_app(_Engine()), "POST", "/api/v1/orders?wait=ack", body=_ORDER
    )
    assert (status, body["status"], body["ack_timeout"]) == (200, "ACKED", False)


# --- Q2: Idempotency-Key ------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("path", "body", "kind"),
    [
        ("/api/v1/orders", _ORDER, "order"),
        ("/api/v1/oco", _OCO, "oco"),
        ("/api/v1/combos", _COMBO, "combo"),
        ("/api/v1/quotes", _QUOTE, "quote"),
    ],
)
async def test_a_retry_with_the_same_key_replays_the_first_reply(
    path: str, body: dict[str, Any], kind: str
) -> None:
    engine = _Engine()
    app = make_app(engine)
    first = await call(app, "POST", path, body=body, headers={"Idempotency-Key": "k-1"})
    second = await call(
        app, "POST", path, body=body, headers={"Idempotency-Key": "k-1"}
    )
    assert engine.kinds() == [kind]  # one write reached the engine
    assert second[0] == first[0] and second[2] == first[2]
    assert second[1].get("idempotent-replayed") == "true"


@pytest.mark.anyio
async def test_without_a_key_every_request_is_a_new_write() -> None:
    engine = _Engine()
    app = make_app(engine)
    await call(app, "POST", "/api/v1/orders", body=_ORDER)
    await call(app, "POST", "/api/v1/orders", body=_ORDER)
    assert engine.kinds() == ["order", "order"]


@pytest.mark.anyio
async def test_a_concurrent_duplicate_waits_for_the_first_instead_of_sending() -> None:
    engine = _Engine(delay=0.05)
    app = make_app(engine)
    headers = {"Idempotency-Key": "k-race"}
    first, second = await asyncio.gather(
        call(app, "POST", "/api/v1/orders?wait=ack", body=_ORDER, headers=headers),
        call(app, "POST", "/api/v1/orders?wait=ack", body=_ORDER, headers=headers),
    )
    assert engine.kinds() == ["order"]
    assert first[2] == second[2]


@pytest.mark.anyio
async def test_a_disconnect_mid_wait_still_records_the_reply() -> None:
    """The order went out before the client gave up; its retry must not
    send a second one."""
    engine = _Engine(delay=0.05)
    app = make_app(engine)
    headers = {"Idempotency-Key": "k-gone"}
    first = asyncio.ensure_future(
        call(app, "POST", "/api/v1/orders?wait=ack", body=_ORDER, headers=headers)
    )
    await asyncio.sleep(0.01)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    retried = await call(
        app, "POST", "/api/v1/orders?wait=ack", body=_ORDER, headers=headers
    )
    assert engine.kinds() == ["order"]
    assert retried[1].get("idempotent-replayed") == "true"


@pytest.mark.anyio
async def test_the_same_key_for_a_different_request_is_409() -> None:
    engine = _Engine()
    app = make_app(engine)
    await call(
        app, "POST", "/api/v1/orders", body=_ORDER, headers={"Idempotency-Key": "k-2"}
    )
    status, _, body = await call(
        app,
        "POST",
        "/api/v1/orders",
        body={**_ORDER, "quantity": 20},
        headers={"Idempotency-Key": "k-2"},
    )
    assert status == 409 and body["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert engine.kinds() == ["order"]


@pytest.mark.anyio
async def test_a_duplicate_of_a_failed_attempt_makes_its_own() -> None:
    """A replace whose cancel times out is a 503; the duplicate waiting on it
    must not inherit that failure but try again itself."""
    engine = _Engine(timeout_prefixes=("order.cancelled.",), delay=0.05)
    app = make_app(engine)
    headers = {"Idempotency-Key": "k-fail"}
    path = "/api/v1/orders/ORD1/replace"
    first, second = await asyncio.gather(
        call(app, "POST", path, body=_ORDER, headers=headers),
        call(app, "POST", path, body=_ORDER, headers=headers),
    )
    assert (first[0], second[0]) == (503, 503)
    assert "idempotent-replayed" not in second[1]
    assert engine.kinds() == ["cancel", "cancel"]


@pytest.mark.anyio
async def test_a_failed_attempt_is_not_remembered() -> None:
    """Only a request that reached the engine is replayed; one refused before
    it (engine unavailable) may be retried with the same key."""
    engine = _Engine(unavailable=True)
    app = make_app(engine)
    headers = {"Idempotency-Key": "k-3"}
    failed = await call(app, "POST", "/api/v1/orders", body=_ORDER, headers=headers)
    engine.unavailable = False
    retried = await call(app, "POST", "/api/v1/orders", body=_ORDER, headers=headers)
    assert (failed[0], retried[0]) == (503, 202)
    assert engine.kinds() == ["order"]


@pytest.mark.anyio
async def test_an_over_long_key_is_400() -> None:
    status, _, body = await call(
        make_app(_Engine()),
        "POST",
        "/api/v1/orders",
        body=_ORDER,
        headers={"Idempotency-Key": "x" * 256},
    )
    assert status == 400 and body["error"]["field"] == "Idempotency-Key"


# --- wait=ack for structures ---------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("path", "body", "id_field"),
    [
        ("/api/v1/oco", _OCO, "oco_id"),
        ("/api/v1/combos", _COMBO, "combo_id"),
        ("/api/v1/quotes", _QUOTE, "symbol"),
    ],
)
async def test_structures_support_wait_ack(
    path: str, body: dict[str, Any], id_field: str
) -> None:
    app = make_app(_Engine())
    pending = await call(app, "POST", path, body=body)
    acked = await call(app, "POST", f"{path}?wait=ack", body=body)
    assert (pending[0], pending[2]["status"], pending[2]["accepted"]) == (
        202,
        "PENDING",
        None,
    )
    assert (acked[0], acked[2]["status"], acked[2]["accepted"]) == (200, "ACKED", True)
    assert acked[2][id_field] == body[id_field]


# --- replace -------------------------------------------------------------------


@pytest.mark.anyio
async def test_replace_whose_cancel_is_refused_is_409_not_a_timeout() -> None:
    engine = _Engine(cancel_accepted=False)
    status, _, body = await call(
        make_app(engine), "POST", "/api/v1/orders/ORD1/replace", body=_ORDER
    )
    assert status == 409
    assert (body["error"]["code"], body["error"]["reject_code"]) == (
        "REPLACE_REJECTED",
        "ORDER_ALREADY_TERMINAL",
    )
    assert engine.kinds() == ["cancel"]  # no replacement sent


@pytest.mark.anyio
async def test_replace_keeps_the_symbol() -> None:
    engine = _Engine()
    engine.cache.orders["ORD1"] = {
        "order_id": "ORD1",
        "symbol": "MSFT",
        "status": "NEW",
    }
    status, _, body = await call(
        make_app(engine), "POST", "/api/v1/orders/ORD1/replace", body=_ORDER
    )
    assert status == 400 and body["error"]["field"] == "symbol"
    assert engine.kinds() == []


@pytest.mark.anyio
async def test_replace_checks_the_symbol_is_ready_before_cancelling() -> None:
    engine = _Engine()
    status, _, body = await call(
        make_app(engine),
        "POST",
        "/api/v1/orders/ORD1/replace",
        body={**_ORDER, "symbol": "TSLA"},
    )
    assert (status, body["error"]["code"]) == (503, "SYMBOLS_NOT_READY")
    assert engine.kinds() == []  # the original was not cancelled


@pytest.mark.anyio
async def test_replace_wait_ack_returns_the_replacements_verdict() -> None:
    status, _, body = await call(
        make_app(_Engine()), "POST", "/api/v1/orders/ORD1/replace?wait=ack", body=_ORDER
    )
    assert (status, body["status"], body["accepted"]) == (200, "ACKED", True)
    assert body["cancelled_order_id"] == "ORD1" and body["replacement_order_id"]


# --- WP-API17: structure cancels report their own outcome ------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("path", "kind", "ident_field", "ident"),
    [
        ("/api/v1/oco/oco-1", "oco_cancel", "oco_id", "oco-1"),
        ("/api/v1/combos/combo-1", "combo_cancel", "combo_id", "combo-1"),
        ("/api/v1/quotes/aapl", "quote_cancel", "symbol", "AAPL"),
    ],
)
async def test_structure_cancels_wait_for_their_own_ack(
    path: str, kind: str, ident_field: str, ident: str
) -> None:
    engine = _Engine()
    app = make_app(engine)
    pending = await call(app, "DELETE", path)
    assert (pending[0], pending[2]["status"], pending[2]["accepted"]) == (
        202,
        "PENDING_CANCEL",
        None,
    )
    acked = await call(app, "DELETE", f"{path}?wait=ack&request_tag=rt-1")
    assert (acked[0], acked[2]["status"], acked[2]["accepted"]) == (200, "ACKED", True)
    assert (acked[2][ident_field], acked[2]["request_tag"]) == (ident, "rt-1")
    assert engine.sent[-1] == (kind, (ident, "rt-1"))


@pytest.mark.anyio
async def test_a_refused_structure_cancel_is_rejected_not_an_error() -> None:
    """As for an order cancel: the refusal is the outcome, in a 200."""
    engine = _Engine(cancel_accepted=False)
    status, _, body = await call(
        make_app(engine), "DELETE", "/api/v1/oco/gone?wait=ack"
    )
    assert (status, body["status"], body["accepted"]) == (200, "REJECTED", False)
    assert body["reject_code"] == "ORDER_NOT_FOUND"


@pytest.mark.anyio
async def test_a_late_structure_cancel_ack_is_202_with_ack_timeout() -> None:
    engine = _Engine(timeout_prefixes=("combo.cancel_ack.",))
    status, _, body = await call(
        make_app(engine), "DELETE", "/api/v1/combos/c?wait=ack"
    )
    assert (status, body["status"], body["ack_timeout"]) == (
        202,
        "PENDING_CANCEL",
        True,
    )
