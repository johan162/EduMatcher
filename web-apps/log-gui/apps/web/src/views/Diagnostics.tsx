/** Diagnostics (design §12): surfaces pm-log-cli's seven heuristics on a schedule. */

import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api.js";

export function DiagnosticsView() {
  const { data, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["diagnostics"],
    queryFn: () => api.diagnostics(),
    refetchInterval: 60_000,
    retry: false,
  });

  if (isError) {
    return (
      <div className="p-4 text-sm text-fg-subtle">
        Diagnostics unavailable: {(error as Error).message}. This is optional — every other view
        still works.
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="flex items-center gap-2 text-sm">
        <span className="text-fg-subtle">
          {data ? `Last run ${new Date(data.ranAt).toLocaleTimeString()} · ${data.findings.length} findings` : "…"}
        </span>
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          className="ml-auto rounded border border-border px-2 py-1 text-xs"
        >
          Re-run
        </button>
      </div>

      {(data?.findings ?? []).map((finding) => (
        <div
          key={finding.heuristic}
          className={
            "rounded border-l-4 bg-bg-subtle p-3 " +
            (finding.severity === "error" ? "border-level-error" : "border-level-warning")
          }
        >
          <div className="font-mono text-sm font-semibold">{finding.heuristic}</div>
          <div className="mt-1 text-sm">{finding.message}</div>
          <div className="mt-1 text-sm text-fg-subtle">→ {finding.recommendation}</div>
          <div className="mt-2 rounded bg-bg-inset px-2 py-1 font-mono text-xs">{finding.repro_command}</div>
        </div>
      ))}

      {data && data.passedHeuristics.length > 0 && (
        <div className="text-sm text-fg-subtle">
          ✓ No findings for: {data.passedHeuristics.join(" · ")}
        </div>
      )}
    </div>
  );
}
