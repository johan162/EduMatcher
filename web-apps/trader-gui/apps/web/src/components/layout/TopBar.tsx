import { useAuthStore } from "@/store/useAuthStore.js";
import { useNotificationStore } from "@/store/useNotificationStore.js";
import { useUiStore } from "@/store/useUiStore.js";
import { useThemeStore } from "@/store/useThemeStore.js";
import { useConnectionHealth } from "@/hooks/useConnectionHealth.js";
import { useSessionClock } from "@/hooks/useSessionClock.js";
import { SESSION_PHASE_META, UNKNOWN_PHASE_META } from "@/lib/sessionState.js";
import { formatCountdown } from "@/lib/formatters.js";
import { ConnectionBadge, type ConnectionBadgeState } from "@/components/ConnectionBadge.js";
import { SettingsPopover } from "@/components/shared/SettingsPopover.js";
import { Bell, LogOut, HelpCircle, Moon, Search, Sun } from "lucide-react";
import appVersion from "../../version.json";

const HEALTH_BADGE: Record<"connected" | "reconnecting" | "disconnected", ConnectionBadgeState> = {
  connected: "live",
  reconnecting: "reconnecting",
  disconnected: "offline",
};

/** Wall clock as HH:MM:SS, for the exchange clock (§9.2). */
function clockLabel(nowMs: number): string {
  return new Date(nowMs).toLocaleTimeString("en-GB", { hour12: false });
}

export function TopBar() {
  const role = useAuthStore((s) => s.role);
  const gatewayId = useAuthStore((s) => s.gatewayId);
  const logout = useAuthStore((s) => s.logout);
  const unread = useNotificationStore((s) => s.unread);
  const toggleEventCenter = useUiStore((s) => s.toggleEventCenter);
  const toggleHelp = useUiStore((s) => s.toggleHelp);
  const toggleCommandPalette = useUiStore((s) => s.toggleCommandPalette);
  const theme = useThemeStore((s) => s.theme);
  const toggleTheme = useThemeStore((s) => s.toggleTheme);
  const health = useConnectionHealth();
  const { now, phase, known, elapsedMs, countdownMs, nextState } = useSessionClock();

  const phaseMeta = known ? SESSION_PHASE_META[phase] : UNKNOWN_PHASE_META;
  const ThemeIcon = theme === "dark" ? Sun : Moon;

  // Countdown when a transition target is known, elapsed-in-phase otherwise
  // — a venue with sessions disabled or a partial schedule still gets a
  // useful clock rather than a blank one. Nothing while the phase itself is
  // unknown: a countdown from an unknown phase is a guess.
  const clockDetail = !known ? null : countdownMs !== null && nextState !== null ? (
      <>
        <span className="text-fg-faint">→</span>
        <span className="text-fg-dim">{SESSION_PHASE_META[nextState].label}</span>
        <span className="font-mono text-fg" aria-label="time to next session phase">
          in {formatCountdown(countdownMs)}
        </span>
      </>
    ) : elapsedMs !== null ? (
      <span className="font-mono text-fg-dim" aria-label="time elapsed in phase">
        {formatCountdown(elapsedMs)} elapsed
      </span>
    ) : null;

  return (
    <header className="h-10 flex items-center px-4 bg-panel border-b border-line flex-shrink-0 z-50">
      {/* Left: wordmark */}
      <div className="flex items-center gap-2 w-56 flex-shrink-0">
        <span className="font-mono font-bold text-sm text-fg">EduMatcher</span>
        <span className="font-mono text-xs text-accent">pm-trader</span>
        <span className="font-mono text-xs text-brand-version">v{appVersion.version}</span>
      </div>

      {/* Centre: session badge + exchange clock + countdown */}
      <div className="flex-1 flex justify-center items-center gap-3 text-xs">
        <span
          key={known ? phase : "UNKNOWN"}
          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium animate-fade-in ${phaseMeta.bgClass} ${phaseMeta.textClass}`}
          aria-label="session phase"
        >
          {phaseMeta.label}
        </span>
        {clockDetail}
        <span className="font-mono text-fg-faint hidden xl:inline" aria-label="exchange clock">
          {clockLabel(now)}
        </span>
      </div>

      {/* Right: WS health, last update, notifications, gateway ID, logout */}
      <div className="flex items-center gap-3 w-56 justify-end">
        {health.lastMarketDataAt !== null && (
          <span className="text-[10px] font-mono text-fg-faint hidden xl:inline">
            Updated {clockLabel(health.lastMarketDataAt)}
          </span>
        )}

        <button
          type="button"
          onClick={toggleCommandPalette}
          aria-label="Command palette"
          title="Search (Ctrl+K)"
          className="text-fg-dim hover:text-fg"
        >
          <Search size={16} />
        </button>

        <button
          type="button"
          onClick={toggleEventCenter}
          className="relative text-fg-dim hover:text-fg"
          aria-label={`Notifications (${unread} unread)`}
        >
          <Bell size={16} />
          {unread > 0 && (
            <span className="absolute -top-1 -right-1 bg-ask text-white text-[10px] rounded-full w-4 h-4 flex items-center justify-center">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </button>

        <SettingsPopover />

        <button
          type="button"
          onClick={toggleTheme}
          title={`Theme: ${theme} — click to switch`}
          aria-label={`Theme: ${theme}`}
          className="text-fg-dim hover:text-fg"
        >
          <ThemeIcon size={16} />
        </button>

        <button
          type="button"
          onClick={toggleHelp}
          aria-label="Help"
          title="Help (Ctrl+/)"
          className="text-fg-dim hover:text-fg"
        >
          <HelpCircle size={16} />
        </button>

        <ConnectionBadge state={HEALTH_BADGE[health.overall]} title={`events: ${health.events} · market-data: ${health.marketData}${
            health.adminMonitor ? ` · monitor: ${health.adminMonitor}` : ""
          }`} />

        <span className="text-xs text-fg-faint hidden lg:inline">{gatewayId}</span>
        <span className="text-xs text-fg-faint hidden lg:inline">{role}</span>

        <button
          type="button"
          onClick={logout}
          className="text-fg-dim hover:text-fg"
          aria-label="Logout"
        >
          <LogOut size={16} />
        </button>
      </div>
    </header>
  );
}
