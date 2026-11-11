import { NavLink } from "react-router-dom";
import {
  Activity,
  BadgeDollarSign,
  BarChart2,
  Briefcase,
  ClipboardCheck,
  History,
  LayoutDashboard,
  Network,
  Plug,
  Receipt,
  ScrollText,
  Scale,
  type LucideIcon,
} from "lucide-react";
import { useAuthStore, type Role } from "@/store/useAuthStore";

interface NavItem {
  to: string;
  label: string;
  Icon: LucideIcon;
}

const ADMIN_ITEMS: NavItem[] = [
  { to: "/overview", label: "Overview", Icon: LayoutDashboard },
  { to: "/participants", label: "Participants", Icon: Network },
  { to: "/symbols", label: "Symbols", Icon: BarChart2 },
  { to: "/events", label: "Events", Icon: ScrollText },
  { to: "/gateway-sessions", label: "Gateway Sessions", Icon: Plug },
  { to: "/reconciliation", label: "Reconciliation", Icon: Scale },
  { to: "/eod", label: "EOD Settlement", Icon: Receipt },
];

const PARTICIPANT_ITEMS: NavItem[] = [
  { to: "/me/positions", label: "My Positions", Icon: Briefcase },
  { to: "/me/trades", label: "My Trades", Icon: Activity },
  { to: "/me/history", label: "Daily & Close History", Icon: History },
  { to: "/me/settlement", label: "EOD Settlement", Icon: BadgeDollarSign },
  { to: "/me/sessions", label: "Gateway Sessions", Icon: Plug },
];

const MM_ITEMS: NavItem[] = [
  { to: "/me/obligations", label: "My Quote Obligations", Icon: ClipboardCheck },
];

export function navItems(role: Role | null): NavItem[] {
  if (role === "ADMIN") return ADMIN_ITEMS;
  if (role === "MARKET_MAKER") return [...PARTICIPANT_ITEMS, ...MM_ITEMS];
  if (role === "TRADER") return PARTICIPANT_ITEMS;
  return [];
}

/** The screens the role may open. Hiding the others is a convenience, not security. */
export function Sidebar() {
  const role = useAuthStore((s) => s.role);
  return (
    <nav aria-label="Main navigation" className="w-56 shrink-0 overflow-y-auto border-r border-line bg-panel py-3">
      <ul className="space-y-0.5 px-2">
        {navItems(role).map(({ to, label, Icon }) => (
          <li key={to}>
            <NavLink
              to={to}
              className={({ isActive }) =>
                `flex items-center gap-2 rounded px-3 py-1.5 text-sm ${
                  isActive ? "bg-accent text-accent-fg" : "text-fg-dim hover:bg-raised hover:text-fg"
                }`
              }
            >
              <Icon size={14} aria-hidden="true" />
              {label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
