"""Subscription registry and fanout selection helpers for CALF."""

from __future__ import annotations

from dataclasses import dataclass, field

StreamKey = tuple[str, str]


@dataclass
class SubscriptionRegistry:
    """Maintain per-client CALF subscriptions as (channel, symbol) pairs.

    Indexed both ways: by client, and by pair (``SYM=*`` is a pair of its
    own). An event then costs a lookup of the clients that want it rather
    than a scan of every client's whole subscription set, which at 64
    clients x 600 pairs took 1.3 ms per event.
    """

    _by_client: dict[int, set[StreamKey]] = field(default_factory=dict)
    _by_stream: dict[StreamKey, set[int]] = field(default_factory=dict)

    def get(self, client_fd: int) -> set[StreamKey]:
        return self._by_client.setdefault(client_fd, set())

    def set_for_client(self, client_fd: int, subscriptions: set[StreamKey]) -> None:
        self.remove_client(client_fd)
        self._by_client[client_fd] = set(subscriptions)
        for key in subscriptions:
            self._by_stream.setdefault(key, set()).add(client_fd)

    def remove_client(self, client_fd: int) -> None:
        for key in self._by_client.pop(client_fd, set()):
            fds = self._by_stream.get(key)
            if fds is None:
                continue
            fds.discard(client_fd)
            if not fds:
                del self._by_stream[key]

    def session_wants(self, client_fd: int, ch: str, sym: str) -> bool:
        subs = self._by_client.get(client_fd, set())
        return (ch, sym) in subs or (ch, "*") in subs

    def wanting(self, ch: str, sym: str) -> set[int]:
        """Clients subscribed to ``(ch, sym)``, directly or by ``SYM=*``."""
        return self._by_stream.get((ch, sym), set()) | self._by_stream.get(
            (ch, "*"), set()
        )
