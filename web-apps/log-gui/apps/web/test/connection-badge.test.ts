/** The shared badge (WP-UI05); rendered to markup, as pm-log has no jsdom setup yet. */

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ConnectionBadge, type ConnectionBadgeState } from "../src/components/ConnectionBadge.js";

const CASES: [ConnectionBadgeState, string, string][] = [
  ["live", "LIVE", "bg-live"],
  ["connecting", "CONNECTING", "bg-warning"],
  ["reconnecting", "RECONNECTING", "bg-warning"],
  ["offline", "OFFLINE", "bg-offline"],
];

describe("ConnectionBadge (WP-UI05)", () => {
  it.each(CASES)("shows %s as the word %s with a %s dot", (state, word, dot) => {
    const html = renderToStaticMarkup(createElement(ConnectionBadge, { state }));
    expect(html).toContain(`data-state="${state}"`);
    expect(html).toContain(`>${word}<`);
    expect(html).toContain(dot);
  });

  it("shows the detail and the title", () => {
    const html = renderToStaticMarkup(createElement(ConnectionBadge, { state: "live", detail: "log-srv", title: "why" }));
    expect(html).toContain(">log-srv<");
    expect(html).toContain('title="why"');
  });
});
