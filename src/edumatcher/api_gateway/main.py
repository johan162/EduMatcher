"""Command-line entry point and FastAPI app factory for ``pm-api-gwy``."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from edumatcher.api_gateway.config import (
    ApiGatewayConfig,
    load_default_api_gateway_config,
)
from edumatcher.api_gateway.engine_client import EngineClient
from edumatcher.api_gateway.index_client import IndexClient
from edumatcher.api_gateway.rate_limit import RateLimiter
from edumatcher.api_gateway.routers import admin, bootstrap, history, orders, reference, ws
from edumatcher.api_gateway.sessions import SessionRegistry
from edumatcher.log_srv.config import (
    load_default_log_client_config,
    load_default_log_server_config,
    resolve_host_default,
)
from edumatcher.logclient.discovery import resolve_handler

_CLIENT_NAME = "pm-api-gwy"
_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s - %(message)s"

log = logging.getLogger(__name__)


def create_app(config: ApiGatewayConfig) -> FastAPI:
    """Create a configured FastAPI application.

    FastAPI automatically publishes OpenAPI at ``/openapi.json`` and Swagger UI
    at ``/docs``.  Those endpoints are controlled by ``swagger_enabled`` in the
    central ``api_gateways`` config.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        loop = asyncio.get_running_loop()
        engine = EngineClient(
            config.engine_pull_addr,
            config.engine_pub_addr,
            loop,
            market_cache_sec=config.market_data_cache_sec,
        )
        engine.start_listener()
        index_client = IndexClient(config.index_pull_addr, config.index_pub_addr, loop)
        index_client.start_listener()
        app.state.config = config
        app.state.engine = engine
        app.state.index_client = index_client
        app.state.sessions = SessionRegistry.from_config(config)
        app.state.rate_limiter = RateLimiter(
            config.rate_limit.writes_per_second,
            config.rate_limit.burst,
        )

        async def _evict_terminal_orders() -> None:
            """Bound the order cache. Without this it grows for the process's
            lifetime and the admin order table would show this morning's
            fills as current."""
            interval = max(60, config.order_retention_sec // 10)
            while True:
                await asyncio.sleep(interval)
                dropped = engine.evict_terminal_orders(config.order_retention_sec)
                if dropped:
                    logging.getLogger(__name__).debug(
                        "evicted %d terminal order(s) older than %ds",
                        dropped,
                        config.order_retention_sec,
                    )

        sweeper = (
            asyncio.create_task(_evict_terminal_orders())
            if config.order_retention_sec > 0
            else None
        )
        try:
            yield
        finally:
            if sweeper is not None:
                sweeper.cancel()
            for gateway_id in engine.active_gateways():
                # Best-effort: a 503 raised here would skip the two
                # stop_listener calls below and leak the reader threads, and
                # "the engine is already gone" is the ordinary case at
                # shutdown, not an error.
                engine.send_disconnect(
                    gateway_id, "api gateway shutdown", require_engine=False
                )
            engine.stop_listener()
            index_client.stop_listener()

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
    app.include_router(admin.router)
    app.include_router(bootstrap.router)
    app.include_router(ws.router)
    return app


def _config_with_overrides(args: argparse.Namespace) -> ApiGatewayConfig:
    config = load_default_api_gateway_config(instance=args.instance)
    engine_pull_addr = config.engine_pull_addr
    engine_pub_addr = config.engine_pub_addr
    index_pull_addr = config.index_pull_addr
    index_pub_addr = config.index_pub_addr
    if args.engine_host:
        engine_pull_addr = f"tcp://{args.engine_host}:5555"
        engine_pub_addr = f"tcp://{args.engine_host}:5556"
        index_pull_addr = f"tcp://{args.engine_host}:5559"
        index_pub_addr = f"tcp://{args.engine_host}:5558"
    return ApiGatewayConfig(
        name=config.name,
        enabled=config.enabled,
        host=args.host or config.host,
        port=args.port or config.port,
        engine_pull_addr=engine_pull_addr,
        engine_pub_addr=engine_pub_addr,
        index_pull_addr=index_pull_addr,
        index_pub_addr=index_pub_addr,
        stats_db=Path(args.stats_db).expanduser() if args.stats_db else config.stats_db,
        market_data_cache_sec=config.market_data_cache_sec,
        log_level=args.log_level.lower() if args.log_level else config.log_level,
        swagger_enabled=config.swagger_enabled,
        credentials=config.credentials,
        rate_limit=config.rate_limit,
        timeouts=config.timeouts,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EduMatcher REST API gateway")
    from edumatcher.cli_version import add_version_argument

    add_version_argument(parser, "pm-api-gwy")
    parser.add_argument(
        "--host", default=None, metavar="ADDR", help="HTTP bind address"
    )
    parser.add_argument(
        "--port", default=None, type=int, metavar="PORT", help="HTTP listen port"
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
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
        default=None,
        help="Logging level override (default: WARNING)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase log verbosity (-v: INFO, -vv: DEBUG)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Reduce output to warnings/errors",
    )
    parser.add_argument(
        "--log-target",
        choices=["server", "stdout", "file"],
        default=None,
        help=(
            "Where this process's own operational log records go: "
            "server (default, auto-detected pm-log-srv), stdout, or file"
        ),
    )
    parser.add_argument(
        "--log-file",
        default=None,
        metavar="PATH",
        help="Operational log file path — required when --log-target file",
    )
    parser.add_argument(
        "--log-failover-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Grace window before falling back to a local log file once "
            "pm-log-srv becomes unreachable (default: 30, from config)"
        ),
    )
    return parser


def _configure_logging(args: argparse.Namespace) -> int:
    log_level = getattr(args, "log_level", None)
    verbose = getattr(args, "verbose", 0)
    quiet = getattr(args, "quiet", False)

    if log_level:
        level_name = str(log_level).upper()
        level = getattr(logging, level_name, logging.WARNING)
    elif verbose >= 2:
        level = logging.DEBUG
    elif verbose == 1:
        level = logging.INFO
    elif quiet:
        level = logging.WARNING
    else:
        level = logging.WARNING

    client_config = load_default_log_client_config()
    server_config = load_default_log_server_config()
    failover_timeout = getattr(args, "log_failover_timeout", None)
    handler = resolve_handler(
        log_target=getattr(args, "log_target", None),
        log_file=getattr(args, "log_file", None),
        client_name=_CLIENT_NAME,
        instance=None,
        host=resolve_host_default(),
        port=server_config.port,
        connect_timeout_sec=client_config.connect_timeout_sec,
        failover_timeout_sec=(
            failover_timeout
            if failover_timeout is not None
            else client_config.failover_timeout_sec
        ),
        failover_dir=client_config.failover_dir,
    )
    logging.basicConfig(level=level, format=_LOG_FORMAT, handlers=[handler])
    return int(level)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _configure_logging(args)
    try:
        config = _config_with_overrides(args)
    except Exception as exc:
        log.error("failed to resolve configuration: %s", exc)
        sys.exit(1)
    if not config.enabled:
        log.warning("selected api_gateways entry is disabled")
        sys.exit(1)
    app = create_app(config)
    try:
        uvicorn.run(app, host=config.host, port=config.port, log_level=config.log_level)
    except Exception as exc:
        log.error("fatal runtime error: %s", exc)
        raise


if __name__ == "__main__":
    main()
