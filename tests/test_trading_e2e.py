"""
In-process end-to-end trading: ALF client → pm-alf-gwy → engine → back out.

The path no other default-suite test runs as a whole: two ALF clients on
real TCP sockets, the real ALF gateway, the real engine loop over real ZMQ,
and the real consumers of what the engine publishes — the CALF market-data
gateway (with a CALF client on TCP) and clearing (with its SQLite store).
Everything runs on threads in this process, on free ports, so the test needs
no exchange deployment and does not collide with a running one.

Every test gets its own exchange (about 0.4 s to start), so the suite's
autouse protections (trade-id run, reject tally, health beacons, clearing's
health endpoint) apply to it as to any other test. A scenario asserts what a
participant can observe:

  * the ALF lines on both sessions — ACK, FILL (price, quantity, liquidity
    flag), TRIGGERED, CANCELLED, AMENDED, and the reject ACK;
  * the public trade on the CALF feed;
  * both gateways' positions in clearing's database.

Background: docs-design/EduMatcher-Matching-Test-Quality-Workplan.md (T7).
"""

from __future__ import annotations

import itertools
import socket
import sqlite3
import threading
import time
import types
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from edumatcher.alf_gwy.config import AlfGatewayConfig
from edumatcher.alf_gwy.gateway import AlfGateway
from edumatcher.clearing.main import ClearingProcess
from edumatcher.engine.config_loader import (
    EngineConfig,
    FixGatewayConfig,
    SymbolConfig,
)
from edumatcher.engine.main import Engine
from edumatcher.md_gateway.config import MarketDataGatewayConfig
from edumatcher.md_gateway.gateway import MarketDataGateway
from edumatcher.models.trade import reset_trade_ids_for_tests

from tests.conftest import free_ports, wait_for_listener
from tests.engine_harness import FakeDropCopy

T1, T2 = "TRADER01", "TRADER02"
SYM = "AAPL"
#: WARM is traded before each test to prove every feed is live.
SYMBOLS = ("WARM", SYM)
TIMEOUT = 10.0  # generous: under xdist a loaded machine can starve a thread

_tags = itertools.count(1)


def _fields(line: str) -> tuple[str, dict[str, str]]:
    """``CMD|K=V|...`` → (CMD, {K: V}). ALF and CALF share the shape."""
    cmd, *pairs = line.split("|")
    return cmd, dict(p.split("=", 1) for p in pairs if "=" in p)


class LineClient:
    """A TCP client of a line protocol that keeps every line it receives."""

    def __init__(self, port: int) -> None:
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=TIMEOUT)
        self.lines: list[str] = []
        self._buf = b""

    def send(self, line: str) -> None:
        self.sock.sendall(line.encode() + b"\n")

    def _read(self, deadline: float) -> None:
        self.sock.settimeout(max(0.01, deadline - time.monotonic()))
        try:
            chunk = self.sock.recv(65536)
        except TimeoutError:
            return
        if not chunk:
            raise ConnectionError("gateway closed the connection")
        self._buf += chunk
        *complete, self._buf = self._buf.split(b"\n")
        self.lines += [c.decode() for c in complete]

    def wait(self, cmd: str, n: int = 1, /, **match: str) -> list[dict[str, str]]:
        """The first *n* received ``cmd`` lines whose fields include *match*,
        reading more until they have arrived."""
        deadline = time.monotonic() + TIMEOUT
        while True:
            found = [
                f
                for c, f in map(_fields, self.lines)
                if c == cmd and all(f.get(k) == v for k, v in match.items())
            ]
            if len(found) >= n:
                return found[:n]
            if time.monotonic() > deadline:
                raise AssertionError(
                    f"no {n} x {cmd} {match} within {TIMEOUT}s; got:\n  "
                    + "\n  ".join(self.lines[-15:])
                )
            self._read(deadline)

    def poll(self, seconds: float) -> None:
        """Read whatever arrives within *seconds*."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._read(deadline)

    def one(self, cmd: str, **match: str) -> dict[str, str]:
        return self.wait(cmd, **match)[0]

    def count(self, cmd: str, **match: str) -> int:
        """How many matching lines have arrived so far (no waiting)."""
        return sum(
            1
            for c, f in map(_fields, self.lines)
            if c == cmd and all(f.get(k) == v for k, v in match.items())
        )

    def close(self) -> None:
        self.sock.close()


class Trader(LineClient):
    """An authenticated ALF session."""

    def __init__(self, port: int, gateway_id: str) -> None:
        self.id = gateway_id
        deadline = time.monotonic() + TIMEOUT
        while True:
            super().__init__(port)
            try:
                self._logon(deadline)
                return
            except ConnectionError:
                # A session made while the engine was still starting is
                # dropped by its startup announcement: log on again, as the
                # gateway tells a real client to.
                self.close()
                assert time.monotonic() < deadline, f"{gateway_id}: no session"

    def _logon(self, deadline: float) -> None:
        hello = f"HELLO|CLIENT={self.id.lower()}|PROTO=ALF1|ID={self.id}"
        # Until the gateway's PUSH to the engine is connected it answers
        # ENGINE_UNAVAILABLE and keeps the session open: say HELLO again.
        self.send(hello)
        while not any(line.startswith("WELCOME") for line in self.lines):
            if any("ENGINE_UNAVAILABLE" in line for line in self.lines):
                self.lines.clear()
                time.sleep(0.05)
                self.send(hello)
            assert time.monotonic() < deadline, f"{self.id}: no WELCOME"
            self._read(min(deadline, time.monotonic() + 0.1))
        # NEW is refused until the tick sizes have arrived (SYMBOLS_NOT_READY).
        self.one("END", TYPE="SYMBOLS")

    def new(self, sym: str, side: str, type_: str, qty: int, **extra: str) -> str:
        """Submit NEW, wait for its accepted ACK, return the order id."""
        tag = f"E2E-{next(_tags)}"
        fields = "".join(f"|{k}={v}" for k, v in extra.items())
        self.send(f"NEW|SYM={sym}|SIDE={side}|TYPE={type_}|QTY={qty}{fields}|TAG={tag}")
        ack = self.one("ACK", TAG=tag)
        assert ack["ACCEPTED"] == "TRUE", ack
        return ack["ORDER_ID"]


@dataclass
class Exchange:
    t1: Trader
    t2: Trader
    md: LineClient
    db_path: Path

    def rows(self, sym: str) -> dict[str, dict[str, Any]]:
        """Clearing's position rows for *sym*, by gateway (none while
        clearing has not created its database yet)."""
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        except sqlite3.OperationalError:
            return {}
        conn.row_factory = sqlite3.Row
        try:
            return {
                r["gateway_id"]: dict(r)
                for r in conn.execute(
                    "SELECT * FROM gateway_symbol_positions WHERE symbol = ?", (sym,)
                )
            }
        finally:
            conn.close()

    def positions(self, sym: str, expected: dict[str, int]) -> dict[str, Any]:
        """Wait until clearing's database holds *expected* net quantities
        for *sym*; return its rows by gateway."""
        deadline = time.monotonic() + TIMEOUT
        rows = self.rows(sym)
        while {g: r["net_qty"] for g, r in rows.items()} != expected:
            if time.monotonic() > deadline:
                raise AssertionError(f"clearing for {sym}: {rows} != {expected}")
            time.sleep(0.02)
            rows = self.rows(sym)
        return rows


def _patch_engine(mp: pytest.MonkeyPatch, tmp: Path, pull: int, pub: int) -> None:
    """Point the engine at free ports and a scratch directory, and let its
    run loop live on a thread."""
    em = "edumatcher.engine.main"
    mp.setattr(f"{em}.ENGINE_PULL_BIND_ADDR", f"tcp://127.0.0.1:{pull}")
    mp.setattr(f"{em}.ENGINE_PUB_BIND_ADDR", f"tcp://127.0.0.1:{pub}")
    for name in ("GTC_ORDERS_FILE", "GTC_COMBOS_FILE", "BOOK_STATS_FILE"):
        mp.setattr(f"{em}.{name}", tmp / f"{name.lower()}.json")
    mp.setattr(f"{em}.RUN_SEQ_FILE", tmp / "run_seq.json")
    mp.setattr(f"{em}.DropCopyPublisher", lambda *a, **k: FakeDropCopy())
    # signal.signal() raises off the main thread; scoped, as engine_harness
    # scopes time.sleep, so the process-wide signal module is untouched.
    mp.setattr(
        f"{em}.signal",
        types.SimpleNamespace(signal=lambda *a: None, SIGINT=2, SIGTERM=15),
    )
    cfg = EngineConfig(
        symbols={s: SymbolConfig(name=s) for s in SYMBOLS},
        fix_gateways={g: FixGatewayConfig(id=g, description=g) for g in (T1, T2)},
    )
    mp.setattr(f"{em}.load_engine_config", lambda _: cfg)


@pytest.fixture
def exchange(tmp_path: Path) -> Iterator[Exchange]:
    (tmp_path / "engine_config.yaml").write_text("dummy: true\n")
    (drop_copy,) = free_ports(1)  # only connected to, never bound
    with pytest.MonkeyPatch.context() as mp:
        # free_ports() releases its ports before the engine binds them, and
        # under xdist another process occasionally takes one in between. The
        # engine then exits; pick new ports and build it again.
        for _ in range(5):
            pull, pub = free_ports(2)
            _patch_engine(mp, tmp_path, pull, pub)
            reset_trade_ids_for_tests()  # Engine.run sets the run sequence itself
            try:
                engine = Engine(config_path=str(tmp_path / "engine_config.yaml"))
                break
            except SystemExit:
                continue
        else:
            raise AssertionError("the engine could not bind its ports")
        engine_pull, engine_pub = f"tcp://127.0.0.1:{pull}", f"tcp://127.0.0.1:{pub}"
        # The TCP gateways bind port 0, so the OS picks a free port at bind
        # time; the port is read back once they listen.
        alf = AlfGateway(
            AlfGatewayConfig(
                bind_address="127.0.0.1",
                port=0,
                engine_pull_addr=engine_pull,
                engine_pub_addr=engine_pub,
                drop_copy_pub_addr=f"tcp://127.0.0.1:{drop_copy}",
                gateway_roles=((T1, "TRADER"), (T2, "TRADER")),
            )
        )
        md = MarketDataGateway(
            MarketDataGatewayConfig(
                bind_address="127.0.0.1",
                port=0,
                engine_pub_addr=engine_pub,
                engine_pull_addr=engine_pull,
            ),
            known_symbols=set(SYMBOLS),
        )
        db_path = tmp_path / "clearing.db"
        clearing = ClearingProcess(
            pub_addr=engine_pub, db_path=db_path, flush_size=1, print_every=0
        )
        stops: list[Callable[[], None]] = [
            lambda: setattr(engine, "_running", False),
            alf.stop,
            md.stop,
            clearing.stop,
        ]
        threads = [
            threading.Thread(target=run, daemon=True, name=name)
            for name, run in (
                ("e2e-engine", engine.run),
                ("e2e-alf-gwy", alf.run),
                ("e2e-md-gwy", md.run),
                ("e2e-clearing", clearing.run),
            )
        ]
        for t in threads:
            t.start()
        clients: list[LineClient] = []
        try:
            deadline = time.monotonic() + TIMEOUT
            while not engine._running:  # startup published; now serving
                assert time.monotonic() < deadline, "engine never started"
                time.sleep(0.01)
            alf_port, md_port = _listening_port(alf), _listening_port(md)
            feed = LineClient(md_port)
            clients.append(feed)
            feed.send("HELLO|CLIENT=e2e-md|PROTO=CALF1")
            feed.one("WELCOME")
            feed.send("SUB|CH=TRADE|SYM=*")
            t1, t2 = Trader(alf_port, T1), Trader(alf_port, T2)
            clients += [t1, t2]
            ex = Exchange(t1, t2, feed, db_path)
            _warm_up(ex)
            yield ex
        finally:
            for c in clients:
                c.close()
            for stop in stops:
                stop()
            for t in threads:
                t.join(timeout=5)


def _listening_port(gateway: AlfGateway | MarketDataGateway) -> int:
    """The port a gateway started with port 0 is listening on."""
    deadline = time.monotonic() + TIMEOUT
    while (server := gateway._server) is None or server.getsockname()[1] == 0:
        assert time.monotonic() < deadline, "gateway never bound its port"
        time.sleep(0.01)
    port: int = server.getsockname()[1]
    wait_for_listener("127.0.0.1", port)
    return port


def _warm_up(ex: Exchange) -> None:
    """Trade WARM until the CALF feed and clearing have both seen a print:
    their SUB sockets join asynchronously and miss what comes before."""
    deadline = time.monotonic() + TIMEOUT
    while not (ex.md.count("TRADE", SYM="WARM") and ex.rows("WARM")):
        assert time.monotonic() < deadline, "CALF feed or clearing never saw WARM"
        ex.t1.new("WARM", "SELL", "LIMIT", 1, PRICE="100.00")
        ex.t2.new("WARM", "BUY", "LIMIT", 1, PRICE="100.00")
        ex.md.poll(0.2)


# ---------------------------------------------------------------------------
# Helpers for the assertions
# ---------------------------------------------------------------------------


def fills(trader: Trader, order_id: str) -> list[tuple[str, ...]]:
    """(qty, price, liquidity, status) of the order's FILL line."""
    return [
        (f["FILL_QTY"], f["FILL_PRICE"], f["LIQUIDITY"], f["STATUS"])
        for f in trader.wait("FILL", ORDER_ID=order_id)
    ]


def prints(ex: Exchange, n: int = 1) -> list[tuple[str, str, str]]:
    """(price, qty, aggressor side) of the first *n* CALF trades on SYM."""
    return [(t["PX"], t["QTY"], t["SIDE"]) for t in ex.md.wait("TRADE", n, SYM=SYM)]


def position(rows: dict[str, Any], gw: str) -> tuple[int, int, int, int, int]:
    """(net, bought, sold, buy notional, sell notional) in ticks."""
    r = rows[gw]
    return (
        r["net_qty"],
        r["buy_qty"],
        r["sell_qty"],
        r["buy_notional"],
        r["sell_notional"],
    )


# ---------------------------------------------------------------------------
# One crossing scenario per order type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "type_, extra",
    [
        ("LIMIT", {"PRICE": "101.00"}),
        ("MARKET", {}),
        ("IOC", {"PRICE": "100.00"}),
        ("FOK", {"PRICE": "100.00"}),
    ],
)
def test_an_aggressive_order_trades_with_a_resting_limit(
    exchange: Exchange, type_: str, extra: dict[str, str]
) -> None:
    ex = exchange
    sell = ex.t1.new(SYM, "SELL", "LIMIT", 10, PRICE="100.00")

    buy = ex.t2.new(SYM, "BUY", type_, 10, **extra)

    assert fills(ex.t1, sell) == [("10", "100.0", "MAKER", "FILLED")]
    assert fills(ex.t2, buy) == [("10", "100.0", "TAKER", "FILLED")]
    (trade,) = ex.md.wait("TRADE", SYM=SYM)
    assert (trade["PX"], trade["QTY"], trade["SIDE"]) == ("100.0", "10", "BUY")
    assert ex.t2.one("FILL", ORDER_ID=buy)["TRADE_IDS"] == trade["TRADE_ID"]
    rows = ex.positions(SYM, {T1: -10, T2: 10})
    assert position(rows, T1) == (-10, 0, 10, 0, 100000)
    assert position(rows, T2) == (10, 10, 0, 100000, 0)


@pytest.mark.parametrize("type_, extra", [("IOC", {"PRICE": "100.00"}), ("MARKET", {})])
def test_an_unfilled_remainder_is_cancelled_with_a_reason(
    exchange: Exchange, type_: str, extra: dict[str, str]
) -> None:
    ex = exchange
    sell = ex.t1.new(SYM, "SELL", "LIMIT", 10, PRICE="100.00")

    taker = ex.t2.new(SYM, "BUY", type_, 15, **extra)

    assert fills(ex.t1, sell) == [("10", "100.0", "MAKER", "FILLED")]
    assert fills(ex.t2, taker) == [("10", "100.0", "TAKER", "PARTIAL")]
    cancelled = ex.t2.one("CANCELLED", ORDER_ID=taker)
    assert cancelled["CANCEL_REASON"] == "INSUFFICIENT_LIQUIDITY"
    assert prints(ex) == [("100.0", "10", "BUY")]
    ex.positions(SYM, {T1: -10, T2: 10})


def test_a_resting_iceberg_fills_peak_by_peak(exchange: Exchange) -> None:
    ex = exchange
    ice = ex.t1.new(SYM, "SELL", "ICEBERG", 10, PRICE="100.00", VISIBLE="4")

    buy = ex.t2.new(SYM, "BUY", "LIMIT", 10, PRICE="100.00")

    assert prints(ex, 3) == [("100.0", q, "BUY") for q in ("4", "4", "2")]
    # One FILL per order for the whole sweep, naming every print in it.
    trade_ids = ",".join(t["TRADE_ID"] for t in ex.md.wait("TRADE", 3, SYM=SYM))
    for trader, order_id, liquidity in ((ex.t1, ice, "MAKER"), (ex.t2, buy, "TAKER")):
        (fill,) = trader.wait("FILL", ORDER_ID=order_id)
        assert (fill["FILL_QTY"], fill["STATUS"], fill["LIQUIDITY"]) == (
            "10",
            "FILLED",
            liquidity,
        )
        assert fill["TRADE_IDS"] == trade_ids
    ex.positions(SYM, {T1: -10, T2: 10})


@pytest.mark.parametrize(
    "type_, extra, becomes",
    [
        ("STOP", {"STOP": "100.00"}, "MARKET"),
        ("STOP_LIMIT", {"STOP": "100.00", "PRICE": "101.00"}, "LIMIT"),
        ("TRAILING_STOP", {"STOP": "100.00", "TRAIL": "0.50"}, "MARKET"),
    ],
)
def test_a_stop_triggered_by_a_print_trades(
    exchange: Exchange, type_: str, extra: dict[str, str], becomes: str
) -> None:
    """A 1-lot print at 100.00 triggers TRADER02's BUY stop, which buys the
    10 lots offered at 101.00."""
    ex = exchange
    ex.t1.new(SYM, "SELL", "LIMIT", 1, PRICE="100.00")
    offer = ex.t1.new(SYM, "SELL", "LIMIT", 10, PRICE="101.00")
    stop = ex.t2.new(SYM, "BUY", type_, 10, **extra)

    ex.t2.new(SYM, "BUY", "LIMIT", 1, PRICE="100.00")

    triggered = ex.t2.one("TRIGGERED", ORDER_ID=stop)
    assert (triggered["TYPE"], triggered["BECOMES"]) == (type_, becomes)
    assert fills(ex.t2, stop) == [("10", "101.0", "TAKER", "FILLED")]
    assert fills(ex.t1, offer) == [("10", "101.0", "MAKER", "FILLED")]
    assert prints(ex, 2) == [("100.0", "1", "BUY"), ("101.0", "10", "BUY")]
    rows = ex.positions(SYM, {T1: -11, T2: 11})
    assert position(rows, T2) == (11, 11, 0, 10000 + 101000, 0)


# ---------------------------------------------------------------------------
# Cancel and amend round trips; a reject
# ---------------------------------------------------------------------------


def test_cancel_round_trip_and_the_wrong_owner_reject(exchange: Exchange) -> None:
    ex = exchange
    bid = ex.t1.new(SYM, "BUY", "LIMIT", 10, PRICE="99.00")

    ex.t2.send(f"CANCEL|ID={bid}|RTAG=NOT-MINE")

    reject = ex.t2.one("ACK", ORDER_ID=bid)
    assert {k: reject[k] for k in ("ACCEPTED", "REJECT_CODE", "REASON", "RTAG")} == {
        "ACCEPTED": "FALSE",
        "REJECT_CODE": "NOT_OWNER",
        "REASON": "Cannot cancel an order owned by another gateway",
        "RTAG": "NOT-MINE",
    }
    assert ex.t1.count("ACK", ORDER_ID=bid) == 1  # the owner hears nothing new

    ex.t1.send(f"CANCEL|ID={bid}|RTAG=MINE")

    cancelled = ex.t1.one("CANCELLED", ORDER_ID=bid)
    assert cancelled["RTAG"] == "MINE"
    assert "CANCEL_REASON" not in cancelled  # the owner asked; no exchange cause


def test_amend_round_trip_and_a_crossing_amend_trades(exchange: Exchange) -> None:
    ex = exchange
    bid = ex.t1.new(SYM, "BUY", "LIMIT", 10, PRICE="99.00")

    ex.t1.send(f"AMEND|ID={bid}|QTY=5|RTAG=SMALLER")

    smaller = ex.t1.one("AMENDED", RTAG="SMALLER")
    assert (smaller["QTY"], smaller["REMAINING"], smaller["PRIORITY_RESET"]) == (
        "5",
        "5",
        "FALSE",
    )

    ask = ex.t2.new(SYM, "SELL", "LIMIT", 5, PRICE="100.00")
    ex.t1.send(f"AMEND|ID={bid}|PRICE=100.00|RTAG=CROSS")

    assert ex.t1.one("AMENDED", RTAG="CROSS")["PRIORITY_RESET"] == "TRUE"
    assert fills(ex.t1, bid) == [("5", "100.0", "TAKER", "FILLED")]
    assert fills(ex.t2, ask) == [("5", "100.0", "MAKER", "FILLED")]
    assert prints(ex) == [("100.0", "5", "BUY")]
    ex.positions(SYM, {T1: 5, T2: -5})
