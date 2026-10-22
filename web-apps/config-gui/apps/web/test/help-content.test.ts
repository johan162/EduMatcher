/** pm-config's help content (WP-UI08); a data test, as this app has no component-test setup yet. */

import { describe, expect, it } from "vitest";
import { HELP_TOPICS } from "../src/components/help/helpContent";

describe("help content", () => {
  it("has unique topics, each with a title and something to read", () => {
    const ids = HELP_TOPICS.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const t of HELP_TOPICS) {
      expect(t.title.trim()).not.toBe("");
      expect(t.blocks.length).toBeGreaterThan(0);
    }
  });

  it("covers the workflow, the personas and every tab", () => {
    const text = JSON.stringify(HELP_TOPICS);
    for (const word of ["Beginner", "Intermediate", "Expert", "Review & Export", "Circuit Breakers", "Import"]) {
      expect(text).toContain(word);
    }
  });
});
