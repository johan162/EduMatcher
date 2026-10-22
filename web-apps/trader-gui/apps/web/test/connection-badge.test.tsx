// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { ConnectionBadge, type ConnectionBadgeState } from "../src/components/ConnectionBadge";

afterEach(cleanup);

const CASES: [ConnectionBadgeState, string, string][] = [
  ["live", "LIVE", "bg-live"],
  ["connecting", "CONNECTING", "bg-warning"],
  ["reconnecting", "RECONNECTING", "bg-warning"],
  ["offline", "OFFLINE", "bg-offline"],
];

describe("ConnectionBadge (WP-UI05)", () => {
  it.each(CASES)("shows %s as the word %s with a %s dot", (state, word, dot) => {
    render(<ConnectionBadge state={state} />);
    const badge = screen.getByTestId("connection-badge");
    expect(badge.getAttribute("data-state")).toBe(state);
    expect(badge.textContent).toBe(word);
    expect(badge.querySelector("span")!.className).toContain(dot);
  });

  it("shows the detail after the word and the title on hover", () => {
    render(<ConnectionBadge state="live" detail="GW01" title="why" />);
    const badge = screen.getByTestId("connection-badge");
    expect(badge.textContent).toBe("LIVEGW01");
    expect(badge.getAttribute("title")).toBe("why");
  });
});
