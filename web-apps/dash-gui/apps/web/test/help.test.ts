import { describe, expect, it } from "vitest";
import { columnHelp, widgetHelp } from "../src/lib/help.js";

describe("help text", () => {
  it("explains every column of the process, participant and book tables", () => {
    const ids = {
      Processes: ["state", "key", "uptime", "rss", "cpu", "loop", "lag"],
      Participants: ["id", "role", "conn", "since", "orders", "now", "avg-min", "avg-h", "avg-d", "rej", "rest", "cdh"],
      "Order books": ["symbol", "long", "resting", "stops", "bid", "ask", "mem", "garbage", "trades", "state"],
      "Application metrics": ["name", "label", "kind", "value"],
    };
    for (const [table, cols] of Object.entries(ids)) for (const id of cols) expect(columnHelp(table, id), `${table}/${id}`).toBeTruthy();
  });

  it("explains a gateway's clients tile by its kind, and nothing it does not know", () => {
    expect(widgetHelp("MD clients")).toMatch(/market-data/);
    expect(widgetHelp("XYZ clients")).toBeUndefined();
    expect(widgetHelp("Engine p99")).toMatch(/99/);
  });
});
