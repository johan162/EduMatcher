/**
 * Top bar (design §12.2): the wordmark and version as every EduMatcher GUI
 * shows them, then theme, settings and the connection state on the right.
 * WP-D1 adds the exchange status, session clock and time picker.
 */

import { Moon, Sun } from "lucide-react";
import { StatusDot } from "../StatusDot.js";
import { SettingsPopover } from "../shared/SettingsPopover.js";
import { useDashStore, type ConnectionState } from "../../store/useDashStore.js";
import { usePrefsStore } from "../../store/usePrefsStore.js";
import appVersion from "../../version.json";

const CONNECTION: Record<ConnectionState, { tone: "live" | "warn" | "down"; label: string }> = {
  LIVE: { tone: "live", label: "LIVE" },
  NO_MONITOR: { tone: "warn", label: "NO MONITOR" },
  OFFLINE: { tone: "down", label: "OFFLINE" },
};

export function TopBar() {
  const connection = useDashStore((s) => s.connection());
  const theme = usePrefsStore((s) => s.theme);
  const toggleTheme = usePrefsStore((s) => s.toggleTheme);

  const { tone, label } = CONNECTION[connection];
  const ThemeIcon = theme === "dark" ? Sun : Moon;

  return (
    <header className="flex h-12 shrink-0 items-center gap-6 border-b border-border bg-bg-subtle px-4 text-sm">
      <div className="flex items-baseline gap-2">
        <span className="font-mono font-bold text-sm text-fg">EduMatcher</span>
        <span className="font-mono text-xs text-accent">pm-dash</span>
        <span className="font-mono text-xs text-brand-version">v{appVersion.version}</span>
      </div>

      <div className="ml-auto flex items-center gap-4">
        <button
          type="button"
          onClick={toggleTheme}
          title={`Theme: ${theme} — click to switch`}
          aria-label={`Theme: ${theme}`}
          className="rounded p-1.5 text-fg-subtle hover:bg-bg-inset hover:text-fg"
        >
          <ThemeIcon size={16} />
        </button>

        <SettingsPopover />

        <StatusDot tone={tone}>
          <span className="text-xs font-semibold tracking-wider">{label}</span>
        </StatusDot>
      </div>
    </header>
  );
}
