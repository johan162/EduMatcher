/**
 * The event log (design §13, row 7): newest first, filterable by kind,
 * each event's time on the session clock and its severity in glyph and
 * word. Virtualised: only the rows in view (and a few either side) are in
 * the DOM, so a long day's log scrolls as lightly as a short one.
 */

import clsx from "clsx";
import { useMemo, useState } from "react";
import type { EventKind, HealthEvent } from "@edumatcher/dash-types";
import { SEVERITY } from "../../lib/status.js";
import { formatTime } from "../../lib/time.js";

export interface EventLogProps {
  label: string;
  events: readonly HealthEvent[];
  tz: string;
  /** Visible height in px. */
  height?: number;
  rowHeight?: number;
}

const OVERSCAN = 5;

/** The rows to render for a scroll position: [first, last) of `count`. */
export function windowOf(scrollTop: number, height: number, rowHeight: number, count: number): [number, number] {
  const first = Math.max(0, Math.floor(scrollTop / rowHeight) - OVERSCAN);
  const last = Math.min(count, Math.ceil((scrollTop + height) / rowHeight) + OVERSCAN);
  return [first, last];
}

export function EventLog({ label, events, tz, height = 240, rowHeight = 22 }: EventLogProps) {
  const [hidden, setHidden] = useState<ReadonlySet<EventKind>>(new Set());
  const [scrollTop, setScrollTop] = useState(0);

  const kinds = useMemo(() => [...new Set(events.map((e) => e.kind))].sort(), [events]);
  const shown = useMemo(
    () => events.filter((e) => !hidden.has(e.kind)).sort((a, b) => b.seq - a.seq),
    [events, hidden],
  );
  const [first, last] = windowOf(scrollTop, height, rowHeight, shown.length);

  const toggle = (kind: EventKind) =>
    setHidden((h) => {
      const next = new Set(h);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });

  return (
    <section aria-label={label} className="flex flex-col gap-2">
      <div role="group" aria-label="Event kinds" className="flex flex-wrap gap-1">
        {kinds.map((kind) => (
          <button
            key={kind}
            type="button"
            aria-pressed={!hidden.has(kind)}
            onClick={() => toggle(kind)}
            className={clsx(
              "rounded px-2 py-0.5 text-[11px] font-medium",
              hidden.has(kind) ? "bg-bg-inset text-fg-faint line-through" : "bg-bg-raised text-fg",
            )}
          >
            {kind}
          </button>
        ))}
      </div>
      <div
        role="log"
        aria-label={`${label}, newest first`}
        data-count={shown.length}
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
        style={{ height }}
        className="overflow-y-auto rounded border border-border bg-bg-inset font-mono text-xs"
      >
        <ol style={{ height: shown.length * rowHeight, position: "relative" }} className="m-0 list-none p-0">
          {shown.slice(first, last).map((e, i) => {
            const look = SEVERITY[e.severity];
            return (
              <li
                key={e.seq}
                data-seq={e.seq}
                style={{ position: "absolute", top: (first + i) * rowHeight, height: rowHeight, left: 0, right: 0 }}
                className="flex items-center gap-3 whitespace-nowrap px-2"
              >
                <span className="tabular text-fg-subtle">{formatTime(e.ts, tz)}</span>
                <span className={clsx("w-14 font-semibold", look.text)}>
                  <span aria-hidden="true">{look.glyph}</span> {look.label}
                </span>
                <span className="w-32 text-fg">{e.kind}</span>
                <span className="w-40 truncate text-fg">{e.subject}</span>
                <span className="truncate text-fg-subtle">{e.detail}</span>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}
