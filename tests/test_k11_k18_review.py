"""Post-commit review findings for K11-K18.

Six defects found reviewing the K11-K18 work packages, each reproduced here
before being fixed:

R1  ``IdempotencyStore._prune`` stops at the first entry whose future is not
    done. K14's part-done saga parks a *permanently pending* future on a
    retained entry, so that entry and every entry behind it is never evicted.
R2  K16/P6 moved history.py's nine SQLite reads off the event loop but left
    ``fetch_positions`` opening and querying clearing.db synchronously.
R3  BALF sends the symbol request before setting ``symbols_pending``; a full
    engine PUSH queue raises there and leaves a session that is neither
    authenticated nor pending, so nothing ever answers its LOGON.
R4  K16/G1 only registers write interest for ``BlockingIOError``. Any other
    transient ``OSError`` leaves the session dirty-but-not-blocked, which is
    exactly the busy-spin G1 removed.
R5  ``config_coerce.as_int`` routes strings through ``float()``, so an integer
    beyond 2**53 is silently rounded -- the one thing the module promises not
    to do.

R6 (``_in_stats_db`` returning ``Any``) is a typing defect with no runtime
symptom; ``mypy``/``pyright`` are its regression test.
"""

from __future__ import annotations

import asyncio
import errno
import selectors
from typing import Any, cast

import pytest
import zmq

from edumatcher.api_gateway.idempotency import IdempotencyStore
from edumatcher.api_gateway.routers.reference import fetch_positions
from edumatcher.balf_gwy.gateway import BalfGateway, ClientSession as BalfSession
from edumatcher.config_coerce import as_int

from tests.test_gateway_k16_k17 import (
    GW,
    _alf,
    _alf_session,
    _balf,
    _FakeSub,
    _sel,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# ---------------------------------------------------------------------------
# R1 — an abandoned saga entry must not pin the prune cursor
# ---------------------------------------------------------------------------


def _abandon(store: IdempotencyStore, scope: str, key: str) -> None:
    """Leave *key* the way a part-done saga attempt leaves it (K14)."""
    entry = store._entries[(scope, key)]
    entry.state["cancelled"] = True
    entry.owned = False
    entry.future = asyncio.get_running_loop().create_future()


@pytest.mark.anyio
async def test_r1_an_abandoned_saga_entry_is_pruned_once_it_expires() -> None:
    """Its future never completes, so a prune that stops at the first
    unfinished entry keeps it -- and the whole store -- for ever."""
    store = IdempotencyStore(ttl_sec=0.0)
    store.claim("gw", "key-a", "fp-a")
    _abandon(store, "gw", "key-a")

    store.claim("gw", "key-b", "fp-b")

    assert ("gw", "key-a") not in store._entries, (
        "an expired entry nobody retried must be evicted even though the "
        "future its failed attempt left behind is still pending"
    )


@pytest.mark.anyio
async def test_r1_an_abandoned_entry_does_not_block_entries_behind_it() -> None:
    store = IdempotencyStore(ttl_sec=0.0)
    store.claim("gw", "key-a", "fp-a")
    _abandon(store, "gw", "key-a")
    entry_b, _ = store.claim("gw", "key-b", "fp-b")
    entry_b.future.set_result((200, {}))

    store.claim("gw", "key-c", "fp-c")

    assert set(store._entries) == {("gw", "key-c")}, (
        "prune walks oldest-first and returns on the first entry it keeps, so "
        "a stuck head hides every completed entry behind it"
    )


@pytest.mark.anyio
async def test_r1_an_expired_key_may_be_reused_for_a_different_request() -> None:
    """The user-visible symptom: the key outlives its TTL, so the client's
    next, unrelated use of it is refused as a reuse."""
    store = IdempotencyStore(ttl_sec=0.0)
    store.claim("gw", "key-a", "fp-a")
    _abandon(store, "gw", "key-a")

    entry, owner = store.claim("gw", "key-a", "a-different-fingerprint")

    assert owner is True
    assert entry.state == {}, "the expired saga's recorded steps must not leak"


@pytest.mark.anyio
async def test_r1_a_live_attempt_is_still_protected_from_pruning() -> None:
    """The fix must not evict an entry whose attempt is actually running."""
    store = IdempotencyStore(ttl_sec=0.0)
    store.claim("gw", "key-a", "fp-a")  # owned, future pending == in flight

    store.claim("gw", "key-b", "fp-b")

    assert ("gw", "key-a") in store._entries


# ---------------------------------------------------------------------------
# R2 — the clearing-DB read must leave the event loop
# ---------------------------------------------------------------------------


def test_r2_the_clearing_db_read_runs_off_the_event_loop() -> None:
    """``_period_realized_pnl`` opens and queries SQLite synchronously. Called
    straight from ``fetch_positions`` it stalls every other request on the
    loop, including the engine round-trip this handler is about to make."""
    assert "to_thread" in fetch_positions.__code__.co_names, (
        "fetch_positions must hand the blocking clearing.db read to a worker "
        "thread, the way history.py's _in_stats_db does (P6)"
    )


# ---------------------------------------------------------------------------
# R3 — a refused symbol request must not strand the logon
# ---------------------------------------------------------------------------


class _FullPush:
    """An engine PUSH socket whose queue is full."""

    def __init__(self) -> None:
        self.closed = False

    def send_multipart(self, frames: list[bytes]) -> None:
        raise zmq.Again()

    def close(self) -> None:
        pass


class _NullSock:
    def __init__(self, fileno: int = 77) -> None:
        self._fileno = fileno

    def fileno(self) -> int:
        return self._fileno

    def close(self) -> None:
        pass


def _balf_pending_logon(gw: BalfGateway) -> BalfSession:
    session = BalfSession(sock=cast(Any, _NullSock()), addr=("127.0.0.1", 40000))
    session.gateway_id = GW
    session.auth_pending = True
    gw._clients[session.sock.fileno()] = session
    return session


def test_r3_a_refused_symbol_request_rejects_the_logon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The engine accepted the connect, but its PUSH queue is full, so the
    symbol request never goes out. Nothing will ever answer it, and the
    session is left neither authenticated nor pending -- invisible to both
    the symbols sweep and the pending-auth timeout."""
    gw = _balf(monkeypatch, _FakeSub())
    gw._push = cast(Any, _FullPush())
    session = _balf_pending_logon(gw)

    gw._handle_gateway_auth(GW, {"accepted": True, "description": "ok"})

    assert session.authenticated is False
    assert session.out_queue, "the client must be told its logon failed"
    assert b"ENGINE_UNAVAILABLE" in session.out_queue[0]
    assert session.closing is True


def test_r3_a_session_awaiting_symbols_is_always_sweepable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``symbols_pending`` has to be set before the send, not after it, or a
    send that raises leaves a session no timeout can reach."""
    gw = _balf(monkeypatch, _FakeSub())
    session = _balf_pending_logon(gw)

    gw._handle_gateway_auth(GW, {"accepted": True, "description": "ok"})

    assert session.logon_in_progress, (
        "until the metadata arrives the session must stay visible to the "
        "auth-timeout sweep"
    )


# ---------------------------------------------------------------------------
# R4 — every retryable write error must park the session, not spin the loop
# ---------------------------------------------------------------------------


class _TransientErrorSocket:
    """A client socket whose ``send`` fails with a retryable ``OSError``."""

    def __init__(self, fileno: int, err: int) -> None:
        self._fileno = fileno
        self._err = err
        self.send_calls = 0

    def fileno(self) -> int:
        return self._fileno

    def send(self, data: bytes) -> int:
        self.send_calls += 1
        raise OSError(self._err, "transient")

    def recv(self, size: int) -> bytes:
        raise BlockingIOError(errno.EAGAIN, "would block")

    def close(self) -> None:
        pass


@pytest.mark.parametrize("err", [errno.ENOBUFS, errno.ENOMEM])
def test_r4_a_transient_write_error_parks_the_session(
    monkeypatch: pytest.MonkeyPatch, err: int
) -> None:
    """Neither peer-gone nor ``EAGAIN``: the old code just broke out, leaving
    the session dirty but not write-blocked, so ``_has_pending_writes()``
    stayed true and the loop selected with a zero timeout for ever."""
    gw = _alf(monkeypatch)
    sock = _TransientErrorSocket(42, err)
    session = _alf_session(gw, cast(Any, sock))
    gw._queue_raw(session, b"HB|TS=now\n")

    gw._flush_client_writes()

    assert 42 in gw._clients, "a retryable error must not drop the client"
    assert (
        gw._has_pending_writes() is False
    ), "a parked session must not hold the select loop at a zero timeout"
    assert _sel(gw).events[42] & selectors.EVENT_WRITE


def test_r4_an_interrupted_write_is_retried_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``EINTR`` means the syscall was interrupted, not that the peer is slow:
    retry it rather than waiting for a writability edge that already passed."""
    gw = _alf(monkeypatch)

    class _InterruptOnce:
        def __init__(self) -> None:
            self.send_calls = 0

        def fileno(self) -> int:
            return 42

        def send(self, data: bytes) -> int:
            self.send_calls += 1
            if self.send_calls == 1:
                raise OSError(errno.EINTR, "interrupted")
            return len(data)

        def close(self) -> None:
            pass

    sock = _InterruptOnce()
    session = _alf_session(gw, cast(Any, sock))
    gw._queue_raw(session, b"HB|TS=now\n")

    gw._flush_client_writes()

    assert sock.send_calls == 2
    assert not session.out_queue, "the retry should have drained the queue"
    assert gw._has_pending_writes() is False


def test_r4_a_zero_length_write_does_not_spin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gw = _alf(monkeypatch)

    class _ZeroSock:
        def fileno(self) -> int:
            return 42

        def send(self, data: bytes) -> int:
            return 0

        def close(self) -> None:
            pass

    session = _alf_session(gw, cast(Any, _ZeroSock()))
    gw._queue_raw(session, b"HB|TS=now\n")

    gw._flush_client_writes()

    assert gw._has_pending_writes() is False


# ---------------------------------------------------------------------------
# R5 — strict coercion must not round what it accepts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["9007199254740993", "9223372036854775807", b"9007199254740993"],
)
def test_r5_a_large_integer_string_keeps_every_digit(raw: Any) -> None:
    """Routing strings through ``float()`` rounds past 2**53, so the config
    silently holds a different number than the operator wrote."""
    assert as_int(raw, "x.y") == int(raw)


def test_r5_integral_float_strings_are_still_accepted() -> None:
    """The fix must not tighten what was already allowed."""
    assert as_int("1e3", "x.y") == 1000
    assert as_int(" 42 ", "x.y") == 42


@pytest.mark.parametrize("raw", ["1.5", "abc", "", "nan", "inf"])
def test_r5_non_integral_strings_are_still_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        as_int(raw, "x.y")
