/**
 * Footer status strip (design §7.1): the session indicator every EduMatcher
 * GUI shows (WP-UI01) -- phase, next phase, countdown and a clock in the
 * exchange's session timezone -- then halt count and CALF health.
 *
 * The clock ticks on its own interval rather than off the data stream, so a
 * lobby display shows a visibly stopped clock when the tab has genuinely
 * frozen — which is more honest than a timestamp that merely stopped updating
 * because no ticks arrived.
 */

import clsx from "clsx";
import { SessionIndicator } from "../SessionIndicator.js";
import { useLiveStore } from "../../store/useLiveStore.js";
import { ageSec, isLate, liveTickLabel } from "../../lib/data-age.js";
import { useNow } from "../../lib/staleness.js";

export function StatusStrip() {
  const sessionPhase = useLiveStore((s) => s.sessionPhase);
  const haltCount = useLiveStore((s) => Object.keys(s.halted).length);
  const connection = useLiveStore((s) => s.connectionState());
  const symbolCount = useLiveStore((s) => s.symbols.length);
  const sessionTimezone = useLiveStore((s) => s.sessionTimezone);
  const lastTickAt = useLiveStore((s) => s.lastTickAt);
  const nextPhase = useLiveStore((s) => s.sessionNextPhase);
  const nextAt = useLiveStore((s) => s.sessionNextAt);
  // Its own coarse clock: an age changes because time passes, not because
  // data arrived, so it cannot be driven off the frame stream — which is the
  // whole point of showing it.
  const tickAge = ageSec(lastTickAt, useNow(5_000));

  return (
    <footer className="flex h-7 shrink-0 items-center gap-4 border-t border-border bg-bg-subtle px-4 text-xs text-fg-subtle">
      {/* A phase from a feed that is not live is stale: shown as Unknown. */}
      <SessionIndicator
        state={connection === "LIVE" ? sessionPhase : null}
        nextState={nextPhase}
        nextAt={nextAt}
        timeZone={sessionTimezone}
      />

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
