"""Measure the /api/v1/clearing routes on a realistic retained-trade ledger.

Clearing GUI workplan CG9 step 4 (and finding F2): builds a synthetic
``clearing.db`` -- by default 90 trading days x 2 000 trades, 40 gateways, 20
symbols -- through pm-clearing's own store helpers (``apply_schema``,
``flush_batch``), with daily rows and positions derived from the generated
trades so reconciliation finds nothing. Then it calls every route through the
real gateway app (``create_app``, in process, no network) as an ADMIN and as
a participant, and prints per route the p50/p95 latency, the response size
and, for the trade and reconciliation queries, SQLite's query plan.

    poetry run python tools/clearing_api_bench.py [--days 90] [--per-day 2000]

Nothing here is a pass/fail test; the numbers go into the workplan.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from edumatcher.api_gateway.config import ApiCredential, ApiGatewayConfig
from edumatcher.api_gateway.main import create_app
from edumatcher.api_gateway.rate_limit import RateLimiter
from edumatcher.api_gateway.routers import clearing as clearing_router
from edumatcher.api_gateway.sessions import SessionRegistry
from edumatcher.clearing.query import open_readonly_connection
from edumatcher.clearing.store import (
    DailySummaryRow,
    PositionRow,
    TradeEventRow,
    flush_batch,
    open_writer_connection,
)
from edumatcher.eod.ledger import open_ledger

ADMIN, PARTICIPANT = "bench-admin", "bench-participant"
NS_PER_DAY = 86_400 * 10**9
#: 2026-01-01T00:00:00Z
EPOCH_NS = 1_767_225_600 * 10**9


class _Engine:
    """Answers the only engine calls clearing routes make."""

    async def authenticate(
        self, gateway_id: str, timeout: float = 3.0
    ) -> tuple[bool, str]:
        return True, ""

    async def resolve_role(self, gateway_id: str, timeout: float) -> str:
        return "ADMIN" if gateway_id == "OPS01" else "TRADER"


def build(path: Path, days: int, per_day: int, gateways: int, symbols: int) -> str:
    """Write the ledger; return the first trading day."""
    rng = random.Random(7)
    gws = [f"GW{i:03d}" for i in range(gateways)]
    syms = [f"SYM{i:02d}" for i in range(symbols)]
    conn = open_writer_connection(path)
    daily: dict[tuple[str, str, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    pos: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0])
    seq = 0
    first_day = ""
    for day in range(days):
        start = EPOCH_NS + day * NS_PER_DAY + 9 * 3600 * 10**9
        trade_date = time.strftime("%Y-%m-%d", time.gmtime((start // 10**9)))
        first_day = first_day or trade_date
        trades = []
        for n in range(per_day):
            seq += 1
            buyer, seller = rng.sample(gws, 2)
            sym = rng.choice(syms)
            qty = rng.randint(1, 500)
            price = rng.randint(1_000, 50_000)
            ts = start + n * (8 * 3600 * 10**9 // per_day)
            trades.append(
                TradeEventRow(
                    id=f"000001-{seq:09d}",
                    ts_ns=ts,
                    trade_date=trade_date,
                    symbol=sym,
                    quantity=qty,
                    price=price,
                    buy_order_id=f"B{seq}",
                    sell_order_id=f"S{seq}",
                    buy_gateway_id=buyer,
                    sell_gateway_id=seller,
                    aggressor_side="BUY",
                    ingest_ts_ns=ts + 10**9,
                    match_type="CONTINUOUS",
                    msg_id=f"MSG{seq}",
                )
            )
            for gw, side in ((buyer, 0), (seller, 1)):
                d = daily[(trade_date, gw, sym)]
                d[side] += qty
                d[2 + side] += qty * price
                p = pos[(gw, sym)]
                p[side] += qty
                p[2 + side] += qty * price
                p[4] = ts
        rows = [
            DailySummaryRow(
                trade_date=k[0],
                gateway_id=k[1],
                symbol=k[2],
                delta_traded_qty=v[0] + v[1],
                delta_traded_notional=v[2] + v[3],
                delta_buy_qty=v[0],
                delta_sell_qty=v[1],
                delta_buy_notional=v[2],
                delta_sell_notional=v[3],
                delta_net_amount=v[2] - v[3],
                delta_realized_pnl=0.0,
                end_net_qty=0,
                end_avg_cost=0.0,
                end_unrealized_pnl=0.0,
                last_trade_ts_ns=start,
                updated_ts_ns=start,
            )
            for k, v in daily.items()
            if k[0] == trade_date
        ]
        flush_batch(conn, trades, [], rows)
    positions = [
        PositionRow(
            gateway_id=gw,
            symbol=sym,
            net_qty=p[0] - p[1],
            avg_cost=20_000.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            mark_price=20_000,
            buy_qty=p[0],
            sell_qty=p[1],
            buy_notional=p[2],
            sell_notional=p[3],
            last_trade_ts_ns=p[4],
            updated_ts_ns=p[4],
        )
        for (gw, sym), p in pos.items()
    ]
    flush_batch(conn, [], positions, [])
    conn.close()
    return first_day


def app_for(clearing_db: Path, eod_db: Path) -> Any:
    config = ApiGatewayConfig(
        swagger_enabled=False, clearing_db=clearing_db, eod_db=eod_db
    )
    app = create_app(config)
    app.state.config = config
    app.state.engine = _Engine()
    app.state.rate_limiter = RateLimiter(1000, 1000)
    app.state.sessions = SessionRegistry(
        (
            ApiCredential(ADMIN, "OPS01", "admin"),
            ApiCredential(PARTICIPANT, "GW001", "participant"),
        )
    )
    return app


async def call(app: Any, path: str, key: str) -> tuple[int, int]:
    """One GET through the ASGI app: (status, body bytes)."""
    route, _, query = path.partition("?")
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": route,
            "raw_path": route.encode(),
            "query_string": query.encode(),
            "root_path": "",
            "headers": [(b"authorization", f"Bearer {key}".encode())],
            "server": ("bench", 80),
            "client": ("bench", 1),
        },
        receive,
        send,
    )
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    return int(start["status"]), len(body)


async def measure(app: Any, path: str, key: str, runs: int) -> dict[str, Any]:
    times = []
    status = size = 0
    for _ in range(runs):
        t0 = time.perf_counter()
        status, size = await call(app, path, key)
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    return {
        "status": status,
        "bytes": size,
        "p50_ms": round(statistics.median(times), 1),
        "p95_ms": round(times[max(0, int(len(times) * 0.95) - 1)], 1),
    }


def plans(db: Path) -> dict[str, list[str]]:
    from edumatcher.clearing import store

    conn = open_readonly_connection(db)
    out: dict[str, list[str]] = {}
    probes: dict[str, dict[str, Any]] = {
        "trades (venue, newest page)": {"limit": 500},
        "trades (one gateway)": {"gateway": "GW001", "limit": 500},
        "trades (one day)": {"date_value": "2026-02-15", "limit": 500},
    }
    for name, kwargs in probes.items():
        captured: list[str] = []
        conn.set_trace_callback(captured.append)
        store.query_trades(conn, **kwargs)
        conn.set_trace_callback(None)
        sql = captured[-1]
        out[name] = [r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + sql)]
    conn.close()
    return out


async def main_async(args: argparse.Namespace) -> None:
    clearing_router._HEALTH_ADDR = "tcp://127.0.0.1:1"
    clearing_router._HEALTH_TIMEOUT_MS = 50
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "clearing.db"
        eod = Path(tmp) / "eod.db"
        t0 = time.perf_counter()
        first = build(db, args.days, args.per_day, args.gateways, args.symbols)
        open_ledger(eod).close()
        print(
            f"ledger: {args.days * args.per_day} trades, {db.stat().st_size // 2**20} MiB,"
            f" built in {time.perf_counter() - t0:.0f}s"
        )
        app = app_for(db, eod)
        to = time.strftime(
            "%Y-%m-%d", time.gmtime((EPOCH_NS + (args.days - 1) * NS_PER_DAY) // 10**9)
        )
        week = time.strftime(
            "%Y-%m-%d", time.gmtime((EPOCH_NS + (args.days - 7) * NS_PER_DAY) // 10**9)
        )
        routes = [
            ("polled", "/api/v1/clearing/summary", ADMIN),
            ("polled", "/api/v1/clearing/participants", ADMIN),
            ("polled", "/api/v1/clearing/positions", ADMIN),
            ("polled", "/api/v1/clearing/positions", PARTICIPANT),
            ("polled", "/api/v1/clearing/exposure", PARTICIPANT),
            ("30 s", "/api/v1/clearing/health", ADMIN),
            ("on demand", "/api/v1/clearing/trades?limit=200", ADMIN),
            ("on demand", "/api/v1/clearing/trades?limit=200", PARTICIPANT),
            ("on demand", f"/api/v1/clearing/trades?limit=200&date={to}", ADMIN),
            ("on demand", "/api/v1/clearing/daily", PARTICIPANT),
            ("on demand", "/api/v1/clearing/close-snapshots", PARTICIPANT),
            ("on demand", "/api/v1/clearing/symbols", ADMIN),
            ("on demand", "/api/v1/clearing/session-events", ADMIN),
            ("explicit", f"/api/v1/clearing/reconciliation?from={week}&to={to}", ADMIN),
            (
                "explicit",
                f"/api/v1/clearing/reconciliation?from={first}&to={to}",
                ADMIN,
            ),
        ]
        print(
            f"{'cadence':<10} {'route':<72} {'who':<11} {'p50':>8} {'p95':>8} {'bytes':>9}"
        )
        for cadence, path, key in routes:
            runs = 3 if cadence == "explicit" else args.runs
            r = await measure(app, path, key, runs)
            who = "admin" if key == ADMIN else "participant"
            print(
                f"{cadence:<10} {path:<72} {who:<11} {r['p50_ms']:>6}ms {r['p95_ms']:>6}ms"
                f" {r['bytes']:>9}"
                + ("" if r["status"] == 200 else f"  HTTP {r['status']}")
            )
        print(json.dumps(plans(db), indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--per-day", type=int, default=2000)
    parser.add_argument("--gateways", type=int, default=40)
    parser.add_argument("--symbols", type=int, default=20)
    parser.add_argument("--runs", type=int, default=20)
    asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    main()
