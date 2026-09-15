#!/usr/bin/env python3
"""
gen_verification_set.py — Generate a deterministic matching-engine verification dataset.

Steps performed
---------------
1.  Build market-maker (MM) seed orders for AAPL, AMAZ, MSFT, GOOG and write
    them to  data/verify/mm_orders.fix
2.  Generate <count> random single-leg orders (LIMIT, MARKET, FOK, IOC,
    ICEBERG, STOP, STOP_LIMIT) and write them to  data/verify/test_orders.fix
3.  Paper-trade the complete order stream (MM + test) directly through
    OrderBook, record every fill, and save the final per-symbol book state
    to  data/verify/paper_result.json

The .fix files are the single source of truth used by both this script and the
replay tool.  The paper_result.json is the expected ("golden") result against
which the engine's live output is compared.

Usage
-----
    poetry run python tools/gen_verification_set.py          # seed 42, 1 000 orders
    poetry run python tools/gen_verification_set.py --seed 7 --count 500
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import Order, OrderType, Side, SmpAction, TIF
from edumatcher.models.price import to_ticks_or_none
from edumatcher.models.trade import set_run_seq

# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------

VERIFY_DIR = ROOT / "data" / "verify"

MM_FIX_FILE = VERIFY_DIR / "mm_orders.fix"
TEST_FIX_FILE = VERIFY_DIR / "test_orders.fix"
PAPER_RESULT = VERIFY_DIR / "paper_result.json"
ENGINE_CONFIG = VERIFY_DIR / "verify_engine_config.yaml"

#: The id ``replay_to_engine.py`` authenticates as. The config below has
#: to admit it and nothing else.
REPLAY_GATEWAY_ID = "VERIFY01"

# ---------------------------------------------------------------------------
# Symbol definitions
# ---------------------------------------------------------------------------

SYMBOLS = ["AAPL", "AMAZ", "MSFT", "GOOG"]

# Reference mid-prices (used to size price offsets)
REF_PRICE: dict[str, float] = {
    "AAPL": 150.00,
    "AMAZ": 180.00,
    "MSFT": 420.00,
    "GOOG": 160.00,
}

# ---------------------------------------------------------------------------
# Market-maker order book initialisation
# ---------------------------------------------------------------------------
# Each symbol gets 5 bid levels and 5 ask levels.
# Level[i] = (offset_from_mid, qty).
# MSFT uses a wider spread (higher price → larger absolute tick).

_LEVELS_STD = [
    (0.25, 500),
    (0.50, 300),
    (0.75, 200),
    (1.00, 500),
    (1.25, 300),
]
_LEVELS_MSFT = [
    (0.50, 500),
    (1.00, 300),
    (1.50, 200),
    (2.00, 500),
    (2.50, 300),
]

# For extra book depth, each non-first level gets a second order at a slightly
# different quantity so the "count" column > 1.
_DEPTH_EXTRA: dict[str, list[tuple[float, int]]] = {
    "AAPL": [(0.25, 200), (0.75, 150)],
    "AMAZ": [(0.25, 150), (0.75, 200)],
    "MSFT": [(0.50, 200), (1.50, 100)],
    "GOOG": [(0.25, 250), (0.75, 150)],
}


def _mm_orders_for_symbol(symbol: str) -> list[str]:
    """Return FIX lines that seed liquidity for one symbol."""
    mid = REF_PRICE[symbol]
    levels = _LEVELS_MSFT if symbol == "MSFT" else _LEVELS_STD
    extra = _DEPTH_EXTRA.get(symbol, [])

    lines: list[str] = []
    for offset, qty in levels:
        bid = round(mid - offset, 2)
        ask = round(mid + offset, 2)
        lines.append(
            f"NEW|SYM={symbol}|SIDE=BUY|TYPE=LIMIT|QTY={qty}|PRICE={bid:.2f}|TIF=DAY"
        )
        lines.append(
            f"NEW|SYM={symbol}|SIDE=SELL|TYPE=LIMIT|QTY={qty}|PRICE={ask:.2f}|TIF=DAY"
        )

    for offset, qty in extra:
        bid = round(mid - offset, 2)
        ask = round(mid + offset, 2)
        lines.append(
            f"NEW|SYM={symbol}|SIDE=BUY|TYPE=LIMIT|QTY={qty}|PRICE={bid:.2f}|TIF=DAY"
        )
        lines.append(
            f"NEW|SYM={symbol}|SIDE=SELL|TYPE=LIMIT|QTY={qty}|PRICE={ask:.2f}|TIF=DAY"
        )
    return lines


def build_mm_orders() -> list[str]:
    """Return the full list of market-maker FIX lines for all symbols."""
    lines = []
    for sym in SYMBOLS:
        lines.append(f"# --- {sym} market-maker seed ---")
        lines.extend(_mm_orders_for_symbol(sym))
    return lines


# ---------------------------------------------------------------------------
# Random test-order generation
# ---------------------------------------------------------------------------

_ORDER_TYPES = [
    ("LIMIT", 35),
    ("MARKET", 22),
    ("FOK", 10),
    ("IOC", 10),
    ("ICEBERG", 13),
    ("STOP", 5),
    ("STOP_LIMIT", 5),
]
_TYPE_NAMES = [t for t, _ in _ORDER_TYPES]
_TYPE_WEIGHTS = [w for _, w in _ORDER_TYPES]


def _generate_one_order(rng: random.Random, symbol: str) -> str:
    """Return a single random FIX line for the given symbol."""
    mid = REF_PRICE[symbol]
    half_s = (_LEVELS_MSFT if symbol == "MSFT" else _LEVELS_STD)[0][0]

    side_str = rng.choice(["BUY", "SELL"])
    otype = rng.choices(_TYPE_NAMES, weights=_TYPE_WEIGHTS, k=1)[0]
    qty = rng.randrange(1, 11) * 50  # 50 … 500

    # Whether this order is "near market" (more likely to match) or "away"
    near = rng.random() < 0.60

    if otype == "MARKET":
        return f"NEW|SYM={symbol}|SIDE={side_str}|TYPE=MARKET|QTY={qty}"

    if otype == "LIMIT":
        if side_str == "BUY":
            price = round(
                (
                    mid + half_s * rng.uniform(-3.0, 0.8)
                    if near
                    else mid - half_s * rng.uniform(1.5, 5.0)
                ),
                2,
            )
        else:
            price = round(
                (
                    mid + half_s * rng.uniform(-0.8, 3.0)
                    if near
                    else mid + half_s * rng.uniform(1.5, 5.0)
                ),
                2,
            )
        return (
            f"NEW|SYM={symbol}|SIDE={side_str}|TYPE=LIMIT|QTY={qty}|PRICE={price:.2f}"
        )

    if otype in ("FOK", "IOC"):
        if side_str == "BUY":
            price = round(mid + half_s * rng.uniform(-1.5, 2.0), 2)
        else:
            price = round(mid + half_s * rng.uniform(-2.0, 1.5), 2)
        return (
            f"NEW|SYM={symbol}|SIDE={side_str}|TYPE={otype}|QTY={qty}|PRICE={price:.2f}"
        )

    if otype == "ICEBERG":
        if side_str == "BUY":
            price = round(mid + half_s * rng.uniform(-2.0, 0.2), 2)
        else:
            price = round(mid + half_s * rng.uniform(-0.2, 2.0), 2)
        total_qty = qty * rng.randint(2, 5)
        # The visible slice is drawn independently of the total, so it could
        # exceed it -- and an ICEBERG whose visible_qty is larger than its
        # quantity is an order the engine rejects outright (M7,
        # engine/main.py, QTY_OUT_OF_RANGE). The paper trader drives OrderBook
        # directly and never sees that validation, so every such order made
        # the two sides disagree by construction.
        visible = min(rng.choice([50, 100, 150, 200]), total_qty)
        return (
            f"NEW|SYM={symbol}|SIDE={side_str}|TYPE=ICEBERG"
            f"|QTY={total_qty}|PRICE={price:.2f}|VISIBLE={visible}"
        )

    # STOP — triggers when last_trade_price crosses the stop level
    if otype == "STOP":
        if side_str == "BUY":
            stop = round(mid + half_s * rng.uniform(0.5, 3.0), 2)
        else:
            stop = round(mid - half_s * rng.uniform(0.5, 3.0), 2)
        return f"NEW|SYM={symbol}|SIDE={side_str}|TYPE=STOP|QTY={qty}|STOP={stop:.2f}"

    # STOP_LIMIT
    if side_str == "BUY":
        stop = round(mid + half_s * rng.uniform(0.5, 3.0), 2)
        limit = round(stop + half_s * rng.uniform(0.1, 0.5), 2)
    else:
        stop = round(mid - half_s * rng.uniform(0.5, 3.0), 2)
        limit = round(stop - half_s * rng.uniform(0.1, 0.5), 2)
    return (
        f"NEW|SYM={symbol}|SIDE={side_str}|TYPE=STOP_LIMIT"
        f"|QTY={qty}|STOP={stop:.2f}|PRICE={limit:.2f}"
    )


def build_test_orders(rng: random.Random, count: int) -> list[str]:
    """Generate <count> random test orders spread evenly across all symbols."""
    lines: list[str] = []
    sym_cycle = [SYMBOLS[i % len(SYMBOLS)] for i in range(count)]
    rng.shuffle(sym_cycle)
    for sym in sym_cycle:
        lines.append(_generate_one_order(rng, sym))
    return lines


# ---------------------------------------------------------------------------
# FIX-line parser  (replicates gateway + engine logic)
# ---------------------------------------------------------------------------


def parse_fix_line(line: str, gateway_id: str = "PAPER01") -> Optional[Order]:
    """Parse a FIX-like NEW order line into an Order object."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = line.split("|")
    if not parts or parts[0].upper() != "NEW":
        return None

    kv: dict[str, str] = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            kv[k.upper()] = v

    try:
        symbol = kv["SYM"].upper()
        side = Side(kv["SIDE"].upper())
        order_type = OrderType(kv["TYPE"].upper())
        quantity = int(kv["QTY"])
        tif_val = TIF(kv.get("TIF", "DAY").upper())
        price = float(kv["PRICE"]) if "PRICE" in kv else None
        stop_price = float(kv["STOP"]) if "STOP" in kv else None
        visible = int(kv["VISIBLE"]) if "VISIBLE" in kv else None
        trail = float(kv["TRAIL"]) if "TRAIL" in kv else None
    except (KeyError, ValueError) as exc:
        print(f"[PAPER] Parse error '{line}': {exc}", file=sys.stderr)
        return None

    return Order.create(
        symbol=symbol,
        side=side,
        order_type=order_type,
        quantity=quantity,
        gateway_id=gateway_id,
        tif=tif_val,
        # The FIX line carries display money and the engine takes ticks.
        # Converting is the submitting gateway's job, and these tools are
        # standing in for one.
        price_ticks=to_ticks_or_none(price, symbol),
        stop_price_ticks=to_ticks_or_none(stop_price, symbol),
        visible_qty=visible,
        trail_offset_ticks=to_ticks_or_none(trail, symbol),
        smp_action=SmpAction.NONE,
    )


# ---------------------------------------------------------------------------
# Paper trader — uses OrderBook directly, no ZMQ
# ---------------------------------------------------------------------------


def _snapshot_for_result(book: OrderBook) -> dict:
    """Strip snapshot down to the fields used for comparison."""
    snap = book.snapshot()
    return {
        "bids": [{"price": b["price"], "qty": b["qty"]} for b in snap["bids"]],
        "asks": [{"price": a["price"], "qty": a["qty"]} for a in snap["asks"]],
        "last_price": snap["last_price"],
        "last_buy_price": snap["last_buy_price"],
        "last_sell_price": snap["last_sell_price"],
    }


def paper_trade(mm_lines: list[str], test_lines: list[str]) -> dict:
    """
    Process all orders through OrderBook instances and return final book state.

    Returns
    -------
    dict  symbol → {bids, asks, last_price, last_buy_price, last_sell_price}
    """
    # A trade id is f"{run_seq:06d}-{trade_seq:09d}" and the engine sets the
    # run half at startup from a durable counter. Nothing does that here --
    # this is an OrderBook in a bare process -- so minting the first trade
    # raised RuntimeError. Zero says "paper run", and the comparison never
    # looks at a trade id: it compares book state.
    set_run_seq(0)

    books: dict[str, OrderBook] = {sym: OrderBook(sym) for sym in SYMBOLS}

    total_trades = 0
    total_orders = 0
    skipped = 0

    t0 = time.monotonic()
    all_lines = mm_lines + test_lines

    for raw in all_lines:
        order = parse_fix_line(raw)
        if order is None:
            skipped += 1
            continue
        if order.symbol not in books:
            print(
                f"[PAPER] Unknown symbol '{order.symbol}' — skipping", file=sys.stderr
            )
            skipped += 1
            continue

        trades, _events = books[order.symbol].process(order)
        total_orders += 1
        total_trades += len(trades)

    elapsed = time.monotonic() - t0
    print(
        f"[PAPER] Processed {total_orders} orders ({skipped} skipped) "
        f"→ {total_trades} trades  ({elapsed*1000:.1f} ms)"
    )

    result: dict[str, dict] = {}
    for sym, book in books.items():
        result[sym] = _snapshot_for_result(book)
        snap = result[sym]
        print(
            f"  {sym:6s}  bids={len(snap['bids'])} levels  "
            f"asks={len(snap['asks'])} levels  "
            f"last={snap['last_price']}"
        )
    return result


# ---------------------------------------------------------------------------
# Engine configuration
# ---------------------------------------------------------------------------


def build_engine_config() -> str:
    """The engine configuration this dataset has to be replayed against.

    Written here rather than kept as a file because the two must agree and
    nothing would notice if they stopped: the symbols the config admits and
    the symbols the orders name are the same list, and it is the one above.
    The file it used to be was gitignored under ``data/**`` and had never been
    committed, so on any checkout at all the run died at step 2.

    ``sessions_enabled: false`` is the load-bearing line. It defaults to
    *true*, under which the engine starts CLOSED and waits for
    ``pm-scheduler`` to open the market -- and this script never starts one,
    so every order would come back MARKET_CLOSED and the comparison would
    report a total mismatch rather than an error. The verification wants a
    market that is simply always open.

    Only ``VERIFY01`` is admitted, so a production gateway that happens to be
    connected to the same sockets cannot bleed orders into the run.
    """
    symbols = "\n".join(
        f"  {symbol}:\n    reference_price: {REF_PRICE[symbol]:.2f}"
        for symbol in SYMBOLS
    )
    return (
        "# Generated by tools/gen_verification_set.py -- do not edit.\n"
        "# Regenerated on every run, from the same SYMBOLS and REF_PRICE the\n"
        "# orders are built from.\n"
        "\n"
        "# The engine is the whole market here: no scheduler runs, so session\n"
        "# handling has to be off or the engine sits in CLOSED and rejects\n"
        "# every order with MARKET_CLOSED.\n"
        "sessions_enabled: false\n"
        "\n"
        "gateways:\n"
        "  alf:\n"
        f"    - id: {REPLAY_GATEWAY_ID}\n"
        "\n"
        "symbols:\n"
        f"{symbols}\n"
    )


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    ap.add_argument(
        "--count", type=int, default=1000, help="Number of test orders (default: 1000)"
    )
    args = ap.parse_args()

    VERIFY_DIR.mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)

    # ── STEP 1: market-maker orders ──────────────────────────────────────────
    mm_lines = build_mm_orders()
    MM_FIX_FILE.write_text("\n".join(mm_lines) + "\n", encoding="utf-8")
    n_mm = sum(1 for l in mm_lines if l.startswith("NEW"))
    print(f"[GEN] Wrote {n_mm} MM orders  → {MM_FIX_FILE}")

    # ── STEP 1b: the engine configuration to replay them against ─────────────
    ENGINE_CONFIG.write_text(build_engine_config(), encoding="utf-8")
    print(f"[GEN] Wrote engine config    → {ENGINE_CONFIG}")

    # ── STEP 2: random test orders ───────────────────────────────────────────
    test_lines = build_test_orders(rng, args.count)
    TEST_FIX_FILE.write_text("\n".join(test_lines) + "\n", encoding="utf-8")
    print(f"[GEN] Wrote {len(test_lines)} test orders  → {TEST_FIX_FILE}")

    # ── STEP 3: paper trade ──────────────────────────────────────────────────
    print("[GEN] Running paper trade …")
    result = paper_trade(mm_lines, test_lines)

    PAPER_RESULT.write_text(
        json.dumps(result, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(f"[GEN] Saved paper result     → {PAPER_RESULT}")
    print("[GEN] Done — run replay_to_engine.py to get the engine result.")


if __name__ == "__main__":
    main()
