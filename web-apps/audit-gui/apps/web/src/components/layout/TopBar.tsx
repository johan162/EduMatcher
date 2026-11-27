import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { HelpCircle, LogOut } from "lucide-react";
import { HelpDrawer } from "@/components/help/HelpDrawer";
import { ExplainToggle } from "@/components/shared/Explain";
import { SettingsPopover } from "@/components/shared/SettingsPopover";
import { SnapshotPicker } from "@/components/snapshot/SnapshotPicker";
import { useAuthStore } from "@/store/useAuthStore";
import { useConnectionStore } from "@/store/useConnectionStore";
import { AboutButton } from "./AboutButton";
import appVersion from "../../version.json";

/** Brand, the evidence selector, Explain, settings, help, the gateway's state and log out (clearing-gui's layout). */
export function TopBar() {
  const navigate = useNavigate();
  const gatewayId = useAuthStore((s) => s.gatewayId);
  const logout = useAuthStore((s) => s.logout);
  const [helpOpen, setHelpOpen] = useState(false);
  const closeHelp = useCallback(() => setHelpOpen(false), []);

  return (
    <header className="z-50 flex h-10 flex-shrink-0 items-center gap-4 border-b border-line bg-panel px-4">
      <div className="flex min-w-56 flex-shrink-0 items-center gap-2 whitespace-nowrap">
        <AboutButton app="pm-audit-gui" version={appVersion.version} />
        <span className="font-mono text-sm font-bold text-fg">MarketSim</span>
        <span className="font-mono text-xs text-accent">pm-audit-gui</span>
        <span className="font-mono text-xs text-brand-version">v{appVersion.version}</span>
      </div>

      <div className="flex min-w-0 flex-1 items-center">
        <SnapshotPicker />
      </div>

      <div className="flex items-center justify-end gap-3 text-xs">
        <ExplainToggle />
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
        <span className="hidden text-fg-faint lg:inline">{gatewayId} · Admin</span>
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
  const text = state === "online" ? "API connected" : state === "offline" ? "API unreachable" : "API: no request yet";
  const tone = state === "online" ? "bg-bid" : state === "offline" ? "bg-ask" : "bg-fg-faint";
  return (
    <span role="status" aria-live="polite" className="flex items-center gap-1.5">
      <span className={`inline-block h-2 w-2 rounded-full ${tone}`} aria-hidden="true" />
      {text}
    </span>
  );
}
