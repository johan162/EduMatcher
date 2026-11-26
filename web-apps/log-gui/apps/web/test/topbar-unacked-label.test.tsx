// @vitest-environment jsdom
/** The top-bar unacked link names the level it counts, so it is not read as "all alerts". */

import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import type { LogLevel } from "@edumatcher/log-types";
import { TopBar } from "../src/components/layout/TopBar.js";

afterEach(cleanup);

function renderWith(alertLevel: LogLevel, count: number) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(["ui-config"], { alertLevel, timezone: "UTC" });
  client.setQueryData(["issues", { acked: false, minLevel: alertLevel }], {
    issues: Array.from({ length: count }, (_, i) => ({ fingerprint: String(i) })),
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TopBar theme="dark" onThemeChange={() => undefined} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return screen.getByRole("link", { name: /unacked/ });
}

describe("top bar unacked label", () => {
  it("says errors at the default ERROR level", () => {
    expect(renderWith("ERROR", 2).textContent).toBe("⚠ 2 unacked errors");
  });

  it("says warnings and errors when the alert level is WARNING", () => {
    expect(renderWith("WARNING", 3).textContent).toBe("⚠ 3 unacked warnings+errors");
  });
});
