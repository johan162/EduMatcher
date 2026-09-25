import { useState } from "react";
import { useAdminIndexesQuery, useHistoryIndexDailyQuery } from "@/queries/index.js";
import { ApiError } from "@/api/apiFetch.js";

const th = "px-2 py-1.5 text-left font-medium";
const thr = "px-2 py-1.5 text-right font-medium";

function fmtLevel(v: number | null | undefined): string {
  return v == null ? "—" : v.toFixed(2);
}

/**
 * Index Administration (§15.3) — read-only. Configured indexes (id, description,
 * base value, constituents) from `GET /admin/indexes`, and recent recorded
 * levels from `GET /history/index-daily` for the selected index.
 *
 * NOTE: `POST /admin/indexes/{id}/rebalance` does exist (a live pm-index bridge),
 * so this is no longer "blocked on a future bridge" as an earlier design
 * revision stated — but a corporate-action rebalance UI is out of scope for this
 * read-only admin phase, so no write control is shown here.
 */
export function AdminIndexesPage() {
  const indexesQuery = useAdminIndexesQuery();
  const indexes = indexesQuery.data?.indexes ?? [];
  const [selected, setSelected] = useState<string | null>(null);

  const dailyQuery = useHistoryIndexDailyQuery(selected);
  const statsUnavailable = dailyQuery.error instanceof ApiError && dailyQuery.error.status === 503;
  const rows = dailyQuery.data?.daily ?? [];

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-fg">Index Administration</h1>
        <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px] text-fg-dim">Read-only</span>
      </div>

      <p className="rounded border border-line bg-panel px-2 py-1.5 text-[11px] text-fg-dim">
        Index definitions are static configuration. Rebalancing (corporate actions) is available via
        the API (`POST /admin/indexes/&#123;id&#125;/rebalance`, pm-index bridge) but is not surfaced
        as a UI control in this read-only phase; use `pm-index-admin-cli` for write operations.
      </p>

      {indexesQuery.isError && (
        <p className="text-xs text-ask">Could not load index configuration from the engine.</p>
      )}

      {/* Configured indexes (§15.3) */}
      <section aria-label="Configured indexes" className="flex flex-col gap-1">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-fg-dim">
          Configured Indexes
        </h2>
        <div className="overflow-auto rounded border border-line">
          <table className="w-full border-collapse text-xs">
            <thead className="bg-panel text-fg-dim">
              <tr>
                <th className={th}>Index</th>
                <th className={th}>Description</th>
                <th className={thr}>Base Value</th>
                <th className={thr}>Constituents</th>
              </tr>
            </thead>
            <tbody>
              {indexes.map((idx) => (
                <tr
                  key={idx.id}
                  onClick={() => setSelected(idx.id)}
                  aria-selected={selected === idx.id}
                  className={`cursor-pointer border-b border-raised ${
                    selected === idx.id ? "bg-elevated" : "hover:bg-raised"
                  }`}
                >
                  <td className="px-2 py-1 font-mono font-medium">{idx.id}</td>
                  <td className="px-2 py-1 text-fg-dim">{idx.description || "—"}</td>
                  <td className="px-2 py-1 text-right font-mono">{idx.base_value}</td>
                  <td className="px-2 py-1 text-right font-mono text-fg-dim" title={idx.constituents.join(", ")}>
                    {idx.constituents.length}
                  </td>
                </tr>
              ))}
              {indexes.length === 0 && !indexesQuery.isLoading && (
                <tr>
                  <td colSpan={4} className="px-2 py-6 text-center text-fg-faint">
                    No indexes configured.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Recent recorded levels (§15.3 read-only history) */}
      <section aria-label="Index history" className="flex flex-col gap-1">
        <h2 className="text-[11px] font-semibold uppercase tracking-wide text-fg-dim">
          Recent Levels {selected ? `· ${selected}` : ""}
        </h2>
        {!selected ? (
          <p className="rounded border border-line p-4 text-center text-xs text-fg-faint">
            Select an index above to see its recorded daily levels.
          </p>
        ) : statsUnavailable ? (
          <p className="rounded border border-line p-4 text-xs text-fg-dim">
            Index history unavailable — the stats database is not running.
          </p>
        ) : (
          <div className="overflow-auto rounded border border-line">
            <table className="w-full border-collapse text-xs">
              <thead className="bg-panel text-fg-dim">
                <tr>
                  <th className={th}>Date</th>
                  <th className={thr}>Open</th>
                  <th className={thr}>High</th>
                  <th className={thr}>Low</th>
                  <th className={thr}>Close</th>
                  <th className={th}>Session</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={`${r.date ?? i}`} className="border-b border-raised">
                    <td className="px-2 py-1 font-mono">{r.date ?? "—"}</td>
                    <td className="px-2 py-1 text-right font-mono">{fmtLevel(r.open_level)}</td>
                    <td className="px-2 py-1 text-right font-mono">{fmtLevel(r.high_level)}</td>
                    <td className="px-2 py-1 text-right font-mono">{fmtLevel(r.low_level)}</td>
                    <td className="px-2 py-1 text-right font-mono text-fg">{fmtLevel(r.close_level)}</td>
                    <td className="px-2 py-1 text-fg-dim">{r.close_session_state ?? "—"}</td>
                  </tr>
                ))}
                {rows.length === 0 && !dailyQuery.isLoading && (
                  <tr>
                    <td colSpan={6} className="px-2 py-6 text-center text-fg-faint">
                      No recorded levels for {selected}.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
