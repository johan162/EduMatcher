"""``Idempotency-Key``: a retried write reaches the engine once.

A client that times out at the network layer cannot tell whether its order was
sent. With a key, retrying is safe: the first request with that key (per
gateway) runs; every later one with the same key -- including one that arrives
while the first is still waiting for its ack -- gets the first reply replayed,
and nothing is sent twice.

* The key is bound to the request it first came with. The same key on a
  different request (another body, another path) is ``409
  IDEMPOTENCY_KEY_REUSED`` -- a client bug, never a silent replay of something
  else.
* Only a reply is remembered. A request that failed before reaching the engine
  (engine unavailable, validation) leaves nothing behind and may be retried.
* A multi-step write records the steps it completed. ``POST
  /orders/{id}/replace`` is a two-step saga (cancel, then submit the
  replacement); if the replacement fails the entry is *kept* with the cancel
  recorded, so the retry resumes at the replacement rather than cancelling an
  already-cancelled order and never submitting anything (P2).
* Keys live in this process for ``order_retention_sec`` and are lost on a
  gateway restart, like the gateway's order cache. One process per gateway id
  (enforced by config), so per-process is per-gateway.

``client_tag`` is untouched: it stays the non-unique label of design D1.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, Request, Response, status

#: Longest key accepted, as most APIs that take this header allow.
MAX_KEY_LENGTH = 255

#: (status code or None for the route default, the handler's result)
Reply = tuple[int | None, Any]


@dataclass
class _Entry:
    fingerprint: str
    created: float
    future: asyncio.Future[Reply] = field(
        default_factory=lambda: asyncio.get_running_loop().create_future()
    )
    #: Steps the handler has completed, carried across retries of this key.
    state: dict[str, Any] = field(default_factory=dict)
    #: False once a failed attempt released it, so a retry may run it again.
    owned: bool = True


class IdempotencyStore:
    """Remembered replies, per (gateway, key), for ``ttl_sec``."""

    def __init__(self, ttl_sec: float) -> None:
        self._ttl = ttl_sec
        self._entries: OrderedDict[tuple[str, str], _Entry] = OrderedDict()

    def _prune(self, now: float) -> None:
        while self._entries:
            first = next(iter(self._entries.values()))
            if not first.future.done() or now - first.created < self._ttl:
                return
            self._entries.popitem(last=False)

    def claim(self, scope: str, key: str, fingerprint: str) -> tuple[_Entry, bool]:
        """Return the key's entry and whether the caller owns (must run) it."""
        now = time.monotonic()
        self._prune(now)
        entry = self._entries.get((scope, key))
        if entry is None:
            entry = _Entry(fingerprint=fingerprint, created=now)
            self._entries[(scope, key)] = entry
            return entry, True
        if entry.fingerprint == fingerprint and not entry.owned:
            # A previous attempt failed part-way and left recorded steps.
            # This caller takes it over and resumes from entry.state.
            entry.owned = True
            entry.future = asyncio.get_running_loop().create_future()
            return entry, True
        if entry.fingerprint != fingerprint:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": {
                        "code": "IDEMPOTENCY_KEY_REUSED",
                        "message": "This Idempotency-Key was used for a different "
                        "request; use a new key for a new request.",
                        "field": "Idempotency-Key",
                    }
                },
            )
        return entry, False

    def forget(self, scope: str, key: str) -> None:
        self._entries.pop((scope, key), None)


async def _fingerprint(request: Request) -> str:
    raw = await request.body()
    try:
        body: Any = json.dumps(json.loads(raw), sort_keys=True) if raw else ""
    except ValueError:
        body = raw.decode(errors="replace")
    text = f"{request.method} {request.url.path}?{request.url.query}\n{body}"
    return hashlib.sha256(text.encode()).hexdigest()


async def idempotent(
    request: Request,
    response: Response,
    scope: str,
    key: str | None,
    run: Callable[[dict[str, Any]], Awaitable[Any]],
) -> Any:
    """Run *run* once per *key*; replay its reply (status and body) after.

    The route's handler calls this around everything that sends to the engine.
    A duplicate waits on the first attempt; if that attempt fails, the
    duplicate makes its own attempt instead of inheriting the failure.

    *run* is given the key's saga state: a dict that survives a failed attempt
    and is handed to the retry, so a handler whose first engine write
    succeeded can record that and resume rather than repeat it.
    """
    if key is None:
        return await run({})
    store: IdempotencyStore = request.app.state.idempotency
    fingerprint = await _fingerprint(request)
    while True:
        entry, owner = store.claim(scope, key, fingerprint)
        if owner:
            break
        # Bound to the future we actually awaited: a failed saga attempt
        # swaps a fresh one onto the entry, and asking the entry afterwards
        # would miss the cancellation we were woken by.
        waited = entry.future
        try:
            code, result = await asyncio.shield(waited)
        except asyncio.CancelledError:
            if waited.cancelled():
                continue  # the first attempt failed: try again ourselves
            raise
        if code is not None:
            response.status_code = code
        response.headers["Idempotent-Replayed"] = "true"
        return result
    # Its own task, so a client that disconnects mid-wait cannot cancel an
    # attempt whose write has already gone out: the reply is still recorded
    # and the client's retry gets it instead of sending a second order.
    attempt = asyncio.ensure_future(run(entry.state))

    def record(done: asyncio.Future[Any]) -> None:
        if done.cancelled() or done.exception() is not None:
            waited = entry.future
            if entry.state:
                # Part of this write reached the engine. Keep the entry so the
                # retry resumes from the recorded step; release it so the
                # retry (or a waiter below) may own it.
                entry.owned = False
                entry.future = asyncio.get_running_loop().create_future()
            else:
                store.forget(scope, key)
            waited.cancel()
        else:
            entry.future.set_result((response.status_code, done.result()))

    attempt.add_done_callback(record)
    return await asyncio.shield(attempt)
