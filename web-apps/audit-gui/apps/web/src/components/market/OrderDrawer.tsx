/**
 * The order drawer (design §9.3, §9.9): one click from any lifeline to its
 * story, its checks and its raw records. URL-addressed (`order`, `run`,
 * `tab`), so Back/Forward and a copied link restore it.
 */
import { useEffect } from "react";
import { X } from "lucide-react";
import { useOrderEvents, useOrderStory } from "@/api/queries";
import { QueryState } from "@/components/shared/QueryState";
import { receiptTime } from "@/lib/time";

export type DrawerTab = "story" | "checks" | "raw";

const TABS: { id: DrawerTab; label: string }[] = [
  { id: "story", label: "Story" },
  { id: "checks", label: "Checks" },
  { id: "raw", label: "Raw evidence" },
];

interface Props {
  snapshotId: string;
  orderId: string;
  run: number | null;
  tab: DrawerTab;
  onTab: (tab: DrawerTab) => void;
  onClose: () => void;
}

export function OrderDrawer({ snapshotId, orderId, run, tab, onTab, onClose }: Props) {
  const story = useOrderStory(snapshotId, orderId, run);
  const raw = useOrderEvents(snapshotId, orderId, tab === "raw");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside
      role="dialog"
      aria-label={`Order ${orderId.slice(0, 8)}…${run !== null ? ` (run ${run})` : ""}`}
      className="flex h-full w-[34rem] max-w-full shrink-0 flex-col border-l border-line bg-panel"
    >
      <header className="flex items-center gap-2 border-b border-line px-3 py-2">
        <h2 className="font-mono text-sm font-semibold" title={orderId}>
          Order {orderId.slice(0, 8)}…
        </h2>
        {run !== null && <span className="text-xs text-fg-dim">run {run}</span>}
        <span className="flex-1" />
        <button type="button" onClick={onClose} aria-label="Close" className="text-fg-dim hover:text-fg">
          <X size={16} />
        </button>
      </header>
      <div role="tablist" aria-label="Order evidence" className="flex gap-1 border-b border-line px-3">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => onTab(t.id)}
            className={`px-2 py-1.5 text-xs ${tab === t.id ? "border-b-2 border-accent text-fg" : "text-fg-dim hover:text-fg"}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" className="min-h-0 flex-1 overflow-auto p-3 text-xs">
        {tab === "story" && (
          <QueryState query={story}>
            {(s) => (
              <div className="space-y-3">
                {s.episodes.map((e) => (
                  <p key={e.id} className="text-fg-dim">
                    <span className="font-semibold text-fg">{e.kind}</span> {e.anchor.slice(0, 8)}… · {e.outcome} · {e.summary}
                  </p>
                ))}
                <ol className="space-y-1.5">
                  {s.beats.map((b) => (
                    <li key={`${b.episode}-${b.seq}`} className="grid grid-cols-[auto_1fr] gap-x-2">
                      <span className="font-mono text-fg-faint">{receiptTime(b.receipt_ts).slice(11)}</span>
                      <span>{b.text}</span>
                    </li>
                  ))}
                </ol>
                <p className="text-fg-faint">
                  Narration by pm-audit-replay; links are labelled by confidence ({s.links.map((l) => l.confidence).join(", ") || "none"}).
                </p>
              </div>
            )}
          </QueryState>
        )}
        {tab === "checks" && (
          <QueryState query={story}>
            {(s) =>
              s.anomalies.length === 0 ? (
                <p>No finding on this order's episodes.</p>
              ) : (
                <ul className="space-y-1.5">
                  {s.anomalies.map((a, i) => (
                    <li key={i}>
                      <span className="font-mono font-semibold">{a.code}</span> · {a.severity} · {a.lane} lane — {a.detail}
                    </li>
                  ))}
                </ul>
              )
            }
          </QueryState>
        )}
        {tab === "raw" && (
          <QueryState query={raw}>
            {(page) => (
              <>
                <table className="w-full border-collapse text-left">
                  <caption className="sr-only">Raw evidence</caption>
                  <thead className="text-fg-dim">
                    <tr>
                      <th className="pr-2 font-normal">Receipt (UTC)</th>
                      <th className="pr-2 font-normal">Topic</th>
                      <th className="pr-2 font-normal">Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.events.map((e) => (
                      <tr key={e.key} className="border-t border-line align-top">
                        <td className="pr-2 font-mono">{receiptTime(e.receipt_ts).slice(11)}</td>
                        <td className="pr-2 font-mono">
                          {e.topic}
                          <pre className="mt-1 whitespace-pre-wrap break-all text-[10px] text-fg-dim">{JSON.stringify(e.fields)}</pre>
                        </td>
                        <td className="font-mono">{`${e.source.file ?? "?"}:${e.source.line}`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {page.has_more && <p className="mt-2 text-fg-dim">The first 1,000 records naming this order are shown.</p>}
              </>
            )}
          </QueryState>
        )}
      </div>
    </aside>
  );
}
