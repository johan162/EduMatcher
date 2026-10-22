// @vitest-environment jsdom
/** The right-hand group of the top bar has one order in every web app (WP-UI07). */

import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { TopBar } from "../src/components/layout/TopBar.js";

afterEach(cleanup);

/** True when `a` comes before `b` in the document. */
const before = (a: HTMLElement, b: HTMLElement) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

describe("top bar order (WP-UI07)", () => {
  it("puts the theme toggle, then settings, then the connection badge", () => {
    render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><TopBar theme="dark" onThemeChange={() => undefined} /></MemoryRouter></QueryClientProvider>);
    const theme = screen.getByRole("button", { name: /^Theme/ });
    const settings = screen.getByRole("button", { name: "Settings" });
    const badge = screen.getByTestId("connection-badge");
    expect(before(theme, settings)).toBe(true);
    expect(before(settings, badge)).toBe(true);
  });
});
