/**
 * The one writable store in the whole application (design §11.2, §16.4).
 *
 * Separate SQLite file from `log.db`, so `pm-log-srv`'s append-only,
 * single-writer guarantee on `log_events` is never touched by this project.
 */

import { DatabaseSync } from "node:sqlite";
import type { AckHistoryAction, AckHistoryEntry, AckRecord } from "@edumatcher/log-types";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

const SCHEMA = `
CREATE TABLE IF NOT EXISTS issue_acks (
    fingerprint        TEXT PRIMARY KEY,
    acked_at           TEXT NOT NULL,
    acked_by           TEXT NOT NULL,
    note               TEXT,
    acked_through_seq  INTEGER NOT NULL,
    level              TEXT NOT NULL,
    process            TEXT NOT NULL,
    logger             TEXT NOT NULL,
    sample_message     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_acks_at ON issue_acks(acked_at);

CREATE TABLE IF NOT EXISTS ack_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint  TEXT NOT NULL,
    action       TEXT NOT NULL,
    at           TEXT NOT NULL,
    by           TEXT NOT NULL,
    note         TEXT
);
`;

interface AckRow {
  fingerprint: string;
  acked_at: string;
  acked_by: string;
  note: string | null;
  acked_through_seq: number;
  level: string;
  process: string;
  logger: string;
  sample_message: string;
}

function toAckRecord(row: AckRow): AckRecord {
  return {
    fingerprint: row.fingerprint,
    ackedAt: row.acked_at,
    ackedBy: row.acked_by,
    note: row.note,
    ackedThroughSeq: row.acked_through_seq,
  };
}

export class AckStore {
  private readonly db: DatabaseSync;

  constructor(path: string) {
    mkdirSync(dirname(path), { recursive: true });
    this.db = new DatabaseSync(path);
    this.db.exec("PRAGMA journal_mode = WAL");
    this.db.exec(SCHEMA);
  }

  get(fingerprint: string): AckRecord | null {
    const row = this.db
      .prepare("SELECT * FROM issue_acks WHERE fingerprint = ?")
      .get(fingerprint) as AckRow | undefined;
    return row ? toAckRecord(row) : null;
  }

  getAll(): Map<string, AckRecord> {
    const rows = this.db.prepare("SELECT * FROM issue_acks").all() as unknown as AckRow[];
    return new Map(rows.map((r) => [r.fingerprint, toAckRecord(r)]));
  }

  ack(input: {
    fingerprint: string;
    ackedBy: string;
    note: string | null;
    ackedThroughSeq: number;
    level: string;
    process: string;
    logger: string;
    sampleMessage: string;
  }): AckRecord {
    const ackedBefore =
      this.db
        .prepare("SELECT 1 AS found FROM ack_history WHERE fingerprint = ? LIMIT 1")
        .get(input.fingerprint) !== undefined;
    const ackedAt = new Date().toISOString();
    this.db
      .prepare(
        `INSERT INTO issue_acks
           (fingerprint, acked_at, acked_by, note, acked_through_seq, level, process, logger, sample_message)
         VALUES (@fingerprint, @acked_at, @acked_by, @note, @acked_through_seq, @level, @process, @logger, @sample_message)
         ON CONFLICT(fingerprint) DO UPDATE SET
           acked_at = excluded.acked_at,
           acked_by = excluded.acked_by,
           note = excluded.note,
           acked_through_seq = excluded.acked_through_seq`,
      )
      .run({
        fingerprint: input.fingerprint,
        acked_at: ackedAt,
        acked_by: input.ackedBy,
        note: input.note,
        acked_through_seq: input.ackedThroughSeq,
        level: input.level,
        process: input.process,
        logger: input.logger,
        sample_message: input.sampleMessage,
      });
    this.appendHistory(input.fingerprint, ackedBefore ? "REACK" : "ACK", input.ackedBy, input.note);
    return this.get(input.fingerprint)!;
  }

  unack(fingerprint: string, by: string): boolean {
    const result = this.db.prepare("DELETE FROM issue_acks WHERE fingerprint = ?").run(fingerprint);
    const changed = Number(result.changes) > 0;
    if (changed) {
      this.appendHistory(fingerprint, "UNACK", by, null);
    }
    return changed;
  }

  history(fingerprint: string): AckHistoryEntry[] {
    const rows = this.db
      .prepare("SELECT * FROM ack_history WHERE fingerprint = ? ORDER BY id ASC")
      .all(fingerprint) as unknown as AckHistoryEntry[];
    return rows;
  }

  private appendHistory(
    fingerprint: string,
    action: AckHistoryAction,
    by: string,
    note: string | null,
  ): void {
    this.db
      .prepare(
        "INSERT INTO ack_history (fingerprint, action, at, by, note) VALUES (?,?,?,?,?)",
      )
      .run(fingerprint, action, new Date().toISOString(), by, note);
  }

  get ackedCount(): number {
    const row = this.db.prepare("SELECT COUNT(*) AS n FROM issue_acks").get() as { n: number };
    return row.n;
  }
}
