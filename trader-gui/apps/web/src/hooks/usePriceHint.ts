import { useBookStore } from "@/store/useBookStore.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";

/**
 * Best available price anchor for the order-ticket "Ref:" hint (§12.6).
 *
 * There is **no** per-symbol reference/collar-anchor price available to
 * TRADER/MARKET_MAKER over REST: the live collar anchor lives only on the
 * ADMIN-only `GET /api/v1/admin/risk/state` (`collar_reference_price`), and
 * `GET /symbols`/`GET /reference/risk` carry no per-symbol price. So the hint
 * uses the data a trader actually has, most-live first:
 *   1. the live last trade price (`bookStore`, fed by the WS book/trade feed),
 *   2. the current bid/ask mid,
 *   3. the static `prev_close` from `GET /symbols`.
 * Returns `null` when none is known yet (e.g. before the book has streamed).
 */
export function usePriceHint(symbol: string | null): number | null {
  const book = useBookStore((s) => (symbol ? s.books[symbol] : undefined));
  const prevClose = useSymbolStore((s) =>
    symbol ? (s.symbols.find((m) => m.symbol === symbol)?.prev_close ?? null) : null,
  );

  if (!symbol) return null;
  if (book?.lastPrice != null) return book.lastPrice;
  const bid = book?.bids[0]?.price;
  const ask = book?.asks[0]?.price;
  if (bid != null && ask != null) return (bid + ask) / 2;
  return prevClose;
}
