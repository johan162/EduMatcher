import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import { useWsEvent } from "@/hooks/useWsEvent.js";
import { useNotificationStore } from "@/store/useNotificationStore.js";
import { useQuotePrefillStore } from "@/store/useQuotePrefillStore.js";
import type { ActiveQuote } from "@/types/index.js";

/** Human label for a quote.status value (§14.1.2). */
function statusLabel(status: string): string {
  switch (status) {
    case "INACTIVE_BID_FILLED":
      return "bid leg filled";
    case "INACTIVE_ASK_FILLED":
      return "ask leg filled";
    case "ACTIVE":
      return "active";
    case "CANCELLED":
      return "cancelled";
    default:
      return status.toLowerCase();
  }
}

/**
 * Bridge MARKET_MAKER quote lifecycle events (`/events`) into the quote
 * dashboard, the Event Center (§20), and Sonner fill alerts (§14.1.2). Mounted
 * once at the app root; inert for TRADER/ADMIN (no `quote.*` events reach them).
 *
 * Data flow (§14.3): the quote cards read `GET /quotes/bootstrap` (ActiveQuote,
 * the reliable per-side source) and `GET /quotes/legs`. Those caches are
 * reconciled to engine truth by invalidating on:
 *  - `orders.snapshot` — the first `/events` frame on connect AND every
 *    reconnect, so the dashboard resyncs before replayed live events continue.
 *  - `quote.ack` / `quote.status` — each quote lifecycle change.
 *
 * `quote.status`/`quote.ack` payloads carry no `symbol`, so it is resolved from
 * the bootstrap cache by `quote_id`. A filled leg raises a toast with a
 * "Re-quote" action that prefills the New Quote form from the previous quote.
 */
export function useQuoteEvents(): void {
  const qc = useQueryClient();
  const push = useNotificationStore((s) => s.push);
  const setPrefill = useQuotePrefillStore((s) => s.setPrefill);

  const invalidateQuotes = () => {
    void qc.invalidateQueries({ queryKey: ["quotes/bootstrap"] });
    void qc.invalidateQueries({ queryKey: ["quotes/legs"] });
  };

  const findQuote = (quoteId: string): ActiveQuote | undefined =>
    qc.getQueryData<ActiveQuote[]>(["quotes/bootstrap"])?.find((q) => q.quote_id === quoteId);

  // Reconcile on connect and every reconnect.
  useWsEvent("orders.snapshot", () => invalidateQuotes());

  useWsEvent("quote.ack", (env) => {
    const d = env.data;
    const quote = findQuote(d.quote_id);
    const label = quote?.symbol ?? d.quote_id ?? "quote";
    if (d.accepted) {
      push({
        ts: Date.now(),
        kind: "ACK",
        title: `Quote ${label} accepted`,
        detail: d.quote_id || label,
      });
    } else {
      toast.error(`Quote ${label} rejected: ${d.reason || "rejected"}`);
      push({
        ts: Date.now(),
        kind: "REJECT",
        title: `Quote ${label} rejected`,
        detail: d.reason || "rejected",
      });
    }
    invalidateQuotes();
  });

  useWsEvent("quote.status", (env) => {
    const d = env.data;
    const quote = findQuote(d.quote_id);
    const symbol = quote?.symbol ?? d.quote_id ?? "quote";
    const filled = d.status === "INACTIVE_BID_FILLED" || d.status === "INACTIVE_ASK_FILLED";

    if (filled) {
      const side = d.status === "INACTIVE_BID_FILLED" ? "BID" : "ASK";
      toast.success(`${symbol} ${side} filled — quote inactive`, {
        action: quote
          ? {
              label: "Re-quote",
              onClick: () =>
                setPrefill({
                  symbol: quote.symbol,
                  bid_price: quote.bid_price,
                  bid_qty: quote.bid_qty,
                  ask_price: quote.ask_price,
                  ask_qty: quote.ask_qty,
                  quote_id: quote.quote_id,
                }),
            }
          : undefined,
      });
      push({
        ts: Date.now(),
        kind: "FILL",
        title: `${symbol} ${side} leg filled`,
        detail: `${statusLabel(d.status)}${d.reason ? ` · ${d.reason}` : ""}`,
      });
    } else {
      push({
        ts: Date.now(),
        kind: d.status === "CANCELLED" ? "CANCEL" : "SYSTEM",
        title: `Quote ${symbol} · ${statusLabel(d.status)}`,
        detail: d.reason || d.status,
      });
    }
    invalidateQuotes();
  });
}
