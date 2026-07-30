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
import { SessionBadge } from "../Badge.js";
import { useLiveStore } from "../../store/useLiveStore.js";

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
  const clock = useUtcClock();

  return (
    <footer className="flex h-7 shrink-0 items-center gap-4 border-t border-border bg-bg-subtle px-4 text-xs text-fg-subtle">
      <span className="flex items-center gap-2">
        {sessionPhase ?? "AWAITING SESSION"}
        <SessionBadge phase={sessionPhase} />
      </span>

      <span className={haltCount > 0 ? "font-semibold text-halt" : undefined}>
        {haltCount === 0
          ? "no halts"
          : `${haltCount} symbol${haltCount === 1 ? "" : "s"} halted`}
      </span>

      <span>{symbolCount} symbols</span>

      <span className="ml-auto flex items-center gap-4">
        <span>CALF {connection === "LIVE" ? "connected" : connection.toLowerCase()}</span>
        <span className="tabular">{clock} UTC</span>
      </span>
    </footer>
  );
}
