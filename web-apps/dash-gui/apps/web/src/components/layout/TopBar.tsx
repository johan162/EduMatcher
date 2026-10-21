/**
 * Top bar (design §12.2): the wordmark and version as every EduMatcher GUI
 * shows them, the exchange status pill and the session indicator (WP-UI01),
 * then the time picker, refresh, theme, settings and the bridge connection on
 * the right.
 */

import clsx from "clsx";
import { Moon, Sun } from "lucide-react";
import { SessionIndicator } from "../SessionIndicator.js";
import { StatusDot } from "../StatusDot.js";
import { SettingsPopover } from "../shared/SettingsPopover.js";
import { RefreshPicker, TimePicker } from "./TimePicker.js";
import { EXCHANGE_STATUS, UNKNOWN_STATUS } from "../../lib/status.js";
import { useDashStore, type SocketState } from "../../store/useDashStore.js";
import { usePrefsStore } from "../../store/usePrefsStore.js";
import appVersion from "../../version.json";

/** The bridge connection only; pm-monitor's own state is the banner's. */
const SOCKET: Record<SocketState, { tone: "live" | "warn" | "down"; label: string }> = {
  OPEN: { tone: "live", label: "LIVE" },
  CONNECTING: { tone: "warn", label: "CONNECTING" },
  CLOSED: { tone: "down", label: "OFFLINE" },
};

function ExchangeStatusPill() {
  const status = useDashStore((s) => s.snapshot?.exchange.status);
  const look = status ? EXCHANGE_STATUS[status] : UNKNOWN_STATUS;
  return (
    <span
      role="status"
      aria-label={`Exchange status ${look.label}`}
      className={clsx("flex items-center gap-1.5 rounded border px-2 py-0.5 text-xs font-semibold tracking-wider", look.text, look.border)}
    >
      <span aria-hidden="true">{look.glyph}</span>
      {look.label}
    </span>
  );
}

/** The session phase from pm-md-gwy; pm-monitor's trading date goes in the tooltip. */
function SessionBadge() {
  const session = useDashStore((s) => s.session);
  const tz = useDashStore((s) => s.sessionTz);
  const tradingDate = useDashStore((s) => s.snapshot?.exchange.trading_date);
  return (
    <span data-testid="session-badge" title={tradingDate ? `Trading date ${tradingDate} (${tz})` : tz}>
      <SessionIndicator
        state={session?.state ?? null}
        nextState={session?.nextState ?? null}
        nextAt={session?.nextAt ?? null}
        timeZone={tz}
      />
    </span>
  );
}

export function TopBar() {
  const socket = useDashStore((s) => s.socket);
  const theme = usePrefsStore((s) => s.theme);
  const toggleTheme = usePrefsStore((s) => s.toggleTheme);

  const { tone, label } = SOCKET[socket];
  const ThemeIcon = theme === "dark" ? Sun : Moon;

  return (
    <header className="flex h-12 shrink-0 items-center gap-6 border-b border-border bg-bg-subtle px-4 text-sm">
      <div className="flex items-baseline gap-2">
        <span className="font-mono font-bold text-sm text-fg">EduMatcher</span>
        <span className="font-mono text-xs text-accent">pm-dash</span>
        <span className="font-mono text-xs text-brand-version">v{appVersion.version}</span>
      </div>

      <ExchangeStatusPill />
      <SessionBadge />

      <div className="ml-auto flex items-center gap-2">
        <TimePicker />
        <RefreshPicker />
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
