/**
 * Footer status strip (design §7.1): halt count and CALF health. The session
 * indicator lives in the top bar, where every other EduMatcher GUI has it.
 */

import clsx from "clsx";
import { useLiveStore } from "../../store/useLiveStore.js";
import { ageSec, isLate, liveTickLabel } from "../../lib/data-age.js";
import { useNow } from "../../lib/staleness.js";

export function StatusStrip() {
  const haltCount = useLiveStore((s) => Object.keys(s.halted).length);
  const connection = useLiveStore((s) => s.connectionState());
  const symbolCount = useLiveStore((s) => s.symbols.length);
  const lastTickAt = useLiveStore((s) => s.lastTickAt);
  // Its own coarse clock: an age changes because time passes, not because
  // data arrived, so it cannot be driven off the frame stream — which is the
  // whole point of showing it.
  const tickAge = ageSec(lastTickAt, useNow(5_000));

  return (
    <footer className="flex h-7 shrink-0 items-center gap-4 border-t border-border bg-bg-subtle px-4 text-xs text-fg-subtle">
      <span className={haltCount > 0 ? "font-semibold text-halt" : undefined}>
        {haltCount === 0 ? "no halts" : `${haltCount} symbol${haltCount === 1 ? "" : "s"} halted`}
      </span>

      <span>{symbolCount} symbols</span>

      <span className="ml-auto flex items-center gap-4">
        {/*
         * Connection state and data age answer different questions, so they
         * are shown as two readings rather than one. "CALF connected" says
         * the pipe is open; it says nothing about whether anything is coming
         * down it, and a silent feed behind a healthy socket is the case a
         * reader most needs to catch (§ T-M4).
         */}
        <span>CALF {connection === "LIVE" ? "connected" : connection.toLowerCase()}</span>
        <span
          className={clsx("tabular", isLate("live", tickAge) && "font-semibold text-halt")}
          title="Time since the last market-data frame. A connected feed can still be silent."
        >
          {liveTickLabel(tickAge)}
        </span>
      </span>
    </footer>
  );
}
