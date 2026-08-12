import { useAuthStore } from "@/store/useAuthStore.js";
import { useSessionStore } from "@/store/useSessionStore.js";
import { useNotificationStore } from "@/store/useNotificationStore.js";
import { useConnectionHealth } from "@/hooks/useConnectionHealth.js";
import { SESSION_PHASE_META } from "@/lib/sessionState.js";
import { Bell, LogOut, Wifi, WifiOff, Activity } from "lucide-react";

export function TopBar() {
  const { role, gatewayId, logout } = useAuthStore();
  const { phase } = useSessionStore();
  const unread = useNotificationStore((s) => s.unread);
  const health = useConnectionHealth();

  const phaseMeta = SESSION_PHASE_META[phase];

  const healthDotClass =
    health.overall === "connected"
      ? "text-bid"
      : health.overall === "reconnecting"
        ? "text-amber-400"
        : "text-ask";

  const HealthIcon =
    health.overall === "connected"
      ? Wifi
      : health.overall === "reconnecting"
        ? Activity
        : WifiOff;

  return (
    <header className="h-10 flex items-center px-4 bg-[#12121a] border-b border-[#2a2a45] flex-shrink-0 z-50">
      {/* Left: wordmark */}
      <div className="flex items-center gap-2 w-56 flex-shrink-0">
        <span className="font-mono font-bold text-sm text-[#e8e8f0]">EduMatcher</span>
        <span className="text-xs text-[#505070]">pm-trading-ui</span>
      </div>

      {/* Centre: session badge + clock */}
      <div className="flex-1 flex justify-center items-center gap-3">
        <span
          className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${phaseMeta.bgClass} ${phaseMeta.textClass}`}
        >
          {phaseMeta.label}
        </span>
      </div>

      {/* Right: WS health, notifications, gateway ID, logout */}
      <div className="flex items-center gap-3 w-56 justify-end">
        <span className={`flex items-center gap-1 text-xs ${healthDotClass}`}>
          <HealthIcon size={12} />
          <span className="hidden md:inline capitalize">{health.overall}</span>
        </span>

        <button
          type="button"
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
