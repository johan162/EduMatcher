import { describe, it, expect } from "vitest";
import { ApiError } from "@/api/apiFetch";
import { isUnconfirmed, summarizeSettled } from "@/lib/bulkOutcome";

// WP-API15: only ENGINE_TIMEOUT means "sent, outcome unknown". Every other
// error -- a 503 ENGINE_UNAVAILABLE or SYMBOLS_NOT_READY included -- means the
// gateway refused before anything reached the engine.
describe("isUnconfirmed", () => {
  it("is true only for ENGINE_TIMEOUT", () => {
    expect(isUnconfirmed(new ApiError(503, "ENGINE_TIMEOUT", "no reply"))).toBe(true);
    expect(isUnconfirmed(new ApiError(503, "ENGINE_UNAVAILABLE", "engine down"))).toBe(false);
    expect(isUnconfirmed(new ApiError(503, "SYMBOLS_NOT_READY", "not loaded"))).toBe(false);
    expect(isUnconfirmed(new Error("network"))).toBe(false);
  });
});

describe("summarizeSettled", () => {
  it("counts an unavailable engine as failed, not pending", () => {
    const outcome = summarizeSettled([
      { status: "fulfilled", value: {} },
      { status: "rejected", reason: new ApiError(503, "ENGINE_TIMEOUT", "no reply") },
      { status: "rejected", reason: new ApiError(503, "ENGINE_UNAVAILABLE", "engine down") },
    ]);
    expect(outcome).toEqual({ ok: 1, pending: 1, failed: 1 });
  });
});
