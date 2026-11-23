"""Every reply ExchangeCommandClient waits for must reach its SUB socket.

The client's PUB/SUB socket only delivers topics it subscribed to, so a wait
for an unsubscribed reply never completes: the engine does the work and the
caller still gets a CommandTimeoutError. ``KILL|GW=<other>``, ``KILL``
(global), ``QCANCEL`` and the reference reload all did exactly that.

Since the Admin commands review 2026-11 (H1) the client subscribes for its
whole life only to the exact topics of replies addressed to its own id; a
reply keyed by a symbol or a target gateway is subscribed by ``_ask`` for the
one request. Anything subscribed but never awaited only fills an idle
client's queue until ZeroMQ drops the next reply.
"""

from __future__ import annotations

import inspect
import re
from collections import deque
from typing import Any

import zmq

from edumatcher.commands import client


def _class_source() -> str:
    return inspect.getsource(client.ExchangeCommandClient)


def test_replies_are_awaited_only_through_ask_or_connect() -> None:
    """A method that called ``_send``/``_recv`` itself would skip the
    temporary subscription and the drain."""
    src = _class_source()
    callers = []
    for match in re.finditer(r"self\._recv\(", src):
        head = src[: match.start()]
        callers.append(re.findall(r"\n    def (\w+)\(", head)[-1])
    assert sorted(set(callers)) == ["_ask", "connect"]


def test_every_own_topic_is_awaited() -> None:
    src = _class_source()
    for builder in (*client._OWN_ENGINE_TOPICS, *client._OWN_INDEX_TOPICS):
        # kill_switch_ack / quote_cancel_ack are awaited for a target that is
        # the client's own id when the console acts on itself.
        assert f"{builder.__name__}(" in src, builder.__name__


class _RecordingSub:
    def __init__(self, log: list[tuple[str, str]]) -> None:
        self._log = log

    def setsockopt_string(self, option: int, value: str) -> None:
        name = "SUB" if option == zmq.SUBSCRIBE else "UNSUB"
        self._log.append((name, value))

    def poll(self, timeout: int = 0) -> int:
        return 0


class _RecordingPush:
    def __init__(self, log: list[tuple[str, str]]) -> None:
        self._log = log

    def send_multipart(self, frames: list[bytes]) -> None:
        self._log.append(("SEND", frames[0].decode()))


def _bare_client(log: list[tuple[str, str]]) -> Any:
    c = client.ExchangeCommandClient.__new__(client.ExchangeCommandClient)
    c._gw_id = "GW_ADMIN"
    c._timeout_ms = 1000
    c._recv_queue = None
    c._sub = _RecordingSub(log)
    c._index_sub = _RecordingSub(log)
    c._push = _RecordingPush(log)
    c._recv = lambda *_a, **_k: {"orders": []}
    return c


def test_a_target_keyed_reply_is_subscribed_only_around_its_request() -> None:
    log: list[tuple[str, str]] = []
    _bare_client(log).order_list("trader01")
    assert log == [
        ("SUB", "order.orders.TRADER01"),
        ("SEND", "order.orders_request"),
        ("UNSUB", "order.orders.TRADER01"),
    ]


def test_an_own_reply_needs_no_temporary_subscription() -> None:
    log: list[tuple[str, str]] = []
    _bare_client(log).volume()
    assert log == [("SEND", "system.volume_request")]


def test_index_send_retries_until_the_pusher_connects() -> None:
    class _Flaky:
        def __init__(self) -> None:
            self.calls = 0

        def send_multipart(self, frames: list[bytes]) -> None:
            self.calls += 1
            if self.calls < 3:
                raise zmq.Again()

    c = client.ExchangeCommandClient.__new__(client.ExchangeCommandClient)
    c._timeout_ms = 2000
    c._recv_queue = deque()  # injected-queue mode: nothing to drain
    flaky = _Flaky()
    c._index_push = flaky
    c._send_index([b"x"])
    assert flaky.calls == 3
