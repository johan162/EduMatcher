/**
 * Level 2 depth ladder (design §14).
 *
 * Aggregated quantity per price level, never order-by-order — CALF
 * deliberately keeps per-order identity out of the public feed at every
 * version (§14.2), so the `#` column is a count of orders resting at that
 * price, not a list of them.
 *
 * Each `DEPTH` message carries a side's complete current ladder, so rendering
 * replaces wholesale and never patches a level in place (§14.4).
 */

import type { DepthFrame } from "@edumatcher/terminal-types";
import { ABSENT, price, qty } from "../lib/format.js";

/**
 * Bar length is relative to the largest level shown on *either* side, so the
 * two halves stay visually comparable — scaling each side independently would
 * make a thin book look as deep as a heavy one.
 */
function peakQty(frame: DepthFrame): number {
  const all = [...frame.bids, ...frame.asks].map(([, quantity]) => quantity);
  return all.length > 0 ? Math.max(...all) : 0;
}

export function DepthLadder({ frame, rowClass }: { frame: DepthFrame | null; rowClass: string }) {
  if (!frame) {
    return <p className="py-6 text-center text-sm text-fg-faint">Awaiting the first depth snapshot</p>;
  }

  const peak = peakQty(frame);
  // Rows beyond the gateway's configured LEVELS simply do not exist in the
  // feed — there is no "load more", since a client cannot request a deeper
  // ladder than the gateway publishes (§14.5).
  const rows = Math.max(frame.bids.length, frame.asks.length);

  if (rows === 0) {
    return <p className="py-6 text-center text-sm text-fg-faint">No resting orders on either side</p>;
  }

  return (
    <table className="w-full text-left tabular">
      <thead>
        <tr className="border-b border-border text-[10px] uppercase tracking-widest text-fg-faint">
          <th className="py-1 text-right font-medium">#</th>
          <th className="py-1 text-right font-medium">Bid qty</th>
          <th className="py-1 text-right font-medium">Bid</th>
          <th className="w-1/4 py-1" />
          <th className="py-1 font-medium">Ask</th>
          <th className="py-1 font-medium">Ask qty</th>
          <th className="py-1 font-medium">#</th>
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: rows }, (_, i) => {
          const bid = frame.bids[i];
          const ask = frame.asks[i];
          return (
            <tr key={i} className={`border-b border-border/40 ${rowClass}`}>
              <td className="text-right text-fg-faint">{bid ? qty(bid[2]) : ABSENT}</td>
              <td className="text-right">{bid ? qty(bid[1]) : ABSENT}</td>
              <td className="text-right font-semibold text-up">{bid ? price(bid[0]) : ABSENT}</td>
              <td>
                <div className="flex items-center gap-px">
                  <div className="flex flex-1 justify-end">
                    {bid && peak > 0 && (
                      <span className="block h-2 bg-up/40" style={{ width: `${(bid[1] / peak) * 100}%` }} />
                    )}
                  </div>
                  <div className="flex-1">
                    {ask && peak > 0 && (
                      <span className="block h-2 bg-down/40" style={{ width: `${(ask[1] / peak) * 100}%` }} />
                    )}
                  </div>
                </div>
              </td>
              <td className="font-semibold text-down">{ask ? price(ask[0]) : ABSENT}</td>
              <td>{ask ? qty(ask[1]) : ABSENT}</td>
              <td className="text-fg-faint">{ask ? qty(ask[2]) : ABSENT}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
