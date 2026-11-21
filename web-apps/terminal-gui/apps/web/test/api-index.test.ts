import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../src/lib/api.js";

describe("api.indexSnapshots", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("asks pm-stats to bucket the levels", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ snapshots: [], next_cursor: null }),
    } as Response);
    vi.stubGlobal("fetch", fetchMock);

    await api.indexSnapshots("EDU50", "2026-11-21", "1m");

    const url = new URL(fetchMock.mock.calls[0]![0] as string, "http://x");
    expect(url.pathname).toBe("/api/history/index-snapshots");
    expect(url.searchParams.get("index_id")).toBe("EDU50");
    expect(url.searchParams.get("from")).toBe("2026-11-21");
    expect(url.searchParams.get("interval")).toBe("1m");
  });
});
