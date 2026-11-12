import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { HelpCircle, LogOut } from "lucide-react";
import { useAuthStore } from "@/store/useAuthStore";
import { useConnectionStore } from "@/store/useConnectionStore";
import { SettingsPopover } from "@/components/shared/SettingsPopover";
import { HelpDrawer } from "@/components/help/HelpDrawer";
import appVersion from "../../version.json";

const ROLE_LABEL = { ADMIN: "Admin", TRADER: "Trader", MARKET_MAKER: "Market maker" } as const;

/** Brand, who is logged in, whether the API gateway answers, settings, help and log out -- trader-gui's layout. */
export function TopBar() {
  const navigate = useNavigate();
  const gatewayId = useAuthStore((s) => s.gatewayId);
  const role = useAuthStore((s) => s.role);
  const logout = useAuthStore((s) => s.logout);
  const [helpOpen, setHelpOpen] = useState(false);
  const closeHelp = useCallback(() => setHelpOpen(false), []);

  return (
    <header className="h-10 flex items-center px-4 bg-panel border-b border-line flex-shrink-0 z-50">
      {/* Left: wordmark */}
      <div className="flex items-center gap-2 w-56 flex-shrink-0">
        <span className="font-mono font-bold text-sm text-fg">EduMatcher</span>
        <span className="font-mono text-xs text-accent">pm-clearing-gui</span>
        <span className="font-mono text-xs text-brand-version">v{appVersion.version}</span>
      </div>

      <div className="flex-1 flex justify-center items-center text-xs text-fg-dim">read-only</div>

      <div className="flex items-center gap-3 justify-end text-xs">
        <SettingsPopover />

        <button
          type="button"
          onClick={() => setHelpOpen((v) => !v)}
          aria-label="Help"
          title="Help"
          className="text-fg-dim hover:text-fg"
        >
          <HelpCircle size={16} />
        </button>

        <ConnectionBadge />

        <span className="text-xs text-fg-faint hidden lg:inline">{gatewayId}</span>
        {role && <span className="text-xs text-fg-faint hidden lg:inline">{ROLE_LABEL[role]}</span>}

        <button
          type="button"
          onClick={() => {
            logout();
            navigate("/login", { replace: true });
          }}
          className="text-fg-dim hover:text-fg"
          aria-label="Log out"
          title="Log out"
        >
          <LogOut size={16} />
        </button>
      </div>
      {helpOpen && <HelpDrawer onClose={closeHelp} />}
    </header>
  );
}

/** "API connected" / "API unreachable", from the last request's outcome. */
export function ConnectionBadge() {
  const state = useConnectionStore((s) => s.state);
  const text =
    state === "online" ? "API connected" : state === "offline" ? "API unreachable" : "API: no request yet";
  const tone = state === "online" ? "bg-bid" : state === "offline" ? "bg-ask" : "bg-fg-faint";
  return (
    <span role="status" aria-live="polite" className="flex items-center gap-1.5">
      <span className={`inline-block h-2 w-2 rounded-full ${tone}`} aria-hidden="true" />
      {text}
    </span>
  );
}
