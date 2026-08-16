// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { HelpDrawer } from "@/components/help/HelpDrawer";
import { ShortcutsDialog } from "@/components/help/ShortcutsDialog";
import { FieldInfo } from "@/components/shared/FieldInfo";
import { useUiStore } from "@/store/useUiStore";
import { SHORTCUTS } from "@/lib/shortcuts";
import { HELP_TOPICS } from "@/components/help/helpContent";

beforeEach(() => {
  cleanup();
  useUiStore.setState({ helpOpen: false, shortcutsOpen: false, eventCenterOpen: false });
});

describe("useUiStore help/shortcuts (§19)", () => {
  it("opening help closes the event center (mutually exclusive right sheets)", () => {
    useUiStore.setState({ eventCenterOpen: true });
    useUiStore.getState().toggleHelp();
    expect(useUiStore.getState().helpOpen).toBe(true);
    expect(useUiStore.getState().eventCenterOpen).toBe(false);
  });

  it("opening the event center closes help", () => {
    useUiStore.setState({ helpOpen: true });
    useUiStore.getState().toggleEventCenter();
    expect(useUiStore.getState().eventCenterOpen).toBe(true);
    expect(useUiStore.getState().helpOpen).toBe(false);
  });
});

describe("HelpDrawer (§19.1)", () => {
  it("lists every help topic and shows the first by default", () => {
    render(<HelpDrawer />);
    for (const t of HELP_TOPICS) {
      expect(screen.getByRole("button", { name: t.title })).toBeTruthy();
    }
    // First topic content is visible (Getting Started → "What is EduMatcher?").
    expect(screen.getByText("What is EduMatcher?")).toBeTruthy();
  });

  it("switches content when a topic is selected", () => {
    render(<HelpDrawer />);
    fireEvent.click(screen.getByRole("button", { name: "Order Types" }));
    expect(screen.getByText(/Fill or Kill/)).toBeTruthy();
  });

  it("renders the shared shortcuts table inside the Keyboard Shortcuts topic", () => {
    render(<HelpDrawer />);
    fireEvent.click(screen.getByRole("button", { name: "Keyboard Shortcuts" }));
    // A known shortcut row is present.
    expect(screen.getByText("Toggle the help drawer")).toBeTruthy();
  });

  it("closes on Escape", () => {
    const close = vi.fn();
    useUiStore.setState({ closeHelp: close });
    render(<HelpDrawer />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(close).toHaveBeenCalled();
  });
});

describe("ShortcutsDialog (§19.4)", () => {
  it("renders the full shortcut reference", () => {
    render(<ShortcutsDialog />);
    expect(screen.getByText("Keyboard shortcuts")).toBeTruthy();
    // Every shortcut's action text is listed.
    for (const s of SHORTCUTS.slice(0, 5)) {
      expect(screen.getByText(s.action)).toBeTruthy();
    }
  });
});

describe("FieldInfo (§19.3)", () => {
  it("reveals help text on focus and hides on blur", async () => {
    render(<FieldInfo label="Price" lines={["Required for LIMIT orders.", "e.g. 150.25"]} />);
    const trigger = screen.getByRole("button", { name: "Price help" });
    expect(screen.queryByRole("tooltip")).toBeNull();
    fireEvent.focus(trigger);
    await waitFor(() => expect(screen.getByRole("tooltip")).toBeTruthy());
    expect(screen.getByText("Required for LIMIT orders.")).toBeTruthy();
    fireEvent.blur(trigger);
    await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
  });

  it("reveals help text on hover", () => {
    render(<FieldInfo label="Quantity" lines={["Whole number of shares."]} />);
    fireEvent.mouseEnter(screen.getByRole("button", { name: "Quantity help" }));
    expect(screen.getByText("Whole number of shares.")).toBeTruthy();
  });
});
