/**
 * Times on the venue's clock, for components: `useFormatNs` for text built in
 * a component, `<Time>` where a cell or tile shows one time. Both re-render
 * when the session timezone arrives (lib/time.ts).
 */
import { useCallback } from "react";
import { formatIso, formatNs } from "@/lib/time";
import { useVenueTimeZoneStore } from "@/store/useVenueTimeZoneStore";

export function useFormatNs(): (ns: number | null | undefined) => string {
  const zone = useVenueTimeZoneStore((s) => s.timeZone);
  return useCallback((ns) => formatNs(ns, zone), [zone]);
}

/** An epoch-ns time (`ns`) or an ISO-8601 instant (`iso`). */
export function Time({ ns, iso }: { ns?: number | null; iso?: string }) {
  const zone = useVenueTimeZoneStore((s) => s.timeZone);
  return <span className="num">{iso !== undefined ? formatIso(iso, zone) : formatNs(ns, zone)}</span>;
}
