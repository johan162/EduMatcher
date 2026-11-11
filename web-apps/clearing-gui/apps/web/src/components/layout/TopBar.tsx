import { useNavigate } from "react-router-dom";
import { LogOut } from "lucide-react";
import { useAuthStore } from "@/store/useAuthStore";
import { useConnectionStore } from "@/store/useConnectionStore";
import appVersion from "../../version.json";

const ROLE_LABEL = { ADMIN: "Admin", TRADER: "Trader", MARKET_MAKER: "Market maker" } as const;

/** Brand, who is logged in, whether the API gateway answers, and log out. */
export function TopBar() {
  const navigate = useNavigate();
  const gatewayId = useAuthStore((s) => s.gatewayId);
  const role = useAuthStore((s) => s.role);
  const logout = useAuthStore((s) => s.logout);

  return (
    <header className="flex h-10 shrink-0 items-center gap-4 border-b border-line bg-panel px-4">
      <span className="font-mono text-sm font-bold">EduMatcher Clearing</span>
      <span className="font-mono text-[11px] text-fg-faint">v{appVersion.version}</span>
      <span className="text-xs text-fg-dim">read-only</span>
      <div className="ml-auto flex items-center gap-4 text-xs">
        <ConnectionBadge />
        <span>
          <span className="font-mono">{gatewayId}</span>
          {role && <span className="ml-1 text-fg-dim">({ROLE_LABEL[role]})</span>}
        </span>
        <button
          type="button"
          onClick={() => {
            logout();
            navigate("/login", { replace: true });
          }}
          className="flex items-center gap-1 rounded px-2 py-1 text-fg-dim hover:bg-raised hover:text-fg"
        >
          <LogOut size={12} aria-hidden="true" />
          Log out
        </button>
      </div>
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
