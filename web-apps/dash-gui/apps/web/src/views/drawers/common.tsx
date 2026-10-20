/**
 * What the three drawers share (D4.2): the figures list, the subject's
 * events, the cross-app link, and the drawer's body for a subject the
 * latest snapshot does not hold.
 */

import { ExternalLink } from "lucide-react";
import { useMemo, type ReactNode } from "react";
import type { EventsResponse, HealthEvent } from "@edumatcher/dash-types";
import { Drawer } from "../../components/layout/Drawer.js";
import { EventLog } from "../../components/widgets/EventLog.js";
import { useHistory } from "../../hooks/history.js";
import { getJson, query } from "../../lib/api.js";
import { useDashStore } from "../../store/useDashStore.js";

/** Label and value pairs, in a grid that wraps on narrow drawers. */
export function Facts({ label, items }: { label: string; items: readonly (readonly [string, ReactNode])[] }) {
  return (
    <dl aria-label={label} className="m-0 grid grid-cols-2 gap-x-6 gap-y-2 text-xs sm:grid-cols-3">
      {items.map(([name, value]) => (
        <div key={name} className="min-w-0">
          <dt className="truncate text-[11px] uppercase tracking-wide text-fg-faint">{name}</dt>
          <dd className="m-0 truncate tabular text-fg">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A titled part of a drawer. */
export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="mt-5">
      <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-fg-subtle">{title}</h3>
      {children}
    </section>
  );
}

/** A link into a sibling GUI, opened in a new tab. */
export function CrossLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 whitespace-nowrap text-accent hover:underline">
      {children}
      <ExternalLink size={12} aria-hidden="true" />
    </a>
  );
}

/**
 * The drawer while its subject cannot be shown: before the first snapshot,
 * or when the latest one does not hold it (a mistyped or outdated link).
 */
export function Unavailable({ kind, title, what }: { kind: string; title: string; what: string }) {
  const loaded = useDashStore((s) => s.snapshot !== null);
  return (
    <Drawer kind={kind} title={title}>
      <p role="status" className="m-0 text-sm text-fg-subtle">
        {loaded ? `No ${what} “${title}” in the latest snapshot.` : "Waiting for the first snapshot…"}
      </p>
    </Drawer>
  );
}

/** The events about one subject over the picked range, the live ones added. */
export function SubjectEvents({ subject }: { subject: string }) {
  const tz = useDashStore((s) => s.sessionTz);
  const live = useDashStore((s) => s.events);
  const history = useHistory<EventsResponse>(`events|${subject}`, (range, signal) =>
    getJson(`/api/events?${query({ range, subject, limit: 500 })}`, signal),
  );
  const events = useMemo(() => {
    const bySeq = new Map<number, HealthEvent>();
    for (const e of history.data?.events ?? []) bySeq.set(e.seq, e);
    for (const e of live) if (e.subject === subject) bySeq.set(e.seq, e);
    return [...bySeq.values()];
  }, [history.data, live, subject]);
  return (
    <Section title="Events">
      <EventLog label={`Events of ${subject}`} events={events} tz={tz} height={176} />
    </Section>
  );
}
