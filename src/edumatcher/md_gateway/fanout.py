"""Subscription registry and fanout selection helpers for CALF."""

from __future__ import annotations

from dataclasses import dataclass, field

StreamKey = tuple[str, str]


@dataclass
class SubscriptionRegistry:
    """Maintain per-client CALF subscriptions as (channel, symbol) pairs."""

    _by_client: dict[int, set[StreamKey]] = field(default_factory=dict)

    def get(self, client_fd: int) -> set[StreamKey]:
        return self._by_client.setdefault(client_fd, set())

    def set_for_client(self, client_fd: int, subscriptions: set[StreamKey]) -> None:
        self._by_client[client_fd] = set(subscriptions)

    def remove_client(self, client_fd: int) -> None:
        self._by_client.pop(client_fd, None)

    def session_wants(self, client_fd: int, ch: str, sym: str) -> bool:
        subs = self._by_client.get(client_fd, set())
        for sub_ch, sub_sym in subs:
            if sub_ch != ch:
                continue
            if sub_sym == "*" or sub_sym == sym:
                return True
        return False
