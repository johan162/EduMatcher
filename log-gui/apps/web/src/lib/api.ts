/** Thin REST client for `/api/*` (design §16.2). All reads are GET. */

import type {
  AckRecord,
  ByLevelResponse,
  ByProcessResponse,
  DiagnosticsResponse,
  Issue,
  LogFilter,
  LogRow,
  ProcessRow,
  StatsSummary,
  TimeseriesResponse,
} from "@edumatcher/log-types";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error((body as { message?: string }).message ?? `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

function filterToQuery(filter: LogFilter, extra: Record<string, string | number | undefined> = {}): string {
  const params = new URLSearchParams();
  if (filter.minLevel) params.set("minLevel", filter.minLevel);
  if (filter.processes?.length) params.set("processes", filter.processes.join(","));
  if (filter.loggers?.length) params.set("loggers", filter.loggers.join(","));
  if (filter.sessions?.length) params.set("sessions", filter.sessions.join(","));
  if (filter.contains) params.set("contains", filter.contains);
  if (filter.exceptionsOnly) params.set("exceptionsOnly", "true");
  if (filter.from) params.set("from", filter.from);
  if (filter.to) params.set("to", filter.to);
  for (const [key, value] of Object.entries(extra)) {
    if (value !== undefined) params.set(key, String(value));
  }
  return params.toString();
}

export const api = {
  logs: (filter: LogFilter, opts: { cursor?: number; limit?: number; direction?: "ASC" | "DESC" } = {}) =>
    getJson<{ rows: LogRow[] }>(`/api/logs?${filterToQuery(filter, opts)}`),

  logsCount: (filter: LogFilter) => getJson<{ count: number }>(`/api/logs/count?${filterToQuery(filter)}`),

  statsSummary: () => getJson<StatsSummary>("/api/stats/summary"),

  timeseries: (window: string, bucket: string, groupBy?: "level" | "process") =>
    getJson<TimeseriesResponse>(
      `/api/stats/timeseries?window=${window}&bucket=${bucket}${groupBy ? `&group_by=${groupBy}` : ""}`,
    ),

  byLevel: (window: string) => getJson<ByLevelResponse>(`/api/stats/by-level?window=${window}`),

  byProcess: (window: string, level?: string) =>
    getJson<ByProcessResponse>(`/api/stats/by-process?window=${window}${level ? `&level=${level}` : ""}`),

  processes: () => getJson<{ processes: ProcessRow[] }>("/api/processes"),

  issues: (opts: { acked?: boolean; minLevel?: string } = {}) => {
    const params = new URLSearchParams();
    if (opts.acked !== undefined) params.set("acked", String(opts.acked));
    if (opts.minLevel) params.set("min_level", opts.minLevel);
    return getJson<{ issues: Issue[] }>(`/api/issues?${params.toString()}`);
  },

  issueEvents: (fingerprint: string) =>
    getJson<{ fingerprint: string; rows: LogRow[] }>(`/api/issues/${fingerprint}/events`),

  ackIssue: async (fingerprint: string, ackedBy: string, note?: string): Promise<AckRecord> => {
    const res = await fetch(`/api/issues/${fingerprint}/ack`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ackedBy, note }),
    });
    if (!res.ok) throw new Error(`ack failed: ${res.status}`);
    const body = (await res.json()) as { ack: AckRecord };
    return body.ack;
  },

  unackIssue: async (fingerprint: string, by: string): Promise<void> => {
    await fetch(`/api/issues/${fingerprint}/ack`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ by }),
    });
  },

  diagnostics: (opts: { process?: string; since?: string } = {}) => {
    const params = new URLSearchParams();
    if (opts.process) params.set("process", opts.process);
    if (opts.since) params.set("since", opts.since);
    return getJson<DiagnosticsResponse>(`/api/diagnostics?${params.toString()}`);
  },

  bridgeStatus: () =>
    getJson<{
      lalfPs: { ok: boolean; detail: string };
      logDb: { ok: boolean; detail: string };
      wsClients: number;
      fingerprintsIndexed: number;
      acksStored: number;
      subId: string;
      lastSeq: number;
    }>("/api/bridge/status"),
};
