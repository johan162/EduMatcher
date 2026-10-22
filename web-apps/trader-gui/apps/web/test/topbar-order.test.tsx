// @vitest-environment jsdom
/** The right-hand group of the top bar has one order in every web app (WP-UI07). */

import { cleanup, render, screen } from "@testing-library/react";

import { afterEach, describe, expect, it } from "vitest";
import { TopBar } from "@/components/layout/TopBar";

afterEach(cleanup);

/** True when `a` comes before `b` in the document. */
const before = (a: HTMLElement, b: HTMLElement) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

describe("top bar order (WP-UI07)", () => {
  it("puts tools, then theme, settings, help, the connection badge and the identity", () => {
    render(<TopBar />);
    const theme = screen.getByRole("button", { name: /^Theme/ });
    const settings = screen.getByRole("button", { name: "Settings" });
    const help = screen.getByRole("button", { name: "Help" });
    const badge = screen.getByTestId("connection-badge");
    const logout = screen.getByRole("button", { name: "Logout" });
    const search = screen.getByRole("button", { name: "Command palette" });
    expect(before(search, theme)).toBe(true);
    expect(before(theme, settings)).toBe(true);
    expect(before(settings, help)).toBe(true);
    expect(before(help, badge)).toBe(true);
    expect(before(badge, logout)).toBe(true);
  });
});
