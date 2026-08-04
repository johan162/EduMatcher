/** Processes board (design §10): connect/disconnect registry, launchpad to the Explorer. */

import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
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

export function ProcessesView() {
  const navigate = useNavigate();
  const uiConfig = useUiConfig();
  const { data } = useQuery({
    queryKey: ["processes"],
    queryFn: api.processes,
    refetchInterval: 10_000,
  });

  const rows = data?.processes ?? [];

  return (
    <div className="p-4">
      <p className="mb-2 text-xs text-fg-subtle">
        ● logging · ⚠ silent for{" "}
        {uiConfig ? `${uiConfig.processSilenceSec}s` : "…"} or more · ○ disconnected
      </p>
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase text-fg-subtle">
          <tr className="border-b border-border">
            <th className="py-1 pr-2"> </th>
            <th className="py-1 pr-2">Process</th>
            <th className="py-1 pr-2">PID</th>
            <th className="py-1 pr-2">Host</th>
            <th className="py-1 pr-2">Connected</th>
            <th className="py-1 pr-2">Last seen</th>
            <th className="py-1 pr-2">Logs</th>
            <th className="py-1 pr-2">Errors</th>
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
              <td className="py-1 pr-2">{row.process}</td>
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
                No processes recorded yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
