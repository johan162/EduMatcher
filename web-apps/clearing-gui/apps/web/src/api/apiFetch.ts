/**
 * The one REST client of the clearing GUI.
 *
 * - Sends `Authorization: Bearer <key>` (the logged-in key, or `apiKey` for
 *   the login probe, which must not store a key before it is known to work).
 * - Calls only same-origin `/api/...` paths: the Vite dev server and the
 *   production static server proxy them to pm-api-gwy. The browser never
 *   learns a database path or another service's address.
 * - Validates every 2xx body against its Zod schema. A mismatch is a
 *   `ContractError`, so a changed contract shows as an error rather than as
 *   a blank or wrong table.
 * - Maps the gateway's error envelope to `ApiError`, logs out on a 401
 *   (unknown or revoked key, as trader-gui does), and turns a request that
 *   never got an answer into `NetworkError`.
 */
import type { z } from "zod";
import { ApiError, ContractError, NetworkError } from "@/api/errors";
import { useAuthStore } from "@/store/useAuthStore";
import { markOffline, markOnline } from "@/store/useConnectionStore";

export interface FetchOptions {
  /** Use this key instead of the stored one (the login probe). */
  apiKey?: string;
  signal?: AbortSignal;
}

export async function apiFetch<S extends z.ZodType>(
  path: string,
  schema: S,
  options: FetchOptions = {},
): Promise<z.infer<S>> {
  const key = options.apiKey ?? useAuthStore.getState().apiKey;
  let res: Response;
  try {
    res = await fetch(path, {
      headers: key ? { Authorization: `Bearer ${key}` } : {},
      signal: options.signal,
    });
  } catch (err) {
    // An abort is TanStack Query cancelling a stale request: not an outage.
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    markOffline();
    throw new NetworkError(err instanceof Error ? err.message : String(err));
  }
  markOnline();

  if (!res.ok) {
    if (res.status === 401) useAuthStore.getState().logout();
    throw await toApiError(res);
  }

  let body: unknown;
  try {
    body = await res.json();
  } catch {
    // An HTML page where JSON was expected: a proxy routing /api elsewhere.
    throw new ContractError(path, "the reply is not JSON");
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    throw new ContractError(path, describeIssues(parsed.error));
  }
  return parsed.data;
}

async function toApiError(res: Response): Promise<ApiError> {
  let envelope: unknown = null;
  try {
    envelope = await res.json();
  } catch {
    // A proxy's plain-text error page: keep the HTTP status text.
  }
  const error =
    typeof envelope === "object" && envelope !== null && "error" in envelope
      ? (envelope as { error: unknown }).error
      : null;
  if (typeof error === "object" && error !== null) {
    const e = error as Record<string, unknown>;
    return new ApiError(
      res.status,
      typeof e["code"] === "string" ? e["code"] : "UNKNOWN",
      typeof e["message"] === "string" ? e["message"] : res.statusText,
      typeof e["field"] === "string" ? e["field"] : undefined,
    );
  }
  return new ApiError(res.status, "UNKNOWN", res.statusText || `HTTP ${res.status}`);
}

/** `positions.0.net_qty: Invalid input: expected number` -- at most three. */
function describeIssues(error: z.ZodError): string {
  return error.issues
    .slice(0, 3)
    .map((issue) => `${issue.path.join(".") || "(body)"}: ${issue.message}`)
    .join("; ");
}
