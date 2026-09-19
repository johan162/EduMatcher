// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { apiFetch } from "@/api/apiFetch";
import { useAuthStore } from "@/store/useAuthStore";

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: "",
    json: async () => body,
  } as Response;
}

beforeEach(() => {
  useAuthStore.setState({
    apiKey: "key-1",
    gatewayId: "gw-1",
    role: "TRADER",
    gatewayCount: null,
  });
});

describe("L4: apiFetch logs the user out on a 401", () => {
  it("logs out and still throws ApiError(401)", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse(401, { error: { code: "UNAUTHORIZED", message: "bad key" } }),
        ),
    );
    await expect(apiFetch("/api/v1/status")).rejects.toMatchObject({ status: 401 });
    expect(useAuthStore.getState().apiKey).toBeNull();
    expect(useAuthStore.getState().role).toBeNull();
    vi.unstubAllGlobals();
  });

  it("does not log out on a non-401 error (e.g. a 403 role mismatch)", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse(403, { error: { code: "ROLE_UNSUPPORTED", message: "nope" } }),
        ),
    );
    await expect(apiFetch("/api/v1/status")).rejects.toMatchObject({ status: 403 });
    expect(useAuthStore.getState().apiKey).toBe("key-1");
    vi.unstubAllGlobals();
  });

  it("a 401 on the pre-login probe is a harmless no-op (already logged out)", async () => {
    useAuthStore.getState().logout();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse(401, { error: { code: "UNAUTHORIZED", message: "bad key" } }),
        ),
    );
    await expect(apiFetch("/api/v1/status")).rejects.toMatchObject({ status: 401 });
    expect(useAuthStore.getState().apiKey).toBeNull();
    vi.unstubAllGlobals();
  });
});
