import { describe, expect, it } from "vitest";
import { buildByLevelQuery, buildByProcessQuery, buildTimeseriesQuery } from "../src/aggregates.js";

describe("buildTimeseriesQuery", () => {
  it("produces a bucketed GROUP BY with no group-by column when groupBy is null", () => {
    const { sql, params } = buildTimeseriesQuery({}, "1m", null);
    expect(sql).toContain("GROUP BY bucket_start");
    expect(sql).not.toContain("bucket_start, level");
    expect(sql).not.toContain("bucket_start, process");
    expect(params).toEqual([]);
  });

  it("adds the group column to SELECT and GROUP BY for level", () => {
    const { sql } = buildTimeseriesQuery({}, "5m", "level");
    expect(sql).toContain("level AS grp");
    expect(sql).toContain("GROUP BY bucket_start, level");
  });

  it("adds the group column to SELECT and GROUP BY for process", () => {
    const { sql } = buildTimeseriesQuery({}, "1h", "process");
    expect(sql).toContain("process AS grp");
    expect(sql).toContain("GROUP BY bucket_start, process");
  });

  it("uses a distinct bucket width per bucket size (1m != 5m expression)", () => {
    const oneMin = buildTimeseriesQuery({}, "1m", null).sql;
    const fiveMin = buildTimeseriesQuery({}, "5m", null).sql;
    expect(oneMin).not.toBe(fiveMin);
    expect(oneMin).toContain("/ 60)");
    expect(fiveMin).toContain("/ 300)");
  });

  it("threads filter params through untouched", () => {
    const { params } = buildTimeseriesQuery({ processes: ["pm-engine"] }, "1m", null);
    expect(params).toEqual(["pm-engine"]);
  });
});

describe("buildByLevelQuery / buildByProcessQuery", () => {
  it("groups by level", () => {
    const { sql } = buildByLevelQuery({});
    expect(sql).toContain("GROUP BY level");
  });

  it("groups by process", () => {
    const { sql } = buildByProcessQuery({});
    expect(sql).toContain("GROUP BY process");
  });
});
