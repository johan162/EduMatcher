"""Refusals made at the REST gateway reach the audit trail (A3)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

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
