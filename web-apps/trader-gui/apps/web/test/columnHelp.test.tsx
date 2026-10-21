// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { HeaderTip } from "@/components/shared/HeaderTip";
import { FieldHelp } from "@/components/shared/FieldHelp";
import { COLUMN_HELP } from "@/lib/columnHelp";
import { FIELD_HELP } from "@/lib/fieldHelp";
import { HELP_TOPICS } from "@/components/help/helpContent";
import { HelpDrawer } from "@/components/help/HelpDrawer";

beforeEach(cleanup);

describe("column and field help (WP-UI02)", () => {
  it("explains a column heading in a tip that opens on focus", () => {
    render(<HeaderTip table="blotter" col="Remaining" />);
    fireEvent.focus(screen.getByRole("button", { name: "Remaining help" }));
    expect(screen.getByRole("tooltip").textContent).toMatch(/counts down/);
  });

  it("shows nothing for a heading without help", () => {
    const { container } = render(<HeaderTip table="blotter" col="No such column" />);
    expect(container.firstChild).toBeNull();
  });

  it("explains a form field", () => {
    render(<FieldHelp form="oco" field="Stop price" />);
    fireEvent.focus(screen.getByRole("button", { name: "Stop price help" }));
    expect(screen.getByRole("tooltip").textContent).toMatch(/triggers/);
  });

  it("has no empty help text", () => {
    for (const table of Object.values(COLUMN_HELP))
      for (const lines of Object.values(table)) expect(lines.every((l) => l.trim().length > 0)).toBe(true);
    for (const form of Object.values(FIELD_HELP))
      for (const lines of Object.values(form)) expect(lines.every((l) => l.trim().length > 0)).toBe(true);
  });
});

describe("order type help (WP-UI02.4)", () => {
  it("describes every order type the ticket offers, with an example for each family", () => {
    const text = JSON.stringify(HELP_TOPICS);
    for (const t of ["Market", "Limit", "Stop-Limit", "FOK", "IOC", "Iceberg", "Trailing Stop", "OCO", "Combo"]) {
      expect(text).toContain(t);
    }
    const topics = HELP_TOPICS.filter((t) => t.id.startsWith("ot-"));
    expect(topics.length).toBeGreaterThanOrEqual(5);
    for (const t of topics) expect(t.blocks.some((b) => b.example)).toBe(true);
  });

  it("renders glossary terms, examples and notes", () => {
    render(<HelpDrawer />);
    fireEvent.click(screen.getByRole("button", { name: "Stop, Stop-Limit & Trailing" }));
    expect(screen.getByText("Trailing Stop", { selector: "h3" })).toBeTruthy();
    expect(screen.getAllByText("Needs").length).toBeGreaterThan(0);
    expect(document.querySelector("pre")?.textContent).toMatch(/stop/i);
  });
});
