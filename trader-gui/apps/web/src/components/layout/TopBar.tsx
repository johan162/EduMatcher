import { useAuthStore } from "@/store/useAuthStore.js";
import { useNotificationStore } from "@/store/useNotificationStore.js";
import { useUiStore } from "@/store/useUiStore.js";
import { useConnectionHealth } from "@/hooks/useConnectionHealth.js";
import { useSessionClock } from "@/hooks/useSessionClock.js";
import { SESSION_PHASE_META } from "@/lib/sessionState.js";
import { formatCountdown } from "@/lib/formatters.js";
import { SettingsPopover } from "@/components/shared/SettingsPopover.js";
import { Bell, LogOut, Wifi, WifiOff, Activity } from "lucide-react";

const HEALTH_META = {
  connected: { dot: "text-emerald-400", Icon: Wifi, label: "Connected" },
  reconnecting: { dot: "text-amber-400", Icon: Activity, label: "Reconnecting" },
  disconnected: { dot: "text-red-500", Icon: WifiOff, label: "Disconnected" },
} as const;

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
  const health = useConnectionHealth();
  const { now, phase, elapsedMs, countdownMs, nextState } = useSessionClock();

  const phaseMeta = SESSION_PHASE_META[phase];
  const { dot, Icon, label } = HEALTH_META[health.overall];

  // Countdown when a transition target is known, elapsed-in-phase otherwise
  // — a venue with sessions disabled or a partial schedule still gets a
  // useful clock rather than a blank one.
  const clockDetail =
    countdownMs !== null && nextState !== null ? (
      <>
        <span className="text-[#505070]">→</span>
        <span className="text-[#9090b0]">{SESSION_PHASE_META[nextState].label}</span>
        <span className="font-mono text-[#e8e8f0]" aria-label="time to next session phase">
          in {formatCountdown(countdownMs)}
        </span>
      </>
    ) : elapsedMs !== null ? (
      <span className="font-mono text-[#9090b0]" aria-label="time elapsed in phase">
        {formatCountdown(elapsedMs)} elapsed
      </span>
    ) : null;

  return (
    <header className="h-10 flex items-center px-4 bg-[#12121a] border-b border-[#2a2a45] flex-shrink-0 z-50">
      {/* Left: wordmark */}
      <div className="flex items-center gap-2 w-56 flex-shrink-0">
        <span className="font-mono font-bold text-sm text-[#e8e8f0]">EduMatcher</span>
        <span className="text-xs text-[#505070]">pm-trading-ui</span>
      </div>

      {/* Centre: session badge + exchange clock + countdown */}
      <div className="flex-1 flex justify-center items-center gap-3 text-xs">
        <span
          key={phase}
          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium animate-fade-in ${phaseMeta.bgClass} ${phaseMeta.textClass}`}
        >
          {phaseMeta.label}
        </span>
        {clockDetail}
        <span className="font-mono text-[#505070] hidden xl:inline" aria-label="exchange clock">
          {clockLabel(now)}
        </span>
      </div>

      {/* Right: WS health, last update, notifications, gateway ID, logout */}
      <div className="flex items-center gap-3 w-56 justify-end">
        <span
          className={`flex items-center gap-1 text-xs ${dot}`}
          title={`events: ${health.events} · market-data: ${health.marketData}${
            health.adminMonitor ? ` · monitor: ${health.adminMonitor}` : ""
          }`}
        >
          <Icon size={12} />
          <span className="hidden md:inline">{label}</span>
        </span>

        {health.lastMarketDataAt !== null && (
          <span className="text-[10px] font-mono text-[#505070] hidden xl:inline">
            Updated {clockLabel(health.lastMarketDataAt)}
          </span>
        )}

        <button
          type="button"
          onClick={toggleEventCenter}
          className="relative text-[#9090b0] hover:text-[#e8e8f0]"
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

        <span className="text-xs text-[#505070] hidden lg:inline">{gatewayId}</span>
        <span className="text-xs text-[#505070] hidden lg:inline">{role}</span>

        <button
          type="button"
          onClick={logout}
          className="text-[#9090b0] hover:text-[#e8e8f0]"
          aria-label="Logout"
        >
          <LogOut size={16} />
        </button>
      </div>
    </header>
  );
}
