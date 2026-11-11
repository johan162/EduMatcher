"""
A small, realistic clearing venue for the ``/api/v1/clearing`` tests.

``clearing.db`` is written by the real ``ClearingProcess``: every trade is a
generated ``TradeExecuted`` message, framed with an envelope the way the
engine publishes it, and fed through the process's own dispatch, so the rows,
the close snapshots, the ``GAP``/``PHASE``/``EOD`` events and the gateway
sessions are what pm-clearing itself records. ``eod.db`` is then settled from
those snapshots with pm-eod's own ``settle_date``/``record_day``.

The venue (all dates UTC, the clearing session timezone):

* ``2026-11-02``: TRADER01 buys 100 then 50 AAPL (2 decimals) from MM01 and
  sells 1000 EURUSD (4 decimals) to it; close.
* ``2026-11-03``: trade ids jump from 3 to 6 (a ``GAP`` of two trades);
  TRADER01 sells 40 AAPL to MM01 and buys 500 EURUSD from it; MM01
  disconnects; close; the engine's ``system.eod``.

So both participants hold long and short positions in both symbols, OPS01
(the ADMIN) has none, and a read-only key has no gateway at all.

Not a test module (no test_ prefix) -- pytest will not collect it.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from edumatcher.api_gateway.config import ApiCredential, ApiGatewayConfig
from edumatcher.api_gateway.main import create_app
from edumatcher.api_gateway.rate_limit import RateLimiter
from edumatcher.api_gateway.sessions import SessionRegistry
from edumatcher.clearing.main import ClearingProcess
from edumatcher.clearing.query import open_readonly_connection
from edumatcher.eod.ledger import last_settled_before, open_ledger, record_day
from edumatcher.eod.ledger import record_run
from edumatcher.eod.settle import Settlement, settle_date
from edumatcher.models.envelope import Envelope
from edumatcher.models.generated.session import TOPIC_SESSION_STATE
from edumatcher.models.generated.system import (
    PREFIX_GATEWAY_BYE,
    TOPIC_EOD,
    TOPIC_GATEWAY_CONNECT,
    topic_gateways,
    topic_symbols,
)
from edumatcher.models.generated.trade import TOPIC_TRADE_EXECUTED, TradeExecuted
from edumatcher.models.message import encode, encode_with_envelope

DAY1 = "2026-11-02"
DAY2 = "2026-11-03"
#: A date pm-eod ran on but could not settle (its gate failed).
DAY3 = "2026-11-04"

ADMIN_KEY = "key-ops"
TRADER_KEY = "key-trader"
MM_KEY = "key-mm"
READ_ONLY_KEY = "key-ro"

ROLES = {"OPS01": "ADMIN", "TRADER01": "TRADER", "MM01": "MARKET_MAKER"}
KEYS = {"ADMIN": ADMIN_KEY, "TRADER": TRADER_KEY, "MARKET_MAKER": MM_KEY}

#: Roster opening balances, minor units.
OPENINGS = {"TRADER01": 1_000_000, "MM01": 5_000_000}


def ns(day: str, hhmm: str) -> int:
    """Epoch nanoseconds of ``day`` at ``hh:mm`` UTC."""
    moment = datetime.fromisoformat(f"{day}T{hhmm}:00+00:00")
    return int(moment.timestamp()) * 1_000_000_000


def _trade(
    seq: int,
    at: int,
    symbol: str,
    buyer: str,
    seller: str,
    qty: int,
    price: float,
    tick_decimals: int,
    match_type: str = "CONTINUOUS",
) -> TradeExecuted:
    trade = TradeExecuted(
        id=f"000007-{seq:09d}",
        run_seq=7,
        symbol=symbol,
        buy_order_id=f"B{seq}",
        sell_order_id=f"S{seq}",
        buy_gateway_id=buyer,
        sell_gateway_id=seller,
        price=price,
        quantity=qty,
        aggressor_side="BUY",
        ts_ns=at,
        tick_decimals=tick_decimals,
        match_type=match_type,  # type: ignore[arg-type]
    )
    trade.validate()
    return trade


#: (trade, audit msg_id) in feed order.
TRADES: list[tuple[TradeExecuted, str]] = [
    (
        _trade(1, ns(DAY1, "10:00"), "AAPL", "TRADER01", "MM01", 100, 187.25, 2),
        "01JC0000000000000000000001",
    ),
    (
        _trade(
            2,
            ns(DAY1, "11:00"),
            "EURUSD",
            "MM01",
            "TRADER01",
            1000,
            1.085,
            4,
        ),
        "01JC0000000000000000000002",
    ),
    (
        _trade(
            3,
            ns(DAY1, "16:30"),
            "AAPL",
            "TRADER01",
            "MM01",
            50,
            187.5,
            2,
            match_type="CLOSING_AUCTION",
        ),
        "01JC0000000000000000000003",
    ),
    (
        _trade(6, ns(DAY2, "10:00"), "AAPL", "MM01", "TRADER01", 40, 188.0, 2),
        "01JC0000000000000000000006",
    ),
    (
        _trade(7, ns(DAY2, "11:00"), "EURUSD", "TRADER01", "MM01", 500, 1.0862, 4),
        "01JC0000000000000000000007",
    ),
]


@dataclass(frozen=True)
class Venue:
    clearing_db: Path
    eod_db: Path
    roster: Path


class _Feed:
    """Feeds frames to a ClearingProcess at a controlled clearing clock."""

    def __init__(self, process: ClearingProcess) -> None:
        self.process = process

    def at(self, moment: int, frames: list[bytes]) -> None:
        with patch("edumatcher.clearing.main.now_ns", return_value=moment):
            self.process._handle_message(frames)

    def trade(self, trade: TradeExecuted, msg_id: str) -> None:
        frames = encode_with_envelope(
            TOPIC_TRADE_EXECUTED, trade.to_dict(), Envelope(msg_id=msg_id)
        )
        # The ingest clock: one second after the exchange stamped the print.
        with patch("edumatcher.clearing.main.now_ns", return_value=trade.ts_ns + 10**9):
            self.process._handle_message(frames)
            self.process.flush_now()

    def phase(self, moment: int, state: str, prev: str) -> None:
        self.at(
            moment, encode(TOPIC_SESSION_STATE, {"state": state, "prev_state": prev})
        )


def build_clearing_db(path: Path) -> None:
    """Record the venue into ``clearing.db`` through pm-clearing's own code."""
    process = ClearingProcess(
        pub_addr="inproc://unused",
        db_path=path,
        print_every=0,
        # Fixed dates: never prune them, whenever the suite runs.
        retention_days=0,
        session_tz=timezone.utc,
    )
    feed = _Feed(process)
    try:
        for gateway in ("OPS01", "TRADER01", "MM01"):
            feed.at(
                ns(DAY1, "08:00"),
                encode(TOPIC_GATEWAY_CONNECT, {"gateway_id": gateway}),
            )
        feed.phase(ns(DAY1, "09:00"), "CONTINUOUS", "PRE_OPEN")
        for trade, msg_id in TRADES[:3]:
            feed.trade(trade, msg_id)
        feed.phase(ns(DAY1, "17:00"), "CLOSED", "CONTINUOUS")

        feed.phase(ns(DAY2, "09:00"), "CONTINUOUS", "CLOSED")
        for trade, msg_id in TRADES[3:]:
            feed.trade(trade, msg_id)
        feed.at(
            ns(DAY2, "12:00"),
            encode(
                f"{PREFIX_GATEWAY_BYE}MM01", {"gateway_id": "MM01", "reason": "logout"}
            ),
        )
        feed.phase(ns(DAY2, "17:00"), "CLOSED", "CONTINUOUS")
        feed.at(ns(DAY2, "18:00"), encode(TOPIC_EOD, {"books": []}))
    finally:
        process._conn.close()


def build_eod_db(clearing_db: Path, path: Path) -> None:
    """Settle both closed dates with pm-eod's own arithmetic and ledger.

    Real snapshots cancel exactly, so the ``EXCHANGE`` rounding line pm-eod
    writes for float noise is added to the second day by hand: one minor unit
    taken from TRADER01, the shape such a residual has.
    """
    with closing(open_readonly_connection(clearing_db)) as clearing:
        ledger = open_ledger(path)
        try:
            day1 = settle_date(clearing, DAY1, None)
            record_day(ledger, DAY1, day1)
            record_run(ledger, DAY1, "ok", f"{DAY1}T18:05:00Z", f"{DAY1}T18:05:02Z", [])

            day2 = settle_date(clearing, DAY2, last_settled_before(ledger, DAY2))
            amounts = dict(day2.amounts_minor)
            amounts["TRADER01"] -= 1
            record_day(ledger, DAY2, Settlement(amounts, 1, day2.detail))
            record_run(
                ledger,
                DAY2,
                "report-failed",
                f"{DAY2}T18:05:00Z",
                f"{DAY2}T18:05:03Z",
                [{"step": "report", "status": "fail", "message": "disk full"}],
            )
            record_run(
                ledger,
                DAY3,
                "failed",
                f"{DAY3}T18:05:00Z",
                f"{DAY3}T18:05:01Z",
                [{"step": "gate", "status": "fail", "message": "not closed"}],
            )
        finally:
            ledger.close()


def write_roster(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "traders:\n"
        "  - gateway: TRADER01\n"
        "    name: Alice Andersson\n"
        "    opening_balance: 10000.00\n"
        "  - gateway: MM01\n"
        "    name: Market Maker One\n"
        "    opening_balance: 50000\n",
        encoding="utf-8",
    )


def build_venue(data_dir: Path) -> Venue:
    """Both databases and the roster, laid out the way pm-eod lays them out."""
    venue = Venue(
        clearing_db=data_dir / "clearing.db",
        eod_db=data_dir / "eod.db",
        roster=data_dir / "ref_data" / "roster.yaml",
    )
    build_clearing_db(venue.clearing_db)
    build_eod_db(venue.clearing_db, venue.eod_db)
    write_roster(venue.roster)
    return venue


#: What the engine resolves per requester on GET /api/v1/symbols: MM01
#: carries an obligation on EURUSD only, TRADER01 none.
SYMBOLS: dict[str, list[dict[str, Any]]] = {
    "MM01": [
        {"symbol": "AAPL", "tick_decimals": 2, "enforce_mm_obligation": False},
        {
            "symbol": "EURUSD",
            "tick_decimals": 4,
            "enforce_mm_obligation": True,
            "mm_max_spread_ticks": 5,
            "mm_min_qty": 1000,
        },
    ],
}


class FakeEngine:
    """The engine calls the clearing GUI's routes make: auth, role lookup,
    the ADMIN gateway roster (``/status``) and the per-requester symbol
    settings (``/symbols``)."""

    def __init__(self, roles: dict[str, str] | None = None) -> None:
        self.roles = dict(ROLES if roles is None else roles)

    async def authenticate(
        self, gateway_id: str, timeout: float = 3.0
    ) -> tuple[bool, str]:
        return True, ""

    async def resolve_role(self, gateway_id: str, timeout: float) -> str:
        return self.roles.get(gateway_id, "TRADER")

    def request_gateways(self, gateway_id: str) -> None:
        pass

    def request_symbols(self, gateway_id: str) -> None:
        pass

    async def await_topic(self, topic: str, timeout: float) -> dict[str, Any]:
        for gateway in self.roles:
            if topic == topic_gateways(gateway):
                return {
                    "gateways": [
                        {"id": gw, "role": role, "connected": True}
                        for gw, role in self.roles.items()
                    ]
                }
            if topic == topic_symbols(gateway):
                plain = [
                    {"symbol": "AAPL", "tick_decimals": 2},
                    {"symbol": "EURUSD", "tick_decimals": 4},
                ]
                return {"symbols": SYMBOLS.get(gateway, plain)}
        raise TimeoutError(f"no fake reply for {topic}")


#: A health address nothing listens on: the probe gets no reply.
SILENT_HEALTH_ADDR = "tcp://127.0.0.1:1"


def make_clearing_app(venue: Venue, **config: Any) -> Any:
    """The real app wired to *venue*, with every role's key configured."""
    settings: dict[str, Any] = {
        "swagger_enabled": False,
        "clearing_db": venue.clearing_db,
        "eod_db": venue.eod_db,
        **config,
    }
    cfg = ApiGatewayConfig(**settings)
    app = create_app(cfg)
    app.state.config = cfg
    app.state.engine = FakeEngine()
    app.state.rate_limiter = RateLimiter(100, 100)
    app.state.sessions = SessionRegistry(
        (
            ApiCredential(ADMIN_KEY, "OPS01", "ops"),
            ApiCredential(TRADER_KEY, "TRADER01", "trader"),
            ApiCredential(MM_KEY, "MM01", "mm"),
            ApiCredential(READ_ONLY_KEY, None, "read-only"),
        )
    )
    return app


def rows(db: Path, sql: str, *params: Any) -> list[dict[str, Any]]:
    """Read *db* directly, to compare an API answer with what is stored."""
    with closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params)]
