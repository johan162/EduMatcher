import { describe, expect, it } from "vitest";
import { rowMatchesFilter } from "../src/row-filter.js";
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
    level: "INFO",
    logger: "edumatcher.engine.book",
    module: "book.py",
    line: 412,
    has_exception: false,
    truncated: false,
    message: "hello world",
    ...overrides,
  };
}

describe("rowMatchesFilter", () => {
  it("matches everything against an empty filter", () => {
    expect(rowMatchesFilter(row(), {})).toBe(true);
  });

  it("applies minLevel as a floor", () => {
    expect(rowMatchesFilter(row({ level: "WARNING" }), { minLevel: "WARNING" })).toBe(true);
    expect(rowMatchesFilter(row({ level: "INFO" }), { minLevel: "WARNING" })).toBe(false);
  });

  it("filters by process allow-list", () => {
    expect(rowMatchesFilter(row({ process: "pm-md-gwy" }), { processes: ["pm-engine"] })).toBe(
      false,
    );
  });

  it("filters loggers by prefix", () => {
    expect(
      rowMatchesFilter(row({ logger: "edumatcher.engine.book" }), {
        loggers: ["edumatcher.engine"],
      }),
    ).toBe(true);
    expect(
      rowMatchesFilter(row({ logger: "edumatcher.md_gateway" }), {
        loggers: ["edumatcher.engine"],
      }),
    ).toBe(false);
  });

  it("filters exceptionsOnly", () => {
    expect(rowMatchesFilter(row({ has_exception: false }), { exceptionsOnly: true })).toBe(false);
    expect(rowMatchesFilter(row({ has_exception: true }), { exceptionsOnly: true })).toBe(true);
  });

  it("filters contains case-insensitively", () => {
    expect(rowMatchesFilter(row({ message: "Connection RESET" }), { contains: "reset" })).toBe(
      true,
    );
    expect(rowMatchesFilter(row({ message: "all fine" }), { contains: "reset" })).toBe(false);
  });
});
