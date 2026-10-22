// @vitest-environment jsdom
/** The help panel and its content (WP-UI08). */

import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { HelpButton } from "../src/components/help/HelpButton";
import { HELP_TOPICS } from "../src/components/help/helpContent";

afterEach(cleanup);

describe("help content", () => {
  it("has unique topics, each with a title and something to read", () => {
    const ids = HELP_TOPICS.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const t of HELP_TOPICS) {
      expect(t.title.trim()).not.toBe("");
      expect(t.blocks.length).toBeGreaterThan(0);
      for (const b of t.blocks) {
        expect(Boolean(b.paragraphs?.length || b.bullets?.length || b.terms?.length || b.example || b.note)).toBe(true);
      }
    }
  });

  it("explains the connection badge and the session badge, which every live app shows", () => {
    const ids = HELP_TOPICS.map((t) => t.id);
    expect(ids).toContain("connection");
    expect(ids).toContain("session");
    const connection = JSON.stringify(HELP_TOPICS.find((t) => t.id === "connection"));
    for (const word of ["LIVE", "OFFLINE"]) expect(connection).toContain(word);
  });
});

describe("HelpButton", () => {
  it("opens a panel listing every topic, shows the chosen one, and closes on Escape", () => {
    render(<HelpButton topics={HELP_TOPICS} />);
    expect(screen.queryByRole("dialog", { name: "Help" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Help" }));
    const nav = screen.getByRole("navigation", { name: "Help topics" });
    for (const t of HELP_TOPICS) expect(nav.textContent).toContain(t.title);

    const second = HELP_TOPICS[1]!;
    fireEvent.click(screen.getByRole("button", { name: second.title }));
    expect(screen.getByRole("heading", { name: second.title })).toBeTruthy();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Help" })).toBeNull();
  });

  it("closes from its close button", () => {
    render(<HelpButton topics={HELP_TOPICS} />);
    fireEvent.click(screen.getByRole("button", { name: "Help" }));
    fireEvent.click(screen.getByRole("button", { name: "Close help" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
