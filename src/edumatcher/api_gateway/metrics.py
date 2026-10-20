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

from typing import Any, Protocol

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from edumatcher.health import counter, gauge
from edumatcher.models.generated.health import MetricSample

#: WebSocket paths -> channel label. A closed set fixed in code (K4).
WS_CHANNELS: dict[str, str] = {
    "/api/v1/events": "events",
    "/api/v1/admin/monitor": "admin/monitor",
    "/api/v1/admin/sim": "admin/sim",
    "/api/v1/market-data": "market-data",
}
OTHER_CHANNEL = "other"


class _EngineCounters(Protocol):
    @property
    def dropped_events(self) -> dict[str, int]: ...

    @property
    def engine_timeouts(self) -> int: ...


class ApiMetrics:
    """Counters the middleware and the routes update; read by the beacon."""

    def __init__(self) -> None:
        self.http_requests = 0
        self.http_5xx = 0
        self.ws_sessions: dict[str, int] = {
            channel: 0 for channel in (*WS_CHANNELS.values(), OTHER_CHANNEL)
        }

    def samples(self, engine: _EngineCounters | None) -> list[MetricSample]:
        out = [
            counter("api.http_requests", self.http_requests),
            counter("api.http_5xx", self.http_5xx),
        ]
        out.extend(
            gauge("api.ws_sessions", n, channel)
            for channel, n in sorted(self.ws_sessions.items())
        )
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


def install(app: Any) -> ApiMetrics:
    """Attach the middleware and return the counters (``app.state.metrics``)."""
    metrics = ApiMetrics()
    app.add_middleware(MetricsMiddleware, metrics=metrics)
    app.state.health_metrics = metrics
    return metrics
