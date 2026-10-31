"""Every ack ExchangeCommandClient waits for must be one it subscribes to.

The client's PUB/SUB socket only delivers topics it subscribed to, so a
``_recv(topic_x(...))`` whose prefix is missing from ``_ACK_SUB_PREFIXES``
never completes: the engine does the work and the caller still gets a
CommandTimeoutError. ``KILL|GW=<other>``, ``KILL`` (global), ``QCANCEL`` and
the reference reload all did exactly that.
"""

from __future__ import annotations

import inspect
import re

from edumatcher.commands import client


def test_every_awaited_topic_is_subscribed() -> None:
    src = inspect.getsource(client.ExchangeCommandClient)
    names = set(re.findall(r"self\._recv\(\s*(topic_\w+)\(", src))
    assert names, "no awaited topics found - the pattern needs updating"

    unsubscribed = []
    for name in sorted(names):
        topic = getattr(client, name)("X")
        if not any(topic.startswith(p) for p in client._ACK_SUB_PREFIXES):
            unsubscribed.append(topic)
    assert not unsubscribed


def test_index_send_retries_until_the_pusher_connects() -> None:
    import zmq

    class _Flaky:
        def __init__(self) -> None:
            self.calls = 0

        def send_multipart(self, frames: list[bytes]) -> None:
            self.calls += 1
            if self.calls < 3:
                raise zmq.Again()

    c = client.ExchangeCommandClient.__new__(client.ExchangeCommandClient)
    c._timeout_ms = 2000
    flaky = _Flaky()
    c._index_push = flaky
    c._send_index([b"x"])
    assert flaky.calls == 3
