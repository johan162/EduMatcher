"""
Shared harness: the real scheduler loop driving a real Engine in-process.

The scheduler talks to the engine over two sockets: a PUSH it sends
``session.transition`` / ``session.next`` / ``system.session_state_request``
on, and a SUB it reads ``session.state`` and its own
``system.session_status.SCHEDULER`` replies from. :class:`EngineBridge` stands
in for the PUSH (it hands each message to the engine's own handler) and
:class:`EngineSub` for the SUB (it reads, in order, what the engine published
on the subscribed topics). No mock answers what a test expects: the engine
decides what is applied and what is broadcast.

Not a test module (no test_ prefix) — pytest will not collect it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Callable

from edumatcher.engine.main import Engine
from edumatcher.models.message import decode
from edumatcher.scheduler import main as sched
from tests.engine_harness import FakeSock, make_engine


@dataclass
class EngineRef:
    """The engine the doubles talk to; :meth:`restart` replaces it."""

    monkeypatch: Any
    tmp_path: Any
    engine: Engine = field(init=False)
    pub: FakeSock = field(init=False)
    run_seq: int = 1

    def __post_init__(self) -> None:
        self.engine, self.pub = make_engine(
            self.monkeypatch, self.tmp_path, sessions_enabled=True
        )

    def drive(self, *states: str, command_id: str = "") -> None:
        """Apply transitions as another producer (an operator) would."""
        for state in states:
            payload: dict[str, Any] = {"to_state": state}
            if command_id:
                payload["reply_to"] = {"command_id": command_id, "gateway_id": "OPS"}
            self.engine._handle_session_transition(payload)

    def restart(self, *, announce: bool = True) -> None:
        """A fresh engine process: boots CLOSED, publishes ``system.startup``."""
        self.run_seq += 1
        self.engine, self.pub = make_engine(
            self.monkeypatch, self.tmp_path, sessions_enabled=True, run_seq=self.run_seq
        )
        if announce:
            self.engine._announce_startup(self.run_seq)

    @property
    def state(self) -> str:
        return self.engine._session_state.value


class EngineBridge:
    """PUSH double: each message goes to the current engine's handler.

    ``applied`` records ``(to_state, before, after)`` for every transition;
    ``on_transition`` runs before the engine sees one (to restart the engine
    or to stand in for a lost message: return False to drop it).
    """

    def __init__(
        self,
        ref: EngineRef,
        on_transition: Callable[[str], bool | None] | None = None,
    ) -> None:
        self.ref = ref
        self.on_transition = on_transition
        self.applied: list[tuple[str, str, str]] = []
        self.topics: list[str] = []

    def send_multipart(self, frames: list[bytes]) -> None:
        topic, payload = decode(frames)
        self.topics.append(topic)
        if topic == "session.transition":
            to_state = str(payload["to_state"])
            if self.on_transition is not None and self.on_transition(to_state) is False:
                return
            before = self.ref.state
            self.ref.engine._handle_session_transition(payload)
            self.applied.append((to_state, before, self.ref.state))
        elif topic == "session.next":
            self.ref.engine._handle_session_next(payload)
        elif topic == "system.session_state_request":
            self.ref.engine._handle_session_state_request(payload)

    def close(self) -> None:
        pass

    def transitions(self) -> list[str]:
        """The transitions the engine applied, in order."""
        return [to for to, before, after in self.applied if before != after]


class EngineSub:
    """SUB double over the current engine's published frames.

    Subscribes by topic prefix, as ZMQ does. Each engine (a restart makes a
    new one) has its own read position; a frame published before the
    double first looked at an engine is still delivered, as a connected SUB
    would have queued it.
    """

    def __init__(self, ref: EngineRef, *prefixes: str) -> None:
        self.ref = ref
        self.prefixes = prefixes or (
            "session.state",
            "system.session_status.SCHEDULER",
            "system.startup",
        )
        self._pos: dict[int, int] = {}
        self._seen: list[int] = []

    def _frames(self) -> tuple[list[list[bytes]], int]:
        pub = self.ref.pub
        if id(pub) not in self._pos:
            self._pos[id(pub)] = 0
        return pub.sent, self._pos[id(pub)]

    def _next_index(self) -> int | None:
        frames, i = self._frames()
        while i < len(frames):
            topic, _ = decode(frames[i])
            if topic.startswith(self.prefixes):
                return i
            i += 1
        return None

    def poll(self, timeout: int = 0) -> int:
        if self._next_index() is not None:
            return 1
        if timeout:
            time.sleep(min(timeout, 5) / 1000.0)
        return 0

    def recv_multipart(self) -> list[bytes]:
        i = self._next_index()
        assert i is not None, "recv_multipart on an empty EngineSub"
        frames, _ = self._frames()
        self._pos[id(self.ref.pub)] = i + 1
        return frames[i]

    def close(self) -> None:
        pass


def fast_timeouts(monkeypatch: Any, ms: int = 100) -> None:
    """Shorten the confirmation and state-query waits for tests."""
    monkeypatch.setattr(
        sched, "_confirm_transition", partial(sched._confirm_transition, timeout_ms=ms)
    )
    monkeypatch.setattr(
        sched,
        "_query_engine_status",
        partial(sched._query_engine_status, timeout_ms=ms),
    )
    monkeypatch.setattr(
        sched,
        "_query_engine_state",
        partial(sched._query_engine_state, timeout_ms=ms),
    )


class _ReplyingSub:
    """SUB double for tests with a mock PUSH: each scripted frame becomes
    readable only after the next send, as an engine's reply would.

    A MagicMock SUB whose ``poll`` always returns 1 models a reply that was
    queued before the request, which the scheduler now discards (C3).
    """

    def __init__(self, push: Any, *replies: list[bytes]) -> None:
        self._replies = list(replies)
        self._queue: list[list[bytes]] = []
        push.send_multipart.side_effect = self._on_send

    def _on_send(self, _frames: list[bytes]) -> None:
        if self._replies:
            self._queue.append(self._replies.pop(0))

    def poll(self, timeout: int = 0) -> int:
        return 1 if self._queue else 0

    def recv_multipart(self) -> list[bytes]:
        return self._queue.pop(0)

    def close(self) -> None:
        pass


def replying_sub(push: Any, *replies: list[bytes]) -> Any:
    """A :class:`_ReplyingSub`, typed loosely to stand in for a ZMQ socket."""
    return _ReplyingSub(push, *replies)
