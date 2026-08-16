import type { GatewayRole } from "@/types/index.js";

/** What a command palette action does (§21.1). Effects are applied by the palette. */
export type CommandActionKind =
  | "navigate"
  | "toggle-event-center"
  | "toggle-help"
  | "open-shortcuts"
  | "flatten-all";

export interface ActionCommand {
  id: string;
  label: string;
  kind: CommandActionKind;
  /** Route for `navigate` commands. */
  to?: string;
  /** Optional shortcut hint shown on the right. */
  keys?: string;
}

const ALL_ROLES_NAV: ActionCommand[] = [
  { id: "nav-market", label: "Market Overview", kind: "navigate", to: "/market" },
  { id: "nav-watchlist", label: "Watchlist", kind: "navigate", to: "/watchlist", keys: "Ctrl+L" },
];

const TRADER_NAV: ActionCommand[] = [
  { id: "nav-workspace", label: "Trading Workspace", kind: "navigate", to: "/workspace" },
  { id: "nav-order-entry", label: "Order Entry", kind: "navigate", to: "/orders/entry" },
  { id: "nav-orders", label: "Active Orders", kind: "navigate", to: "/orders", keys: "F4" },
  { id: "nav-history", label: "Trade History", kind: "navigate", to: "/orders/history" },
  { id: "nav-positions", label: "Positions", kind: "navigate", to: "/positions", keys: "F3" },
];

const MM_NAV: ActionCommand[] = [
  { id: "nav-quotes", label: "Quote Management", kind: "navigate", to: "/quotes" },
  { id: "nav-quote-bootstrap", label: "Quote Bootstrap", kind: "navigate", to: "/quotes/bootstrap" },
  { id: "nav-positions", label: "Positions", kind: "navigate", to: "/positions", keys: "F3" },
];

const ADMIN_NAV: ActionCommand[] = [
  { id: "nav-admin-dashboard", label: "System Dashboard", kind: "navigate", to: "/admin/dashboard" },
  { id: "nav-admin-session", label: "Session Control", kind: "navigate", to: "/admin/session" },
  { id: "nav-admin-gateways", label: "Gateway Management", kind: "navigate", to: "/admin/gateways" },
  { id: "nav-admin-risk", label: "Risk Controls", kind: "navigate", to: "/admin/risk" },
  { id: "nav-admin-cb", label: "Circuit Breakers", kind: "navigate", to: "/admin/circuit-breakers" },
  { id: "nav-admin-symbols", label: "Symbol Management", kind: "navigate", to: "/admin/symbols" },
  { id: "nav-admin-indexes", label: "Index Administration", kind: "navigate", to: "/admin/indexes" },
  { id: "nav-admin-monitor", label: "Monitor Log", kind: "navigate", to: "/admin/monitor" },
];

const COMMON_ACTIONS: ActionCommand[] = [
  { id: "act-event-center", label: "Notification / Event Center", kind: "toggle-event-center", keys: "Ctrl+." },
  { id: "act-help", label: "Open Help", kind: "toggle-help", keys: "Ctrl+/" },
  { id: "act-shortcuts", label: "Keyboard Shortcuts", kind: "open-shortcuts", keys: "?" },
];

/** The full action-command list for a role (navigation + common actions). */
export function actionCommandsForRole(role: GatewayRole | null): ActionCommand[] {
  const nav =
    role === "TRADER"
      ? TRADER_NAV
      : role === "MARKET_MAKER"
        ? MM_NAV
        : role === "ADMIN"
          ? ADMIN_NAV
          : [];
  const flatten: ActionCommand[] =
    role === "TRADER" || role === "MARKET_MAKER"
      ? [{ id: "act-flatten-all", label: "Flatten All positions", kind: "flatten-all", keys: "Ctrl+Shift+F" }]
      : [];
  return [...ALL_ROLES_NAV, ...nav, ...flatten, ...COMMON_ACTIONS];
}

/** Case-insensitive substring filter on a label; empty query returns all. */
export function filterByLabel<T extends { label: string }>(items: T[], query: string): T[] {
  const q = query.trim().toLowerCase();
  if (q === "") return items;
  return items.filter((i) => i.label.toLowerCase().includes(q));
}
