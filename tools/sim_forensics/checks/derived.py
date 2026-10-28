"""F — derived data and market data, recomputed from the records they derive from."""

from __future__ import annotations

import json
import math
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sim_forensics.audit import Line, audit_files, lines
from sim_forensics.dataset import Dataset, iso_ns
from sim_forensics.registry import Outcome, Sample, Skipped, check


@dataclass
class _Day:
    trade_count: int = 0
    volume: int = 0
    turnover: int = 0
    open_price: int | None = None
    close_price: int | None = None
    high_price: int | None = None
    low_price: int | None = None
    largest_trade_qty: int = 0
    largest_trade_price: int | None = None


_FIELDS = (
    "trade_count",
    "volume",
    "turnover",
    "open_price",
    "close_price",
    "high_price",
    "low_price",
    "largest_trade_qty",
    "largest_trade_price",
)


@check(
    "F1",
    "cross-store",
    "daily_stats OHLCV/turnover/VWAP recomputed from trade_log",
    needs=("stats",),
)
def daily_stats_match_trade_log(ds: Dataset) -> Outcome:
    """Recompute every (date, symbol) row from all of trade_log.

    Trades are taken in engine order (trade id), not pm-stats's receive
    order, so open/close also prove the recorder saw trades in sequence.
    Not bounded by the cut: both tables are pm-stats's own.
    """
    days: dict[tuple[str, str], _Day] = {}
    rows = ds.conn.execute(
        "SELECT session_date(ts), symbol, price, quantity "
        "FROM stats.trade_log ORDER BY trade_id"
    )
    for date, symbol, price, qty in rows:
        d = days.setdefault((date, symbol), _Day())
        d.trade_count += 1
        d.volume += qty
        d.turnover += price * qty
        if d.open_price is None:
            d.open_price = price
        d.close_price = price
        d.high_price = price if d.high_price is None else max(d.high_price, price)
        d.low_price = price if d.low_price is None else min(d.low_price, price)
        if qty > d.largest_trade_qty:
            d.largest_trade_qty, d.largest_trade_price = qty, price

    samples: list[Sample] = []
    stored = ds.conn.execute(
        "SELECT date, symbol, vwap, " + ", ".join(_FIELDS) + " FROM stats.daily_stats"
    )
    seen = set()
    for date, symbol, vwap, *values in stored:
        seen.add((date, symbol))
        expected = days.get((date, symbol), _Day())
        diffs = {
            name: {"stored": value, "expected": getattr(expected, name)}
            for name, value in zip(_FIELDS, values)
            if value != getattr(expected, name)
        }
        exp_vwap = expected.turnover / expected.volume if expected.volume else None
        if not _same_vwap(vwap, exp_vwap):
            diffs["vwap"] = {"stored": vwap, "expected": exp_vwap}
        if diffs:
            samples.append({"date": date, "symbol": symbol, "diffs": diffs})
    for date, symbol in sorted(days.keys() - seen):
        samples.append({"date": date, "symbol": symbol, "diffs": "no daily_stats row"})
    return Outcome(len(samples), samples, f"{len(days)} (date, symbol) days traded")


def _same_vwap(stored: float | None, expected: float | None) -> bool:
    if stored is None or expected is None:
        return stored is expected
    return math.isclose(stored, expected, rel_tol=1e-12)


# ---------------------------------------------------------------------------
# F2 / F3 -- market data against the audit's book snapshots
# ---------------------------------------------------------------------------

#: pm-stats stamps a price snapshot with its receipt time, truncated to the
#: second; the engine published the book message it used (the message's
#: ts_ns) up to this long before (pm-stats's queue under load). The audit
#: line's own time is pm-audit's write time, so it only pre-selects the
#: messages, with the same slack on both sides.
_LAG_S = 5
#: Book snapshots carry the last five trades (OrderBook.snapshot()).
_RECENT = 5
_TRADE_KEYS = (
    "id",
    "symbol",
    "buy_order_id",
    "sell_order_id",
    "buy_gateway_id",
    "sell_gateway_id",
    "price",
    "quantity",
    "ts_ns",
)
_UNSET = object()
_KEEP_F6 = 50
SEC = 1_000_000_000


def _ticks(price: float | None, td: int) -> int | None:
    return None if price is None else round(price * 10**td)


def _best(levels: list[dict[str, Any]], td: int) -> int | None:
    return _ticks(levels[0]["price"], td) if levels else None


def _same(got: Any, want: Any) -> bool:
    """Equal; floats to within float noise (the engine sums in another
    order than this replay might)."""
    if isinstance(want, float) and isinstance(got, (int, float)):
        return math.isclose(got, want, rel_tol=1e-9, abs_tol=1e-9)
    return bool(got == want)


@dataclass
class _Row:
    """One price_snapshots row and the audit window that must explain it."""

    ts: str
    lo: str
    hi: str
    #: The window the book message's ts_ns must fall in.
    lo_ns: int
    hi_ns: int
    bid: int | None
    ask: int | None
    matched: bool = False


@dataclass
class _Tape:
    """What a symbol's book snapshot must say about its trades."""

    last: tuple[float, int] | None = None
    buy: object = _UNSET
    sell: object = _UNSET
    recent: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=_RECENT))
    traded: bool = False
    #: A trade arrived since the last snapshot was checked.
    dirty: bool = True
    #: The trade fields of the last checked snapshot, unparsed.
    tail: str = ""


class _Market:
    """One pass over the audit for F2, F3 and F6 (and G2's engine starts)."""

    def __init__(self, ds: Dataset) -> None:
        self.ds = ds
        self.f2: list[Sample] = []
        self.f3: list[Sample] = []
        self.rows: dict[str, list[_Row]] = defaultdict(list)
        self.next_row: dict[str, int] = defaultdict(int)
        self.tapes: dict[str, _Tape] = defaultdict(_Tape)
        #: (date, symbol) → first non-empty best bid and ask the audit shows.
        self.opens: dict[tuple[str, str], list[int | None]] = {}
        self.eod: dict[str, Any] | None = None
        self.eod_ts = ""
        self.start_ts = ""
        self.from_start = False
        #: When each engine start (system.startup_recovery) was written.
        self.starts: list[str] = []
        self.snapshots = self.checked = self.outside = 0
        self.f6: list[Sample] = []
        self.f6_count = self.depths = self.depths_unpaired = 0
        self._days: dict[str, str] = {}
        if "stats" in ds.stores:
            self._load_rows()

    def _load_rows(self) -> None:
        prev: dict[str, float | None] = {}
        for ts, symbol, mid, bid, ask, pct in self.ds.conn.execute(
            "SELECT ts, symbol, mid_price, best_bid, best_ask, pct_change "
            "FROM stats.price_snapshots ORDER BY symbol, ts"
        ):
            moment = datetime.fromisoformat(ts)
            lo = moment - timedelta(seconds=_LAG_S)
            hi = moment + timedelta(seconds=1 + _LAG_S)
            at = iso_ns(ts)
            self.rows[symbol].append(
                _Row(
                    ts,
                    lo.isoformat(timespec="milliseconds"),
                    hi.isoformat(timespec="milliseconds"),
                    at - _LAG_S * SEC,
                    at + SEC,
                    bid,
                    ask,
                )
            )
            self._row_itself(symbol, ts, mid, bid, ask, pct, prev)

    def _row_itself(
        self,
        symbol: str,
        ts: str,
        mid: float | None,
        bid: int | None,
        ask: int | None,
        pct: float | None,
        prev: dict[str, float | None],
    ) -> None:
        """A row's mid and pct_change follow from its own bid/ask and the
        symbol's previous row, as pm-stats computes them."""
        sides = [p for p in (bid, ask) if p is not None]
        if sides and mid != sum(sides) / len(sides):
            self.f2.append({"symbol": symbol, "ts": ts, "error": "mid", "mid": mid})
        base = prev.get(symbol)
        expected = (
            round((mid - base) / base * 100, 4)
            if mid is not None and base not in (None, 0)
            else None
        )
        if symbol in prev and pct != expected:
            self.f2.append(
                {"symbol": symbol, "ts": ts, "error": "pct_change", "stored": pct, "expected": expected}  # fmt: skip
            )
        prev[symbol] = mid

    def day(self, ts: str) -> str:
        """Session date of an audit timestamp (cached per hour)."""
        hour = ts[:13]
        if hour not in self._days:
            moment = datetime.fromisoformat(ts).astimezone(self.ds.session_tz)
            self._days[hour] = moment.date().isoformat()
        return self._days[hour]

    def run(self, stream: Iterable[Line]) -> None:
        # The engine publishes depth.<SYM> right after book.<SYM>, from the
        # same book state (Engine._flush_snapshots).
        prev_book: Line | None = None
        for ln in stream:
            if not self.start_ts:
                self.start_ts = ln.ts
                self.from_start = ln.topic == "system.startup_recovery"
            topic = ln.topic
            book, prev_book = prev_book, None
            if topic == "trade.executed":
                self._trade(json.loads(ln.body))
            elif topic.startswith("book.") and "." not in topic[5:]:
                self._book(topic[5:], ln)
                prev_book = ln
            elif topic.startswith("depth."):
                self._depth(topic[6:], ln, book)
            elif topic == "system.eod":
                self.eod, self.eod_ts = json.loads(ln.body), ln.ts
            elif topic == "system.startup_recovery":
                self.starts.append(ln.ts)
        for symbol in self.rows:
            self._close_rows(symbol, "~")

    def _trade(self, p: dict[str, Any]) -> None:
        tape = self.tapes[p["symbol"]]
        tape.last = (p["price"], p["quantity"])
        if p["aggressor_side"] == "BUY":
            tape.buy = p["price"]
        elif p["aggressor_side"] == "SELL":
            tape.sell = p["price"]
        tape.recent.append({k: p.get(k) for k in _TRADE_KEYS})
        tape.traded = tape.dirty = True

    def _book(self, symbol: str, ln: Line) -> None:
        self.snapshots += 1
        parsed: list[dict[str, Any]] = []  # parsed only if a check needs it

        def payload() -> dict[str, Any]:
            if not parsed:
                parsed.append(json.loads(ln.body))
            return parsed[0]

        self._close_rows(symbol, ln.ts)
        rows, i = self.rows.get(symbol), self.next_row[symbol]
        # Windows of consecutive rows (15 min apart) never overlap.
        if rows and i < len(rows) and rows[i].lo <= ln.ts and not rows[i].matched:
            p, row = payload(), rows[i]
            td = p["tick_decimals"]
            best = (_best(p["bids"], td), _best(p["asks"], td))
            if row.lo_ns <= p["ts_ns"] < row.hi_ns and best == (row.bid, row.ask):
                row.matched = True
        key = (self.day(ln.ts), symbol)
        first = self.opens.setdefault(key, [None, None])
        if first[0] is None or first[1] is None:
            p = payload()
            td = p["tick_decimals"]
            first[0] = first[0] if first[0] is not None else _best(p["bids"], td)
            first[1] = first[1] if first[1] is not None else _best(p["asks"], td)

        tape = self.tapes[symbol]
        tail = ln.body[ln.body.find('"last_price"') :]
        if not tape.dirty and tail == tape.tail:
            return  # same trades, same fields: the verdict cannot change
        tape.dirty, tape.tail = False, tail
        self._tape(symbol, tape, payload(), ln.ts)

    def _depth(self, symbol: str, ln: Line, book: Line | None) -> None:
        """F6: a depth message's figures recomputed from its book message,
        as ``OrderBook.depth_snapshot`` computes them."""
        self.depths += 1
        if book is None or book.topic != f"book.{symbol}":
            self.depths_unpaired += 1
            return
        d, b = json.loads(ln.body), json.loads(book.body)
        td, tol, mid = b["tick_decimals"], d["tolerance_ticks"], d["mid_price_ticks"]
        scale = float(10**td)
        bids = {round(lv["price"] * 10**td): lv["qty"] for lv in b["bids"] if lv["qty"] > 0}  # fmt: skip
        asks = {round(lv["price"] * 10**td): lv["qty"] for lv in b["asks"] if lv["qty"] > 0}  # fmt: skip
        bid_depth = sum(q for px, q in bids.items() if mid - tol <= px <= mid)
        ask_depth = sum(q for px, q in asks.items() if mid <= px <= mid + tol)
        total = bid_depth + ask_depth
        imbalance = (bid_depth - ask_depth) / total if total > 0 else 0.0
        cost = sum(px * q for px, q in asks.items() if mid <= px <= mid + tol)
        micro = mid / scale
        if bids and asks:
            bid, ask = max(bids) / scale, min(asks) / scale
            micro = (bid + ask) / 2 + imbalance * (ask - bid) / 2
        expected: dict[str, Any] = {
            "mid_price_ticks": _ticks(b["last_price"], td),
            "mid_price": mid / scale,
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "imbalance": imbalance,
            "microprice": micro,
            "cost_to_move": cost / scale,
        }
        diffs = {
            k: {"depth": d.get(k), "book": v}
            for k, v in expected.items()
            if not _same(d.get(k), v)
        }
        if diffs:
            self.f6_count += 1
            if len(self.f6) < _KEEP_F6:
                self.f6.append({"symbol": symbol, "ts": ln.ts, "diffs": diffs})

    def _close_rows(self, symbol: str, ts: str) -> None:
        """Settle the symbol's rows whose window has passed by *ts*."""
        rows = self.rows.get(symbol)
        if not rows:
            return
        i = self.next_row[symbol]
        while i < len(rows) and rows[i].hi < ts:
            row = rows[i]
            if row.lo < self.start_ts and not self.from_start:
                self.outside += 1
            else:
                self.checked += 1
                if not row.matched:
                    self.f2.append(
                        {"symbol": symbol, "ts": row.ts, "error": "no book message in the audit has this bid/ask", "bid": row.bid, "ask": row.ask}  # fmt: skip
                    )
            i += 1
        self.next_row[symbol] = i

    def _tape(self, symbol: str, tape: _Tape, p: dict[str, Any], ts: str) -> None:
        if tape.buy is _UNSET:
            # Restored at startup (book_stats.json or the config), so only
            # the first snapshot can say what they were.
            tape.buy, tape.sell = p["last_buy_price"], p["last_sell_price"]
        if not tape.traded and not self.from_start:
            # The audit starts mid-run: the trades before it are unknown.
            self._adopt(tape, p)
            return
        expected = {
            "last_price": tape.last[0] if tape.last else None,
            "last_qty": tape.last[1] if tape.last else None,
            "last_buy_price": tape.buy,
            "last_sell_price": tape.sell,
            "recent_trades": list(tape.recent),
        }
        diffs = {
            k: {"book": p.get(k), "trades": v}
            for k, v in expected.items()
            if p.get(k) != v
        }
        if diffs:
            self.f3.append({"symbol": symbol, "ts": ts, "diffs": diffs})
            self._adopt(tape, p)  # count each wrong snapshot once, not its sequels

    def _adopt(self, tape: _Tape, p: dict[str, Any]) -> None:
        if p["last_price"] is not None:
            tape.last = (p["last_price"], p["last_qty"])
        tape.buy, tape.sell = p["last_buy_price"], p["last_sell_price"]
        tape.recent = deque(
            ({k: t.get(k) for k in _TRADE_KEYS} for t in p["recent_trades"]),
            maxlen=_RECENT,
        )

    def daily_bid_ask(self) -> list[Sample]:
        """daily_stats open_bid/open_ask: the first non-empty best bid and
        ask of the trading date; close_bid/close_ask: system.eod's books."""
        samples: list[Sample] = []
        closes: dict[tuple[str, str], tuple[int | None, int | None]] = {}
        if self.eod is not None:
            day = self.day(self.eod_ts)
            for b in self.eod["books"]:
                td = b["tick_decimals"]
                closes[(day, b["symbol"])] = (
                    _best(b["bids"], td),
                    _best(b["asks"], td),
                )
        first_day = self.day(self.start_ts)
        for date, symbol, ob, oa, cb, ca in self.ds.conn.execute(
            "SELECT date, symbol, open_bid, open_ask, close_bid, close_ask "
            "FROM stats.daily_stats"
        ):
            if date < first_day or (date == first_day and not self.from_start):
                continue  # the audit does not reach back to the day's start
            opened = tuple(self.opens.get((date, symbol), (None, None)))
            if (ob, oa) != opened:
                samples.append(
                    {"date": date, "symbol": symbol, "error": "open bid/ask", "stored": [ob, oa], "audit": list(opened)}  # fmt: skip
                )
            close = closes.get((date, symbol), (None, None))
            if self.eod is not None and (cb, ca) != close:
                samples.append(
                    {"date": date, "symbol": symbol, "error": "close bid/ask", "stored": [cb, ca], "audit": list(close)}  # fmt: skip
                )
        return samples


def market_pass(ds: Dataset) -> _Market:
    cached = ds.cache.get("market")
    if isinstance(cached, _Market):
        return cached
    files = audit_files(ds.data_dir)
    if not files:
        raise Skipped("no audit.log in the data dir")
    m = _Market(ds)
    m.run(lines(files))
    ds.cache["market"] = m
    return m


@check(
    "F2",
    "cross-store",
    "price_snapshots and daily open/close bid/ask are the engine's book messages",
    needs=("stats",),
)
def price_snapshots_match_books(ds: Dataset) -> Outcome:
    """Each price_snapshots row must equal one book.<SYM> message the audit
    holds from the row's second back by the receipt lag; mid and pct_change
    follow from the row itself. Rows from before the audit starts are not
    checked."""
    m = market_pass(ds)
    samples = m.f2 + m.daily_bid_ask()
    eod = "system.eod in the audit" if m.eod else "no system.eod in the audit: close bid/ask not checked"  # fmt: skip
    note = (
        f"{m.checked} price_snapshots rows checked, {m.outside} before the audit; "
        f"{eod}"
    )
    return Outcome(len(samples), samples, note)


@check(
    "F3",
    "cross-store",
    "Book messages' last price, last qty, side prices and recent trades follow the trades",
    needs=(),
)
def books_follow_trades(ds: Dataset) -> Outcome:
    """Replays trade.executed per symbol, in publish order: last_price/qty
    is the last trade, last_buy/sell_price the last BUY/SELL-aggressor trade
    (auction prints update neither), recent_trades the last five."""
    m = market_pass(ds)
    note = f"{m.snapshots} book messages"
    if not m.from_start:
        note += "; the audit starts mid-run, so each symbol's first snapshot is taken as given"
    return Outcome(len(m.f3), m.f3, note)


@check(
    "F4",
    "cross-store",
    "book_stats.json holds each symbol's last trade prices",
    needs=("stats",),
)
def book_stats_match_trades(ds: Dataset) -> Outcome:
    """The engine persists prev_close = the book's last trade price and the
    last BUY/SELL-aggressor prices; trade_log's last trades must agree. A
    symbol whose prev_close is empty although daily_stats has closed it
    before has lost its reference price."""
    path = ds.data_dir / "book_stats.json"
    if not path.is_file():
        raise Skipped("no book_stats.json in the data dir")
    stats = json.loads(path.read_text())
    td = dict(ds.conn.execute("SELECT symbol, tick_decimals FROM stats.instruments"))
    last: dict[str, dict[str, int]] = defaultdict(dict)
    for symbol, price, aggressor in ds.conn.execute(
        "SELECT symbol, price, aggressor_side FROM stats.trade_log ORDER BY trade_id"
    ):
        last[symbol]["prev_close"] = price
        if aggressor == "BUY":
            last[symbol]["last_buy_price"] = price
        elif aggressor == "SELL":
            last[symbol]["last_sell_price"] = price
    closed = {
        s
        for (s,) in ds.conn.execute(
            "SELECT DISTINCT symbol FROM stats.daily_stats WHERE close_price IS NOT NULL"
        )
    }
    samples: list[Sample] = []
    for symbol, persisted in sorted(stats.items()):
        decimals = td.get(symbol, 2)
        for key, expected in last.get(symbol, {}).items():
            got = _ticks(persisted.get(key), decimals)
            if got != expected:
                samples.append(
                    {"symbol": symbol, "field": key, "book_stats": got, "trade_log": expected}  # fmt: skip
                )
        if persisted.get("prev_close") is None and symbol in closed:
            samples.append(
                {"symbol": symbol, "field": "prev_close", "error": "empty, but daily_stats has a close"}  # fmt: skip
            )
    for symbol in sorted(last.keys() - stats.keys()):
        samples.append({"symbol": symbol, "error": "traded, not in book_stats.json"})
    note = f"{len(stats)} symbols, {len(last)} traded"
    return Outcome(len(samples), samples, note)


@check(
    "F6",
    "cross-store",
    "depth.* figures (depth, imbalance, microprice, cost to move) follow from book.*",
    needs=(),
)
def depth_follows_book(ds: Dataset) -> Outcome:
    """Each depth.<SYM> recomputed from the book.<SYM> published just before
    it: the window is the book's last price ± tolerance_ticks."""
    m = market_pass(ds)
    note = f"{m.depths} depth messages, {m.depths_unpaired} not right after their book"
    return Outcome(m.f6_count + m.depths_unpaired, m.f6, note)
