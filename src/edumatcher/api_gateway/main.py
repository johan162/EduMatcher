"""Command-line entry point and FastAPI app factory for ``pm-api-gateway``."""

from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from edumatcher.api_gateway.config import ApiGatewayConfig, load_api_gateway_config
from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.api_gateway.rate_limit import RateLimiter
from edumatcher.api_gateway.routers import history, orders, reference, ws
from edumatcher.api_gateway.sessions import SessionRegistry
from edumatcher.config import ENGINE_CONFIG_FILE


def create_app(config: ApiGatewayConfig) -> FastAPI:
    """Create a configured FastAPI application.

    FastAPI automatically publishes OpenAPI at ``/openapi.json`` and Swagger UI
    at ``/docs``.  Those endpoints are controlled by ``swagger_enabled`` in the
    central ``api_gateway`` config block.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        loop = asyncio.get_running_loop()
        engine = EngineClient(config.engine_pull_addr, config.engine_pub_addr, loop)
        engine.start_listener()
        app.state.config = config
        app.state.engine = engine
        app.state.sessions = SessionRegistry.from_config(config)
        app.state.rate_limiter = RateLimiter(
            config.rate_limit.writes_per_second,
            config.rate_limit.burst,
        )
        try:
            yield
        finally:
            for gateway_id in engine.active_gateways():
                engine.send_disconnect(gateway_id, "api gateway shutdown")
            engine.stop_listener()

    docs_url = "/docs" if config.swagger_enabled else None
    openapi_url = "/openapi.json" if config.swagger_enabled else None
    app = FastAPI(
        title="EduMatcher API Gateway",
        version="1.0.0",
        description="REST/JSON and WebSocket gateway for EduMatcher order entry and market data.",
        docs_url=docs_url,
        redoc_url=None,
        openapi_url=openapi_url,
        lifespan=lifespan,
    )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(  # pyright: ignore[reportUnusedFunction]
        _request: object,
        exc: RequestValidationError,
    ) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = first.get("loc", [])
        field = str(loc[-1]) if loc else None
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "VALIDATION",
                    "message": str(first.get("msg", "Invalid request")),
                    "field": field,
                }
            },
        )

    app.include_router(orders.router)
    app.include_router(reference.router)
    app.include_router(history.router)
    app.include_router(ws.router)
    return app


def _config_with_overrides(args: argparse.Namespace) -> ApiGatewayConfig:
    config_path = Path(args.config).expanduser() if args.config else ENGINE_CONFIG_FILE
    config = load_api_gateway_config(config_path, instance=args.instance)
    engine_pull_addr = config.engine_pull_addr
    engine_pub_addr = config.engine_pub_addr
    if args.engine_host:
        engine_pull_addr = f"tcp://{args.engine_host}:5555"
        engine_pub_addr = f"tcp://{args.engine_host}:5556"
    return ApiGatewayConfig(
        name=config.name,
        enabled=config.enabled,
        host=args.host or config.host,
        port=args.port or config.port,
        engine_pull_addr=engine_pull_addr,
        engine_pub_addr=engine_pub_addr,
        stats_db=Path(args.stats_db).expanduser() if args.stats_db else config.stats_db,
        log_level=args.log_level or config.log_level,
        swagger_enabled=config.swagger_enabled,
        credentials=config.credentials,
        rate_limit=config.rate_limit,
        timeouts=config.timeouts,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="EduMatcher REST API gateway")
    parser.add_argument(
        "--host", default=None, metavar="ADDR", help="HTTP bind address"
    )
    parser.add_argument(
        "--port", default=None, type=int, metavar="PORT", help="HTTP listen port"
    )
    parser.add_argument(
        "--config", default=None, metavar="PATH", help="Path to engine_config.yaml"
    )
    parser.add_argument(
        "--instance",
        default=None,
        metavar="NAME",
        help="Named api_gateways entry to run when multiple API gateway processes are configured",
    )
    parser.add_argument(
        "--engine-host",
        default=None,
        metavar="HOST",
        help="Override engine host in ZMQ URLs",
    )
    parser.add_argument(
        "--stats-db", default=None, metavar="PATH", help="Path to stats.db"
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["debug", "info", "warning", "error"],
        help="uvicorn logging level",
    )
    args = parser.parse_args()
    try:
        config = _config_with_overrides(args)
    except Exception as exc:
        print(f"[API-GW] FATAL: {exc}", file=sys.stderr)
        sys.exit(1)
    if not config.enabled:
        print("[API-GW] api_gateway.enabled is false", file=sys.stderr)
        sys.exit(1)
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port, log_level=config.log_level)


if __name__ == "__main__":
    main()
