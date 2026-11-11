// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";
import { apiFetch } from "@/api/apiFetch";
import { ApiError, ContractError, NetworkError } from "@/api/errors";
import { useAuthStore } from "@/store/useAuthStore";
import { useConnectionStore } from "@/store/useConnectionStore";

const Body = z.object({ count: z.number().int() });

function respond(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  useAuthStore.setState({ apiKey: "key-1", gatewayId: "TRADER01", role: "TRADER" });
  useConnectionStore.setState({ state: "unknown", lastOkAt: null });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiFetch", () => {
  it("sends the bearer key and returns the parsed body", async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(200, { count: 3, extra: "ignored" }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(apiFetch("/api/v1/clearing/positions", Body)).resolves.toEqual({ count: 3 });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer key-1");
    expect(useConnectionStore.getState().state).toBe("online");
  });

  it("turns a body that does not match the contract into a ContractError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respond(200, { count: "three" })));
    const err = await apiFetch("/api/v1/clearing/positions", Body).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ContractError);
    expect((err as ContractError).path).toBe("/api/v1/clearing/positions");
    expect((err as ContractError).message).toMatch(/count/);
  });

  it("maps the error envelope to an ApiError", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        respond(403, { error: { code: "SCOPE_DENIED", message: "not MM01" } }),
      ),
    );
    const err = await apiFetch("/x", Body).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 403, code: "SCOPE_DENIED", message: "not MM01" });
    expect(useAuthStore.getState().apiKey).toBe("key-1");
  });

  it("logs out on a 401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(respond(401, { error: { code: "AUTH", message: "Unknown" } })),
    );
    await expect(apiFetch("/x", Body)).rejects.toMatchObject({ status: 401 });
    expect(useAuthStore.getState().apiKey).toBeNull();
  });

  it("reports an unreachable gateway as a NetworkError and marks the connection down", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    await expect(apiFetch("/x", Body)).rejects.toBeInstanceOf(NetworkError);
    expect(useConnectionStore.getState().state).toBe("offline");
  });

  it("an explicit key overrides the stored one (the login probe)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(respond(200, { count: 1 }));
    vi.stubGlobal("fetch", fetchMock);
    await apiFetch("/x", Body, { apiKey: "candidate" });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer candidate");
  });
});
