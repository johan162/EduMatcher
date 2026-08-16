import { describe, expect, it } from "vitest";
import { computeFingerprint, normaliseMessage } from "../src/fingerprint.js";
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

describe("normaliseMessage", () => {
  it("replaces integers >= 3 digits with <N>", () => {
    expect(normaliseMessage("port 5555 refused")).toBe("port <N> refused");
    expect(normaliseMessage("ab 12 cd")).toBe("ab 12 cd"); // 2-digit unaffected
  });

  it("replaces hex runs >= 6 chars with <HEX>", () => {
    expect(normaliseMessage("session 7f3a9c21 expired")).toBe("session <HEX> expired");
  });

  it("replaces quoted strings with <STR>", () => {
    expect(normaliseMessage("book invariant violated for 'AAPL'")).toBe(
      "book invariant violated for <STR>",
    );
  });

  it("replaces float literals with <F>", () => {
    expect(normaliseMessage("price 123.45 rejected")).toBe("price <F> rejected");
  });

  it("replaces ISO timestamps with <TS>", () => {
    expect(normaliseMessage("seen at 2026-07-29T10:00:00Z again")).toBe(
      "seen at <TS> again",
    );
  });
});

describe("computeFingerprint", () => {
  it("is stable across recurrences with different variable data", () => {
    const a = row({ message: "ConnectionRefusedError: [Errno 111] Connection refused" });
    const b = row({ message: "ConnectionRefusedError: [Errno 111] Connection refused" });
    expect(computeFingerprint(a)).toBe(computeFingerprint(b));
  });

  it("differs when process, logger, or level differ", () => {
    const base = row();
    const diffProcess = row({ process: "pm-md-gwy" });
    const diffLevel = row({ level: "CRITICAL" });
    expect(computeFingerprint(base)).not.toBe(computeFingerprint(diffProcess));
    expect(computeFingerprint(base)).not.toBe(computeFingerprint(diffLevel));
  });

  it("groups messages that normalise to the same shape despite different literals", () => {
    const a = row({ message: "rate limit exceeded for key 'abc123xyz'" });
    const b = row({ message: "rate limit exceeded for key 'zzz999qqq'" });
    expect(computeFingerprint(a)).toBe(computeFingerprint(b));
  });

  it("fingerprints traceback rows on only the final frame + exception line", () => {
    const tracebackA = [
      "ConnectionRefusedError: [Errno 111] Connection refused",
      "Traceback (most recent call last):",
      "  File \"book.py\", line 412, in match",
      "    conn.send(order)",
      "ConnectionRefusedError: [Errno 111] Connection refused",
    ].join("\n");
    const tracebackB = [
      "different intermediate context entirely, unrelated locals: {'x': 999}",
      "Traceback (most recent call last):",
      "  File \"book.py\", line 412, in match",
      "    conn.send(order)",
      "ConnectionRefusedError: [Errno 111] Connection refused",
    ].join("\n");
    const a = row({ message: tracebackA, has_exception: true });
    const b = row({ message: tracebackB, has_exception: true });
    expect(computeFingerprint(a)).toBe(computeFingerprint(b));
  });

  it("returns a 16-character hex string", () => {
    const fp = computeFingerprint(row());
    expect(fp).toMatch(/^[0-9a-f]{16}$/);
  });
});
