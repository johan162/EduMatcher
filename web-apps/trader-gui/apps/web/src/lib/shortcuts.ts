/**
 * The keyboard shortcut reference (§21). Shared by the Shortcuts dialog (§19.4)
 * and the Help drawer's "Keyboard Shortcuts" topic so the two never drift.
 *
 * This is the reference *table* only — the actual key bindings live where the
 * behaviour does (e.g. `B`/`S`/`F1` in the Order Ticket; `Ctrl+/`/`?` in the
 * help hook). Phase 15 wires the remaining bindings; the table documents the
 * full intended set.
 */
export interface ShortcutRow {
  keys: string;
  scope: string;
  action: string;
}

export const SHORTCUTS: ShortcutRow[] = [
  { keys: "F1", scope: "Global", action: "Focus the order ticket (TRADER)" },
  { keys: "F2", scope: "MARKET_MAKER", action: "New quote form for the active symbol" },
  { keys: "F3", scope: "Global", action: "Toggle the position panel" },
  { keys: "F4", scope: "TRADER", action: "Toggle the order blotter" },
  { keys: "B", scope: "Order ticket", action: "Submit BUY with the ticket's parameters" },
  { keys: "S", scope: "Order ticket", action: "Submit SELL with the ticket's parameters" },
  { keys: "Ctrl+K", scope: "Global", action: "Open the command palette (symbol / action search)" },
  { keys: "Ctrl+.", scope: "Global", action: "Toggle the Notification / Event Center" },
  { keys: "Ctrl+L", scope: "Global", action: "Toggle the Watchlist panel" },
  { keys: "Shift+F", scope: "Position row", action: "Flatten the selected position (MARKET close)" },
  { keys: "Ctrl+Shift+F", scope: "Global", action: "Flatten All (always confirms)" },
  { keys: "Escape", scope: "Global", action: "Close the open modal / panel / drawer" },
  { keys: "Ctrl+Enter", scope: "Form focus", action: "Submit the focused form (OCO / Combo)" },
  { keys: "Ctrl+/", scope: "Global", action: "Toggle the help drawer" },
  { keys: "?", scope: "Not in an input", action: "Open this keyboard shortcut reference" },
  { keys: "Delete / Backspace", scope: "Blotter row", action: "Cancel the selected order" },
  { keys: "↑ / ↓", scope: "Blotter", action: "Navigate rows" },
  { keys: "Ctrl+A", scope: "Blotter", action: "Select all visible rows" },
  { keys: "Enter", scope: "Blotter row", action: "Open the Order Detail drawer" },
];
