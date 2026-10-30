"""
Drive the real pm-api-gwy app (``create_app()``) through raw ASGI calls.

Route-level tests call handler functions directly and so never reach the
app-level pieces: exception handlers, the bearer security dependency, the
status code FastAPI finally sends, and which paths exist at all. This harness
runs a request through the whole ASGI stack, middleware included, without an
HTTP client (httpx is not a dependency). ``app.state`` is populated by hand
instead of by the lifespan, which would start ZMQ.

Not a test module (no test_ prefix) — pytest will not collect it.
"""

from __future__ import annotations

import json
from typing import Any

from edumatcher.api_gateway.config import ApiCredential, ApiGatewayConfig
from edumatcher.api_gateway.main import create_app
from edumatcher.api_gateway.rate_limit import RateLimiter
from edumatcher.api_gateway.sessions import SessionRegistry

#: (status, lower-cased headers, JSON body)
Reply = tuple[int, dict[str, str], dict[str, Any]]

TRADER_KEY = "key-trader"  # gateway GW01
READ_ONLY_KEY = "key-ro"  # gateway_id null


def make_app(engine: Any) -> Any:
    """The configured app, with *engine* standing in for EngineClient."""
    config = ApiGatewayConfig(swagger_enabled=False)
    app = create_app(config)
    app.state.config = config
    app.state.engine = engine
    app.state.rate_limiter = RateLimiter(100, 100)
    app.state.sessions = SessionRegistry(
        (
            ApiCredential(TRADER_KEY, "GW01", "trader"),
            ApiCredential(READ_ONLY_KEY, None, "read-only"),
        )
    )
    return app


async def call(
    app: Any,
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    authorization: str | None = f"Bearer {TRADER_KEY}",
) -> Reply:
    """One request through the whole ASGI stack, middleware included."""
    path, _, query = path.partition("?")
    headers = [(b"content-type", b"application/json")]
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    messages = [
        {
            "type": "http.request",
            "body": json.dumps(body).encode() if body is not None else b"",
            "more_body": False,
        }
    ]
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "root_path": "",
        "headers": headers,
        "server": ("test", 80),
        "client": ("client", 1),
    }
    try:
        await app(scope, receive, send)
    except RuntimeError:
        # Starlette re-raises an unhandled error after sending the 500 (so the
        # server can log it); the response is already in `sent`.
        pass
    start = next(m for m in sent if m["type"] == "http.response.start")
    raw = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    return (
        int(start["status"]),
        {k.decode().lower(): v.decode() for k, v in start["headers"]},
        json.loads(raw),
    )
