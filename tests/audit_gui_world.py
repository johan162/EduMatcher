"""The "audit world": one recorded trading session for the Audit GUI tests.

``build`` drives a real in-process Engine through a short but complete
session and records everything it publishes the way pm-audit would: the
engine's own publisher stack (``CausalPublisher`` over ``SequencedPublisher``)
stamps the envelope and the ``seq``/``eseq`` counters, pm-audit's
``_meta_section`` renders them, and ``AuditFile`` writes the day file. The
commands go in as a gateway sends them (a root envelope from ``CausalPusher``)
and come out through ``Engine._echo_command``, as in ``Engine.run``.

The tables below say what the session must contain. They are written from
the exchange contract (price-time priority, the session state machine, stop
triggering, SMP, IOC, iceberg slices), not from what the engine printed; the
comment by each number says how it follows. Every later Audit GUI work
package reads this world and these tables rather than writing its own data
(workplan section 3).

Not a test module (no test_ prefix): pytest does not collect it.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, NamedTuple
from unittest import mock
from zoneinfo import ZoneInfo

import edumatcher.engine.main as engine_main
import edumatcher.models.clock as models_clock
from edumatcher.api_gateway.config import ApiCredential, ApiGatewayConfig
from edumatcher.api_gateway.main import create_app
from edumatcher.api_gateway.rate_limit import RateLimiter
from edumatcher.api_gateway.sessions import SessionRegistry
from edumatcher.audit.archive import archive_day, archive_lock
from edumatcher.audit.main import _meta_section
from edumatcher.audit.service.session import AuditService
from edumatcher.audit.service.snapshot import AuditCollection
from edumatcher.audit.writer import AuditFile
from edumatcher.cli_version import package_version
from edumatcher.config_deploy import deploy
from edumatcher.market_sim.news_history import append_news_event, append_value_jumps
from edumatcher.messaging.bus import CausalPublisher, SequencedPublisher
from edumatcher.models.envelope import envelope_frame, new_ulid
from edumatcher.models.generated.news import NewsEvent
from edumatcher.models.generated.order import OrderAmend, OrderCancel, OrderNew
from edumatcher.models.generated.quote import QuoteNew
from edumatcher.models.generated.risk import SymbolHalt, SymbolResume
from edumatcher.models.generated.session import SessionTransition
from edumatcher.models.generated.system import GatewayConnect
from edumatcher.models.message import decode, decode_push_envelope, encode
from edumatcher.models.order import Order, OrderType, Side, TIF
from edumatcher.models.trade import reset_trade_ids_for_tests, set_run_seq
from edumatcher.sim_forensics import checks as _checks  # noqa: F401  (registers them)
from edumatcher.sim_forensics.dataset import Dataset
from edumatcher.sim_forensics.registry import REGISTRY, Result
from edumatcher.sim_forensics.report import write as write_forensics_report

#: Session timezone of the world's configuration.
TZ = ZoneInfo("Europe/Stockholm")
#: The trading day recorded (a Monday; CEST, so 09:00 local is 07:00Z).
DAY = "2026-06-15"
SEC = 1_000_000_000
MS = 1_000_000
#: Engine clock at the first published message (system.startup).
START_NS = int(datetime(2026, 6, 15, 7, 0, tzinfo=timezone.utc).timestamp()) * SEC
#: pm-audit stamps a line this long after the engine published it.
RECEIPT_LATENCY_NS = 1 * MS
#: The simulator's clock runs this far ahead of the engine's (variant
#: ``sim_context``): a news event stamped ``t`` happened at engine time
#: ``t - SIM_CLOCK_OFFSET_NS``.
SIM_CLOCK_OFFSET_NS = 250 * MS

#: Every variant ``build`` accepts.
VARIANTS = frozenset(
    {
        "gap",
        "restart",
        "run_reset",
        "no_config",
        "zstd_archive",
        "torn_tail",
        "sim_context",
        "forensics_report",
    }
)

#: Symbol -> tick_decimals. Two scales, so no reader can get away with one.
TICK_DECIMALS = {"AAA": 2, "BBB": 4}

#: Trading gateways. OPS01 is the instructor console: it halts and resumes,
#: and never trades.
MM, T1, T2, T3, OPS = "MM01", "TRADER01", "TRADER02", "TRADER03", "OPS01"
TRADING_GATEWAYS = (MM, T1, T2, T3)


class Execution(NamedTuple):
    """One venue execution: who sold to whom, how much, at what tick price."""

    symbol: str
    seller: str
    buyer: str
    qty: int
    price_ticks: int


#: Run 1's venue executions, one per ``trade.executed`` (fills and drop
#: copies are never extra executions). Both books start empty
#: (``require_mm_seed_quotes: false``, no seed quotes), so only the orders
#: below can trade.
EXECUTIONS: tuple[Execution, ...] = (
    # Opening auction, AAA: TRADER01 bids 100 @ 100.00; TRADER02 offers 60 and
    # TRADER03 40, both @ 100.00. Every order is at one price, so the uncross
    # is 100.00 x 100; the sells fill in time priority (TRADER02 first).
    Execution("AAA", T2, T1, 60, 10000),
    Execution("AAA", T3, T1, 40, 10000),
    # Opening auction, BBB: TRADER01 bids 1000 @ 2.5000, TRADER03 offers 1000
    # @ 2.5000: one uncross print.
    Execution("BBB", T3, T1, 1000, 25000),
    # Layering-like sequence: TRADER02 buys 50 @ 100.10 from MM01's ask
    # (MM01's quote after the replacement burst is 99.90 / 100.10 x 200).
    Execution("AAA", MM, T2, 50, 10010),
    # Stop cascade. TRADER02 sells 200 @ 99.90 into MM01's bid 99.90 x 200:
    Execution("AAA", T2, MM, 200, 9990),
    # ... the last price 99.90 <= TRADER03's sell stop (99.90): its market
    # sell of 20 takes the best bid, TRADER01's 99.85 x 100 ...
    Execution("AAA", T3, T1, 20, 9985),
    # ... the last price 99.85 <= TRADER02's sell stop (99.85): its market
    # sell of 30 takes 30 more of TRADER01's 99.85 bid (50 left).
    Execution("AAA", T2, T1, 30, 9985),
    # Iceberg and IOC probes, BBB: TRADER03 offers 3000 @ 2.5100 showing
    # 1000. TRADER02's IOC buys of 1000, 1000 and 1500 @ 2.5100 each take one
    # 1000 slice (the third leaves 500 unfilled).
    Execution("BBB", T3, T2, 1000, 25100),
    Execution("BBB", T3, T2, 1000, 25100),
    Execution("BBB", T3, T2, 1000, 25100),
    # Three-gateway cycle, BBB, 500 @ 2.5200: each buyer rests first, then
    # the seller crosses it. TRADER01 -> TRADER02 -> TRADER03 -> TRADER01.
    Execution("BBB", T1, T2, 500, 25200),
    Execution("BBB", T2, T3, 500, 25200),
    Execution("BBB", T3, T1, 500, 25200),
    # Paired round trip, BBB, 200 @ 2.5300: TRADER01 sells to TRADER03, then
    # buys the same 200 back.
    Execution("BBB", T1, T3, 200, 25300),
    Execution("BBB", T3, T1, 200, 25300),
    # Closing auction, AAA: MM01's requoted ask is 100.10 x 100; TRADER03
    # bids 10 and TRADER02 20 @ 100.10. Uncross 100.10 x 30, the buys in time
    # priority (TRADER03 first).
    Execution("AAA", MM, T3, 10, 10010),
    Execution("AAA", MM, T2, 20, 10010),
)

#: Trade ids are ``<run_seq:06d>-<counter:09d>``; run 1 makes one per row.
TRADE_IDS = frozenset(f"000001-{n:09d}" for n in range(1, len(EXECUTIONS) + 1))

#: Seller -> buyer totals per symbol: (symbol, seller, buyer) -> (qty, trades).
#: Added up by hand from the rows above, not from them by code.
FLOWS: dict[tuple[str, str, str], tuple[int, int]] = {
    ("AAA", T2, T1): (90, 2),  # 60 in the opening auction + 30 from stop 2
    ("AAA", T3, T1): (60, 2),  # 40 in the opening auction + 20 from stop 1
    ("AAA", MM, T2): (70, 2),  # 50 layering buy + 20 in the closing auction
    ("AAA", T2, MM): (200, 1),  # the sell that set off the stops
    ("AAA", MM, T3): (10, 1),  # closing auction
    ("BBB", T3, T1): (1700, 3),  # 1000 opening + 500 cycle + 200 round trip
    ("BBB", T3, T2): (3000, 3),  # the three iceberg slices
    ("BBB", T1, T2): (500, 1),  # cycle
    ("BBB", T2, T3): (500, 1),  # cycle
    ("BBB", T1, T3): (200, 1),  # round trip
}

#: Owner cancellations (an ``order.cancel`` from the order's own gateway
#: that the engine carried out), per gateway: TRADER01 its amended bid,
#: TRADER02 pulls its three layering offers, TRADER03 its four-bid cancel
#: burst.
OWNER_CANCELS = {T1: 1, T2: 3, T3: 4}

#: System cancellations by ``cancel_reason``.
SYSTEM_CANCELS = {
    # Three replacements of MM01's two-sided quote, two legs each.
    "QUOTE_REPLACED": 6,
    # The operator halt of AAA cancels MM01's live quote legs: the ask (150
    # left); the bid was filled by the stop cascade's first sell.
    "CIRCUIT_BREAKER_HALT": 1,
    # TRADER01's sell would trade with its own 99.85 bid; its configured SMP
    # action is CANCEL_AGGRESSOR.
    "SELF_MATCH_PREVENTED": 1,
    # The third IOC probe's unfilled 500.
    "INSUFFICIENT_LIQUIDITY": 1,
}

#: DAY orders still resting at the close expire there: MM01's requoted bid
#: (99.80 x 100), its ask (100 - 30 = 70 left), TRADER01's 99.85 bid (50 left).
EXPIRED_AT_CLOSE = 3

#: Iceberg slices refilled: after the first and the second probe (the third
#: probe takes the last slice, which leaves nothing to refill).
ICEBERG_REFILLS = 2

#: ``amend_bid``'s life on the book, one (price ticks, displayed qty) per
#: segment: TRADER01 bids 100 @ 2.4000 on BBB, amends the price to 2.4500,
#: then the size to 60, then cancels. BBB never trades below 2.5000, so
#: nothing touches it.
AMENDMENTS = {"amend_bid": ((24000, 100), (24500, 100), (24500, 60))}

#: MM01's quote after the replacement burst, as AAA's best bid/ask in ticks.
QUOTE_AFTER_BURST = (9990, 10010)  # a quoted spread of 20 ticks = 0.20


class Life(NamedTuple):
    """How one named order begins and ends.

    ``end`` is ``filled``, ``cancel.owner``, ``cancel.system:<reason>``,
    ``expired`` or ``open`` (still resting when the trail ends).
    """

    gateway: str
    symbol: str
    side: str
    qty: int
    filled: int
    end: str


#: The named orders' lifecycles (``World.orders`` gives each one's id).
LIVES: dict[str, Life] = {
    "open_buy": Life(T1, "AAA", "BUY", 100, 100, "filled"),
    "open_sell_1": Life(T2, "AAA", "SELL", 60, 60, "filled"),
    "open_sell_2": Life(T3, "AAA", "SELL", 40, 40, "filled"),
    "bbb_open_buy": Life(T1, "BBB", "BUY", 1000, 1000, "filled"),
    "bbb_open_sell": Life(T3, "BBB", "SELL", 1000, 1000, "filled"),
    "layer_1": Life(T2, "AAA", "SELL", 500, 0, "cancel.owner"),
    "layer_2": Life(T2, "AAA", "SELL", 500, 0, "cancel.owner"),
    "layer_3": Life(T2, "AAA", "SELL", 500, 0, "cancel.owner"),
    "layer_buy": Life(T2, "AAA", "BUY", 50, 50, "filled"),
    "burst_1": Life(T3, "AAA", "BUY", 10, 0, "cancel.owner"),
    "burst_2": Life(T3, "AAA", "BUY", 10, 0, "cancel.owner"),
    "burst_3": Life(T3, "AAA", "BUY", 10, 0, "cancel.owner"),
    "burst_4": Life(T3, "AAA", "BUY", 10, 0, "cancel.owner"),
    "gtc_bid": Life(T1, "AAA", "BUY", 10, 0, "open"),
    "stop_bid": Life(T1, "AAA", "BUY", 100, 50, "expired"),
    "stop_1": Life(T3, "AAA", "SELL", 20, 20, "filled"),
    "stop_2": Life(T2, "AAA", "SELL", 30, 30, "filled"),
    "stop_push": Life(T2, "AAA", "SELL", 200, 200, "filled"),
    "smp_sell": Life(T1, "AAA", "SELL", 10, 0, "cancel.system:SELF_MATCH_PREVENTED"),
    "iceberg": Life(T3, "BBB", "SELL", 3000, 3000, "filled"),
    "ioc_1": Life(T2, "BBB", "BUY", 1000, 1000, "filled"),
    "ioc_2": Life(T2, "BBB", "BUY", 1000, 1000, "filled"),
    "ioc_3": Life(T2, "BBB", "BUY", 1500, 1000, "cancel.system:INSUFFICIENT_LIQUIDITY"),  # fmt: skip
    "cycle_buy_1": Life(T2, "BBB", "BUY", 500, 500, "filled"),
    "cycle_sell_1": Life(T1, "BBB", "SELL", 500, 500, "filled"),
    "cycle_buy_2": Life(T3, "BBB", "BUY", 500, 500, "filled"),
    "cycle_sell_2": Life(T2, "BBB", "SELL", 500, 500, "filled"),
    "cycle_buy_3": Life(T1, "BBB", "BUY", 500, 500, "filled"),
    "cycle_sell_3": Life(T3, "BBB", "SELL", 500, 500, "filled"),
    "amend_bid": Life(T1, "BBB", "BUY", 100, 0, "cancel.owner"),
    "pair_buy_1": Life(T3, "BBB", "BUY", 200, 200, "filled"),
    "pair_sell_1": Life(T1, "BBB", "SELL", 200, 200, "filled"),
    "pair_buy_2": Life(T1, "BBB", "BUY", 200, 200, "filled"),
    "pair_sell_2": Life(T3, "BBB", "SELL", 200, 200, "filled"),
    "close_buy_1": Life(T3, "AAA", "BUY", 10, 10, "filled"),
    "close_buy_2": Life(T2, "AAA", "BUY", 20, 20, "filled"),
}

#: The session phases in the order the engine enters them (run 1).
PHASES = ("PRE_OPEN", "OPENING_AUCTION", "CONTINUOUS", "CLOSING_AUCTION", "CLOSED")

#: Variant ``run_reset``: run 2 starts from run 1's persisted book (only the
#: GTC bid survives the close), opens without an auction, and TRADER02 sells
#: 10 @ 99.00 into that bid under an order id it already used in run 1
#: (``layer_1``'s). One execution, numbered from 1 again in run 2.
RUN_2_EXECUTIONS = (Execution("AAA", T2, T1, 10, 9900),)
RUN_2_TRADE_IDS = frozenset({"000002-000000001"})

#: Variant ``forensics_report``: the statuses in the imported report.
FORENSICS_STATUSES = {"E1": "PASS", "E2": "FAIL", "C1": "SKIPPED", "E4": "ERROR"}


@dataclass(frozen=True)
class World:
    """A built world. ``data`` is the evidence collection directory (D1)."""

    data: Path
    variants: frozenset[str]
    #: Name (a ``LIVES`` key) -> the order id the gateway sent.
    orders: dict[str, str]
    #: Scenario step -> engine time (ns) it began at. The ``news_*`` marks are
    #: when the simulator published, read on the engine's clock.
    marks: dict[str, int]
    #: Variant ``gap``: the first and last ``eseq`` removed from the trail.
    gap_eseq: tuple[int, int] | None = None
    #: Variant ``sim_context``: ``market_sim_news.db``.
    news_db: Path | None = None
    #: Variant ``forensics_report``: pm-sim-forensics' ``findings.json``.
    forensics_report: Path | None = None

    @property
    def audit_log(self) -> Path:
        return self.data / "audit.log"

    @property
    def parts_dir(self) -> Path:
        return self.data / "audit"


def order_id(name: str) -> str:
    """The fixed 32-hex order id the world's gateway uses for *name*."""
    return hashlib.md5(name.encode()).hexdigest()


#: The world's engine configuration. Empty books (no seed quotes), sessions
#: on (the scheduler's transitions are sent as commands), no collars or
#: breakers (the halt is the instructor's), and every trader's SMP action is
#: CANCEL_AGGRESSOR. MM01 never inactivates a quote on a fill, so a fill of
#: one leg leaves the other resting.
CONFIG_YAML = f"""\
sessions_enabled: true
locale:
  session_timezone: {TZ.key}
enforce_collars: false
enforce_circuit_breakers: false
require_mm_seed_quotes: false
participants:
- id: {MM}
  role: MARKET_MAKER
  disconnect_behaviour: CANCEL_QUOTES_ONLY
  quote_refresh_policy: NEVER_INACTIVATE
  smp_action: CANCEL_AGGRESSOR
- id: {T1}
  role: TRADER
  disconnect_behaviour: CANCEL_ALL
  smp_action: CANCEL_AGGRESSOR
- id: {T2}
  role: TRADER
  disconnect_behaviour: CANCEL_ALL
  smp_action: CANCEL_AGGRESSOR
- id: {T3}
  role: TRADER
  disconnect_behaviour: CANCEL_ALL
  smp_action: CANCEL_AGGRESSOR
- id: {OPS}
  role: ADMIN
  disconnect_behaviour: LEAVE_ALL
symbols:
  AAA:
    tick_decimals: 2
    last_buy_price: 100.0
    last_sell_price: 100.0
  BBB:
    tick_decimals: 4
    last_buy_price: 2.5
    last_sell_price: 2.5
"""


class _Clock:
    """Stands in for ``time`` in :mod:`edumatcher.models.clock`: the engine's
    clock, moved on by the script one step per command."""

    def __init__(self) -> None:
        self.ns = START_NS

    def time_ns(self) -> int:
        return self.ns


class _Recorder:
    """pm-audit at the far end of the engine's PUB socket: every message the
    publisher stack sends becomes one audit line, stamped on receipt."""

    def __init__(self, path: Path, clock: _Clock) -> None:
        self.path = path
        self.clock = clock
        self.file = AuditFile(path, 10 * 1024 * 1024, TZ)

    def send_multipart(self, frames: list[bytes]) -> None:
        # As pm-audit's AuditProcess._receive_one_message.
        topic, payload = decode(frames)
        ns = self.clock.ns + RECEIPT_LATENCY_NS
        now = datetime.fromtimestamp(ns // SEC, timezone.utc) + timedelta(
            microseconds=ns % SEC // 1000
        )
        ts = now.isoformat(timespec="milliseconds")
        meta = _meta_section(frames)
        line = f"[{ts}] [{topic}] [{meta}] {json.dumps(payload)}"
        self.file.write(now.astimezone(TZ).date().isoformat(), [line])

    def restart(self) -> None:
        """pm-audit stops and starts again: its next line is preceded by a
        recorder-start marker."""
        self.file.close()
        self.file = AuditFile(self.path, 10 * 1024 * 1024, TZ, announce_start=True)

    def close(self, linger: int | None = None) -> None:
        """The engine closing its PUB socket at shutdown; pm-audit runs on."""

    def finish(self) -> None:
        self.file.close()


class _Session:
    """One engine run, driven command by command as ``Engine.run`` does."""

    def __init__(
        self,
        data: Path,
        recorder: _Recorder,
        clock: _Clock,
        make_engine: Callable[[CausalPublisher], engine_main.Engine],
        run: int,
    ) -> None:
        self.clock = clock
        self.pub = CausalPublisher(SequencedPublisher(recorder))
        reset_trade_ids_for_tests()
        set_run_seq(run)
        with self._files(data):
            self.engine = make_engine(self.pub)
            # Every maintenance pass publishes what is due, so each command's
            # book and indicative observations follow it.
            self.engine.snapshot_interval_sec = 0.0
            self.engine.auction_indicative_interval_sec = 0.0
            self.engine._startup(run)
        self.data = data

    @staticmethod
    def _files(data: Path) -> Any:
        return mock.patch.multiple(
            engine_main,
            DATA_DIR=data,
            GTC_ORDERS_FILE=data / "gtc_orders.json",
            GTC_COMBOS_FILE=data / "gtc_combos.json",
            BOOK_STATS_FILE=data / "book_stats.json",
        )

    def send(self, topic: str, payload: dict[str, Any]) -> None:
        """A gateway's command: a root envelope (``CausalPusher``), echoed
        into the trail, dispatched with its cause set, then a maintenance
        pass; one second of engine time later the next command comes."""
        msg = new_ulid()
        frames = [*encode(topic, payload), envelope_frame(msg, "", msg)]
        with self._files(self.data):
            recorded = self.engine._echo_command(topic, frames)
            self.pub.set_cause(decode_push_envelope(frames) if recorded else None)
            try:
                self.engine._dispatch_pull_message(topic, payload)
            finally:
                self.pub.clear_cause()
            self.engine._run_maintenance()
        self.clock.ns += SEC

    def shutdown(self) -> None:
        with self._files(self.data):
            self.engine._shutdown()


class _Script:
    """The session's commands, named so the tables can refer to them."""

    def __init__(self, marks: dict[str, int]) -> None:
        self.marks = marks
        self.orders: dict[str, str] = {}
        self.session: _Session

    def mark(self, name: str) -> None:
        self.marks[name] = self.session.clock.ns

    def connect(self) -> None:
        for gw in (*TRADING_GATEWAYS, OPS):
            self.session.send(
                "system.gateway_connect", GatewayConnect(gateway_id=gw).to_dict()
            )

    def phase(self, state: str) -> None:
        self.mark(f"phase_{state}")
        self.session.send(
            "session.transition", SessionTransition(to_state=state).to_dict()
        )

    def order(
        self,
        name: str,
        gateway: str,
        symbol: str,
        side: Side,
        qty: int,
        price: int | None,
        *,
        order_type: OrderType = OrderType.LIMIT,
        tif: TIF = TIF.DAY,
        stop: int | None = None,
        visible: int | None = None,
    ) -> None:
        order = Order.create(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=qty,
            gateway_id=gateway,
            tif=tif,
            price_ticks=price,
            stop_price_ticks=stop,
            visible_qty=visible,
            tick_decimals=TICK_DECIMALS[symbol],
        )
        order.id = self.orders.setdefault(name, order_id(name))
        payload = OrderNew.from_dict(order.to_dict()).to_dict()
        self.session.send("order.new", payload)

    def cancel(self, name: str, gateway: str) -> None:
        payload = OrderCancel(order_id=self.orders[name], gateway_id=gateway)
        self.session.send("order.cancel", payload.to_dict())

    def amend(
        self,
        name: str,
        gateway: str,
        *,
        price: float | None = None,
        qty: int | None = None,
    ) -> None:
        payload = OrderAmend(
            order_id=self.orders[name], gateway_id=gateway, price=price, qty=qty
        )
        self.session.send("order.amend", payload.to_dict())

    def quote(self, bid: int, ask: int, qty: int) -> None:
        payload = QuoteNew(
            gateway_id=MM,
            symbol="AAA",
            tick_decimals=TICK_DECIMALS["AAA"],
            bid_price_ticks=bid,
            bid_qty=qty,
            ask_price_ticks=ask,
            ask_qty=qty,
            tif="DAY",
            quote_id="Q1",
        )
        self.session.send("quote.new", payload.to_dict())

    def run_1(self, recorder: _Recorder, restart: bool) -> None:
        """The trading day (see the tables at the top of this module)."""
        buy, sell = Side.BUY, Side.SELL
        self.connect()
        self.phase("PRE_OPEN")
        self.phase("OPENING_AUCTION")
        self.mark("opening_call")
        self.order("open_buy", T1, "AAA", buy, 100, 10000)
        self.order("open_sell_1", T2, "AAA", sell, 60, 10000)
        self.order("open_sell_2", T3, "AAA", sell, 40, 10000)
        self.order("bbb_open_buy", T1, "BBB", buy, 1000, 25000)
        self.order("bbb_open_sell", T3, "BBB", sell, 1000, 25000)
        self.phase("CONTINUOUS")

        self.mark("quote_burst")
        self.quote(9990, 10010, 200)
        self.quote(9991, 10011, 200)
        self.quote(9992, 10012, 200)
        self.quote(9990, 10010, 200)

        self.mark("news_rumour")
        self.session.clock.ns += SEC
        self.mark("layering")
        self.order("layer_1", T2, "AAA", sell, 500, 10020)
        self.order("layer_2", T2, "AAA", sell, 500, 10030)
        self.order("layer_3", T2, "AAA", sell, 500, 10040)
        self.order("layer_buy", T2, "AAA", buy, 50, 10010)
        for name in ("layer_1", "layer_2", "layer_3"):
            self.cancel(name, T2)

        self.mark("cancel_burst")
        for i, price in enumerate((9950, 9960, 9970, 9980), start=1):
            self.order(f"burst_{i}", T3, "AAA", buy, 10, price)
        for i in range(1, 5):
            self.mark(f"burst_cancel_{i}")
            self.cancel(f"burst_{i}", T3)

        self.order("gtc_bid", T1, "AAA", buy, 10, 9900, tif=TIF.GTC)
        self.mark("news_confirmed")
        self.session.clock.ns += SEC
        self.mark("stop_cascade")
        self.order("stop_bid", T1, "AAA", buy, 100, 9985)
        self.order("stop_1", T3, "AAA", sell, 20, None, order_type=OrderType.STOP, stop=9990)  # fmt: skip
        self.order("stop_2", T2, "AAA", sell, 30, None, order_type=OrderType.STOP, stop=9985)  # fmt: skip
        self.order("stop_push", T2, "AAA", sell, 200, 9990)

        self.mark("smp")
        self.order("smp_sell", T1, "AAA", sell, 10, 9985)

        self.mark("news_rumour_2")
        self.session.clock.ns += SEC
        self.mark("iceberg")
        self.order("iceberg", T3, "BBB", sell, 3000, 25100, order_type=OrderType.ICEBERG, visible=1000)  # fmt: skip
        self.order("ioc_1", T2, "BBB", buy, 1000, 25100, order_type=OrderType.IOC)
        self.order("ioc_2", T2, "BBB", buy, 1000, 25100, order_type=OrderType.IOC)
        self.order("ioc_3", T2, "BBB", buy, 1500, 25100, order_type=OrderType.IOC)

        self.mark("cycle")
        for i, (seller, buyer) in enumerate(((T1, T2), (T2, T3), (T3, T1)), start=1):
            self.order(f"cycle_buy_{i}", buyer, "BBB", buy, 500, 25200)
            self.order(f"cycle_sell_{i}", seller, "BBB", sell, 500, 25200)
        self.mark("amend")
        self.order("amend_bid", T1, "BBB", buy, 100, 24000)
        self.amend("amend_bid", T1, price=2.45)
        self.amend("amend_bid", T1, qty=60)
        self.cancel("amend_bid", T1)
        self.mark("news_retracted")
        self.session.clock.ns += SEC
        self.mark("round_trip")
        self.order("pair_buy_1", T3, "BBB", buy, 200, 25300)
        self.order("pair_sell_1", T1, "BBB", sell, 200, 25300)
        self.order("pair_buy_2", T1, "BBB", buy, 200, 25300)
        self.order("pair_sell_2", T3, "BBB", sell, 200, 25300)

        if restart:
            recorder.restart()
        self.mark("halt")
        halt = SymbolHalt(gateway_id=OPS, symbol="AAA", note="instructor halt")
        self.session.send("risk.symbol_halt", halt.to_dict())
        self.session.clock.ns += 30 * SEC
        self.mark("resume")
        resume = SymbolResume(gateway_id=OPS, symbol="AAA", note="resume")
        self.session.send("risk.symbol_resume", resume.to_dict())
        self.quote(9980, 10010, 100)

        self.phase("CLOSING_AUCTION")
        self.mark("closing_call")
        self.order("close_buy_1", T3, "AAA", buy, 10, 10010)
        self.order("close_buy_2", T2, "AAA", buy, 20, 10010)
        self.phase("CLOSED")

    def run_2(self) -> None:
        """Variant ``run_reset``: the next run, with an order id reused."""
        self.connect()
        self.phase("PRE_OPEN")
        self.phase("CONTINUOUS")
        self.mark("run_2_reuse")
        self.order("layer_1", T2, "AAA", Side.SELL, 10, 9900)


def build(tmp_path: Path, **variants: bool) -> World:
    """Record the world under ``tmp_path``; each true keyword adds a variant."""
    unknown = set(variants) - VARIANTS
    if unknown:
        raise ValueError(f"unknown audit world variant(s): {sorted(unknown)}")
    on = frozenset(k for k, v in variants.items() if v)
    data = tmp_path / "data"
    data.mkdir(parents=True)
    source = tmp_path / "config" / "engine_config.yaml"
    source.parent.mkdir()
    source.write_text(CONFIG_YAML, encoding="utf-8")
    # Deployed outside the collection: a run's ref_data may be gone, and the
    # trail's system.startup is what carries the configuration.
    artifact = tmp_path / "deployed" / "engine_config.json"
    compiled = deploy(source, artifact)
    text = artifact.read_text(encoding="utf-8")

    def engine(pub: CausalPublisher) -> engine_main.Engine:
        if "no_config" in on:
            # Started from the YAML rather than a deployed artifact: the
            # engine has no artifact text to announce.
            with mock.patch.object(engine_main, "make_publisher", lambda _: pub):
                return engine_main.Engine(config_path=str(source))
        with (
            mock.patch.object(
                engine_main, "_deployed_config", lambda: (compiled.engine, text)
            ),
            mock.patch.object(engine_main, "make_publisher", lambda _: pub),
        ):
            return engine_main.Engine(config_path=None)

    clock = _Clock()
    marks: dict[str, int] = {}
    script = _Script(marks)
    with _engine_world(clock):
        recorder = _Recorder(data / "audit.log", clock)
        try:
            script.session = _Session(data, recorder, clock, engine, 1)
            script.run_1(recorder, restart="restart" in on)
            script.session.shutdown()
            if "run_reset" in on:
                clock.ns += 60 * SEC
                script.session = _Session(data, recorder, clock, engine, 2)
                script.run_2()
                script.session.shutdown()
        finally:
            recorder.finish()

    gap = _plant_gap(data / "audit.log", script.orders["burst_2"]) if "gap" in on else None  # fmt: skip
    if "torn_tail" in on:
        _tear_tail(data / "audit.log")
    if "zstd_archive" in on:
        _archive(data)
    return World(
        data=data,
        variants=on,
        orders=dict(script.orders),
        marks=marks,
        gap_eseq=gap,
        news_db=_news(data, marks) if "sim_context" in on else None,
        forensics_report=_forensics(data) if "forensics_report" in on else None,
    )


@contextmanager
def _engine_world(clock: _Clock) -> Generator[None]:
    """The engine reads *clock*, and its PULL socket is never opened."""
    models_clock.reset_clock_for_tests()
    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(models_clock, "time", clock))
        stack.enter_context(
            mock.patch.object(engine_main, "make_puller", lambda _: _NoSocket())
        )
        try:
            yield
        finally:
            models_clock.reset_clock_for_tests()


class _NoSocket:
    def close(self, linger: int | None = None) -> None:
        pass


def _rewrite(path: Path, change: Callable[[list[str]], list[str]]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text("".join(change(lines)), encoding="utf-8")


def _plant_gap(path: Path, cancelled: str) -> tuple[int, int]:
    """Remove the second burst cancel's command and every effect of it: a
    contiguous run of ``eseq`` values pm-audit never received."""
    eseqs: list[int] = []

    def change(lines: list[str]) -> list[str]:
        start = next(
            i
            for i, ln in enumerate(lines)
            if "[order.cancel]" in ln and f'"order_id": "{cancelled}"' in ln
        )
        end = next(
            i
            for i, ln in enumerate(lines)
            if i > start and "[order.cancelled." in ln and cancelled in ln
        )
        for ln in lines[start : end + 1]:
            eseqs.append(int(ln.split(" eseq=", 1)[1].split()[0]))
        return lines[:start] + lines[end + 1 :]

    _rewrite(path, change)
    return eseqs[0], eseqs[-1]


def _tear_tail(path: Path) -> None:
    """A crash mid-write: the last line is cut in half, with no newline."""
    data = path.read_bytes()
    last = data.rstrip(b"\n").rsplit(b"\n", 1)[1]
    with path.open("ab") as fh:
        fh.write(last[: len(last) // 2])


def _archive(data: Path) -> None:
    """The day is closed into a part and archived (zstd + manifest entry),
    as pm-audit's archiver does once the day has ended."""
    active = AuditFile(data / "audit.log", 10 * 1024 * 1024, TZ)
    try:
        active.roll()
    finally:
        active.close()
    parts = data / "audit"
    with archive_lock(parts):
        archive_day(parts, DAY, today="2026-06-16")


def _news(data: Path, marks: dict[str, int]) -> Path:
    """``market_sim_news.db`` as pm-market-sim writes it: a rumour on AAA
    that is confirmed (with a true-value jump), and one on BBB that is
    retracted. Stamped on the simulator's clock."""
    path = data / "market_sim_news.db"

    def at(mark: str) -> int:
        return marks[mark] + SIM_CLOCK_OFFSET_NS

    events = [
        NewsEvent("N-AAA-1", at("news_rumour"), "SYMBOL", ["AAA"], "MNA", "RUMOUR", "AAA in bid talks", 0.6, 0.5),  # fmt: skip
        NewsEvent("N-AAA-2", at("news_confirmed"), "SYMBOL", ["AAA"], "MNA", "CONFIRMED", "AAA bid confirmed", 0.8, None, "N-AAA-1"),  # fmt: skip
        NewsEvent("N-BBB-1", at("news_rumour_2"), "SYMBOL", ["BBB"], "LEGAL", "RUMOUR", "BBB faces probe", -0.5, 0.4),  # fmt: skip
        NewsEvent("N-BBB-2", at("news_retracted"), "SYMBOL", ["BBB"], "LEGAL", "RETRACTED", "BBB probe denied", 0.3, None, "N-BBB-1"),  # fmt: skip
    ]
    for event in events:
        append_news_event(path, event.to_dict())
    append_value_jumps(
        path, at("news_confirmed"), {"AAA": math.log(101 / 100)}, {"AAA": 101.0}
    )
    return path


def _forensics(data: Path) -> Path:
    """pm-sim-forensics' report over this run (``--out``), one check in each
    state: written by its own report writer."""

    def result(check: str, status: Any, samples: list[Any], note: str) -> Result:
        return Result(REGISTRY[check], status, len(samples), samples, note, 0.01)

    results = [
        result("E1", "PASS", [], "every state change has a recorded cause"),
        result(
            "E2",
            "FAIL",
            [{"trade_id": "000001-000000004", "diffs": ["trade.executed.quantity: 200 != 199"]}],  # fmt: skip
            "1 output differs",
        ),
        result("C1", "SKIPPED", [], "no clearing.db"),
        result("E4", "ERROR", [], "Traceback (most recent call last):\n  ...\nOSError: boom"),  # fmt: skip
    ]
    # pm-sim-forensics' default --out: forensics/ beside the data dir.
    out = data.parent / "forensics"
    with Dataset.open(data) as ds:
        write_forensics_report(ds, results, out, package_version())
    return out / "findings.json"


#: API keys of ``make_audit_app``, one per role.
ADMIN_KEY = "key-ops01"
TRADER_KEY = "key-trader01"
MARKET_MAKER_KEY = "key-mm01"
READ_ONLY_KEY = "key-ro"

#: The engine's answer to "which role has this gateway?" (world config).
ROLES = {OPS: "ADMIN", T1: "TRADER", T2: "TRADER", T3: "TRADER", MM: "MARKET_MAKER"}


class _RoleEngine:
    """Stands in for EngineClient where the audit routes need it: the key's
    gateway is known (``authenticate``) and has a role (``resolve_role``)."""

    async def authenticate(self, gateway_id: str, timeout: float) -> tuple[bool, str]:
        known = gateway_id in ROLES
        return known, "" if known else f"unknown gateway {gateway_id}"

    async def resolve_role(self, gateway_id: str, timeout: float) -> str | None:
        return ROLES.get(gateway_id)


def make_audit_app(world: World, audit_db: Path | None = None) -> Any:
    """The pm-api-gwy app over *world* (its one audit collection is
    ``world``), with a key for every role (see tests/api_gateway_harness.py
    for driving it with ``call``)."""
    config = ApiGatewayConfig(
        swagger_enabled=False,
        audit_db=audit_db if audit_db is not None else world.data / "audit_index.db",
        audit_collections=(AuditCollection("world", world.data),),
    )
    app = create_app(config)
    app.state.config = config
    # The derivative store beside the collection, never inside it.
    app.state.audit = AuditService(
        config.audit_collections, world.data.parent / "audit-gui"
    )
    app.state.engine = _RoleEngine()
    app.state.rate_limiter = RateLimiter(100, 100)
    app.state.sessions = SessionRegistry(
        (
            ApiCredential(ADMIN_KEY, OPS, "instructor"),
            ApiCredential(TRADER_KEY, T1, "trader"),
            ApiCredential(MARKET_MAKER_KEY, MM, "market maker"),
            ApiCredential(READ_ONLY_KEY, None, "read-only"),
        )
    )
    return app
