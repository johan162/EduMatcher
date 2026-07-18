"""Tests for the pm-api-gwy IndexClient and /history/index-events endpoint.

Design intent under test (not a literal mirror of the implementation):
  - IndexClient correctly bridges pm-index's ZMQ PUSH/PUB request-reply
    exchange to asyncio: a history reply resolves the caller's awaited
    coroutine, an index.error reply raises IndexHistoryError instead of
    silently timing out (the pre-existing sync ExchangeCommandClient does
    time out on errors — this is a deliberate improvement, not parity),
    and no reply within the timeout raises TimeoutError. Exactly one of
    the two competing futures (history vs error) ever resolves the call,
    and both are always cleaned up so a stray/duplicate late reply cannot
    resolve a future the caller has already stopped awaiting.
  - /history/index-events is reachable with a read-only credential (same
    "any valid key" tier as /index-daily and /index-snapshots), validates
    its own params (event types restricted to the structural set, to/from
    ordering) before ever touching the index client, and translates
    IndexClient's exceptions to the documented HTTP contract (503
    INDEX_TIMEOUT, 502 INDEX_ERROR) rather than leaking a raw exception.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

import pytest
import zmq
from fastapi import HTTPException

from edumatcher.api_gateway.index_client import IndexClient, IndexHistoryError
from edumatcher.api_gateway.routers import history
from edumatcher.api_gateway.sessions import Session
from edumatcher.models.message import (
    decode,
    make_index_error_msg,
    make_index_history_msg,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _readonly_session() -> Session:
    return Session(api_key="ro-key", gateway_id=None, description="readonly")


def _trading_session() -> Session:
    return Session(api_key="trading-key", gateway_id="GW01", description="trader")


# ---------------------------------------------------------------------------
# IndexClient — real ZMQ sockets, since the async/thread bridge is the part
# actually worth proving works, not just mocking away.
# ---------------------------------------------------------------------------


@pytest.fixture
def index_zmq_pair() -> (
    Generator[tuple[str, str, "zmq.Socket[bytes]", "zmq.Socket[bytes]"], None, None]
):
    """A fake pm-index: a PULL socket to receive requests, a PUB socket to
    reply on — bound on ports distinct from the real pm-index defaults so
    this never collides with a locally-running instance.
    """
    pull_addr = "tcp://127.0.0.1:16559"
    pub_addr = "tcp://127.0.0.1:16558"
    ctx: zmq.Context[zmq.Socket[bytes]] = zmq.Context.instance()
    fake_pull = ctx.socket(zmq.PULL)
    fake_pull.bind(pull_addr)
    fake_pub = ctx.socket(zmq.PUB)
    fake_pub.bind(pub_addr)
    yield pull_addr, pub_addr, fake_pull, fake_pub
    fake_pull.close(linger=0)
    fake_pub.close(linger=0)


@pytest.mark.anyio
async def test_index_client_resolves_on_history_reply(
    index_zmq_pair: tuple[str, str, "zmq.Socket[bytes]", "zmq.Socket[bytes]"],
) -> None:
    pull_addr, pub_addr, fake_pull, fake_pub = index_zmq_pair
    loop = asyncio.get_running_loop()
    client = IndexClient(pull_addr, pub_addr, loop)
    client.start_listener()
    await asyncio.sleep(0.3)  # let the SUB socket's subscription settle

    pool = concurrent.futures.ThreadPoolExecutor()

    def serve_once() -> None:
        _topic, payload = decode(fake_pull.recv_multipart())
        fake_pub.send_multipart(
            make_index_history_msg(
                payload["gateway_id"],
                payload["index_id"],
                [{"type": "INIT", "timestamp": 1.0, "index_id": payload["index_id"]}],
            )
        )

    server = loop.run_in_executor(pool, serve_once)
    try:
        reply = await client.request_history(
            request_id="ro-test",
            index_id="EDU100",
            from_ts=0.0,
            to_ts=999_999.0,
            types=None,
            max_records=100,
            timeout=3.0,
        )
    finally:
        client.stop_listener()
    await server
    pool.shutdown(wait=False)

    assert reply["records"] == [
        {"type": "INIT", "timestamp": 1.0, "index_id": "EDU100"}
    ]


@pytest.mark.anyio
async def test_index_client_raises_index_history_error_on_error_reply(
    index_zmq_pair: tuple[str, str, "zmq.Socket[bytes]", "zmq.Socket[bytes]"],
) -> None:
    """pm-index rejecting a request (index.error.<id>) must surface as a
    clear exception, not a silent timeout — this is the deliberate
    improvement over the pre-existing sync client's behavior.
    """
    pull_addr, pub_addr, fake_pull, fake_pub = index_zmq_pair
    loop = asyncio.get_running_loop()
    client = IndexClient(pull_addr, pub_addr, loop)
    client.start_listener()
    await asyncio.sleep(0.3)

    pool = concurrent.futures.ThreadPoolExecutor()

    def serve_error() -> None:
        _topic, payload = decode(fake_pull.recv_multipart())
        fake_pub.send_multipart(
            make_index_error_msg(payload["gateway_id"], "unknown index_id")
        )

    server = loop.run_in_executor(pool, serve_error)
    try:
        with pytest.raises(IndexHistoryError, match="unknown index_id"):
            await client.request_history(
                request_id="ro-test2",
                index_id="BOGUS",
                from_ts=0.0,
                to_ts=999_999.0,
                types=None,
                max_records=100,
                timeout=3.0,
            )
    finally:
        client.stop_listener()
    await server
    pool.shutdown(wait=False)


@pytest.mark.anyio
async def test_index_client_times_out_when_no_reply_arrives(
    index_zmq_pair: tuple[str, str, "zmq.Socket[bytes]", "zmq.Socket[bytes]"],
) -> None:
    pull_addr, pub_addr, _fake_pull, _fake_pub = index_zmq_pair
    loop = asyncio.get_running_loop()
    client = IndexClient(pull_addr, pub_addr, loop)
    client.start_listener()
    await asyncio.sleep(0.3)

    try:
        with pytest.raises(TimeoutError):
            await client.request_history(
                request_id="ro-test3",
                index_id="NOREPLY",
                from_ts=0.0,
                to_ts=999_999.0,
                types=None,
                max_records=100,
                timeout=0.4,
            )
    finally:
        client.stop_listener()


@pytest.mark.anyio
async def test_index_client_stale_pending_futures_are_cleaned_up(
    index_zmq_pair: tuple[str, str, "zmq.Socket[bytes]", "zmq.Socket[bytes]"],
) -> None:
    """After a call resolves (or times out), its pending-future bookkeeping
    must not leak — a later, unrelated reply on the same request_id (e.g. a
    stray duplicate) must not resolve a future nobody is awaiting anymore.
    """
    pull_addr, pub_addr, fake_pull, fake_pub = index_zmq_pair
    loop = asyncio.get_running_loop()
    client = IndexClient(pull_addr, pub_addr, loop)
    client.start_listener()
    await asyncio.sleep(0.3)

    pool = concurrent.futures.ThreadPoolExecutor()

    def serve_once() -> None:
        _topic, payload = decode(fake_pull.recv_multipart())
        fake_pub.send_multipart(
            make_index_history_msg(payload["gateway_id"], payload["index_id"], [])
        )

    server = loop.run_in_executor(pool, serve_once)
    await client.request_history(
        request_id="ro-dup",
        index_id="EDU100",
        from_ts=0.0,
        to_ts=999_999.0,
        types=None,
        max_records=100,
        timeout=3.0,
    )
    await server
    # The pending-future maps should be empty for this request_id now — a
    # late/duplicate reply arriving after resolution must not raise or hang.
    assert "index.history.ro-dup" not in client._pending  # noqa: SLF001
    assert "index.error.ro-dup" not in client._pending  # noqa: SLF001
    client.stop_listener()
    pool.shutdown(wait=False)


# ---------------------------------------------------------------------------
# /history/index-events router — fake IndexClient, matching the FakeEngine
# pattern already used in test_api_gateway_routes.py, so these tests focus
# on the router's own validation/translation logic rather than re-proving
# ZMQ wiring (already covered above).
# ---------------------------------------------------------------------------


class _FakeIndexClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.raise_error: Exception | None = None
        self.reply: dict[str, Any] = {"index_id": "EDU100", "records": []}

    async def request_history(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.raise_error is not None:
            raise self.raise_error
        return self.reply


def _request_with(index_client: _FakeIndexClient) -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                index_client=index_client,
                config=SimpleNamespace(timeouts=SimpleNamespace(engine_reply_sec=3.0)),
            )
        )
    )


@pytest.mark.anyio
async def test_history_index_events_reachable_with_readonly_key() -> None:
    fake = _FakeIndexClient()
    fake.reply = {
        "index_id": "EDU100",
        "records": [{"type": "INIT", "timestamp": 1.0}],
    }
    result = await history.history_index_events(
        _request_with(fake),
        _readonly_session(),
        index_id="edu100",
        from_ts=None,
        to_ts=None,
        types=None,
        max_records=10_000,
    )
    assert result == {"events": [{"type": "INIT", "timestamp": 1.0}], "count": 1}
    # index_id is upper-cased before being sent to pm-index, mirroring every
    # other /history/* endpoint's symbol/index_id normalization.
    assert fake.calls[0]["index_id"] == "EDU100"


@pytest.mark.anyio
async def test_history_index_events_also_reachable_with_trading_key() -> None:
    fake = _FakeIndexClient()
    result = await history.history_index_events(
        _request_with(fake),
        _trading_session(),
        index_id="EDU100",
        from_ts=None,
        to_ts=None,
        types=None,
        max_records=10_000,
    )
    assert result["count"] == 0
    # A trading session's own gateway_id is used to address the pm-index
    # reply topic (no synthesized "ro-<key>" id needed in this case).
    assert fake.calls[0]["request_id"] == "GW01"


@pytest.mark.anyio
async def test_history_index_events_readonly_key_gets_synthesized_request_id() -> None:
    fake = _FakeIndexClient()
    await history.history_index_events(
        _request_with(fake),
        _readonly_session(),
        index_id="EDU100",
        from_ts=None,
        to_ts=None,
        types=None,
        max_records=10_000,
    )
    # A read-only session has no gateway_id; request_id must still be a
    # non-empty, caller-unique string so pm-index's reply topic is
    # addressable.
    assert fake.calls[0]["request_id"] == "ro-ro-key"


@pytest.mark.anyio
async def test_history_index_events_rejects_unknown_type() -> None:
    fake = _FakeIndexClient()
    with pytest.raises(HTTPException) as exc_info:
        await history.history_index_events(
            _request_with(fake),
            _readonly_session(),
            index_id="EDU100",
            from_ts=None,
            to_ts=None,
            types=["LEVEL"],
            max_records=10_000,
        )
    assert exc_info.value.status_code == 422
    assert fake.calls == []  # rejected before ever reaching pm-index


@pytest.mark.anyio
async def test_history_index_events_accepts_known_structural_types() -> None:
    fake = _FakeIndexClient()
    await history.history_index_events(
        _request_with(fake),
        _readonly_session(),
        index_id="EDU100",
        from_ts=None,
        to_ts=None,
        types=["CORP_ACTION", "DELIST"],
        max_records=10_000,
    )
    assert fake.calls[0]["types"] == ["CORP_ACTION", "DELIST"]


@pytest.mark.anyio
async def test_history_index_events_rejects_to_before_from() -> None:
    fake = _FakeIndexClient()
    with pytest.raises(HTTPException) as exc_info:
        await history.history_index_events(
            _request_with(fake),
            _readonly_session(),
            index_id="EDU100",
            from_ts=1000.0,
            to_ts=500.0,
            types=None,
            max_records=10_000,
        )
    assert exc_info.value.status_code == 422
    assert fake.calls == []


@pytest.mark.anyio
async def test_history_index_events_defaults_from_to_last_30_days() -> None:
    fake = _FakeIndexClient()
    await history.history_index_events(
        _request_with(fake),
        _readonly_session(),
        index_id="EDU100",
        from_ts=None,
        to_ts=None,
        types=None,
        max_records=10_000,
    )
    call = fake.calls[0]
    span = call["to_ts"] - call["from_ts"]
    # Should default to roughly 30 days (allow generous slack for test
    # runtime, not asserting an exact wall-clock value).
    assert 29 * 86400 < span < 31 * 86400


@pytest.mark.anyio
async def test_history_index_events_timeout_maps_to_503() -> None:
    fake = _FakeIndexClient()
    fake.raise_error = TimeoutError("no reply")
    with pytest.raises(HTTPException) as exc_info:
        await history.history_index_events(
            _request_with(fake),
            _readonly_session(),
            index_id="EDU100",
            from_ts=None,
            to_ts=None,
            types=None,
            max_records=10_000,
        )
    assert exc_info.value.status_code == 503
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["error"]["code"] == "INDEX_TIMEOUT"


@pytest.mark.anyio
async def test_history_index_events_index_error_maps_to_502() -> None:
    fake = _FakeIndexClient()
    fake.raise_error = IndexHistoryError("unknown index_id")
    with pytest.raises(HTTPException) as exc_info:
        await history.history_index_events(
            _request_with(fake),
            _readonly_session(),
            index_id="BOGUS",
            from_ts=None,
            to_ts=None,
            types=None,
            max_records=10_000,
        )
    assert exc_info.value.status_code == 502
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail["error"]["code"] == "INDEX_ERROR"


@pytest.mark.anyio
async def test_history_index_events_surfaces_warnings_when_present() -> None:
    fake = _FakeIndexClient()
    fake.reply = {
        "index_id": "EDU100",
        "records": [],
        "warnings": ["ignored malformed history line"],
    }
    result = await history.history_index_events(
        _request_with(fake),
        _readonly_session(),
        index_id="EDU100",
        from_ts=None,
        to_ts=None,
        types=None,
        max_records=10_000,
    )
    assert result["warnings"] == ["ignored malformed history line"]


@pytest.mark.anyio
async def test_history_index_events_omits_warnings_key_when_absent() -> None:
    fake = _FakeIndexClient()
    fake.reply = {"index_id": "EDU100", "records": []}
    result = await history.history_index_events(
        _request_with(fake),
        _readonly_session(),
        index_id="EDU100",
        from_ts=None,
        to_ts=None,
        types=None,
        max_records=10_000,
    )
    assert "warnings" not in result
