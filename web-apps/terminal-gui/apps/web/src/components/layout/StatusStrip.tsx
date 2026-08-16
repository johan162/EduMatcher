/**
 * Footer status strip (design §7.1): session phase, halt count, CALF health,
 * and a UTC clock.
 *
 * The clock ticks on its own interval rather than off the data stream, so a
 * lobby display shows a visibly stopped clock when the tab has genuinely
 * frozen — which is more honest than a timestamp that merely stopped updating
 * because no ticks arrived.
 */

import { useEffect, useState } from "react";
import clsx from "clsx";
import { SessionBadge } from "../Badge.js";
import { useLiveStore } from "../../store/useLiveStore.js";
import { ageSec, isLate, liveTickLabel } from "../../lib/data-age.js";
import { countdownLabel, countdownTo } from "../../lib/session-countdown.js";
import { useNow } from "../../lib/staleness.js";

function useUtcClock(): string {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);
  return now.toISOString().slice(11, 19);
}

export function StatusStrip() {
  const sessionPhase = useLiveStore((s) => s.sessionPhase);
  const haltCount = useLiveStore((s) => Object.keys(s.halted).length);
  const connection = useLiveStore((s) => s.connectionState());
  const symbolCount = useLiveStore((s) => s.symbols.length);
  const lastTickAt = useLiveStore((s) => s.lastTickAt);
  const nextPhase = useLiveStore((s) => s.sessionNextPhase);
  const nextAt = useLiveStore((s) => s.sessionNextAt);
  const clock = useUtcClock();
  // Its own coarse clock: an age changes because time passes, not because
  // data arrived, so it cannot be driven off the frame stream — which is the
  // whole point of showing it.
  const tickAge = ageSec(lastTickAt, useNow(5_000));
  // Its own one-second clock: a countdown's whole value is that it moves,
  // and the seconds matter most in the last minute of a call phase.
  const countdown = countdownTo(nextPhase, nextAt, useNow(1_000));

  return (
    <footer className="flex h-7 shrink-0 items-center gap-4 border-t border-border bg-bg-subtle px-4 text-xs text-fg-subtle">
      <span className="flex items-center gap-2">
        {sessionPhase ?? "AWAITING SESSION"}
        <SessionBadge phase={sessionPhase} />
      </span>

      {/*
       * Rendered only when the feed named a transition. No countdown is a
       * real state -- a manually driven session, or none scheduled -- and
       * showing `0:00` for it would assert a transition that is not coming
       * (§ T-M6).
       */}
      {countdown && (
        <span
          className={clsx(
            "tabular",
            countdown.overdue ? "font-semibold text-halt" : countdown.imminent && "font-semibold text-fg",
          )}
          title={
            countdown.overdue
              ? "The scheduled moment has passed without the transition arriving"
              : `Next scheduled transition: ${nextAt}`
          }
        >
          {countdownLabel(countdown)}
        </span>
      )}

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
        <span className="tabular">{clock} UTC</span>
      </span>
    </footer>
  );
}
