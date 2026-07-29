import { describe, expect, it } from "vitest";
import { compileOrderLimit, compileWhere } from "../src/filter-to-sql.js";
import type { LogFilter } from "@edumatcher/log-types";

describe("compileWhere", () => {
  it("returns an empty WHERE clause for an empty filter", () => {
    const { whereSql, params } = compileWhere({});
    expect(whereSql).toBe("");
    expect(params).toEqual([]);
  });

  it("expands minLevel to every level at or above the floor", () => {
    const { whereSql, params } = compileWhere({ minLevel: "WARNING" });
    expect(whereSql).toBe("WHERE level IN (?,?,?)");
    expect(params).toEqual(["WARNING", "ERROR", "CRITICAL"]);
  });

  it("binds process/session IN-lists rather than interpolating", () => {
    const { whereSql, params } = compileWhere({
      processes: ["pm-engine", "pm-md-gwy"],
      sessions: ["abc123"],
    });
    expect(whereSql).toBe(
      "WHERE process IN (?,?) AND session IN (?)",
    );
    expect(params).toEqual(["pm-engine", "pm-md-gwy", "abc123"]);
  });

  it("compiles logger prefixes to a bound LIKE OR-group", () => {
    const { whereSql, params } = compileWhere({
      loggers: ["edumatcher.engine", "edumatcher.md_gateway"],
    });
    expect(whereSql).toBe("WHERE (logger LIKE ? OR logger LIKE ?)");
    expect(params).toEqual(["edumatcher.engine%", "edumatcher.md_gateway%"]);
  });

  it("lower-cases contains and wraps it for a bound LIKE, never interpolating the needle", () => {
    const filter: LogFilter = { contains: "Connection RESET" };
    const { whereSql, params } = compileWhere(filter);
    expect(whereSql).toBe("WHERE LOWER(message) LIKE ?");
    expect(params).toEqual(["%connection reset%"]);
    // The needle must never appear in the SQL text itself.
    expect(whereSql).not.toContain("connection reset");
  });

  it("binds a maliciously-crafted contains value safely (no interpolation)", () => {
    const evil = "x'; DROP TABLE log_events; --";
    const { whereSql, params } = compileWhere({ contains: evil });
    expect(whereSql).not.toContain("DROP TABLE");
    expect(params).toEqual([`%${evil.toLowerCase()}%`]);
  });

  it("adds has_exception/from/to/seqAfter/seqBefore clauses, all bound", () => {
    const { whereSql, params } = compileWhere(
      { exceptionsOnly: true, from: "2026-07-01T00:00:00Z", to: "2026-07-02T00:00:00Z" },
      { seqAfter: 100, seqBefore: 200 },
    );
    expect(whereSql).toBe(
      "WHERE has_exception = 1 AND client_ts >= ? AND client_ts <= ? AND seq > ? AND seq < ?",
    );
    expect(params).toEqual(["2026-07-01T00:00:00Z", "2026-07-02T00:00:00Z", 100, 200]);
  });

  it("combines every clause type with AND, in a stable order", () => {
    const filter: LogFilter = {
      minLevel: "ERROR",
      processes: ["pm-engine"],
      loggers: ["edumatcher.engine"],
      exceptionsOnly: true,
      contains: "refused",
    };
    const { whereSql, params } = compileWhere(filter);
    expect(whereSql).toBe(
      "WHERE level IN (?,?) AND process IN (?) AND (logger LIKE ?) AND has_exception = 1 AND LOWER(message) LIKE ?",
    );
    expect(params).toEqual([
      "ERROR",
      "CRITICAL",
      "pm-engine",
      "edumatcher.engine%",
      "%refused%",
    ]);
  });

  it("every '?' placeholder has exactly one corresponding bound param", () => {
    const filter: LogFilter = {
      minLevel: "WARNING",
      processes: ["pm-engine", "pm-api-gwy"],
      loggers: ["edumatcher.engine", "edumatcher.api_gateway"],
      sessions: ["s1"],
      exceptionsOnly: true,
      contains: "boom",
      from: "2026-01-01T00:00:00Z",
      to: "2026-01-02T00:00:00Z",
    };
    const { whereSql, params } = compileWhere(filter, { seqAfter: 5, seqBefore: 500 });
    const placeholderCount = (whereSql.match(/\?/g) ?? []).length;
    expect(placeholderCount).toBe(params.length);
  });
});

describe("compileOrderLimit", () => {
  it("defaults to DESC with a sane limit fallback for invalid input", () => {
    const { sql, params } = compileOrderLimit("bogus" as never, Number.NaN);
    expect(sql).toBe("ORDER BY seq DESC LIMIT ?");
    expect(params).toEqual([200]);
  });

  it("accepts ASC and a positive integer limit", () => {
    const { sql, params } = compileOrderLimit("ASC", 50);
    expect(sql).toBe("ORDER BY seq ASC LIMIT ?");
    expect(params).toEqual([50]);
  });
});
