/**
 * Test support for the clearing GUI.
 *
 * - `example(route)` returns the 200 example the released contract
 *   (`spec/rest/openapi.json`) documents for a route: realistic payloads the
 *   Python suite already holds to the gateway's response models, instead of
 *   hand-written lookalikes.
 * - `stubApi(handlers)` replaces `fetch` with a table keyed by URL pathname and
 *   records every request URL, so a test can assert what the page asked for.
 * - `renderApp(path, auth)` renders the whole application at `path`, with a
 *   probe that exposes the current location.
 *
 * Not a test file (no .test suffix) -- vitest does not collect it.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { vi } from "vitest";
import App from "@/App";
import { useAuthStore, type Role } from "@/store/useAuthStore";

const OPENAPI = path.resolve(__dirname, "../../../../../spec/rest/openapi.json");
const doc = JSON.parse(readFileSync(OPENAPI, "utf-8")) as {
  paths: Record<string, { get: { responses: Record<string, { content: Record<string, { example?: unknown; examples?: Record<string, { value: unknown }> }> }> } }>;
};

/** Every 200 example the contract documents for `route`, as the wire carries it. */
export function examples(route: string): unknown[] {
  const media = doc.paths[route]!.get.responses["200"]!.content["application/json"]!;
  const raw: unknown[] = media.example !== undefined ? [media.example] : [];
  for (const named of Object.values(media.examples ?? {})) raw.push(named.value);
  return raw.map((value) => structuredClone(value));
}

/** The (first) 200 example for `route`, e.g. `/api/v1/clearing/trades`. */
export function example<T = Record<string, unknown>>(route: string): T {
  return examples(route)[0] as T;
}

type Handler = (url: URL) => unknown;

export interface ApiStub {
  /** Every requested URL, in order (pathname + search). */
  requests: string[];
  /** Requests whose pathname is `route`. */
  calls: (route: string) => URL[];
}

/**
 * Stub `fetch` with `handlers` keyed by pathname. A handler returns a body
 * (sent as JSON 200) or a ready `Response`; an unknown path is a 404 in the
 * gateway's error envelope.
 */
export function stubApi(handlers: Record<string, Handler | unknown>): ApiStub {
  const requests: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      const url = new URL(input, "http://gui.test");
      requests.push(url.pathname + url.search);
      const handler = handlers[url.pathname];
      if (handler === undefined) {
        return json(404, { error: { code: "NOT_FOUND", message: url.pathname } });
      }
      // A handler may return a promise; one that never settles keeps the
      // request pending, as a slow gateway would.
      const body: unknown = await (typeof handler === "function" ? (handler as Handler)(url) : handler);
      return body instanceof Response ? body : json(200, body);
    }),
  );
  return {
    requests,
    calls: (route) =>
      requests.map((r) => new URL(r, "http://gui.test")).filter((u) => u.pathname === route),
  };
}

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function apiError(status: number, code: string, message = code): Response {
  return json(status, { error: { code, message } });
}

let navigateInApp: ((path: string) => void) | null = null;

function LocationProbe() {
  const location = useLocation();
  navigateInApp = useNavigate();
  return <output data-testid="location">{location.pathname + location.search}</output>;
}

/** Navigate inside the rendered app, as a link would: mounted screens stay mounted. */
export function navigate(path: string): void {
  act(() => navigateInApp!(path));
}

/** The location the router is at now. */
export function currentPath(): string {
  return screen.getByTestId("location").textContent ?? "";
}

export function signIn(role: Role, gatewayId = role === "ADMIN" ? "OPS01" : "TRADER01"): void {
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
