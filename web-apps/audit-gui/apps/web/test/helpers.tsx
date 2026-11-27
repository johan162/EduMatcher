/**
 * Test support for the audit GUI (as clearing-gui's).
 *
 * - `example(route, method)` returns the example the released contract
 *   (`spec/rest/openapi.json`) documents for a route: payloads the Python
 *   suite already holds to the gateway's response models.
 * - `stubApi(handlers)` replaces `fetch` with a table keyed by pathname (any
 *   method) or `"POST /path"`, and records every request, so a test can
 *   assert what the page asked for.
 * - `renderApp(path)` renders the whole application at `path`, with a probe
 *   that exposes the current location.
 *
 * Not a test file (no .test suffix) -- vitest does not collect it.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { vi } from "vitest";
import App from "@/App";
import { useAuthStore, type Role } from "@/store/useAuthStore";

const OPENAPI = path.resolve(__dirname, "../../../../../spec/rest/openapi.json");

type Media = { example?: unknown; examples?: Record<string, { value: unknown }> };
const doc = JSON.parse(readFileSync(OPENAPI, "utf-8")) as {
  paths: Record<string, Record<string, { responses: Record<string, { content: Record<string, Media> }> }>>;
};

/** Every success example the contract documents for `route`. */
export function examples(route: string, method: "get" | "post" = "get"): unknown[] {
  const responses = doc.paths[route]![method]!.responses;
  const ok = responses["200"] ?? responses["201"];
  const media = ok!.content["application/json"]!;
  const raw: unknown[] = media.example !== undefined ? [media.example] : [];
  for (const named of Object.values(media.examples ?? {})) raw.push(named.value);
  return raw.map((value) => structuredClone(value));
}

/** The (first) success example for `route`. */
export function example<T = Record<string, unknown>>(route: string, method: "get" | "post" = "get"): T {
  return examples(route, method)[0] as T;
}

type Handler = (url: URL, init?: RequestInit) => unknown;

export interface Request {
  method: string;
  url: string;
  body: unknown;
}

export interface ApiStub {
  requests: Request[];
  /** Requests whose pathname is `route`. */
  calls: (route: string) => Request[];
}

/**
 * Stub `fetch`. A handler returns a body (sent as JSON 200) or a ready
 * `Response`; an unknown path is a 404 in the gateway's error envelope.
 */
export function stubApi(handlers: Record<string, Handler | unknown>): ApiStub {
  const requests: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const url = new URL(input, "http://gui.test");
      const method = init?.method ?? "GET";
      requests.push({
        method,
        url: url.pathname + url.search,
        body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
      });
      const handler = handlers[`${method} ${url.pathname}`] ?? handlers[url.pathname];
      if (handler === undefined) {
        return json(404, { error: { code: "NOT_FOUND", message: url.pathname } });
      }
      const body: unknown = await (typeof handler === "function" ? (handler as Handler)(url, init) : handler);
      return body instanceof Response ? body : json(200, body);
    }),
  );
  return {
    requests,
    calls: (route) => requests.filter((r) => new URL(r.url, "http://gui.test").pathname === route),
  };
}

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function apiError(status: number, code: string, message = code, extra: Record<string, unknown> = {}): Response {
  return json(status, { error: { code, message, ...extra } });
}

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname + location.search}</output>;
}

/** The location the router is at now. */
export function currentPath(): string {
  return screen.getByTestId("location").textContent ?? "";
}

export function signIn(role: Role = "ADMIN", gatewayId = "OPS01"): void {
  useAuthStore.setState({ apiKey: `key-${gatewayId}`, gatewayId, role });
}

export function newQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

export function renderApp(initialPath: string, client: QueryClient = newQueryClient()) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <App />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** The contract's snapshot example, for the routes a snapshot is read by. */
export function snapshotExample() {
  return example<SnapshotFixture>("/api/v1/audit/snapshots/{snapshot_id}");
}

export interface SnapshotFixture {
  snapshot_id: string;
  first_ts: string | null;
  last_ts: string | null;
  entries: number;
  runs: unknown[];
  files: { name: string; torn_bytes: number }[];
  capabilities: Record<string, { available: boolean; reason: string | null; detail: string }>;
  manifest: {
    state: "absent" | "verified" | "failed";
    entries: number;
    head_sha256: string | null;
    anchored: boolean;
    problems: { day: string | null; message: string }[];
  };
  forensics: { statuses: Record<string, number> } | null;
}
