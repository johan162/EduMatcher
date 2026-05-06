#!/usr/bin/env python3
"""
compare_results.py — Compare paper-trade result with live-engine result.

Loads:
  data/verify/paper_result.json   expected ("golden") state
  data/verify/engine_result.json  actual engine output

For each symbol the following must agree exactly:
  • Bid price levels  (price, total visible qty) — sorted high→low
  • Ask price levels  (price, total visible qty) — sorted low→high
  • last_price        (last executed trade price)
  • last_buy_price    (last price where BUY was aggressor)
  • last_sell_price   (last price where SELL was aggressor)

Usage
-----
    poetry run python tools/compare_results.py
    poetry run python tools/compare_results.py --paper  custom_paper.json \\
                                                --engine custom_engine.json
    poetry run python tools/compare_results.py --tolerance 0.005  # 0.5% qty diff allowed
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VERIFY_DIR    = ROOT / "data" / "verify"
PAPER_RESULT  = VERIFY_DIR / "paper_result.json"
ENGINE_RESULT = VERIFY_DIR / "engine_result.json"

SYMBOLS = ["AAPL", "AMAZ", "MSFT", "GOOG"]

_GREEN  = "\033[92m"
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_RESET  = "\033[0m"
_BOLD   = "\033[1m"


def _ok(msg: str) -> None:
    print(f"  {_GREEN}✓{_RESET}  {msg}")


def _fail(msg: str) -> None:
    print(f"  {_RED}✗{_RESET}  {msg}")


def _warn(msg: str) -> None:
    print(f"  {_YELLOW}?{_RESET}  {msg}")


def _levels_equal(
    paper: list[dict],
    engine: list[dict],
    label: str,
    tolerance: float,
) -> list[str]:
    """
    Compare two lists of {price, qty} dicts.
    Returns a (possibly empty) list of human-readable mismatch descriptions.
    """
    diffs: list[str] = []

    if len(paper) != len(engine):
        diffs.append(
            f"{label}: depth mismatch — paper={len(paper)} levels, engine={len(engine)} levels"
        )
        # Still compare the levels that exist in both
        for i in range(min(len(paper), len(engine))):
            _compare_level(paper[i], engine[i], label, i, tolerance, diffs)
        # Report extra levels
        for extra in (paper if len(paper) > len(engine) else engine)[min(len(paper), len(engine)):]:
            source = "paper" if len(paper) > len(engine) else "engine"
            diffs.append(f"{label}[extra {source}] price={extra['price']} qty={extra['qty']}")
        return diffs

    for i, (p, e) in enumerate(zip(paper, engine)):
        _compare_level(p, e, label, i, tolerance, diffs)
    return diffs


def _compare_level(
    p: dict, e: dict, label: str, idx: int, tolerance: float, diffs: list[str]
) -> None:
    if abs(p["price"] - e["price"]) > 1e-9:
        diffs.append(
            f"{label}[{idx}] price: paper={p['price']}, engine={e['price']}"
        )
    # Qty comparison — absolute match by default; relative tolerance if set
    p_qty = p["qty"]
    e_qty = e["qty"]
    if tolerance == 0.0:
        if p_qty != e_qty:
            diffs.append(
                f"{label}[{idx}] qty @ {p['price']}: paper={p_qty}, engine={e_qty}"
            )
    else:
        ref = max(p_qty, e_qty, 1)
        if abs(p_qty - e_qty) / ref > tolerance:
            diffs.append(
                f"{label}[{idx}] qty @ {p['price']}: paper={p_qty}, engine={e_qty} "
                f"(diff={abs(p_qty-e_qty)/ref*100:.1f}%)"
            )


def _cmp_scalar(name: str, paper_val, engine_val) -> str | None:
    """Return a diff description if values differ, else None."""
    if paper_val is None and engine_val is None:
        return None
    if paper_val is None or engine_val is None:
        return f"{name}: paper={paper_val}, engine={engine_val}"
    if abs(float(paper_val) - float(engine_val)) > 1e-9:
        return f"{name}: paper={paper_val}, engine={engine_val}"
    return None


def compare(
    paper: dict[str, dict],
    engine: dict[str, dict],
    tolerance: float = 0.0,
    symbols: list[str] | None = None,
) -> bool:
    """
    Compare paper and engine results symbol by symbol.

    Returns True if all symbols pass, False otherwise.
    """
    check_syms = symbols or SYMBOLS
    all_pass   = True

    for sym in check_syms:
        print(f"\n{_BOLD}── {sym} ──────────────────────────────────{_RESET}")

        p = paper.get(sym)
        e = engine.get(sym)

        if p is None and e is None:
            _warn("No data in either result — symbol never traded?")
            continue
        if p is None:
            _fail("Present in engine result but missing from paper result")
            all_pass = False
            continue
        if e is None:
            _fail("Present in paper result but missing from engine result")
            all_pass = False
            continue

        diffs: list[str] = []

        diffs.extend(_levels_equal(p["bids"], e["bids"], "BID", tolerance))
        diffs.extend(_levels_equal(p["asks"], e["asks"], "ASK", tolerance))

        for name in ("last_price", "last_buy_price", "last_sell_price"):
            d = _cmp_scalar(name, p.get(name), e.get(name))
            if d:
                diffs.append(d)

        if diffs:
            all_pass = False
            for d in diffs:
                _fail(d)
        else:
            bid_s  = f"{len(p['bids'])} bid level(s)"
            ask_s  = f"{len(p['asks'])} ask level(s)"
            last_s = f"last={p['last_price']}"
            _ok(f"PASS  — {bid_s}, {ask_s}, {last_s}")

    return all_pass


def print_summary(paper: dict, engine: dict, symbols: list[str]) -> None:
    """Print a compact side-by-side table for quick visual inspection."""
    print(f"\n{_BOLD}{'Symbol':6s}  {'Paper bids':>10s}  {'Paper asks':>10s}  {'Last (P)':>12s}  {'Eng bids':>8s}  {'Eng asks':>8s}  {'Last (E)':>12s}{_RESET}")
    print("-" * 85)
    for sym in symbols:
        p = paper.get(sym, {})
        e = engine.get(sym, {})
        pb = len(p.get("bids", []))
        pa = len(p.get("asks", []))
        eb = len(e.get("bids", []))
        ea = len(e.get("asks", []))
        pl = p.get("last_price")
        el = e.get("last_price")
        match = "✓" if pb == eb and pa == ea and pl == el else "✗"
        colour = _GREEN if match == "✓" else _RED
        print(
            f"{colour}{sym:6s}{_RESET}  {pb:>10d}  {pa:>10d}  {str(pl):>12s}"
            f"  {eb:>8d}  {ea:>8d}  {str(el):>12s}"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument(
        "--paper",  default=str(PAPER_RESULT),
        metavar="FILE", help="Paper-trade result JSON"
    )
    ap.add_argument(
        "--engine", default=str(ENGINE_RESULT),
        metavar="FILE", help="Engine result JSON"
    )
    ap.add_argument(
        "--tolerance", type=float, default=0.0,
        metavar="FRAC", help="Relative qty tolerance (default: 0 = exact match)"
    )
    ap.add_argument(
        "--symbols", nargs="+", default=None,
        metavar="SYM", help="Restrict comparison to these symbols"
    )
    args = ap.parse_args()

    paper_path  = Path(args.paper)
    engine_path = Path(args.engine)

    for p in (paper_path, engine_path):
        if not p.exists():
            print(f"[COMPARE] ERROR: {p} not found.", file=sys.stderr)
            sys.exit(1)

    paper  = json.loads(paper_path.read_text())
    engine = json.loads(engine_path.read_text())
    syms   = args.symbols or SYMBOLS

    print(f"\n{_BOLD}Verification — paper vs engine{_RESET}")
    print(f"  paper:  {paper_path}")
    print(f"  engine: {engine_path}")
    if args.tolerance:
        print(f"  qty tolerance: {args.tolerance*100:.1f}%")

    print_summary(paper, engine, syms)

    passed = compare(paper, engine, tolerance=args.tolerance, symbols=syms)

    print()
    if passed:
        print(f"{_GREEN}{_BOLD}═══  RESULT: PASS  ═══{_RESET}")
        sys.exit(0)
    else:
        print(f"{_RED}{_BOLD}═══  RESULT: FAIL  ═══{_RESET}")
        sys.exit(1)


if __name__ == "__main__":
    main()
