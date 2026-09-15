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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from edumatcher.engine.order_book import OrderBook
from edumatcher.models.order import (
    Order,
    OrderStatus,
    OrderType,
    Side,
    SmpAction,
    TIF,
)
from edumatcher.models.price import from_ticks, to_ticks_exact, to_ticks_or_none
from edumatcher.models.trade import reset_trade_ids_for_tests, set_run_seq

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
    """Return FIX lines that seed liquidity for one symbol.

    These carry readable ids rather than the random hex the test orders use.
    The seed is deterministic and needs no randomness to stay reproducible,
    and an id that says what it is makes the file readable when a diff sends
    you looking at it. Order ids are opaque to the engine either way.
    """
    mid = REF_PRICE[symbol]
    levels = _LEVELS_MSFT if symbol == "MSFT" else _LEVELS_STD
    extra = _DEPTH_EXTRA.get(symbol, [])

    lines: list[str] = []
    for offset, qty in list(levels) + list(extra):
        bid = round(mid - offset, 2)
        ask = round(mid + offset, 2)
        for side, price in (("BUY", bid), ("SELL", ask)):
            order_id = f"mm-{symbol}-{len(lines):03d}"
            lines.append(
                f"NEW|ID={order_id}|SYM={symbol}|SIDE={side}|TYPE=LIMIT"
                f"|QTY={qty}|PRICE={price:.2f}|TIF=DAY"
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


def _new_order_line(rng: random.Random, symbol: str, order_id: str) -> str:
    """Return a single random FIX line for the given symbol.

    The line names its own order id so that a later AMEND can refer to it.
    """
    mid = REF_PRICE[symbol]
    half_s = (_LEVELS_MSFT if symbol == "MSFT" else _LEVELS_STD)[0][0]

    side_str = rng.choice(["BUY", "SELL"])
    otype = rng.choices(_TYPE_NAMES, weights=_TYPE_WEIGHTS, k=1)[0]
    qty = rng.randrange(1, 11) * 50  # 50 … 500

    # Whether this order is "near market" (more likely to match) or "away"
    near = rng.random() < 0.60

    if otype == "MARKET":
        return f"NEW|ID={order_id}|SYM={symbol}|SIDE={side_str}|TYPE=MARKET|QTY={qty}"

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
        return f"NEW|ID={order_id}|SYM={symbol}|SIDE={side_str}|TYPE=LIMIT|QTY={qty}|PRICE={price:.2f}"

    if otype in ("FOK", "IOC"):
        if side_str == "BUY":
            price = round(mid + half_s * rng.uniform(-1.5, 2.0), 2)
        else:
            price = round(mid + half_s * rng.uniform(-2.0, 1.5), 2)
        return f"NEW|ID={order_id}|SYM={symbol}|SIDE={side_str}|TYPE={otype}|QTY={qty}|PRICE={price:.2f}"

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
            f"NEW|ID={order_id}|SYM={symbol}|SIDE={side_str}|TYPE=ICEBERG"
            f"|QTY={total_qty}|PRICE={price:.2f}|VISIBLE={visible}"
        )

    # STOP — triggers when last_trade_price crosses the stop level
    if otype == "STOP":
        if side_str == "BUY":
            stop = round(mid + half_s * rng.uniform(0.5, 3.0), 2)
        else:
            stop = round(mid - half_s * rng.uniform(0.5, 3.0), 2)
        return f"NEW|ID={order_id}|SYM={symbol}|SIDE={side_str}|TYPE=STOP|QTY={qty}|STOP={stop:.2f}"

    # STOP_LIMIT
    if side_str == "BUY":
        stop = round(mid + half_s * rng.uniform(0.5, 3.0), 2)
        limit = round(stop + half_s * rng.uniform(0.1, 0.5), 2)
    else:
        stop = round(mid - half_s * rng.uniform(0.5, 3.0), 2)
        limit = round(stop - half_s * rng.uniform(0.1, 0.5), 2)
    return (
        f"NEW|ID={order_id}|SYM={symbol}|SIDE={side_str}|TYPE=STOP_LIMIT"
        f"|QTY={qty}|STOP={stop:.2f}|PRICE={limit:.2f}"
    )


# ---------------------------------------------------------------------------
# Amendments (task: ~30% of the dataset)
# ---------------------------------------------------------------------------

#: Share of test lines that act on an order already resting rather than
#: submitting a new one.
#: Test lines per run. Ten thousand is enough that the amendment paths are
#: exercised thousands of times rather than tens, and the paper trader does
#: it in under a second.
DEFAULT_COUNT = 10_000

AMEND_SHARE = 0.30

#: Share of price amendments that reprice *through* the opposite best rather
#: than nudging. Without these the marketable-amend path is never reached --
#: see :func:`_amended_price`.
AGGRESSIVE_AMEND_SHARE = 0.35

#: What an amendment does, and how often. Weighted rather than uniform so the
#: common cases stay common: a quantity reduction keeps time priority while a
#: price change or an increase loses it (OrderBook.amend_order), and both
#: paths are worth exercising far more than the rarer "change everything".
_AMEND_KINDS = [
    ("price", 30),
    ("qty_down", 20),
    ("qty_up", 20),
    ("both", 10),
    ("cancel", 20),
]
_AMEND_NAMES = [k for k, _ in _AMEND_KINDS]
_AMEND_WEIGHTS = [w for _, w in _AMEND_KINDS]

_TERMINAL = (
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED,
    OrderStatus.EXPIRED,
)

#: Only these rest in the order index and only these can be amended
#: (OrderBook.amend_order). A MARKET or IOC order never rests, and a pending
#: STOP lives in a separate heap the amend path does not reach.
_AMENDABLE = (OrderType.LIMIT, OrderType.ICEBERG)


def _order_id(rng: random.Random) -> str:
    """A deterministic order id.

    ``Order.create`` mints a fresh random one, which would make ``--seed 42``
    produce a different dataset every run -- and the ids have to be *in* the
    file, because an AMEND names the order it amends and the paper trader and
    the engine must agree about which order that is. They can: the submitting
    gateway assigns the id and the engine adopts it from the wire
    (``_handle_new_order`` reads ``Order.from_dict``), so the generator is
    free to choose them.
    """
    return f"{rng.getrandbits(128):032x}"


def _amended_price(rng: random.Random, order: Order, book: OrderBook) -> float:
    """The new price for a price amendment.

    Two shapes, because they exercise different halves of the engine. A small
    nudge leaves the order resting and tests re-queueing and the priority
    rules. A price *through* the opposite best makes the amend marketable, and
    the engine then pulls the re-inserted order back out and runs it through
    matching -- cancel/replace semantics, so that an amend cannot leave the
    book crossed (H2).

    Only nudging was the original mistake and it was silent: the MM seed
    spread is at least 0.25 wide and the nudge was at most 0.03, so no
    amendment in ten thousand ever crossed, and deleting the whole re-match
    branch from the paper trader did not fail a single test.

    ``order.amend`` is checked with ``to_ticks_exact``, so the result has to
    land on the tick grid -- two decimals here, so two decimals out.
    """
    resting = from_ticks(order.price_ticks or 0, order.symbol)
    if rng.random() < AGGRESSIVE_AMEND_SHARE:
        opposite = (
            book.best_ask_ticks() if order.side == Side.BUY else book.best_bid_ticks()
        )
        if opposite is not None:
            through = from_ticks(opposite, order.symbol)
            step = 0.01 if order.side == Side.BUY else -0.01
            return max(round(through + step, 2), 0.01)
    nudge = rng.choice([-0.03, -0.02, -0.01, 0.01, 0.02, 0.03])
    return max(round(resting + nudge, 2), 0.01)


def _amend_line(rng: random.Random, order: Order, book: OrderBook) -> str:
    """One AMEND or CANCEL against an order that is resting right now.

    Picking blind from every id ever issued was the obvious alternative and is
    not worth it: of ten thousand orders only four or five hundred are still
    resting at the end, so most amendments would be rejected as "order not
    found" and the dataset would exercise the rejection path rather than
    amendment.

    ``PRICE`` here is **display money**, matching ``order.amend`` -- the one
    engine-inbound message that does not carry ticks, because a gateway
    cannot convert without knowing the resting order's symbol (§5.3.1).
    """
    kind = rng.choices(_AMEND_NAMES, weights=_AMEND_WEIGHTS, k=1)[0]
    if kind == "cancel":
        return f"CANCEL|ID={order.id}"

    parts = [f"AMEND|ID={order.id}"]
    if kind in ("price", "both"):
        assert order.price_ticks is not None
        parts.append(f"PRICE={_amended_price(rng, order, book):.2f}")
    if kind in ("qty_down", "qty_up", "both"):
        filled = order.quantity - order.remaining_qty
        if kind == "qty_down":
            # Must still exceed what has already traded, or amend_order
            # refuses it -- a rule worth honouring most of the time so that
            # most reductions actually reduce.
            low = filled + 1
            qty = rng.randint(low, order.quantity) if low < order.quantity else low
        else:
            qty = order.quantity + rng.randrange(1, 5) * 50
        parts.append(f"QTY={qty}")
    return "|".join(parts)


# ---------------------------------------------------------------------------
# FIX-line parser  (replicates gateway + engine logic)
# ---------------------------------------------------------------------------


def _fields(line: str) -> tuple[str, dict[str, str]] | None:
    """``(verb, fields)`` for a dataset line, or None for a blank or comment."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = line.split("|")
    kv: dict[str, str] = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            kv[k.upper()] = v
    return parts[0].upper(), kv


def parse_fix_line(line: str, gateway_id: str = "PAPER01") -> Optional[Order]:
    """Parse a FIX-like NEW order line into an Order object."""
    parsed = _fields(line)
    if parsed is None or parsed[0] != "NEW":
        return None
    _verb, kv = parsed

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

    order = Order.create(
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
    # The dataset names the id so that a later AMEND can refer to it, and so
    # that the paper trader and the engine mean the same order by it.
    if "ID" in kv:
        order.id = kv["ID"]
    return order


# ---------------------------------------------------------------------------
# Paper trader — uses OrderBook directly, no ZMQ
# ---------------------------------------------------------------------------


def _snapshot_for_result(book: OrderBook) -> dict[str, Any]:
    """Strip snapshot down to the fields used for comparison."""
    snap = book.snapshot()
    return {
        "bids": [{"price": b["price"], "qty": b["qty"]} for b in snap["bids"]],
        "asks": [{"price": a["price"], "qty": a["qty"]} for a in snap["asks"]],
        "last_price": snap["last_price"],
        "last_buy_price": snap["last_buy_price"],
        "last_sell_price": snap["last_sell_price"],
    }


def _track(events: list[Order], resting: dict[str, str]) -> None:
    """Keep the live set in step with what the book just did.

    ``process`` reports every order whose status changed, which is how a
    resting order that was consumed by someone else's aggressor leaves the
    set without being looked up.
    """
    for event in events:
        if event.status in _TERMINAL:
            resting.pop(event.id, None)


def _rest_if_live(order: Order, resting: dict[str, str]) -> None:
    if order.order_type in _AMENDABLE and order.status not in _TERMINAL:
        resting[order.id] = order.symbol


def apply_line(line: str, books: dict[str, OrderBook], resting: dict[str, str]) -> int:
    """Apply one dataset line to the paper books. Returns trades produced.

    -1 means the line was not applied at all -- a comment, or an order for a
    symbol this dataset does not cover.
    """
    parsed = _fields(line)
    if parsed is None:
        return -1
    verb, kv = parsed

    if verb == "NEW":
        order = parse_fix_line(line)
        if order is None or order.symbol not in books:
            return -1
        trades, events = books[order.symbol].process(order)
        _track(events, resting)
        _rest_if_live(order, resting)
        return len(trades)

    order_id = kv.get("ID")
    symbol = resting.get(order_id or "")
    if order_id is None or symbol is None:
        # The dataset only ever names an order that was resting when the line
        # was generated, so this is a line that has been hand-edited or a
        # file that has drifted from its own paper result.
        return -1
    book = books[symbol]

    if verb == "CANCEL":
        book.cancel_order(order_id)
        resting.pop(order_id, None)
        return 0

    if verb != "AMEND":
        return -1
    return _apply_amend(kv, order_id, symbol, book, resting)


def _apply_amend(
    kv: dict[str, str],
    order_id: str,
    symbol: str,
    book: OrderBook,
    resting: dict[str, str],
) -> int:
    """The amend path, as ``Engine._handle_amend`` performs it.

    Two steps, not one. ``amend_order`` re-queues the order at its new price
    and quantity, and then a *marketable* amend is pulled back out and run
    through matching -- cancel/replace semantics, so an amend cannot leave the
    book crossed. Doing only the first half would make the paper trader and
    the engine disagree on exactly the orders that amended into the spread.

    The gates the engine applies around this (collars, order limits, session
    and halt state) are all inert under the verification config, which
    configures none of them.
    """
    new_price = float(kv["PRICE"]) if "PRICE" in kv else None
    new_qty = int(kv["QTY"]) if "QTY" in kv else None
    amended, _priority_reset, _err = book.amend_order(
        order_id,
        new_price=to_ticks_exact(new_price, symbol) if new_price is not None else None,
        new_qty=new_qty,
    )
    if amended is None:
        resting.pop(order_id, None)
        return 0

    if amended.price_ticks is None or amended.status in _TERMINAL:
        return 0
    if amended.side == Side.BUY:
        best = book.best_ask_ticks()
        marketable = best is not None and amended.price_ticks >= best
    else:
        best = book.best_bid_ticks()
        marketable = best is not None and amended.price_ticks <= best
    if not marketable:
        return 0

    book.cancel_order(order_id)
    amended.status = OrderStatus.NEW
    trades, events = book.process(amended, match=True)
    _track(events, resting)
    _rest_if_live(amended, resting)
    return len(trades)


@dataclass
class Dataset:
    """A generated session and the book state it produces."""

    mm_lines: list[str]
    test_lines: list[str]
    result: dict[str, dict[str, Any]]
    counts: dict[str, int]


def generate(rng: random.Random, count: int) -> Dataset:
    """Generate *count* test lines, paper-trading as it goes.

    Generation and simulation are one pass because an amendment has to name
    an order that is resting *at that point in the stream*, and only the book
    knows which those are. Generating the whole file first and then replaying
    it -- which is what this did while every line was a NEW -- cannot answer
    that question.
    """
    # A trade id is f"{run_seq:06d}-{trade_seq:09d}" and the engine sets the
    # run half at startup from a durable counter. Nothing does that here --
    # this is an OrderBook in a bare process -- so minting the first trade
    # raised RuntimeError. Zero says "paper run", and the comparison never
    # looks at a trade id: it compares book state.
    reset_trade_ids_for_tests()
    set_run_seq(0)

    books: dict[str, OrderBook] = {sym: OrderBook(sym) for sym in SYMBOLS}
    resting: dict[str, str] = {}
    counts = {"new": 0, "amend": 0, "cancel": 0, "trades": 0, "skipped": 0}

    mm_lines = build_mm_orders()
    for raw in mm_lines:
        trades = apply_line(raw, books, resting)
        if trades < 0:
            counts["skipped"] += 1
        else:
            counts["new"] += 1
            counts["trades"] += trades

    lines: list[str] = []

    sym_cycle = [SYMBOLS[i % len(SYMBOLS)] for i in range(count)]
    rng.shuffle(sym_cycle)
    for symbol in sym_cycle:
        if resting and rng.random() < AMEND_SHARE:
            target_id = rng.choice(sorted(resting))
            target = books[resting[target_id]].get_order(target_id)
            # sorted() because a set's iteration order is not reproducible
            # across runs, and this file has to be a function of its seed.
            if target is not None:
                line = _amend_line(rng, target, books[target.symbol])
                counts["cancel" if line.startswith("CANCEL") else "amend"] += 1
            else:
                line = _new_order_line(rng, symbol, _order_id(rng))
                counts["new"] += 1
        else:
            line = _new_order_line(rng, symbol, _order_id(rng))
            counts["new"] += 1
        lines.append(line)
        counts["trades"] += max(apply_line(line, books, resting), 0)

    return Dataset(
        mm_lines=mm_lines,
        test_lines=lines,
        result={sym: _snapshot_for_result(book) for sym, book in books.items()},
        counts=counts,
    )


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
        "--count",
        type=int,
        default=DEFAULT_COUNT,
        help=f"Number of test lines (default: {DEFAULT_COUNT})",
    )
    args = ap.parse_args()

    VERIFY_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[GEN] Generating and paper-trading {args.count} line(s) …")
    dataset = generate(random.Random(args.seed), args.count)

    MM_FIX_FILE.write_text("\n".join(dataset.mm_lines) + "\n", encoding="utf-8")
    n_mm = sum(1 for line in dataset.mm_lines if line.startswith("NEW"))
    print(f"[GEN] Wrote {n_mm} MM orders  → {MM_FIX_FILE}")

    ENGINE_CONFIG.write_text(build_engine_config(), encoding="utf-8")
    print(f"[GEN] Wrote engine config    → {ENGINE_CONFIG}")

    TEST_FIX_FILE.write_text("\n".join(dataset.test_lines) + "\n", encoding="utf-8")
    counts = dataset.counts
    print(
        f"[GEN] Wrote {len(dataset.test_lines)} test lines  → {TEST_FIX_FILE}\n"
        f"      {counts['new']} new, {counts['amend']} amend, "
        f"{counts['cancel']} cancel → {counts['trades']} trades"
    )

    PAPER_RESULT.write_text(
        json.dumps(dataset.result, indent=2, default=str) + "\n", encoding="utf-8"
    )
    for sym, snap in dataset.result.items():
        print(
            f"  {sym:6s}  bids={len(snap['bids'])} levels  "
            f"asks={len(snap['asks'])} levels  last={snap['last_price']}"
        )
    print(f"[GEN] Saved paper result     → {PAPER_RESULT}")
    print("[GEN] Done — run replay_to_engine.py to get the engine result.")


if __name__ == "__main__":
    main()
