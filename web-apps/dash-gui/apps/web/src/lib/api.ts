/**
 * The bridge's REST API (design §11.2) as the rows use it. Every history
 * request names its window with `range=`, which the bridge resolves to end
 * at its own now, so client and bridge never disagree about "the last hour"
 * by the browser's clock.
 */

import { RANGE_MS, type ApiError, type RangeName } from "@edumatcher/dash-types";

export { RANGE_MS };

/** A request the bridge answered with an error body. */
export class BridgeError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, { signal });
  if (!res.ok) {
    let body: ApiError | undefined;
    try {
      body = (await res.json()) as ApiError;
    } catch {
      // no JSON body
    }
    throw new BridgeError(res.status, body?.error ?? "http_error", body?.message ?? `${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

/** A query string from parameters, leaving out the undefined ones. */
export function query(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined) q.set(key, String(value));
  return q.toString();
}

/** The rate bucket for a range: minutes while they fit the bridge's 1000-point limit. */
export function rateBucket(range: RangeName): { bucket: "1m" | "1h"; bucketMs: number } {
  return RANGE_MS[range] / 60_000 <= 1000 ? { bucket: "1m", bucketMs: 60_000 } : { bucket: "1h", bucketMs: 3600_000 };
}
