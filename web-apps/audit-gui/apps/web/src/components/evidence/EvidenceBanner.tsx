import { useState } from "react";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { useGapCount, useSnapshot } from "@/api/queries";
import type { SnapshotT } from "@/api/schemas";
import { useExplain } from "@/components/shared/Explain";
import { ErrorPanel, describeError } from "@/components/shared/QueryState";
import { receiptTime } from "@/lib/time";

const MANIFEST_TEXT = { verified: "checked, unanchored", failed: "failed", absent: "no manifest" } as const;

/** Whether a check failed: the manifest, or an attached forensics check (FAIL/ERROR). */
export function checkFailed(s: SnapshotT): boolean {
  const statuses = s.forensics?.inputs_match ? s.forensics.statuses : {};
  return s.manifest.state === "failed" || (statuses["FAIL"] ?? 0) > 0 || (statuses["ERROR"] ?? 0) > 0;
}

/**
 * The evidence banner (design §9.2 item 1), above every workspace: extent,
 * recorder gaps, manifest state, forensics, torn tail and what the evidence
 * cannot support. It folds to one line only while every check passed.
 */
export function EvidenceBanner({ snapshotId }: { snapshotId: string }) {
  const snapshot = useSnapshot(snapshotId);
  const [folded, setFolded] = useState(false);
  if (snapshot.isPending) return null;
  if (snapshot.isError) {
    return (
      <section aria-label="Evidence" className="border-b border-line p-3">
        <ErrorPanel error={snapshot.error} onRetry={() => void snapshot.refetch()} />
      </section>
    );
  }
  const s = snapshot.data;
  const failed = checkFailed(s);
  const Icon = failed ? ShieldAlert : ShieldCheck;
  return (
    <section
      aria-label="Evidence"
      className={`border-b px-4 py-2 text-xs ${failed ? "border-ask/50 bg-ask/10" : "border-line bg-panel"}`}
    >
      <div className="flex items-center gap-2">
        <Icon size={14} aria-hidden="true" className={failed ? "text-ask" : "text-fg-dim"} />
        <span>
          {s.first_ts && s.last_ts ? `${receiptTime(s.first_ts)} – ${receiptTime(s.last_ts)}` : "no records"} (receipt
          clock) · {s.entries.toLocaleString("en-US")} records · {s.runs.length} engine run{s.runs.length === 1 ? "" : "s"}
        </span>
        <span className="flex-1" />
        {failed ? (
          <span className="font-semibold text-ask">A check failed: the evidence details stay open.</span>
        ) : (
          <button type="button" onClick={() => setFolded((f) => !f)} className="text-fg-dim hover:text-fg">
            {folded ? "Show details" : "Hide details"}
          </button>
        )}
      </div>
      {(!folded || failed) && <Details s={s} />}
    </section>
  );
}

function Details({ s }: { s: SnapshotT }) {
  const explain = useExplain();
  const torn = s.files.reduce((n, f) => n + f.torn_bytes, 0);
  const statuses = s.forensics?.statuses;
  const restricted = Object.entries(s.capabilities).filter(([, c]) => !c.available);
  return (
    <div className="mt-1.5 grid gap-1 pl-6">
      <Gaps id={s.snapshot_id} />
      <div>
        Manifest: <span data-testid="manifest-state" className="font-semibold">{MANIFEST_TEXT[s.manifest.state]}</span>
        {s.manifest.problems.map((p, i) => (
          <div key={i} className="text-ask">
            {p.day ?? "chain"}: {p.message}
          </div>
        ))}
        {explain && s.manifest.state === "verified" && (
          <div className="text-fg-dim">
            Checked: the hash chain and every archive match. Unanchored: no copy of the head hash is kept outside this
            host, so a rewritten chain would not show.
          </div>
        )}
      </div>
      {statuses && (
        <div>
          Forensics:{" "}
          {Object.entries(statuses)
            .map(([status, n]) => `${n} ${status}`)
            .join(", ")}
          {!s.forensics?.inputs_match && " (about other inputs)"}
        </div>
      )}
      {torn > 0 && <div>Active file: a partial last line ({torn} bytes) left out.</div>}
      {restricted.length > 0 && (
        <div data-testid="restrictions">
          Not available:{" "}
          {restricted.map(([name, c]) => (
            <span key={name} title={c.detail} className="mr-2 font-mono">
              {name}: {c.reason}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/** Recorder gaps, from the replay's ESEQ_GAP findings; an error is never "no gap". */
function Gaps({ id }: { id: string }) {
  const gaps = useGapCount(id);
  if (gaps.isPending) return <div>Gaps: counting…</div>;
  if (gaps.isError) {
    return (
      <div role="alert" className="text-ask">
        Gaps unknown: {describeError(gaps.error)}
      </div>
    );
  }
  const { count, lowerBound } = gaps.data;
  const text =
    count === 0 ? "no recorder gap" : `${lowerBound ? "at least " : ""}${count} recorder gap${count === 1 ? "" : "s"}`;
  return (
    <div>
      Gaps: <span>{text}</span>
    </div>
  );
}
