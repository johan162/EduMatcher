// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { SymbolPicker } from "@/components/shared/SymbolPicker";
import { SettingsPopover } from "@/components/shared/SettingsPopover";
import { useSettingsStore } from "@/store/useSettingsStore";

const FEW = ["AAPL", "MSFT"];
const MANY = Array.from({ length: 25 }, (_, i) => `SYM${String(i).padStart(2, "0")}`);

beforeEach(() => {
  cleanup();
  useSettingsStore.setState({ symbolPickerMode: "auto", symbolPickerThreshold: 20 });
});

describe("SymbolPicker", () => {
  it("renders a <select> in auto mode below the threshold", () => {
    render(<SymbolPicker symbols={FEW} value="AAPL" onChange={() => {}} label="Active symbol" />);
    expect(screen.getByLabelText("Active symbol").tagName).toBe("SELECT");
  });

  it("renders the search combobox in auto mode at/above the threshold", () => {
    render(<SymbolPicker symbols={MANY} value="SYM00" onChange={() => {}} label="Active symbol" />);
    expect(screen.getByRole("button", { name: "Active symbol" })).toBeTruthy();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("forces the dropdown even with many symbols when mode is 'dropdown'", () => {
    useSettingsStore.setState({ symbolPickerMode: "dropdown" });
    render(<SymbolPicker symbols={MANY} value="SYM00" onChange={() => {}} label="Active symbol" />);
    expect(screen.getByLabelText("Active symbol").tagName).toBe("SELECT");
  });

  it("forces the search combobox even with few symbols when mode is 'search'", () => {
    useSettingsStore.setState({ symbolPickerMode: "search" });
    render(<SymbolPicker symbols={FEW} value="AAPL" onChange={() => {}} label="Active symbol" />);
    expect(screen.getByRole("button", { name: "Active symbol" })).toBeTruthy();
  });

  it("selecting from the dropdown calls onChange with the new symbol", () => {
    const onChange = vi.fn();
    render(<SymbolPicker symbols={FEW} value="AAPL" onChange={onChange} label="Active symbol" />);
    fireEvent.change(screen.getByLabelText("Active symbol"), { target: { value: "MSFT" } });
    expect(onChange).toHaveBeenCalledWith("MSFT");
  });

  describe("search combobox", () => {
    beforeEach(() => {
      useSettingsStore.setState({ symbolPickerMode: "search" });
    });

    it("opens the filtered list on click, showing all symbols with an empty query", () => {
      render(<SymbolPicker symbols={FEW} value="AAPL" onChange={() => {}} label="Active symbol" />);
      fireEvent.click(screen.getByRole("button", { name: "Active symbol" }));
      const list = screen.getByRole("listbox", { name: "Active symbol" });
      expect(list.textContent).toContain("AAPL");
      expect(list.textContent).toContain("MSFT");
    });

    it("filters the list as the query changes, case-insensitively", () => {
      render(
        <SymbolPicker symbols={MANY} value="SYM00" onChange={() => {}} label="Active symbol" />,
      );
      fireEvent.click(screen.getByRole("button", { name: "Active symbol" }));
      fireEvent.change(screen.getByPlaceholderText("Type to filter…"), {
        target: { value: "sym1" },
      });
      const options = screen.getAllByRole("option");
      expect(options.map((o) => o.textContent)).toEqual([
        "SYM10",
        "SYM11",
        "SYM12",
        "SYM13",
        "SYM14",
        "SYM15",
        "SYM16",
        "SYM17",
        "SYM18",
        "SYM19",
      ]);
    });

    it("shows 'No matches.' when nothing filters through", () => {
      render(<SymbolPicker symbols={FEW} value="AAPL" onChange={() => {}} label="Active symbol" />);
      fireEvent.click(screen.getByRole("button", { name: "Active symbol" }));
      fireEvent.change(screen.getByPlaceholderText("Type to filter…"), {
        target: { value: "ZZZZ" },
      });
      expect(screen.getByText("No matches.")).toBeTruthy();
    });

    it("Enter selects the highlighted option and closes the list", () => {
      const onChange = vi.fn();
      render(<SymbolPicker symbols={FEW} value="AAPL" onChange={onChange} label="Active symbol" />);
      fireEvent.click(screen.getByRole("button", { name: "Active symbol" }));
      fireEvent.keyDown(screen.getByPlaceholderText("Type to filter…"), { key: "ArrowDown" });
      fireEvent.keyDown(screen.getByPlaceholderText("Type to filter…"), { key: "Enter" });
      expect(onChange).toHaveBeenCalledWith("MSFT");
      expect(screen.queryByRole("listbox")).toBeNull();
    });

    it("clicking an option selects it", () => {
      const onChange = vi.fn();
      render(<SymbolPicker symbols={FEW} value="AAPL" onChange={onChange} label="Active symbol" />);
      fireEvent.click(screen.getByRole("button", { name: "Active symbol" }));
      fireEvent.click(screen.getByRole("option", { name: "MSFT" }));
      expect(onChange).toHaveBeenCalledWith("MSFT");
    });

    it("Escape closes the list without changing the selection", () => {
      const onChange = vi.fn();
      render(<SymbolPicker symbols={FEW} value="AAPL" onChange={onChange} label="Active symbol" />);
      fireEvent.click(screen.getByRole("button", { name: "Active symbol" }));
      fireEvent.keyDown(screen.getByPlaceholderText("Type to filter…"), { key: "Escape" });
      expect(screen.queryByRole("listbox")).toBeNull();
      expect(onChange).not.toHaveBeenCalled();
    });
  });
});

describe("SettingsPopover symbol picker controls", () => {
  it("shows the three mode options and switches on click", () => {
    render(<SettingsPopover />);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    const group = screen.getByRole("radiogroup", { name: "Symbol picker" });
    const auto = screen.getByRole("radio", { name: "Auto" });
    const dropdown = screen.getByRole("radio", { name: "Dropdown" });
    const search = screen.getByRole("radio", { name: "Search" });
    expect(group.contains(auto)).toBe(true);
    expect(auto.getAttribute("aria-checked")).toBe("true");

    fireEvent.click(search);
    expect(useSettingsStore.getState().symbolPickerMode).toBe("search");
    expect(search.getAttribute("aria-checked")).toBe("true");
    expect(dropdown.getAttribute("aria-checked")).toBe("false");
  });

  it("edits the auto threshold", () => {
    render(<SettingsPopover />);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    const input = screen.getByLabelText("Symbol picker auto threshold") as HTMLInputElement;
    expect(input.value).toBe("20");

    fireEvent.change(input, { target: { value: "50" } });
    expect(useSettingsStore.getState().symbolPickerThreshold).toBe(50);
  });

  it("ignores invalid threshold input rather than storing NaN or zero", () => {
    render(<SettingsPopover />);
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));

    const input = screen.getByLabelText("Symbol picker auto threshold") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "0" } });
    expect(useSettingsStore.getState().symbolPickerThreshold).toBe(20);
    fireEvent.change(input, { target: { value: "abc" } });
    expect(useSettingsStore.getState().symbolPickerThreshold).toBe(20);
  });
});
