/**
 * Top bar (design §9.2): the wordmark and version as every EduMatcher GUI shows
 * them, the symbol picker where terminal-gui has its view tabs, the session
 * indicator (WP-UI01), and the theme, settings and connection controls on the
 * right.
 */

import { Moon, Sun } from "lucide-react";
import { SessionIndicator } from "../SessionIndicator.js";
import { ConnectionBadge, type ConnectionBadgeState } from "../ConnectionBadge.js";
import { SymbolPicker } from "../SymbolPicker.js";
import { SettingsPopover } from "../shared/SettingsPopover.js";
import { useBookStore, type ConnectionState } from "../../store/useBookStore.js";
import { usePrefsStore } from "../../store/usePrefsStore.js";
import appVersion from "../../version.json";

const CONNECTION: Record<ConnectionState, ConnectionBadgeState> = {
  LIVE: "live",
  RECONNECTING: "reconnecting",
  OFFLINE: "offline",
};

export function TopBar() {
  const connection = useBookStore((s) => s.connection());
  const source = useBookStore((s) => s.source);
  const session = useBookStore((s) => s.marketSession);
  const timeZone = useBookStore((s) => s.stats?.timezone ?? "UTC");
  const theme = usePrefsStore((s) => s.theme);
  const toggleTheme = usePrefsStore((s) => s.toggleTheme);

  const ThemeIcon = theme === "dark" ? Sun : Moon;

  return (
    <header className="flex h-12 shrink-0 items-center gap-6 border-b border-border bg-bg-subtle px-4 text-sm">
      <div className="flex items-baseline gap-2">
        <span className="font-mono font-bold text-sm text-fg">EduMatcher</span>
        <span className="font-mono text-xs text-accent">pm-book</span>
        <span className="font-mono text-xs text-brand-version">v{appVersion.version}</span>
      </div>

      <SymbolPicker />

      <SessionIndicator
        state={session?.state ?? null}
        nextState={session?.nextState ?? null}
        nextAt={session?.nextAt ?? null}
        timeZone={timeZone}
      />

      <div className="ml-auto flex items-center gap-3">
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

        <ConnectionBadge state={CONNECTION[connection]} detail={source || undefined} />
      </div>
    </header>
  );
}
