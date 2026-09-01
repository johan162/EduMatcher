import { useAuthStore } from "@/store/useAuthStore.js";
import { env } from "@/lib/env.js";

const API_BASE = env("VITE_API_BASE");

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly field?: string,
    public readonly rejectCode?: string,
    public readonly reason?: string,
    public readonly clientTag?: string,
    public readonly requestTag?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * Thin REST client wrapper (§7.3).
 * – Injects Authorization: Bearer <key>
 * – Deserialises JSON responses
 * – Maps HTTP status codes to typed ApiError instances
 * – Throws ApiError(401) so TanStack Query can trigger automatic logout
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const key = useAuthStore.getState().apiKey;
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(key ? { Authorization: `Bearer ${key}` } : {}),
      ...(init?.headers ?? {}),
    },
  });

  if (!res.ok) {
    let body: Record<string, unknown> = {};
    try {
      body = (await res.json()) as Record<string, unknown>;
    } catch {
      // ignore parse errors on error responses
    }
    const err = (body["error"] as Record<string, unknown> | string | undefined) ?? {};
    const code =
      typeof err === "string"
        ? err
        : (((err as Record<string, unknown>)["code"] as string | undefined) ?? "UNKNOWN");
    const message =
      typeof err === "string"
        ? err
        : (((err as Record<string, unknown>)["message"] as string | undefined) ?? res.statusText);
    const field =
      typeof err === "object"
        ? ((err as Record<string, unknown>)["field"] as string | undefined)
        : undefined;
    const rejectCode =
      typeof err === "object"
        ? ((err as Record<string, unknown>)["reject_code"] as string | undefined)
        : undefined;
    const reason =
      typeof err === "object"
        ? ((err as Record<string, unknown>)["reason"] as string | undefined)
        : undefined;
    const clientTag =
      typeof err === "object"
        ? ((err as Record<string, unknown>)["client_tag"] as string | undefined)
        : undefined;
    const requestTag =
      typeof err === "object"
        ? ((err as Record<string, unknown>)["request_tag"] as string | undefined)
        : undefined;
    throw new ApiError(
      res.status,
      code,
      message,
      field,
      rejectCode,
      reason,
      clientTag,
      requestTag,
    );
  }

  // 204 No Content
  if (res.status === 204) return undefined as unknown as T;
  return res.json() as Promise<T>;
}
