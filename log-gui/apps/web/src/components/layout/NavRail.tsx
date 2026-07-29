/** Navigation rail (design §7.3): six destinations, deliberately the whole set. */

import clsx from "clsx";
import { Activity, AlertTriangle, Gauge, HeartPulse, LayoutDashboard, Stethoscope } from "lucide-react";
import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../lib/api.js";

const DESTINATIONS = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/logs", label: "Logs", icon: Gauge, end: false },
  { to: "/alerts", label: "Alerts", icon: AlertTriangle, end: false },
  { to: "/processes", label: "Processes", icon: Activity, end: false },
  { to: "/diagnostics", label: "Diagnostics", icon: Stethoscope, end: false },
  { to: "/health", label: "Health", icon: HeartPulse, end: false },
] as const;

export function NavRail() {
  const { data } = useQuery({
    queryKey: ["issues", { acked: false, minLevel: "ERROR" }],
    queryFn: () => api.issues({ acked: false, minLevel: "ERROR" }),
    refetchInterval: 15_000,
  });
  const unackedCount = data?.issues.length ?? 0;

  return (
    <nav className="flex w-20 shrink-0 flex-col items-center gap-1 border-r border-border bg-bg-subtle py-3">
      {DESTINATIONS.map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={to}
          to={to}
          end={end}
          className={({ isActive }) =>
            clsx(
              "relative flex w-16 flex-col items-center gap-1 rounded py-2 text-[11px]",
              isActive ? "bg-accent/15 text-accent" : "text-fg-subtle hover:bg-bg-inset",
            )
          }
        >
          <Icon size={18} />
          {label}
          {label === "Alerts" && unackedCount > 0 && (
            <span className="absolute right-2 top-1 flex h-4 w-4 items-center justify-center rounded-full bg-level-error text-[10px] font-bold text-white">
              {unackedCount}
            </span>
          )}
        </NavLink>
      ))}
    </nav>
  );
}
