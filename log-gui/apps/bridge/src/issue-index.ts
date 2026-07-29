/**
 * In-memory fingerprint→issue index (design §11.1, §11.5).
 *
 * Rebuildable — losing it costs a startup scan, not data. Ack records (in
 * `AckStore`) are the only thing actually persisted (§11.5).
 */

import type { AckStore } from "./ack-store.js";
import { computeFingerprint } from "./fingerprint.js";
import type { Issue, LogRow } from "@edumatcher/log-types";

const FINGERPRINTABLE_LEVELS = new Set(["WARNING", "ERROR", "CRITICAL"]);

interface IssueState {
  fingerprint: string;
  level: string;
  process: string;
  logger: string;
  sampleMessage: string;
  count: number;
  firstSeen: string;
  lastSeen: string;
  lastSeq: number;
}

export class IssueIndex {
  private readonly issues = new Map<string, IssueState>();

  constructor(private readonly ackStore: AckStore) {}

  /** Feed a batch of rows during the startup backfill scan (no events emitted). */
  seed(rows: LogRow[]): void {
    for (const row of rows) this.absorb(row);
  }

  /**
   * Feed one live row. Returns the updated `Issue` view when the row is
   * fingerprintable (WARNING+), or `null` for rows below the fingerprint
   * threshold — the caller uses a non-null return to decide whether to
   * broadcast a WS `issue` frame (design §6.4).
   */
  ingest(row: LogRow): Issue | null {
    const state = this.absorb(row);
    if (!state) return null;
    return this.toIssue(state);
  }

  private absorb(row: LogRow): IssueState | null {
    if (!FINGERPRINTABLE_LEVELS.has(row.level)) return null;
    const fingerprint = computeFingerprint(row);
    const existing = this.issues.get(fingerprint);
    if (existing) {
      existing.count += 1;
      existing.lastSeen = row.client_ts;
      existing.lastSeq = row.seq;
      return existing;
    }
    const created: IssueState = {
      fingerprint,
      level: row.level,
      process: row.process,
      logger: row.logger,
      sampleMessage: row.message,
      count: 1,
      firstSeen: row.client_ts,
      lastSeen: row.client_ts,
      lastSeq: row.seq,
    };
    this.issues.set(fingerprint, created);
    return created;
  }

  private toIssue(state: IssueState): Issue {
    const ack = this.ackStore.get(state.fingerprint);
    return {
      fingerprint: state.fingerprint,
      level: state.level as Issue["level"],
      process: state.process,
      logger: state.logger,
      sampleMessage: state.sampleMessage,
      count: state.count,
      firstSeen: state.firstSeen,
      lastSeen: state.lastSeen,
      lastSeq: state.lastSeq,
      ack,
      recurredSinceAck: ack !== null && state.lastSeq > ack.ackedThroughSeq,
    };
  }

  list(opts: { acked?: boolean; minLevel?: string } = {}): Issue[] {
    const levelRank: Record<string, number> = {
      DEBUG: 10,
      INFO: 20,
      WARNING: 30,
      ERROR: 40,
      CRITICAL: 50,
    };
    const floor = opts.minLevel ? levelRank[opts.minLevel] ?? 0 : 0;
    const out: Issue[] = [];
    for (const state of this.issues.values()) {
      if ((levelRank[state.level] ?? 0) < floor) continue;
      const issue = this.toIssue(state);
      if (opts.acked === true && issue.ack === null) continue;
      if (opts.acked === false && issue.ack !== null && !issue.recurredSinceAck) continue;
      out.push(issue);
    }
    out.sort((a, b) => b.lastSeq - a.lastSeq);
    return out;
  }

  get(fingerprint: string): Issue | null {
    const state = this.issues.get(fingerprint);
    return state ? this.toIssue(state) : null;
  }

  /** Unacked issue count at `alertLevel` or above — the top-bar badge (design §7.2, §8.5). */
  unackedCount(alertLevel: string): number {
    return this.list({ acked: false, minLevel: alertLevel }).length;
  }

  /** Ages out issues with no activity since `cutoffIso` (design §11.4 "Aged"). */
  pruneOlderThan(cutoffIso: string): void {
    for (const [fingerprint, state] of this.issues) {
      if (state.lastSeen < cutoffIso) this.issues.delete(fingerprint);
    }
  }
}
