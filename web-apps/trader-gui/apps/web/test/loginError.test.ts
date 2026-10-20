import { describe, it, expect } from "vitest";
import { ApiError } from "@/api/apiFetch";
import { describeLoginError } from "@/pages/LoginPage";

describe("describeLoginError", () => {
  it("calls only an unknown key (401) invalid", () => {
    expect(describeLoginError(new ApiError(401, "AUTH", "Unknown API key"))).toBe(
      "Invalid API key.",
    );
  });

  it("names a read-only key as the unsupported role it is", () => {
    expect(describeLoginError(new ApiError(403, "READ_ONLY", "API key is read-only"))).toBe(
      "ROLE_UNSUPPORTED: Unsupported role: READ_ONLY",
    );
  });

  it("shows why the engine refused a valid key's gateway", () => {
    expect(
      describeLoginError(new ApiError(403, "ENGINE_AUTH", "Gateway already connected: MM01")),
    ).toBe("ENGINE_AUTH: Gateway already connected: MM01");
  });

  it("keeps the role check's own error", () => {
    expect(describeLoginError(new ApiError(403, "ROLE_UNSUPPORTED", "Unsupported role: X"))).toBe(
      "ROLE_UNSUPPORTED: Unsupported role: X",
    );
  });
});
