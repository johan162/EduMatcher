/**
 * The order book for the symbol in the URL (design §9): statistics header,
 * then BIDS / ASKS / TRADES sharing one row capacity that fits the screen.
 */

import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { SideLadder, ROW_PX, TradesPanel } from "../components/Panels.js";
import { StatsHeader } from "../components/StatsHeader.js";
import { capacity as capacityOf } from "../lib/ladder.js";
import { useRowsPerPage } from "../lib/hooks.js";
import { useBookStore } from "../store/useBookStore.js";
import { usePrefsStore } from "../store/usePrefsStore.js";

/** The exchange's own default when a symbol's precision is not known yet. */
const DEFAULT_TICK_DECIMALS = 2;

export function BookView() {
  const sym = (useParams()["symbol"] ?? "").toUpperCase();
  const watch = useBookStore((s) => s.watch);
  const book = useBookStore((s) => s.book);
  const stats = useBookStore((s) => s.stats);
  const tape = useBookStore((s) => s.tape);
  const error = useBookStore((s) => s.error);
  const symbols = useBookStore((s) => s.symbols);
  const setCapacity = useBookStore((s) => s.setCapacity);
  const zebra = usePrefsStore((s) => s.zebra);
  const maxLevels = usePrefsStore((s) => s.maxLevels);
  const setLastSymbol = usePrefsStore((s) => s.setLastSymbol);
  const { ref, rows } = useRowsPerPage(ROW_PX);

  // Until the universe arrives every symbol is given the benefit of the doubt; the bridge refuses unknown ones.
  const listed = symbols.some((s) => s.symbol === sym);
  const known = symbols.length === 0 || listed;
  const cap = capacityOf(rows, maxLevels);
  const decimals =
    book?.tickDecimals ?? symbols.find((s) => s.symbol === sym)?.tickDecimals ?? DEFAULT_TICK_DECIMALS;

  useEffect(() => {
    if (known) watch(sym);
  }, [sym, known, watch]);

  // Only a listed symbol becomes where `/` returns to.
  useEffect(() => {
    if (listed) setLastSymbol(sym);
  }, [sym, listed, setLastSymbol]);

  useEffect(() => setCapacity(cap), [cap, setCapacity]);

  if (!known || error) {
    return (
      <div role="alert" className="m-auto text-center">
        <p className="text-lg font-semibold text-halt">{known ? error : `${sym} is not a listed symbol`}</p>
        <p className="mt-2 text-sm text-fg-subtle">Press s or F1 to choose another.</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <StatsHeader book={book} stats={stats} decimals={decimals} />
      {/* Three fixed columns that never reflow; a narrow window scrolls sideways instead. */}
      <div className="min-h-0 flex-1 overflow-x-auto">
        <div className="grid h-full grid-cols-3 gap-3" style={{ minWidth: 720 }}>
          <SideLadder
            side="bid"
            levels={book?.bids ?? []}
            capacity={cap}
            decimals={decimals}
            zebra={zebra}
            bodyRef={ref}
          />
          <SideLadder side="ask" levels={book?.asks ?? []} capacity={cap} decimals={decimals} zebra={zebra} />
          <TradesPanel
            tape={tape}
            capacity={cap}
            decimals={decimals}
            timeZone={stats?.timezone ?? "UTC"}
            zebra={zebra}
          />
        </div>
      </div>
    </div>
  );
}
