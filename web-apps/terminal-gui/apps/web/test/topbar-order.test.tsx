// @vitest-environment jsdom
/** The right-hand group of the top bar has one order in every web app (WP-UI07). */

import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { TopBar } from "../src/components/layout/TopBar.js";

afterEach(cleanup);

/** True when `a` comes before `b` in the document. */
const before = (a: HTMLElement, b: HTMLElement) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

describe("top bar order (WP-UI07)", () => {
  it("puts the density tool, then theme, settings and the connection badge", () => {
    render(<MemoryRouter><TopBar /></MemoryRouter>);
    const density = screen.getByRole("button", { name: /^Density/ });
    const theme = screen.getByRole("button", { name: /^Theme/ });
    const settings = screen.getByRole("button", { name: "Settings" });
    const help = screen.getByRole("button", { name: "Help" });
    const badge = screen.getByTestId("connection-badge");
    expect(before(density, theme)).toBe(true);
    expect(before(theme, settings)).toBe(true);
    expect(before(settings, help)).toBe(true);
    expect(before(help, badge)).toBe(true);
  });
});
