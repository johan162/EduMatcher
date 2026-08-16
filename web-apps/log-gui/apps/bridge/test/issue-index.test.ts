import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { AckStore } from "../src/ack-store.js";
import { IssueIndex } from "../src/issue-index.js";
import type { LogRow } from "@edumatcher/log-types";

function row(overrides: Partial<LogRow> = {}): LogRow {
  return {
    seq: 1,
    client_ts: "2026-07-29T10:00:00.000Z",
    server_ts: "2026-07-29T10:00:00.010Z",
    process: "pm-engine",
    instance: null,
    pid: 123,
    host: "trader-lt",
    session: "s1",
    level: "ERROR",
    logger: "edumatcher.engine.book",
    module: "book.py",
    line: 412,
    has_exception: false,
    truncated: false,
    message: "ConnectionRefusedError: [Errno 111] Connection refused",
    ...overrides,
  };
}

describe("IssueIndex minLevel", () => {
  let dir: string;
  let ackStore: AckStore;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "log-ui-acks-"));
    ackStore = new AckStore(join(dir, "acks.db"));
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it("gates live ingest and the startup seed identically", () => {
    // ISSUES_MIN_LEVEL used to apply only to the seed while live rows were
    // tested against a hard-coded WARNING/ERROR/CRITICAL set, so the index
    // disagreed with itself across a restart. Both paths must now agree.
    const warning = row({ level: "WARNING", seq: 1, message: "disk nearly full" });

    const atWarning = new IssueIndex(ackStore, "WARNING");
    const atError = new IssueIndex(ackStore, "ERROR");

    expect(atWarning.ingest(warning)).not.toBeNull();
    expect(atError.ingest(warning)).toBeNull();

    const seededAtWarning = new IssueIndex(ackStore, "WARNING");
    const seededAtError = new IssueIndex(ackStore, "ERROR");
    seededAtWarning.seed([warning]);
    seededAtError.seed([warning]);

    expect(seededAtWarning.list()).toHaveLength(atWarning.list().length);
    expect(seededAtError.list()).toHaveLength(atError.list().length);
  });

  it("still admits levels above the configured floor", () => {
    const index = new IssueIndex(ackStore, "ERROR");
    expect(index.ingest(row({ level: "CRITICAL", seq: 2 }))).not.toBeNull();
    expect(index.ingest(row({ level: "INFO", seq: 3, message: "started" }))).toBeNull();
  });

  it("defaults to WARNING when no level is configured", () => {
    const index = new IssueIndex(ackStore);
    expect(index.ingest(row({ level: "WARNING", seq: 4, message: "slow" }))).not.toBeNull();
    expect(index.ingest(row({ level: "INFO", seq: 5, message: "ok" }))).toBeNull();
  });
});

describe("IssueIndex", () => {
  let dir: string;
  let ackStore: AckStore;
  let index: IssueIndex;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "log-ui-acks-"));
    ackStore = new AckStore(join(dir, "acks.db"));
    index = new IssueIndex(ackStore);
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it("returns null for rows below the fingerprint threshold (INFO/DEBUG)", () => {
    expect(index.ingest(row({ level: "INFO" }))).toBeNull();
    expect(index.ingest(row({ level: "DEBUG" }))).toBeNull();
  });

  it("groups a storm of identical errors into one issue with a count", () => {
    for (let i = 0; i < 5000; i++) {
      index.ingest(row({ seq: i + 1 }));
    }
    const issues = index.list();
    expect(issues).toHaveLength(1);
    expect(issues[0]!.count).toBe(5000);
  });

  it("marks an issue as recurred after being acked when new events arrive", () => {
    const first = index.ingest(row({ seq: 1 }))!;
    ackStore.ack({
      fingerprint: first.fingerprint,
      ackedBy: "operator1",
      note: "handled",
      ackedThroughSeq: 1,
      level: first.level,
      process: first.process,
      logger: first.logger,
      sampleMessage: first.sampleMessage,
    });
    const acked = index.get(first.fingerprint)!;
    expect(acked.recurredSinceAck).toBe(false);

    index.ingest(row({ seq: 2 }));
    const recurred = index.get(first.fingerprint)!;
    expect(recurred.recurredSinceAck).toBe(true);
  });

  it("list({acked: false}) excludes acked-and-quiet issues but includes recurred ones", () => {
    const issue = index.ingest(row({ seq: 1 }))!;
    ackStore.ack({
      fingerprint: issue.fingerprint,
      ackedBy: "op",
      note: null,
      ackedThroughSeq: 1,
      level: issue.level,
      process: issue.process,
      logger: issue.logger,
      sampleMessage: issue.sampleMessage,
    });
    expect(index.list({ acked: false })).toHaveLength(0);

    index.ingest(row({ seq: 2 }));
    expect(index.list({ acked: false })).toHaveLength(1);
  });

  it("unackedCount reflects only unacknowledged issues at or above the alert level", () => {
    index.ingest(row({ level: "WARNING", message: "low severity" }));
    index.ingest(row({ level: "ERROR", message: "high severity" }));
    expect(index.unackedCount("ERROR")).toBe(1);
    expect(index.unackedCount("WARNING")).toBe(2);
  });

  it("pruneOlderThan removes issues with no activity since the cutoff", () => {
    index.ingest(row({ client_ts: "2026-01-01T00:00:00.000Z" }));
    expect(index.list()).toHaveLength(1);
    index.pruneOlderThan("2026-07-01T00:00:00.000Z");
    expect(index.list()).toHaveLength(0);
  });
});
