"""``pm-api-gwy`` health metrics (operator dashboard §8.5).

One plain ASGI middleware counts HTTP requests and 5xx responses and keeps
the number of open WebSockets per channel, so no router needs editing and a
new WebSocket route is covered the day it is added (as ``other`` until it is
named in ``WS_CHANNELS``). The beacon itself is sent from a lifespan task in
``main.create_app``, which also gives the reporter its event-loop view:
``loop_lag_ms`` there is how late a 0.25 s sleep woke up -- the standard
asyncio stall signal.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from edumatcher.health import counter, gauge
from edumatcher.models.generated.health import MetricSample

#: WebSocket paths -> channel label. A closed set fixed in code (K4).
WS_CHANNELS: dict[str, str] = {
    "/api/v1/ws/private": "private",
    "/api/v1/ws/admin/monitor": "admin/monitor",
    "/api/v1/ws/admin/sim": "admin/sim",
    "/api/v1/ws/market-data": "market-data",
}
OTHER_CHANNEL = "other"
#: The label of requests that did not authenticate: a fixed one, so what a
#: stranger sends can never create a series.
UNAUTH_LABEL = "(unauth)"
#: Scope state key under which ``auth`` leaves the caller's label.
KEY_LABEL_STATE = "api_key_label"


class _EngineCounters(Protocol):
    @property
    def dropped_events(self) -> dict[str, int]: ...

    @property
    def engine_timeouts(self) -> int: ...


class ApiMetrics:
    """Counters the middleware and the routes update; read by the beacon."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.http_requests = 0
        self.http_5xx = 0
        self.ws_sessions: dict[str, int] = {
            channel: 0 for channel in (*WS_CHANNELS.values(), OTHER_CHANNEL)
        }
        # Per API key (by label): requests answered, 429s, and the busiest
        # second. Every configured key is listed from the start (register_keys).
        self.key_requests: dict[str, int] = {UNAUTH_LABEL: 0}
        self.key_throttled: dict[str, int] = {UNAUTH_LABEL: 0}
        self.key_peak: dict[str, int] = {UNAUTH_LABEL: 0}
        #: Busiest second of all requests since start. pm-monitor sees a
        #: beacon every few seconds, so it cannot get this by differencing.
        self.peak = 0
        self._second = int(clock())
        self._in_second: dict[str, int] = {}

    def register_keys(self, labels: list[str]) -> None:
        """List the configured keys, so an idle one shows with zeros."""
        for label in labels:
            self.key_requests.setdefault(label, 0)
            self.key_throttled.setdefault(label, 0)
            self.key_peak.setdefault(label, 0)

    def record(self, label: str, status: int) -> None:
        """One answered request of the key ``label``."""
        second = int(self._clock())
        if second != self._second:
            self._close_second()
            self._second = second
        self.register_keys([label])
        self._in_second[label] = self._in_second.get(label, 0) + 1
        self.key_requests[label] += 1
        if status == 429:
            self.key_throttled[label] += 1

    def _close_second(self) -> None:
        """Fold the second just ended into the peaks."""
        self.peak = max(self.peak, sum(self._in_second.values()))
        for label, n in self._in_second.items():
            if n > self.key_peak.get(label, 0):
                self.key_peak[label] = n
        self._in_second = {}

    def samples(self, engine: _EngineCounters | None) -> list[MetricSample]:
        out = [
            counter("api.http_requests", self.http_requests),
            counter("api.http_5xx", self.http_5xx),
        ]
        out.extend(
            gauge("api.ws_sessions", n, channel)
            for channel, n in sorted(self.ws_sessions.items())
        )
        # The second in progress counts too: it can only grow into the peak.
        out.append(gauge("api.rps_peak", max(self.peak, sum(self._in_second.values()))))
        for label in sorted(self.key_requests):
            out.append(counter("api.key_requests", self.key_requests[label], label))
            out.append(counter("api.key_throttled", self.key_throttled[label], label))
            peak = max(self.key_peak[label], self._in_second.get(label, 0))
            out.append(gauge("api.key_rps_peak", peak, label))
        if engine is not None:
            out.extend(
                counter("api.dropped_events", n, sink)
                for sink, n in sorted(engine.dropped_events.items())
            )
            out.append(counter("api.engine_timeouts", engine.engine_timeouts))
        return out


class MetricsMiddleware:
    """ASGI middleware feeding :class:`ApiMetrics`."""

    def __init__(self, app: ASGIApp, metrics: ApiMetrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        kind = scope["type"]
        if kind == "http":
            await self._http(scope, receive, send)
        elif kind == "websocket":
            channel = WS_CHANNELS.get(scope.get("path", ""), OTHER_CHANNEL)
            sessions = self.metrics.ws_sessions
            sessions[channel] += 1
            try:
                await self.app(scope, receive, send)
            finally:
                sessions[channel] -= 1
        else:
            await self.app(scope, receive, send)

    async def _http(self, scope: Scope, receive: Receive, send: Send) -> None:
        metrics = self.metrics
        metrics.http_requests += 1
        status: list[int] = []
        # `auth` leaves the caller's label here; created now so it is the
        # dict the routed request shares, whatever copies the scope.
        state: dict[str, Any] = scope.setdefault("state", {})

        async def observe(message: Message) -> None:
            if message["type"] == "http.response.start":
                status.append(int(message["status"]))
                if message["status"] >= 500:
                    metrics.http_5xx += 1
            await send(message)

        try:
            await self.app(scope, receive, observe)
        except Exception:
            # Unhandled: Starlette's outermost error middleware turns it into
            # a 500 after it has passed back through here.
            if not status:
                metrics.http_5xx += 1
            raise
        finally:
            metrics.record(
                state.get(KEY_LABEL_STATE, UNAUTH_LABEL),
                status[0] if status else 0,
            )


def install(app: Any) -> ApiMetrics:
    """Attach the middleware and return the counters (``app.state.metrics``)."""
    metrics = ApiMetrics()
    app.add_middleware(MetricsMiddleware, metrics=metrics)
    app.state.health_metrics = metrics
    return metrics
