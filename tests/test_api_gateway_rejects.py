"""Refusals made at the REST gateway reach the audit trail (A3)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import zmq
from fastapi import HTTPException

from edumatcher.api_gateway.engine_client import EngineClient

from edumatcher.api_gateway.rate_limit import RateLimiter
from edumatcher.api_gateway.routers import orders
from edumatcher.api_gateway.sessions import Session, auth, report_refusal
from edumatcher.messaging.reject_report import RejectReporter
from edumatcher.models.message import decode


def request_with(
    sent: list[list[bytes]], *, limiter: RateLimiter | None = None, sessions: Any = None
) -> Any:
    return SimpleNamespace(
        client=SimpleNamespace(host="10.0.0.9", port=5151),
        app=SimpleNamespace(
            state=SimpleNamespace(
                rejects=RejectReporter("REST", sent.append),
                rate_limiter=limiter or RateLimiter(100, 100),
                sessions=sessions,
            )
        ),
    )


def reports(sent: list[list[bytes]]) -> list[dict[str, Any]]:
    return [decode(f)[1] for f in sent if decode(f)[0] == "system.gateway_reject"]


def test_a_rate_limited_write_is_reported_with_its_peer() -> None:
    sent: list[list[bytes]] = []
    request = request_with(sent, limiter=RateLimiter(1, 1))
    session = Session(api_key="secret-key", gateway_id="GW01", description="")
    orders._check_rate_limit(request, session)
    with pytest.raises(HTTPException):
        orders._check_rate_limit(request, session)
    (body,) = reports(sent)
    assert body["source"] == "REST"
    assert body["reject_code"] == "RATE_LIMITED"
    assert body["gateway_id"] == "GW01"
    assert body["peer"] == "10.0.0.9:5151"


def test_the_api_key_never_travels() -> None:
    sent: list[list[bytes]] = []
    request = request_with(sent, limiter=RateLimiter(1, 1))
    session = Session(api_key="secret-key", gateway_id="GW01", description="")
    orders._check_rate_limit(request, session)
    with pytest.raises(HTTPException):
        orders._check_rate_limit(request, session)
    assert b"secret-key" not in b"".join(b"".join(f) for f in sent)


@pytest.mark.anyio
async def test_an_unknown_key_is_reported_as_auth_failed() -> None:
    sent: list[list[bytes]] = []
    request = request_with(sent, sessions=SimpleNamespace(get=lambda _k: None))
    creds: Any = SimpleNamespace(credentials="bad-key")
    with pytest.raises(HTTPException):
        await auth(request, creds)
    (body,) = reports(sent)
    assert body["reject_code"] == "AUTH_FAILED"
    assert body["gateway_id"] == ""


@pytest.mark.anyio
async def test_a_missing_token_is_reported_as_auth_required() -> None:
    sent: list[list[bytes]] = []
    with pytest.raises(HTTPException):
        await auth(request_with(sent), None)
    assert [b["reject_code"] for b in reports(sent)] == ["AUTH_REQUIRED"]


def test_a_gateway_without_a_reporter_records_nothing() -> None:
    request: Any = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    report_refusal(request, "ROLE_DENIED", "x")  # must not raise


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_a_record_the_engine_could_not_take_is_counted_in_the_next() -> None:
    """Messaging review 2026-11, C2: ``EngineClient.report`` used to swallow
    ``zmq.Again``, so the reporter believed a record had gone out."""
    loop = asyncio.new_event_loop()
    push = MagicMock(closed=False)
    try:
        with (
            patch(
                "edumatcher.api_gateway.engine_client.make_pusher", return_value=push
            ),
            patch(
                "edumatcher.api_gateway.engine_client.make_subscriber",
                return_value=MagicMock(),
            ),
        ):
            engine = EngineClient("tcp://127.0.0.1:1", "tcp://127.0.0.1:2", loop)
        now = [0.0]
        reporter = RejectReporter("REST", engine.report, clock=lambda: now[0])
        push.send_multipart.side_effect = zmq.Again()
        reporter.report("AUTH_FAILED", "", "10.0.0.9:1", "unknown API key")
        push.send_multipart.side_effect = None
        now[0] = 2.0
        reporter.report("AUTH_FAILED", "", "10.0.0.9:2", "unknown API key")
        (frames,) = [c.args[0] for c in push.send_multipart.call_args_list[1:]]
        assert decode(frames)[1]["count"] == 2
    finally:
        loop.close()
