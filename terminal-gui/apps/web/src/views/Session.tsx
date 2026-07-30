/**
 * Session & Halt Status Board (design §13).
 *
 * Three panels: the exchange's current session phase, every symbol currently
 * halted with its circuit-breaker detail, and the auctions that have uncrossed
 * since this tab opened.
 *
 * Mounting this view declares the halt board open to the bridge, which is the
 * second of `CB`'s two subscription triggers (§13.2). `CB` refuses `SYM=*`, so
 * the bridge cannot simply hold it for everything: it watches `STATE` for
 * halts and subscribes per symbol on this board's behalf for as long as it is
 * open. Unmounting releases all of them.
 */

import { useEffect, useMemo } from "react";
import { SessionBadge } from "../components/Badge.js";
import { EmptyState, Panel } from "../components/Panel.js";
import { ABSENT, clockUtc, elapsed, price, qty, resumeAt } from "../lib/format.js";
import { sendControl } from "../lib/useTerminalStream.js";
import { sortHalted, useLiveStore } from "../store/useLiveStore.js";
import type { HaltedSymbol } from "../store/useLiveStore.js";
import { DENSITY_ROW_CLASS, usePrefsStore } from "../store/usePrefsStore.js";

export function SessionView() {
  const sessionPhase = useLiveStore((s) => s.sessionPhase);
  const sessionPrev = useLiveStore((s) => s.sessionPrev);
  const sessionSince = useLiveStore((s) => s.sessionSince);
  // Select the stable record, then derive. Selecting a freshly-built array
  // would fail Zustand's identity check on every render and loop forever.
  const haltedBySymbol = useLiveStore((s) => s.halted);
  const halted = useMemo(() => sortHalted(haltedBySymbol), [haltedBySymbol]);
  const auctions = useLiveStore((s) => s.auctions);
  const rowClass = DENSITY_ROW_CLASS[usePrefsStore((s) => s.density)];

  useEffect(() => {
    sendControl({ t: "halt_board", open: true });
    return () => sendControl({ t: "halt_board", open: false });
  }, []);

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4">
      <Panel title="Session status">
        <div className="flex items-baseline gap-3">
          <span className="text-2xl font-semibold tracking-tight">{sessionPhase ?? "AWAITING SESSION"}</span>
          <SessionBadge phase={sessionPhase} />
          <span className="text-sm text-fg-subtle">
            {sessionSince ? `since ${clockUtc(sessionSince)} UTC` : "no transition observed yet"}
            {sessionPrev ? ` · prev ${sessionPrev}` : ""}
          </span>
        </div>
      </Panel>

      <Panel
        title="Active halts"
        right={
          halted.length > 0 ? (
            <span className="text-xs font-semibold text-halt">{halted.length}</span>
          ) : undefined
        }
      >
        {halted.length === 0 ? (
          <EmptyState>No symbols currently halted</EmptyState>
        ) : (
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-border text-[10px] uppercase tracking-widest text-fg-faint">
                <th className="py-1 font-medium">Symbol</th>
                <th className="py-1 font-medium">Level</th>
                <th className="py-1 text-right font-medium">Trigger</th>
                <th className="py-1 text-right font-medium">Reference</th>
                <th className="py-1 font-medium">Resumes</th>
                <th className="py-1 font-medium">Since</th>
              </tr>
            </thead>
            <tbody>
              {halted.map((entry) => (
                <HaltRow key={entry.sym} entry={entry} rowClass={rowClass} />
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="Recent auction results">
        {auctions.length === 0 ? (
          <EmptyState>No auctions completed yet this session</EmptyState>
        ) : (
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-border text-[10px] uppercase tracking-widest text-fg-faint">
                <th className="py-1 font-medium">Symbol</th>
                <th className="py-1 text-right font-medium">Eq. price</th>
                <th className="py-1 text-right font-medium">Qty</th>
                <th className="py-1 text-right font-medium">Trades</th>
                <th className="py-1 font-medium">Imbalance</th>
                <th className="py-1 font-medium">Time</th>
              </tr>
            </thead>
            <tbody>
              {auctions.map((auction) => (
                <tr
                  key={`${auction.sym}-${auction.seq}-${auction.ts}`}
                  className={`border-b border-border/40 ${rowClass}`}
                >
                  <td className="font-semibold">{auction.sym}</td>
                  {/*
                   * An omitted EQPX means the auction found no crossable
                   * interest at all — meaningfully different from crossing at
                   * a price, so it is labelled rather than shown as a dash.
                   */}
                  <td className="text-right tabular">
                    {auction.eqPrice === undefined ? (
                      <span className="text-fg-faint">(no cross)</span>
                    ) : (
                      price(auction.eqPrice)
                    )}
                  </td>
                  <td className="text-right tabular">{qty(auction.eqQty)}</td>
                  <td className="text-right tabular">{qty(auction.tradesCount)}</td>
                  <td>
                    {auction.imbalanceSide ? (
                      <span className={auction.imbalanceSide === "BUY" ? "text-up" : "text-down"}>
                        {auction.imbalanceSide} {qty(auction.imbalanceQty)}
                      </span>
                    ) : (
                      <span className="text-fg-faint">{ABSENT}</span>
                    )}
                  </td>
                  <td className="tabular text-fg-subtle">{clockUtc(auction.ts)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}

/**
 * One halted symbol.
 *
 * Every circuit-breaker field is optional on the wire and each absence means
 * something specific: an operator-initiated (`ADMIN_*`) halt carries no
 * trigger or reference price, and a manual or rest-of-day halt carries no
 * resume time because it ends only when someone says so.
 */
function HaltRow({ entry, rowClass }: { entry: HaltedSymbol; rowClass: string }) {
  const cb = entry.context;
  const mode = cb?.resumptionMode;

  return (
    <tr className={`border-b border-border/40 ${rowClass}`}>
      <td className="font-semibold">{entry.sym}</td>
      <td>
        {cb?.level ? (
          <span className="rounded bg-halt-bg px-1.5 py-0.5 text-[10px] font-bold text-halt">{cb.level}</span>
        ) : (
          <span className="text-fg-faint">{ABSENT}</span>
        )}
      </td>
      <td className="text-right tabular">{price(cb?.triggerPrice)}</td>
      <td className="text-right tabular">{price(cb?.referencePrice)}</td>
      <td className="tabular">
        {mode === "MANUAL" || (mode && !cb?.resumeAt) ? (
          mode
        ) : cb?.resumeAt ? (
          <span>
            {mode ? <span className="mr-1 text-fg-subtle">{mode}</span> : null}
            {resumeAt(cb.resumeAt)}
          </span>
        ) : (
          <span className="text-fg-faint">{ABSENT}</span>
        )}
      </td>
      <td className="tabular text-fg-subtle">
        {clockUtc(entry.since)}
        <span className="ml-2 text-fg-faint">{elapsed(entry.since)}</span>
      </td>
    </tr>
  );
}
