/** Connections board (design §10): the LALF connect/disconnect registry. */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import type { ProcessRow } from "@edumatcher/log-types";
import { api } from "../lib/api.js";
import { useUiConfig } from "../lib/useUiConfig.js";

function idleSeconds(lastSeenAt: string): number {
  return (Date.now() - new Date(lastSeenAt).getTime()) / 1000;
}

function statusGlyph(
  disconnectedAt: string | null,
  lastSeenAt: string,
  silenceSec: number,
): string {
  if (disconnectedAt) return "○";
  return idleSeconds(lastSeenAt) >= silenceSec ? "⚠" : "●";
}

/**
 * A probe is the short-lived connection every process opens before it starts
 * logging: the log client says HELLO purely to decide whether pm-log-srv is
 * reachable, then closes and opens the connection it actually logs over
 * (`logclient/discovery.py:resolve_handler`). Since this table has one row per
 * connection, that probe appears as a second row for the same PID — connected
 * and disconnected in the same second, having logged nothing. Hidden by
 * default because it looks alarmingly like a process flapping.
 */
function isProbe(row: ProcessRow): boolean {
  return row.disconnected_at !== null && row.log_count === 0;
}

export function ConnectionsView() {
  const navigate = useNavigate();
  const uiConfig = useUiConfig();
  const [hideProbes, setHideProbes] = useState(true);
  const { data } = useQuery({
    queryKey: ["processes"],
    queryFn: api.processes,
    refetchInterval: 10_000,
  });

  const all = useMemo(() => data?.processes ?? [], [data]);
  const probeCount = useMemo(() => all.filter(isProbe).length, [all]);
  const rows = hideProbes ? all.filter((row) => !isProbe(row)) : all;

  return (
    <div className="p-4">
      <div className="mb-2 flex flex-wrap items-center gap-4 text-xs text-fg-subtle">
        <p>
          ● logging · ⚠ silent for{" "}
          {uiConfig ? `${uiConfig.processSilenceSec}s` : "…"} or more · ○ disconnected
        </p>
        <label
          className="flex items-center gap-1"
          title="Every process opens a short-lived connection to check whether the log server is there, then a second one to log over. The first shows up here as a connection that disconnected without logging anything."
        >
          <input
            type="checkbox"
            checked={hideProbes}
            onChange={(e) => setHideProbes(e.target.checked)}
          />
          Hide probes{probeCount > 0 ? ` (${probeCount})` : ""}
        </label>
      </div>
      <table className="w-full text-left text-sm">
        {/* Sticky against <main>, which is the scroll container (AppShell).
            The background is required or rows show through as they pass under. */}
        <thead className="sticky top-0 z-10 bg-bg text-xs uppercase text-fg-subtle">
          <tr>
            <th className="border-b border-border py-1 pr-2"> </th>
            <th className="border-b border-border py-1 pr-2">Process</th>
            <th className="border-b border-border py-1 pr-2">PID</th>
            <th className="border-b border-border py-1 pr-2">Host</th>
            <th className="border-b border-border py-1 pr-2">Connected</th>
            <th className="border-b border-border py-1 pr-2">Last seen</th>
            <th className="border-b border-border py-1 pr-2">Logs</th>
            <th className="border-b border-border py-1 pr-2">Errors</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.session}
              className="cursor-pointer border-b border-border/50 font-mono hover:bg-bg-subtle"
              onClick={() => navigate(`/logs?processes=${encodeURIComponent(row.process)}`)}
            >
              <td className="py-1 pr-2">
                {statusGlyph(
                  row.disconnected_at,
                  row.last_seen_at,
                  // Until the config arrives, flag nothing: a spurious ⚠ on
                  // every healthy process is worse than a moment's delay.
                  uiConfig?.processSilenceSec ?? Infinity,
                )}
              </td>
              <td className="py-1 pr-2">
                {row.process}
                {row.instance ? (
                  <span className="text-fg-subtle"> ({row.instance})</span>
                ) : null}
              </td>
              <td className="py-1 pr-2">{row.pid}</td>
              <td className="py-1 pr-2">{row.host}</td>
              <td className="py-1 pr-2 text-fg-subtle">{row.connected_at.slice(11, 19)}</td>
              <td className="py-1 pr-2 text-fg-subtle">
                {row.disconnected_at ? "disconnected" : `${idleSeconds(row.last_seen_at).toFixed(0)}s ago`}
              </td>
              <td className="py-1 pr-2">{row.log_count.toLocaleString()}</td>
              <td className="py-1 pr-2 text-level-error">{row.errorCount}</td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={8} className="py-4 text-center text-fg-subtle">
                {all.length === 0
                  ? "No connections recorded yet."
                  : "Only probe connections recorded — untick “Hide probes” to see them."}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
