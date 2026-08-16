import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { AckStore } from "../src/ack-store.js";

describe("AckStore", () => {
  let dir: string;
  let store: AckStore;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "log-ui-acks-"));
    store = new AckStore(join(dir, "acks.db"));
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  const sample = {
    fingerprint: "abc123",
    ackedBy: "operator1",
    note: "restarted pm-md-gwy",
    ackedThroughSeq: 42,
    level: "ERROR",
    process: "pm-engine",
    logger: "edumatcher.engine.book",
    sampleMessage: "ConnectionRefusedError",
  };

  it("acking then un-acking then re-acking records ACK/UNACK/REACK in history", () => {
    store.ack(sample);
    store.unack(sample.fingerprint, "operator1");
    store.ack(sample);

    const history = store.history(sample.fingerprint);
    expect(history.map((h) => h.action)).toEqual(["ACK", "UNACK", "REACK"]);
  });

  it("get() returns null after un-ack", () => {
    store.ack(sample);
    expect(store.get(sample.fingerprint)).not.toBeNull();
    store.unack(sample.fingerprint, "operator1");
    expect(store.get(sample.fingerprint)).toBeNull();
  });

  it("ack is readable even if the caller never queries log_events again (denormalised fields)", () => {
    store.ack(sample);
    const ack = store.get(sample.fingerprint)!;
    expect(ack.ackedBy).toBe("operator1");
    expect(ack.ackedThroughSeq).toBe(42);
  });

  it("ackedCount reflects only currently-acked issues, not history", () => {
    store.ack(sample);
    expect(store.ackedCount).toBe(1);
    store.unack(sample.fingerprint, "operator1");
    expect(store.ackedCount).toBe(0);
  });
});
