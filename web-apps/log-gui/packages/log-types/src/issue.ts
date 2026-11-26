/**
 * Fingerprint-aggregated issues and their acknowledgement state
 * (design §11.1, §11.2, §16.4).
 */

import type { LogLevel, LogRow } from "./log-row.js";

export interface Issue {
  /** The issue key: the message fingerprint qualified by its day, `<sha1[:16]>.<YYYY-MM-DD>`. */
  fingerprint: string;
  /** The session-timezone calendar day (YYYY-MM-DD) every occurrence in this issue falls on. */
  day: string;
  level: LogLevel;
  process: string;
  logger: string;
  /** One representative raw message, kept for display (over-grouping stays visible on inspection). */
  sampleMessage: string;
  count: number;
  firstSeen: string;
  lastSeen: string;
  lastSeq: number;
  ack: AckRecord | null;
  /** True when `lastSeq` has advanced past `ack.ackedThroughSeq` (design §11.4 "Recurred"). */
  recurredSinceAck: boolean;
}

export interface AckRecord {
  fingerprint: string;
  ackedAt: string;
  ackedBy: string;
  note: string | null;
  ackedThroughSeq: number;
}

export type AckHistoryAction = "ACK" | "UNACK" | "REACK";

export interface AckHistoryEntry {
  id: number;
  fingerprint: string;
  action: AckHistoryAction;
  at: string;
  by: string;
  note: string | null;
}

export interface IssueEventsResponse {
  fingerprint: string;
  rows: LogRow[];
}
