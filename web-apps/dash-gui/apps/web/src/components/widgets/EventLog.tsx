/**
 * The event log (design §13, row 7): newest first, filterable by kind,
 * each event's time on the session clock and its severity in glyph and
 * word. Virtualised: only the rows in view (and a few either side) are in
 * the DOM, so a long day's log scrolls as lightly as a short one.
 *
 * - When the events span more than one session day, each time carries its
 *   date; hovering a row shows its full date, time and text.
 * - Scrolled down, new events arriving at the top do not move what is being
 *   read: the scroll position follows them. At the top, they simply appear.
 * - Changing the filter starts again at the top.
 */

import clsx from "clsx";
import { useLayoutEffect, useMemo, useRef, useState } from "react";
import type { EventKind, HealthEvent } from "@edumatcher/dash-types";
import { SEVERITY } from "../../lib/status.js";
import { formatDate, formatDateTime, formatTime } from "../../lib/time.js";

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
  const top = Math.min(Math.max(0, scrollTop), Math.max(0, count * rowHeight - height));
  const first = Math.max(0, Math.floor(top / rowHeight) - OVERSCAN);
  const last = Math.min(count, Math.ceil((top + height) / rowHeight) + OVERSCAN);
  return [first, last];
}

export function EventLog({ label, events, tz, height = 240, rowHeight = 22 }: EventLogProps) {
  const [hidden, setHidden] = useState<ReadonlySet<EventKind>>(new Set());
  const [scrollTop, setScrollTop] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const newest = useRef<number | null>(null);

  const kinds = useMemo(() => [...new Set(events.map((e) => e.kind))].sort(), [events]);
  const shown = useMemo(
    () => events.filter((e) => !hidden.has(e.kind)).sort((a, b) => b.seq - a.seq),
    [events, hidden],
  );
  const multiDay = useMemo(
    () => shown.length > 1 && formatDate(shown[0]!.ts, tz) !== formatDate(shown.at(-1)!.ts, tz),
    [shown, tz],
  );

  // Keep the rows being read in place when newer ones arrive above them.
  useLayoutEffect(() => {
    const el = box.current;
    const top = shown[0]?.seq ?? null;
    const before = newest.current;
    newest.current = top;
    if (!el || before === null || top === null || el.scrollTop === 0) return;
    const added = shown.findIndex((e) => e.seq <= before);
    if (added > 0) {
      el.scrollTop += added * rowHeight;
      setScrollTop(el.scrollTop);
    }
  }, [shown, rowHeight]);

  const [first, last] = windowOf(scrollTop, height, rowHeight, shown.length);

  const toggle = (kind: EventKind) => {
    setHidden((h) => {
      const next = new Set(h);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
    if (box.current) box.current.scrollTop = 0;
    setScrollTop(0);
    newest.current = null;
  };

  return (
    <section aria-label={label} data-widget="event-log" className="flex min-w-0 flex-col gap-2">
      {kinds.length > 0 && (
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
      )}
      <div
        ref={box}
        role="log"
        aria-label={`${label}, newest first`}
        data-count={shown.length}
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
        style={{ height }}
        className="overflow-y-auto overflow-x-hidden rounded border border-border bg-bg-inset font-mono text-xs"
      >
        {shown.length === 0 ? (
          <p className="m-0 p-2 text-fg-faint">No events</p>
        ) : (
          <ol style={{ height: shown.length * rowHeight, position: "relative" }} className="m-0 list-none p-0">
            {shown.slice(first, last).map((e, i) => {
              const look = SEVERITY[e.severity];
              const at = multiDay ? `${formatDate(e.ts, tz).slice(5)} ${formatTime(e.ts, tz)}` : formatTime(e.ts, tz);
              return (
                <li
                  key={first + i}
                  data-seq={e.seq}
                  title={`${formatDateTime(e.ts, tz)}  ${e.kind}  ${e.subject}  ${e.detail}`.trim()}
                  style={{ position: "absolute", top: (first + i) * rowHeight, height: rowHeight, left: 0, right: 0 }}
                  className="flex min-w-0 items-center gap-3 whitespace-nowrap px-2"
                >
                  <span className="shrink-0 tabular text-fg-subtle">{at}</span>
                  <span className={clsx("w-14 shrink-0 font-semibold", look.text)}>
                    <span aria-hidden="true">{look.glyph}</span> {look.label}
                  </span>
                  <span className="w-32 shrink-0 truncate text-fg">{e.kind}</span>
                  <span className="w-40 min-w-0 truncate text-fg">{e.subject}</span>
                  <span className="min-w-0 flex-1 truncate text-fg-subtle">{e.detail}</span>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </section>
  );
}
