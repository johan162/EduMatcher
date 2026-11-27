// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { LiveModeHelp } from "../src/components/LiveModeHelp";

afterEach(cleanup);

describe("LiveModeHelp", () => {
  it("is closed until the (?) is pressed, then explains both modes with their limits", () => {
    render(<LiveModeHelp bufferRows={2000} historyRows={200} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "What LIVE and history mean" }));
    const text = screen.getByRole("dialog", { name: "LIVE and history" }).textContent ?? "";
    expect(text).toContain("▶ LIVE");
    expect(text).toContain("history");
    expect(text).toContain("newest 2,000");
    expect(text).toContain("newest 200 matching lines");
  });

  it("closes on Escape, on a second press and on a click outside", () => {
    const { container } = render(<LiveModeHelp bufferRows={2000} historyRows={200} />);
    const button = screen.getByRole("button", { name: "What LIVE and history mean" });

    fireEvent.click(button);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(button);
    fireEvent.click(button);
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(button);
    fireEvent.click(container.querySelector("[aria-hidden='true']")!);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
