/**
 * Top bar (design §7.1, §7.2): app name, the full row of view tabs, and the
 * global connection indicator.
 *
 * Tabs live here rather than in a left nav rail, which is where log-gui puts
 * them. Design §7.2 argues the case explicitly — six destinations fit one row,
 * and a terminal wants its horizontal space for data, not chrome.
 */

import clsx from "clsx";
import { Gauge, Moon, Sun } from "lucide-react";
import { NavLink } from "react-router-dom";
import { StatusDot } from "../Badge.js";
import { useLiveStore, type ConnectionState } from "../../store/useLiveStore.js";
import { DENSITY_LABEL, usePrefsStore } from "../../store/usePrefsStore.js";

const VERSION = "v0.1.0";

const VIEWS = [
  { to: "/", label: "Overview", end: true },
  { to: "/symbol", label: "Symbol", end: false },
  { to: "/index", label: "Index", end: false },
  { to: "/tape", label: "Tape", end: false },
  { to: "/movers", label: "Movers", end: false },
  { to: "/session", label: "Session", end: false },
] as const;

const CONNECTION: Record<ConnectionState, { tone: "live" | "warn" | "down"; label: string }> = {
  LIVE: { tone: "live", label: "LIVE" },
  RECONNECTING: { tone: "warn", label: "RECONNECTING" },
  OFFLINE: { tone: "down", label: "OFFLINE" },
};

export function TopBar() {
  const connection = useLiveStore((s) => s.connectionState());
  const gateway = useLiveStore((s) => s.gateway);
  const theme = usePrefsStore((s) => s.theme);
  const toggleTheme = usePrefsStore((s) => s.toggleTheme);
  const density = usePrefsStore((s) => s.density);
  const cycleDensity = usePrefsStore((s) => s.cycleDensity);

  const { tone, label } = CONNECTION[connection];
  const ThemeIcon = theme === "dark" ? Sun : Moon;

  return (
    <header className="flex h-12 shrink-0 items-center gap-6 border-b border-border bg-bg-subtle px-4 text-sm">
      <div className="flex items-baseline gap-2">
        <span className="font-bold tracking-tight text-accent">pm-terminal</span>
        <span className="text-xs text-fg-faint">{VERSION}</span>
      </div>

      <nav className="flex items-center gap-1">
        {VIEWS.map(({ to, label: viewLabel, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              clsx(
                "rounded px-3 py-1.5 text-xs font-semibold uppercase tracking-wider transition-colors",
                isActive
                  ? "bg-accent text-accent-fg"
                  : "text-fg-subtle hover:bg-bg-inset hover:text-fg",
              )
            }
          >
            {viewLabel}
          </NavLink>
        ))}
      </nav>

      <div className="ml-auto flex items-center gap-4">
        <button
          type="button"
          onClick={cycleDensity}
          title={`Density: ${DENSITY_LABEL[density]} — click to cycle`}
          aria-label={`Density: ${DENSITY_LABEL[density]}`}
          className="flex items-center gap-1.5 rounded px-2 py-1 text-xs text-fg-subtle hover:bg-bg-inset hover:text-fg"
        >
          <Gauge size={14} />
          {DENSITY_LABEL[density]}
        </button>

        <button
          type="button"
          onClick={toggleTheme}
          title={`Theme: ${theme} — click to switch`}
          aria-label={`Theme: ${theme}`}
          className="rounded p-1.5 text-fg-subtle hover:bg-bg-inset hover:text-fg"
        >
          <ThemeIcon size={16} />
        </button>

        <StatusDot tone={tone}>
          <span className="text-xs font-semibold tracking-wider">{label}</span>
          {gateway && <span className="ml-1.5 text-xs text-fg-faint">{gateway}</span>}
        </StatusDot>
      </div>
    </header>
  );
}
