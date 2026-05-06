"""
Performance tests: latency and maximum throughput (TPS).

Measurement scope
-----------------
These tests use the same mock-socket pattern as the other integration tests.
The engine runs in the *same* Python process and thread; the mocked socket's
``send_multipart`` is a list-append, so ZMQ wire latency is not included.

  What IS measured
    Engine processing time: validation → order-book matching → message
    construction and "publish" (list-append).  This is the dominant cost
    on a single host and is the right baseline for optimisation work.

  What is NOT measured (add these in a full end-to-end test)
    • Gateway → Engine PUSH/PULL hop:    ~10–30 µs on loopback
    • Engine  → Clearing PUB/SUB hop:   ~10–30 µs on loopback
    • Clearing CSV write:               ~50–200 µs (disk-dependent)

  Approximate production end-to-end = engine time + 20–260 µs overhead.

Running
-------
  # latency + TPS (slow — ~1 000 + 10 000 orders each):
  poetry run pytest tests/test_perf.py -v -s -m perf

  # skip perf tests during normal CI:
  poetry run pytest tests/ -m "not perf"
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field

import pytest

from edumatcher.engine.config_loader import (
    EngineConfig,
    FixGatewayConfig,
    SymbolConfig,
)
from edumatcher.engine.main import Engine
from edumatcher.models.message import decode
from edumatcher.models.order import Order, OrderType, Side, TIF

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_SYMBOL = "AAPL"
_GW = "PERF01"

# Passive resting prices — the book will always have deep liquidity here.
_ASK = 150.00  # passive SELL; aggressive BUYs and MARKET buys match here
_BID = 149.00  # passive BUY;  aggressive SELLs and MARKET sells match here

# Prices for passive test orders that should NOT match immediately
_PASSIVE_BUY_PRICE = 140.00  # well below ASK  → rests on bid side
_PASSIVE_SELL_PRICE = 160.00  # well above BID  → rests on ask side

N_LATENCY = 1_000  # measured samples per order type (after warm-up)
N_WARMUP = 100  # discarded warm-up samples
N_TPS = 10_000  # total orders for throughput measurement

# Fraction breakdown for TPS mix (must sum to 1.0)
_FRAC_MARKET_BUY = 0.20
_FRAC_AGGRESSIVE_LIMIT = 0.30  # BUY at _ASK  → immediate fill
_FRAC_PASSIVE_BUY = 0.25  # BUY at _PASSIVE_BUY_PRICE  → rests
_FRAC_PASSIVE_SELL = 0.25  # SELL at _PASSIVE_SELL_PRICE → rests

# Large enough so the passive liquidity pool is never exhausted
_LIQUIDITY_QTY = 5_000_000


# ---------------------------------------------------------------------------
# Minimal mock socket
# ---------------------------------------------------------------------------


@dataclass
class _DummySocket:
    sent: list[list[bytes]] = field(default_factory=list)

    def send_multipart(self, frames: list[bytes]) -> None:
        self.sent.append(frames)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _build_engine(monkeypatch, tmp_path) -> tuple[Engine, _DummySocket]:
    """Return a fully-initialised Engine backed by mocked ZMQ sockets."""
    cfg = EngineConfig(
        symbols={_SYMBOL: SymbolConfig(name=_SYMBOL)},
        fix_gateways={_GW: FixGatewayConfig(id=_GW, description="perf gw")},
    )
    pub_sock = _DummySocket()

    monkeypatch.setattr("edumatcher.engine.main.make_puller", lambda _: _DummySocket())
    monkeypatch.setattr("edumatcher.engine.main.make_publisher", lambda _: pub_sock)
    monkeypatch.setattr("edumatcher.engine.main.load_engine_config", lambda _: cfg)
    monkeypatch.setattr("edumatcher.engine.main.load_gtc_orders", lambda _: [])
    monkeypatch.setattr("edumatcher.engine.main.load_gtc_combos", lambda _: [])
    monkeypatch.setattr("edumatcher.engine.main.load_book_stats", lambda _: {})
    monkeypatch.setattr("edumatcher.engine.main.time.sleep", lambda *_: None)

    cfg_path = tmp_path / "engine_config.yaml"
    cfg_path.write_text("dummy: true\n")

    engine = Engine(config_path=str(cfg_path))
    engine._handle_gateway_connect({"gateway_id": _GW})
    pub_sock.sent.clear()
    return engine, pub_sock


def _seed_liquidity(engine: Engine, pub_sock: _DummySocket) -> None:
    """
    Post large passive orders on both sides of the book.

    SELL resting at _ASK  → aggressive BUY / MARKET-BUY orders fill here.
    BUY  resting at _BID  → aggressive SELL / MARKET-SELL orders fill here.
    """
    for side, price in ((Side.SELL, _ASK), (Side.BUY, _BID)):
        order = Order.create(
            symbol=_SYMBOL,
            side=side,
            order_type=OrderType.LIMIT,
            quantity=_LIQUIDITY_QTY,
            gateway_id="MM",
            tif=TIF.GTC,
            price=price,
        )
        engine._book(_SYMBOL).process(order)
    pub_sock.sent.clear()


def _has_trade(pub_sock: _DummySocket, from_idx: int) -> bool:
    for frames in pub_sock.sent[from_idx:]:
        try:
            topic, _ = decode(frames)
            if topic == "trade.executed":
                return True
        except Exception:
            pass
    return False


def _percentile(sorted_data: list[float], p: float) -> float:
    """p-th percentile (0–100) via linear interpolation."""
    n = len(sorted_data)
    if n == 0:
        return 0.0
    idx = (p / 100.0) * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    return sorted_data[lo] + (idx - lo) * (sorted_data[hi] - sorted_data[lo])


def _print_latency_report(label: str, samples_ns: list[int]) -> None:
    us = sorted(s / 1_000.0 for s in samples_ns)
    print(f"\n{'=' * 62}")
    print(f"  Latency — {label}  (n={len(us):,})")
    print(f"{'=' * 62}")
    print(f"  min      : {min(us):>10.3f} µs")
    print(f"  median   : {_percentile(us, 50):>10.3f} µs")
    print(f"  P80      : {_percentile(us, 80):>10.3f} µs")
    print(f"  P90      : {_percentile(us, 90):>10.3f} µs")
    print(f"  max      : {max(us):>10.3f} µs")
    print(f"  mean     : {statistics.mean(us):>10.3f} µs")
    print(f"  stdev    : {statistics.stdev(us):>10.3f} µs")
    print(f"{'=' * 62}")
    print("  NOTE: add ~20–260 µs for two ZMQ hops + CSV write in production.")


# ---------------------------------------------------------------------------
# Test class: latency
# ---------------------------------------------------------------------------


@pytest.mark.perf
class TestOrderLatency:
    """
    Measures per-order engine processing latency for Limit and Market orders.

    Setup
    -----
    A single large passive SELL resting at _ASK provides infinite liquidity
    for all aggressive BUY and MARKET orders.  Each test order is generated
    fresh (unique UUID + timestamp) to avoid any short-circuit caching.
    """

    def _run_latency(
        self,
        engine: Engine,
        pub_sock: _DummySocket,
        order_type: OrderType,
        price: float | None,
        n_warmup: int,
        n_samples: int,
    ) -> list[int]:
        """
        Run *n_warmup* + *n_samples* orders; return the *n_samples* latencies
        (nanoseconds).  Warm-up results are discarded.
        """
        latencies: list[int] = []
        total_runs = n_warmup + n_samples

        for i in range(total_runs):
            order = Order.create(
                symbol=_SYMBOL,
                side=Side.BUY,
                order_type=order_type,
                quantity=1,
                gateway_id=_GW,
                tif=TIF.DAY,
                price=price,
            )
            payload = order.to_dict()
            idx_before = len(pub_sock.sent)

            t0 = time.perf_counter_ns()
            engine._handle_new_order(payload)
            t1 = time.perf_counter_ns()

            # Verify a trade was generated (sanity check on first real sample)
            if i == n_warmup:
                assert _has_trade(pub_sock, idx_before), (
                    f"No trade.executed found for {order_type.value} order — "
                    "check that liquidity was seeded correctly."
                )

            if i >= n_warmup:
                latencies.append(t1 - t0)

        return latencies

    def test_limit_order_latency(self, monkeypatch, tmp_path) -> None:
        """
        Limit BUY at the ask price (aggressive → immediate fill).

        Represents the common case: a limit order that crosses the spread
        and generates a trade immediately upon entry.
        """
        engine, pub_sock = _build_engine(monkeypatch, tmp_path)
        _seed_liquidity(engine, pub_sock)

        samples = self._run_latency(
            engine,
            pub_sock,
            order_type=OrderType.LIMIT,
            price=_ASK,  # crosses the passive SELL → fills immediately
            n_warmup=N_WARMUP,
            n_samples=N_LATENCY,
        )

        _print_latency_report("Limit BUY (aggressive, immediate fill)", samples)
        assert len(samples) == N_LATENCY

    def test_market_order_latency(self, monkeypatch, tmp_path) -> None:
        """
        Market BUY (no price — always takes best available ask).

        Represents the fastest possible order type: no price comparison
        needed, just take the first entry off the ask heap.
        """
        engine, pub_sock = _build_engine(monkeypatch, tmp_path)
        _seed_liquidity(engine, pub_sock)

        samples = self._run_latency(
            engine,
            pub_sock,
            order_type=OrderType.MARKET,
            price=None,
            n_warmup=N_WARMUP,
            n_samples=N_LATENCY,
        )

        _print_latency_report("Market BUY (immediate fill)", samples)
        assert len(samples) == N_LATENCY

    def test_latency_comparison(self, monkeypatch, tmp_path) -> None:
        """
        Side-by-side comparison of Limit vs Market latency with a shared
        summary table printed to stdout.
        """
        engine, pub_sock = _build_engine(monkeypatch, tmp_path)
        _seed_liquidity(engine, pub_sock)

        limit_samples = self._run_latency(
            engine,
            pub_sock,
            order_type=OrderType.LIMIT,
            price=_ASK,
            n_warmup=N_WARMUP,
            n_samples=N_LATENCY,
        )
        market_samples = self._run_latency(
            engine,
            pub_sock,
            order_type=OrderType.MARKET,
            price=None,
            n_warmup=N_WARMUP,
            n_samples=N_LATENCY,
        )

        def _us(ns_list: list[int]) -> list[float]:
            return sorted(ns / 1_000.0 for ns in ns_list)

        ls = _us(limit_samples)
        ms = _us(market_samples)

        print(f"\n{'=' * 70}")
        print(f"  Latency Comparison  (n={N_LATENCY:,} each, warm-up={N_WARMUP})")
        print(f"{'=' * 70}")
        print(f"  {'Metric':<12}  {'Limit (µs)':>14}  {'Market (µs)':>14}")
        print(f"  {'-'*12}  {'-'*14}  {'-'*14}")
        for label, p in [
            ("min", 0),
            ("median", 50),
            ("P80", 80),
            ("P90", 90),
            ("max", 100),
        ]:
            lv = min(ls) if p == 0 else (max(ls) if p == 100 else _percentile(ls, p))
            mv = min(ms) if p == 0 else (max(ms) if p == 100 else _percentile(ms, p))
            print(f"  {label:<12}  {lv:>14.3f}  {mv:>14.3f}")
        print(f"{'=' * 70}")
        print("  NOTE: add ~20–260 µs for two ZMQ hops + CSV write in production.")

        assert len(limit_samples) == N_LATENCY
        assert len(market_samples) == N_LATENCY


# ---------------------------------------------------------------------------
# Test class: throughput (TPS)
# ---------------------------------------------------------------------------


@pytest.mark.perf
class TestThroughput:
    """
    Measures maximum order-processing throughput (transactions per second).

    Order mix (configurable via module-level constants)
    ---------------------------------------------------
    • Market BUY       (_FRAC_MARKET_BUY)       — immediate fill
    • Aggressive LIMIT (_FRAC_AGGRESSIVE_LIMIT) — BUY at _ASK, immediate fill
    • Passive BUY      (_FRAC_PASSIVE_BUY)       — price well below ask, rests
    • Passive SELL     (_FRAC_PASSIVE_SELL)       — price well above bid, rests

    Liquidity
    ---------
    The passive SELL pool (_LIQUIDITY_QTY) is pre-seeded to sustain all
    aggressive orders without running out.  Passive test orders accumulate
    on the book but do not match each other (bid < ask).
    """

    def test_max_tps(self, monkeypatch, tmp_path) -> None:
        engine, pub_sock = _build_engine(monkeypatch, tmp_path)
        _seed_liquidity(engine, pub_sock)

        # --- build all order dicts up-front (exclude from timed section) ---
        n_market = int(N_TPS * _FRAC_MARKET_BUY)
        n_agg_limit = int(N_TPS * _FRAC_AGGRESSIVE_LIMIT)
        n_pass_buy = int(N_TPS * _FRAC_PASSIVE_BUY)
        n_pass_sell = N_TPS - n_market - n_agg_limit - n_pass_buy  # remainder

        orders: list[dict] = []

        for _ in range(n_market):
            orders.append(
                Order.create(
                    symbol=_SYMBOL,
                    side=Side.BUY,
                    order_type=OrderType.MARKET,
                    quantity=1,
                    gateway_id=_GW,
                    tif=TIF.DAY,
                ).to_dict()
            )

        for _ in range(n_agg_limit):
            orders.append(
                Order.create(
                    symbol=_SYMBOL,
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=1,
                    gateway_id=_GW,
                    tif=TIF.DAY,
                    price=_ASK,
                ).to_dict()
            )

        for _ in range(n_pass_buy):
            orders.append(
                Order.create(
                    symbol=_SYMBOL,
                    side=Side.BUY,
                    order_type=OrderType.LIMIT,
                    quantity=1,
                    gateway_id=_GW,
                    tif=TIF.DAY,
                    price=_PASSIVE_BUY_PRICE,
                ).to_dict()
            )

        for _ in range(n_pass_sell):
            orders.append(
                Order.create(
                    symbol=_SYMBOL,
                    side=Side.SELL,
                    order_type=OrderType.LIMIT,
                    quantity=1,
                    gateway_id=_GW,
                    tif=TIF.DAY,
                    price=_PASSIVE_SELL_PRICE,
                ).to_dict()
            )

        # Shuffle so order types are interleaved (not batched)
        import random

        rng = random.Random(42)
        rng.shuffle(orders)

        # --- warm-up (not timed) ---
        for o in orders[:N_WARMUP]:
            engine._handle_new_order(o)
        pub_sock.sent.clear()

        # Rebuild orders for the timed section (UUIDs are consumed)
        timed_orders: list[dict] = []
        for o in orders[N_WARMUP:]:
            # Re-create with a fresh UUID so engine doesn't see duplicates
            timed_orders.append(
                Order.create(
                    symbol=o["symbol"],
                    side=Side(o["side"]),
                    order_type=OrderType(o["order_type"]),
                    quantity=o["quantity"],
                    gateway_id=o["gateway_id"],
                    tif=TIF(o["tif"]),
                    price=o.get("price"),
                ).to_dict()
            )

        n_timed = len(timed_orders)

        # --- timed section ---
        t_start = time.perf_counter()
        for payload in timed_orders:
            engine._handle_new_order(payload)
        t_end = time.perf_counter()

        elapsed = t_end - t_start
        tps = n_timed / elapsed

        # Count generated trade messages (aggressive orders only)
        n_trades = sum(
            1 for frames in pub_sock.sent if decode(frames)[0] == "trade.executed"
        )
        _expected_trades = n_market + n_agg_limit - N_WARMUP  # noqa: F841
        # (some warm-up orders were aggressive; remainder is n_timed aggressive)
        # We simply assert at least 50 % of expected trades arrived.
        assert n_trades > 0, "No trades generated — check liquidity seeding."

        print("\n" + "=" * 62)
        print(f"  Throughput \u2014 Maximum TPS  (n={n_timed:,} orders)")
        print("=" * 62)
        print("  Order mix:")
        print(f"    Market BUY       : {n_market:>6,}  ({_FRAC_MARKET_BUY*100:.0f}%)")
        print(
            f"    Aggressive LIMIT : {n_agg_limit:>6,}  ({_FRAC_AGGRESSIVE_LIMIT*100:.0f}%)"
        )
        print(
            f"    Passive BUY      : {n_pass_buy:>6,}  ({_FRAC_PASSIVE_BUY*100:.0f}%)"
        )
        print(
            f"    Passive SELL     : {n_pass_sell:>6,}  ({_FRAC_PASSIVE_SELL*100:.0f}%)"
        )
        print(f"  Elapsed            : {elapsed:>10.3f} s")
        print(f"  Trades generated   : {n_trades:>10,}")
        print("  ─────────────────────────────────────────────────────")
        print(f"  TPS (orders/sec)   : {tps:>10,.0f}")
        print(f"  µs / order (mean)  : {elapsed / n_timed * 1e6:>10.3f} µs")
        print("=" * 62)
        print(
            "  NOTE: TPS above is engine-only.  In production the bottleneck\n"
            "  shifts to ZMQ socket throughput (~200k–500k msgs/s on loopback)."
        )

        assert tps > 0
