"""
Security and auth tests for pm-api-gwy (unit-level).

High priority:
  - Missing / malformed Authorization header
  - Unknown API key
  - Read-only session attempting a write operation

Medium priority:
  - Independent rate-limit buckets per API key
  - TokenBucket exact boundary, token refill
  - TokenBucket with zero rate or burst
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from edumatcher.api_gateway.config import ApiCredential, ApiGatewayConfig
from edumatcher.api_gateway.rate_limit import RateLimiter, TokenBucket
from edumatcher.api_gateway.sessions import (
    Session,
    SessionRegistry,
    _extract_bearer,
    auth,
    require_trading,
)

# ---------------------------------------------------------------------------
# Minimal async engine stub (only the authenticate method is needed)
# ---------------------------------------------------------------------------


class _AcceptingEngine:
    async def authenticate(
        self, gateway_id: str, timeout: float = 3.0
    ) -> tuple[bool, str]:
        return True, ""


class _RejectingEngine:
    async def authenticate(
        self, gateway_id: str, timeout: float = 3.0
    ) -> tuple[bool, str]:
        return False, "gateway not configured"


# ---------------------------------------------------------------------------
# Helper: fake FastAPI request
# ---------------------------------------------------------------------------


def _fake_request(
    credentials: list[tuple[str, str | None]],
    engine: object | None = None,
) -> Any:
    """Create a fake request.app.state with a minimal SessionRegistry."""
    creds = tuple(
        ApiCredential(api_key=key, gateway_id=gw_id, description=f"key-{key}")
        for key, gw_id in credentials
    )
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                sessions=SessionRegistry(creds),
                engine=engine or _AcceptingEngine(),
                config=ApiGatewayConfig(),
            )
        )
    )


# ===========================================================================
# _extract_bearer — header parsing
# ===========================================================================


class TestExtractBearer:
    """_extract_bearer must accept well-formed Bearer tokens and reject everything else."""

    def test_valid_bearer_returns_token(self) -> None:
        assert _extract_bearer("Bearer mytoken123") == "mytoken123"

    def test_bearer_scheme_case_insensitive(self) -> None:
        assert _extract_bearer("bearer MYTOKEN") == "MYTOKEN"

    def test_wrong_scheme_raises_401(self) -> None:
        with pytest.raises(HTTPException) as exc:
            _extract_bearer("Basic dXNlcjpwYXNz")
        assert exc.value.status_code == 401

    def test_empty_string_raises_401(self) -> None:
        with pytest.raises(HTTPException) as exc:
            _extract_bearer("")
        assert exc.value.status_code == 401

    def test_bearer_with_no_token_raises_401(self) -> None:
        """'Bearer' with no following space/token must be rejected."""
        with pytest.raises(HTTPException) as exc:
            _extract_bearer("Bearer")
        assert exc.value.status_code == 401

    def test_bearer_with_empty_token_after_space_raises_401(self) -> None:
        with pytest.raises(HTTPException) as exc:
            _extract_bearer("Bearer ")
        assert exc.value.status_code == 401

    def test_bearer_with_very_long_token_returns_token(self) -> None:
        """A very long token string is not rejected by _extract_bearer itself."""
        long_token = "x" * 10_000
        result = _extract_bearer(f"Bearer {long_token}")
        assert result == long_token

    def test_bearer_token_is_stripped(self) -> None:
        """Leading/trailing whitespace on the token is stripped."""
        assert _extract_bearer("Bearer  spaced  ") == "spaced"


# ===========================================================================
# auth() dependency — full session lookup
# ===========================================================================


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


class TestAuthDependency:
    """auth() must resolve valid sessions and raise HTTP errors for bad inputs."""

    @pytest.mark.anyio
    async def test_valid_key_returns_session(self) -> None:
        request = _fake_request([("valid-key", None)])
        session = await auth(request, authorization="Bearer valid-key")
        assert session.api_key == "valid-key"

    @pytest.mark.anyio
    async def test_unknown_key_raises_401(self) -> None:
        request = _fake_request([("valid-key", None)])
        with pytest.raises(HTTPException) as exc:
            await auth(request, authorization="Bearer no-such-key")
        assert exc.value.status_code == 401

    @pytest.mark.anyio
    async def test_wrong_scheme_raises_401(self) -> None:
        request = _fake_request([("valid-key", None)])
        with pytest.raises(HTTPException) as exc:
            await auth(request, authorization="Basic valid-key")
        assert exc.value.status_code == 401

    @pytest.mark.anyio
    async def test_empty_header_raises_401(self) -> None:
        request = _fake_request([("valid-key", None)])
        with pytest.raises(HTTPException) as exc:
            await auth(request, authorization="")
        assert exc.value.status_code == 401

    @pytest.mark.anyio
    async def test_very_long_garbage_token_raises_401(self) -> None:
        """A plausibly-crafted long token that is not in the registry → 401."""
        request = _fake_request([("valid-key", None)])
        with pytest.raises(HTTPException) as exc:
            await auth(request, authorization="Bearer " + "x" * 10_000)
        assert exc.value.status_code == 401

    @pytest.mark.anyio
    async def test_trading_key_accepted_when_engine_allows(self) -> None:
        request = _fake_request([("trade-key", "GW01")], engine=_AcceptingEngine())
        session = await auth(request, authorization="Bearer trade-key")
        assert session.gateway_id == "GW01"
        assert session.can_trade is True

    @pytest.mark.anyio
    async def test_engine_rejection_raises_403(self) -> None:
        """Engine rejecting gateway auth must surface as HTTP 403."""
        request = _fake_request([("trade-key", "GW01")], engine=_RejectingEngine())
        with pytest.raises(HTTPException) as exc:
            await auth(request, authorization="Bearer trade-key")
        assert exc.value.status_code == 403


# ===========================================================================
# require_trading — read-only session enforcement
# ===========================================================================


class TestRequireTrading:
    def test_trading_session_returns_gateway_id(self) -> None:
        session = Session(api_key="k", gateway_id="GW01", description="")
        assert require_trading(session) == "GW01"

    def test_read_only_session_raises_403(self) -> None:
        session = Session(api_key="ro", gateway_id=None, description="read-only")
        with pytest.raises(HTTPException) as exc:
            require_trading(session)
        assert exc.value.status_code == 403
        detail = exc.value.detail
        assert isinstance(detail, dict)
        assert detail["error"]["code"] == "READ_ONLY"


# ===========================================================================
# RateLimiter — per-key buckets
# ===========================================================================


class TestRateLimiterIndependentBuckets:
    """Each API key gets its own independent token bucket."""

    def test_exhausting_one_key_does_not_affect_another(self) -> None:
        limiter = RateLimiter(writes_per_second=1, burst=1)
        assert limiter.allow("key_a") is True
        assert limiter.allow("key_a") is False  # key_a exhausted
        assert limiter.allow("key_b") is True  # key_b unaffected

    def test_new_key_starts_with_full_burst(self) -> None:
        limiter = RateLimiter(writes_per_second=1, burst=3)
        # Three writes on a fresh key should all succeed
        for _ in range(3):
            assert limiter.allow("fresh-key") is True
        assert limiter.allow("fresh-key") is False

    def test_two_keys_exhausted_independently(self) -> None:
        limiter = RateLimiter(writes_per_second=5, burst=2)
        assert limiter.allow("x") is True
        assert limiter.allow("x") is True
        assert limiter.allow("x") is False

        assert limiter.allow("y") is True
        assert limiter.allow("y") is True
        assert limiter.allow("y") is False

        # Both exhausted — neither should allow another write
        assert limiter.allow("x") is False
        assert limiter.allow("y") is False


# ===========================================================================
# TokenBucket — boundary and refill
# ===========================================================================


class TestTokenBucketBoundaryAndRefill:
    """TokenBucket semantics: burst cap, refill rate, zero-config edge cases."""

    def test_burst_consumed_exactly(self) -> None:
        bucket = TokenBucket(rate_per_second=10, burst=3)
        results = [bucket.allow() for _ in range(4)]
        assert results == [True, True, True, False]

    def test_tokens_refill_over_time(self) -> None:
        bucket = TokenBucket(rate_per_second=10, burst=1)
        assert bucket.allow() is True
        assert bucket.allow() is False  # exhausted

        # Simulate 0.15 s elapsed (≥ 1/10 = 0.1 s)
        bucket.updated_at -= 0.15
        assert bucket.allow() is True

    def test_refill_capped_at_burst(self) -> None:
        """Tokens can never exceed the burst cap even after a long gap."""
        bucket = TokenBucket(rate_per_second=10, burst=2)
        assert bucket.allow() is True
        assert bucket.allow() is True
        assert bucket.allow() is False

        # Simulate a full second — would add 10 tokens but cap is 2
        bucket.updated_at -= 1.0
        assert bucket.allow() is True
        assert bucket.allow() is True
        assert bucket.allow() is False  # still capped at 2

    def test_zero_burst_never_allows(self) -> None:
        """A bucket with burst=0 starts with 0 tokens and never fills above cap."""
        bucket = TokenBucket(rate_per_second=100, burst=0)
        # Even with elapsed time, tokens = min(0, 0 + elapsed*100) = 0 always
        assert bucket.allow() is False

    def test_zero_rate_uses_only_initial_burst(self) -> None:
        """rate=0 means no refill; only the initial burst tokens are available."""
        bucket = TokenBucket(rate_per_second=0, burst=2)
        assert bucket.allow() is True
        assert bucket.allow() is True
        # Simulate elapsed time — no refill because rate=0
        bucket.updated_at -= 100.0
        assert bucket.allow() is False
