/** Alerts / Issues (design §11): fingerprint-aggregated, acknowledgement model. */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { api } from "../lib/api.js";
import { usePrefsStore } from "../store/usePrefsStore.js";
import { SeverityBadge } from "../components/SeverityBadge.js";

type Tab = "unacked" | "acked" | "all";

export function AlertsView() {
  const [tab, setTab] = useState<Tab>("unacked");
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});
  const operatorName = usePrefsStore((s) => s.operatorName);
  const setOperatorName = usePrefsStore((s) => s.setOperatorName);
  const queryClient = useQueryClient();

  const { data } = useQuery({
    queryKey: ["issues", { acked: tab === "all" ? undefined : tab === "acked" }],
    queryFn: () => api.issues({ acked: tab === "all" ? undefined : tab === "acked", minLevel: "WARNING" }),
    refetchInterval: 10_000,
  });

  const ackMutation = useMutation({
    mutationFn: ({ fingerprint, note }: { fingerprint: string; note?: string }) =>
      api.ackIssue(fingerprint, operatorName || "unknown", note),
    onSuccess: (_ack, { fingerprint }) => {
      queryClient.invalidateQueries({ queryKey: ["issues"] });
      setNoteDrafts((d) => {
        const next = { ...d };
        delete next[fingerprint];
        return next;
      });
    },
  });
  const unackMutation = useMutation({
    mutationFn: (fingerprint: string) => api.unackIssue(fingerprint, operatorName || "unknown"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["issues"] }),
  });

  const issues = data?.issues ?? [];

  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="flex items-center gap-3 text-sm">
        {(["unacked", "acked", "all"] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={clsx("rounded px-2 py-1", tab === t ? "bg-accent text-white" : "border border-border")}
          >
            {t}
          </button>
        ))}
        <input
          className="ml-auto rounded border border-border bg-bg px-2 py-1 text-sm"
          placeholder="your name (for ack attribution)"
          value={operatorName}
          onChange={(e) => setOperatorName(e.target.value)}
        />
      </div>

      <div className="flex flex-col gap-2">
        {issues.map((issue) => (
          <div
            key={issue.fingerprint}
            className={clsx(
              "rounded border-l-4 bg-bg-subtle p-3",
              issue.level === "CRITICAL" ? "border-level-critical" : "border-level-error",
            )}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <SeverityBadge level={issue.level} />
                <span className="font-semibold">{issue.process}</span>
                <span className="text-fg-subtle">· {issue.logger}</span>
                <span className="text-fg-subtle">×{issue.count}</span>
                {issue.recurredSinceAck && (
                  <span className="rounded bg-level-warning/20 px-1.5 text-xs text-level-warning">
                    recurred since ack
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {issue.ack ? (
                  <button
                    type="button"
                    onClick={() => unackMutation.mutate(issue.fingerprint)}
                    className="rounded border border-border px-2 py-1 text-xs"
                  >
                    Un-ack
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() =>
                      ackMutation.mutate({
                        fingerprint: issue.fingerprint,
                        note: noteDrafts[issue.fingerprint],
                      })
                    }
                    className="rounded bg-accent px-2 py-1 text-xs font-semibold text-white"
                  >
                    ✓ Acknowledge
                  </button>
                )}
              </div>
            </div>
            <div className="mt-1 truncate font-mono text-sm">{issue.sampleMessage}</div>
            <div className="mt-1 text-xs text-fg-subtle">
              first {issue.firstSeen.slice(11, 19)} · last {issue.lastSeen.slice(11, 19)}
            </div>
            {issue.ack && (
              <div className="mt-1 text-xs text-fg-subtle">
                ✓ acked {issue.ack.ackedAt.slice(11, 16)} by {issue.ack.ackedBy}
                {issue.ack.note && ` — "${issue.ack.note}"`}
              </div>
            )}
            {!issue.ack && (
              <input
                className="mt-2 w-full rounded border border-border bg-bg px-2 py-1 text-xs"
                placeholder="note (what was done)…"
                value={noteDrafts[issue.fingerprint] ?? ""}
                onChange={(e) => setNoteDrafts((d) => ({ ...d, [issue.fingerprint]: e.target.value }))}
              />
            )}
          </div>
        ))}
        {issues.length === 0 && <div className="text-sm text-fg-subtle">No issues in this view.</div>}
      </div>
    </div>
  );
}
