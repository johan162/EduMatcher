#!/usr/bin/env python3
"""
mutate_engine.py — Mutation testing for the matching engine.

Each mutant is one realistic matching bug: a single source edit given as an
exact ``old`` → ``new`` text replacement. For every mutant the tool applies
the edit to a scratch copy of the working tree, runs the test suite there and
reports which tests failed ("killed" the mutant). A mutant no test kills is a
matching rule nothing pins down.

The working tree is never modified. The copy holds every tracked and
untracked-but-not-ignored file as it is on disk (so uncommitted work is
measured), with the project's ``.venv`` symlinked in, and the suite runs with
``PYTHONPATH`` pointing at the copy so the mutated ``src`` wins over the
editable install. An unmutated baseline run comes first; the tool stops if it
is not green, because kills against a red baseline mean nothing.

The mutant list is pinned by tests/test_mutate_engine.py: every ``old`` text
must still occur exactly once, so an engine refactor cannot silently disable
a mutant.

Background: docs-design/EduMatcher-Matching-Test-Quality-Workplan.md (T1).

Usage
-----
    poetry run python tools/mutate_engine.py                 # all mutants, full suite (~50 min)
    poetry run python tools/mutate_engine.py M07 M16         # selected mutants
    poetry run python tools/mutate_engine.py --tests tests/test_auction.py --tests tests/test_amend.py M16
    poetry run python tools/mutate_engine.py --list          # list mutants
    poetry run python tools/mutate_engine.py --check         # verify every mutant applies
"""

from __future__ import annotations

import argparse
import ast
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

OB = "src/edumatcher/engine/order_book.py"
AU = "src/edumatcher/engine/auction.py"
MN = "src/edumatcher/engine/main.py"

#: Pins MUTANTS to the source; excluded from mutation runs (see run_suite).
GUARD_TEST = "tests/test_mutate_engine.py"

#: A hung test run counts as a kill (the bug is detected), but is flagged.
DEFAULT_TIMEOUT_SEC = 900

#: Killing test IDs printed per mutant; the count is always printed in full.
SHOW_KILLERS = 10


@dataclass(frozen=True)
class Mutant:
    id: str
    description: str
    file: str
    old: str
    new: str


MUTANTS: tuple[Mutant, ...] = (
    Mutant(
        "M01",
        "trade prints at the aggressor's limit instead of the resting price",
        OB,
        "_apply_fill(aggressor, best, fill_qty, best_price, trades, events, now)",
        "_apply_fill(aggressor, best, fill_qty, price_limit if price_limit is not None"
        " else best_price, trades, events, now)",
    ),
    Mutant(
        "M02",
        "bids queue newest-first (time priority inverted, bid side)",
        OB,
        "key = (-price, order.arrival_seq)\n"
        "            heap = self._bids\n"
        "            self._bid_qty[price] = self._bid_qty.get(price, 0) + qty",
        "key = (-price, -order.arrival_seq)\n"
        "            heap = self._bids\n"
        "            self._bid_qty[price] = self._bid_qty.get(price, 0) + qty",
    ),
    Mutant(
        "M03",
        "limit BUY will not trade at its own limit price (off by one)",
        OB,
        "if _side == Side.BUY and best_price > price_limit:",
        "if _side == Side.BUY and best_price >= price_limit:",
    ),
    Mutant(
        "M04",
        "amend qty decrease loses priority",
        OB,
        "priority_reset = price_changed or qty_increased",
        "priority_reset = price_changed or qty != old_qty",
    ),
    Mutant(
        "M05",
        "amend qty increase keeps priority",
        OB,
        "priority_reset = price_changed or qty_increased",
        "priority_reset = price_changed",
    ),
    Mutant(
        "M06",
        "BUY stop needs the price strictly above its stop",
        OB,
        "if self.last_trade_price < stop_price:",
        "if self.last_trade_price <= stop_price:",
    ),
    Mutant(
        "M07",
        "SELL stop needs the price strictly below its stop",
        OB,
        "if self.last_trade_price > stop_price:",
        "if self.last_trade_price >= stop_price:",
    ),
    Mutant(
        "M08",
        "SELL trailing stop never ratchets up",
        OB,
        "candidate = trade_price - offset\n                if candidate > stop_price:",
        "candidate = trade_price - offset\n                if False:",
    ),
    Mutant(
        "M09",
        "stop already breached on entry is parked, not triggered",
        OB,
        "            # some unrelated future trade.\n"
        "            if self.last_trade_price is not None and self._stop_is_triggered(",
        "            # some unrelated future trade.\n"
        "            if False and self._stop_is_triggered(",
    ),
    Mutant(
        "M10",
        "stop cascade disabled (a stop's fill cannot trigger the next stop)",
        OB,
        "            if sub_trades and self._has_stops:",
        "            if False:",
    ),
    Mutant(
        "M11",
        "triggered BUY STOP_LIMIT becomes MARKET (limit ignored)",
        OB,
        "            heapq.heappop(self._buy_stops)\n"
        "            stop_order = entry.order\n"
        "            self._note_trigger(stop_order)\n"
        "            if stop_order.order_type == OrderType.STOP:",
        "            heapq.heappop(self._buy_stops)\n"
        "            stop_order = entry.order\n"
        "            self._note_trigger(stop_order)\n"
        "            if True:",
    ),
    Mutant(
        "M12",
        "FOK pre-check counts its own SMP-excluded liquidity",
        OB,
        "if smp != SmpAction.NONE and o.gateway_id == gw:",
        "if False:",
    ),
    Mutant(
        "M13",
        "IOC remainder rests on the book instead of cancelling",
        OB,
        "            order.status = OrderStatus.CANCELLED\n"
        "            # Same cause as the discarded MARKET remainder",
        "            self._rest(order)\n"
        "            return\n"
        "            # Same cause as the discarded MARKET remainder",
    ),
    Mutant(
        "M14",
        "replenished iceberg peak keeps its time priority",
        OB,
        "        order.arrival_seq = self._next_seq()\n"
        "        new_peak = order.displayed_qty or 0",
        "        new_peak = order.displayed_qty or 0",
    ),
    Mutant(
        "M15",
        "aggressor_side inverted on trades",
        OB,
        "aggressor_side = _AUCTION_AGGRESSOR if both_resting else aggressor.side.value",
        "aggressor_side = _AUCTION_AGGRESSOR if both_resting else"
        " ('SELL' if aggressor.side.value == 'BUY' else 'BUY')",
    ),
    Mutant(
        "M16",
        "auction tie-break maximises surplus instead of minimising it",
        AU,
        "surplus < best_surplus",
        "surplus > best_surplus or best_surplus == float('inf')",
    ),
    Mutant(
        "M17",
        "auction picks the highest price among full ties (documented: lowest)",
        AU,
        "(exec_qty == best_qty and surplus < best_surplus)",
        "(exec_qty == best_qty and surplus <= best_surplus)",
    ),
    Mutant(
        "M18",
        "marketable amend is not re-matched (book left crossed)",
        MN,
        "            if marketable:",
        "            if False:",
    ),
    Mutant(
        "M19",
        "ATC orders not expired after the closing auction",
        MN,
        "            self._expire_tif(TIF.ATC)",
        "            pass",
    ),
    Mutant(
        "M20",
        "DAY orders not expired at the close",
        MN,
        "            self._expire_tif(TIF.DAY)",
        "            pass",
    ),
    Mutant(
        "M21",
        "cancel ownership check removed",
        MN,
        "            if resting is not None and resting.gateway_id != gateway_id:\n"
        '                self._dbg_count("cancel_reject_ownership")',
        "            if False:\n"
        '                self._dbg_count("cancel_reject_ownership")',
    ),
    Mutant(
        "M22",
        "SMP CANCEL_RESTING self-trades instead of cancelling the resting order",
        OB,
        "                elif _smp_action == SmpAction.CANCEL_RESTING:\n"
        "                    self._smp_cancel_resting(best, events)\n"
        "                    continue  # skip this resting order; try next",
        "                elif _smp_action == SmpAction.CANCEL_RESTING:\n"
        "                    pass",
    ),
    Mutant(
        "M23",
        "passive iceberg filled beyond its shown slice (finding #17)",
        OB,
        "            _passive_avail = (\n"
        "                best.displayed_qty\n"
        "                if best.order_type == OrderType.ICEBERG\n"
        "                and best.displayed_qty is not None\n"
        "                else best.remaining_qty\n"
        "            )\n"
        "            fill_qty = min(aggressor.remaining_qty, _passive_avail)",
        "            _passive_avail = best.remaining_qty\n"
        "            fill_qty = min(aggressor.remaining_qty, _passive_avail)",
    ),
    Mutant(
        "M24",
        "unfilled MARKET remainder cancelled silently (no terminal event)",
        OB,
        "                order.cancel_reason,\n"
        "            )\n"
        "            events.append(order)\n"
        "\n"
        "    def _match_limit",
        "                order.cancel_reason,\n"
        "            )\n"
        "\n"
        "    def _match_limit",
    ),
    Mutant(
        "M25",
        "uncross fills an iceberg's hidden quantity in one pass (bug A)",
        AU,
        "fill_qty = min(_shown_qty(best_bid), _shown_qty(best_ask))",
        "fill_qty = min(best_bid.remaining_qty, best_ask.remaining_qty)",
    ),
    Mutant(
        "M26",
        "auction equilibrium counts only an iceberg's shown slice (bug A)",
        AU,
        "qty[o.price_ticks] = qty.get(o.price_ticks, 0) + o.remaining_qty",
        "qty[o.price_ticks] = qty.get(o.price_ticks, 0) + (o.displayed_qty or 0"
        " if o.order_type == OrderType.ICEBERG else o.remaining_qty)",
    ),
    Mutant(
        "M27",
        "qty-decrease amend refills an iceberg's used peak, priority kept (bug B)",
        OB,
        "order.displayed_qty = min(order.displayed_qty or 0, order.remaining_qty)",
        "order.displayed_qty = min(order.visible_qty, order.remaining_qty)",
    ),
    Mutant(
        "M28",
        "trailing stop already breached on entry is parked (T2, rule G3)",
        OB,
        "            # Same on-entry rule as STOP / STOP_LIMIT above (M2).\n"
        "            if self.last_trade_price is not None and self._stop_is_triggered(",
        "            # Same on-entry rule as STOP / STOP_LIMIT above (M2).\n"
        "            if False and self._stop_is_triggered(",
    ),
    Mutant(
        "M29",
        "incoming iceberg rests with what is left of a part-used peak (T2, rule G4)",
        OB,
        "                order.displayed_qty = min(order.visible_qty, order.remaining_qty)\n"
        "            self._rest(order)",
        "                order.displayed_qty = min(\n"
        "                    order.visible_qty,\n"
        "                    order.remaining_qty,\n"
        "                    order.visible_qty - (order.quantity - order.remaining_qty) % order.visible_qty,\n"
        "                )\n"
        "            self._rest(order)",
    ),
    Mutant(
        "M30",
        "FOK pre-check counts liquidity behind its own order (T2, bug C)",
        OB,
        "                if stops_sweep:\n                    return total",
        "                if stops_sweep:\n                    continue",
    ),
    Mutant(
        "M31",
        "uncross stop cascade runs depth-first, not queued (T3, I19)",
        MN,
        "                sub_trades, sub_events = book.run_stops(now_ns())\n"
        "                self._publish_dispatch(sub_trades, sub_events)",
        "                for stop in book._check_stops(0) + book._check_trailing_stops(0):\n"
        "                    sub_trades, sub_events = book.process(stop)\n"
        "                    self._publish_dispatch(sub_trades, sub_events)",
    ),
)


def mutated_source(mutant: Mutant, root: Path = ROOT) -> str:
    """The mutant's file with its edit applied. Raises if ``old`` is not unique."""
    source = (root / mutant.file).read_text()
    count = source.count(mutant.old)
    if count != 1:
        raise ValueError(
            f"{mutant.id}: expected the pattern exactly once in {mutant.file}, "
            f"found {count}. Update the mutant to match the current source."
        )
    return source.replace(mutant.old, mutant.new)


def check(mutants: tuple[Mutant, ...]) -> list[str]:
    """Problems with *mutants* against the current source; empty when all apply."""
    problems: list[str] = []
    for m in mutants:
        try:
            ast.parse(mutated_source(m))
        except ValueError as exc:  # already names the mutant
            problems.append(str(exc))
        except SyntaxError as exc:
            problems.append(f"{m.id}: mutated {m.file} does not parse: {exc}")
    return problems


def make_copy(dest: Path) -> None:
    """Copy the working tree (tracked + untracked, not ignored) into *dest*."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        check=True,
    ).stdout.split(b"\0")
    for raw in listed:
        if not raw:
            continue
        rel = raw.decode()
        src = ROOT / rel
        if not src.is_file():  # deleted in the working tree but still tracked
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    # Tests that shell out to `poetry run …` need the in-project venv.
    (dest / ".venv").symlink_to(ROOT / ".venv")


@dataclass(frozen=True)
class SuiteRun:
    returncode: int  # pytest's: 0 all passed, 1 tests failed, 2+ error/usage/none
    failed: list[str]  # failing test IDs
    summary: str  # pytest's final summary line
    output: str


def run_suite(copy: Path, tests: list[str], timeout: int) -> SuiteRun:
    """Run pytest in *copy*. Raises subprocess.TimeoutExpired when it hangs."""
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *tests,
        "-n",
        "logical",
        "-q",
        "-rfE",
        "-p",
        "no:cacheprovider",
        # Not `-p no:cov`: pyproject's addopts carry --cov flags that need the
        # plugin loaded.
        "--no-cov",
        # The mutant-list guard fails for every mutant by design (the mutated
        # source no longer holds its own pattern); counting it would add one
        # kill to every mutant and hide the survivors.
        f"--ignore={GUARD_TEST}",
    ]
    env = {**os.environ, "PYTHONPATH": f"{copy / 'src'}{os.pathsep}{copy}"}
    proc = subprocess.run(
        cmd, cwd=copy, env=env, capture_output=True, text=True, timeout=timeout
    )
    out = proc.stdout + proc.stderr
    failed = sorted(
        {
            line.split(" ")[1]
            for line in out.splitlines()
            if line.startswith(("FAILED ", "ERROR "))
        }
    )
    summary = next(
        (
            line.strip("= ")
            for line in reversed(out.splitlines())
            if " passed" in line or " failed" in line or " error" in line
        ),
        "no pytest summary",
    )
    return SuiteRun(proc.returncode, failed, summary, out)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mutation testing for the matching engine (see module docstring)."
    )
    parser.add_argument("ids", nargs="*", help="mutant IDs to run (default: all)")
    parser.add_argument(
        "--tests",
        action="append",
        metavar="PATH",
        help="pytest selection to run per mutant; repeat for several (default: tests)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SEC,
        help=f"seconds per suite run before it counts as hung (default {DEFAULT_TIMEOUT_SEC})",
    )
    parser.add_argument("--list", action="store_true", help="list mutants and exit")
    parser.add_argument(
        "--check", action="store_true", help="verify every mutant applies and exit"
    )
    args = parser.parse_args()

    if args.list:
        for m in MUTANTS:
            print(f"{m.id}  {m.description}  ({m.file})")
        return 0

    problems = check(MUTANTS)
    if problems or args.check:
        print("\n".join(problems) if problems else f"all {len(MUTANTS)} mutants apply")
        return 1 if problems else 0

    unknown = set(args.ids) - {m.id for m in MUTANTS}
    if unknown:
        parser.error(f"unknown mutant(s): {', '.join(sorted(unknown))}")
    selected = [m for m in MUTANTS if not args.ids or m.id in args.ids]
    tests: list[str] = args.tests or ["tests"]

    with tempfile.TemporaryDirectory(prefix="mutate_engine_") as tmp:
        copy = Path(tmp)
        make_copy(copy)

        print(f"baseline: running {' '.join(tests)} unmutated …", flush=True)
        base = run_suite(copy, tests, args.timeout)
        if base.returncode != 0:
            print(
                f"baseline is not green (pytest exit {base.returncode}, {base.summary}):"
            )
            print("\n".join(base.output.splitlines()[-30:]))
            return 1
        print(f"baseline: {base.summary}\n", flush=True)

        rows: list[tuple[Mutant, str]] = []
        for m in selected:
            path = copy / m.file
            original = path.read_text()
            path.write_text(mutated_source(m, copy))
            start = time.monotonic()
            failed: list[str] = []
            try:
                run = run_suite(copy, tests, args.timeout)
                failed, summary = run.failed, run.summary
                if run.returncode == 0:
                    kills = "0"
                elif run.returncode == 1:
                    kills = str(len(failed))
                else:  # import/collection error: detected, but by no single test
                    kills = "error"
                    summary = f"pytest exit {run.returncode}, {summary}"
            except subprocess.TimeoutExpired:
                summary, kills = f"hung after {args.timeout} s", "hung"
            finally:
                path.write_text(original)
            secs = time.monotonic() - start
            verdict = "SURVIVED" if kills == "0" else f"killed by {kills}"
            print(f"{m.id} {verdict:<14} {m.description}  [{secs:.0f} s, {summary}]")
            for test_id in failed[:SHOW_KILLERS]:
                print(f"      {test_id}")
            if len(failed) > SHOW_KILLERS:
                print(f"      … and {len(failed) - SHOW_KILLERS} more")
            sys.stdout.flush()
            rows.append((m, kills))

    print("\n| ID | Mutant | Kills |\n|---|---|---|")
    for m, kills in rows:
        shown = f"**{kills}**" if kills == "0" else kills
        print(f"| {m.id} | {m.description} | {shown} |")
    survivors = [m.id for m, kills in rows if kills == "0"]
    print(f"\n{len(rows) - len(survivors)}/{len(rows)} killed", end="")
    print(f"; survived: {', '.join(survivors)}" if survivors else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())
