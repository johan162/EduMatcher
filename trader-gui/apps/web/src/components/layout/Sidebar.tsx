import { NavLink } from "react-router-dom";
import { useAuthStore } from "@/store/useAuthStore.js";
import {
  BarChart2,
  Layers,
  BookOpen,
  Clock,
  TrendingUp,
  Activity,
  Briefcase,
  Settings,
  LayoutDashboard,
  ShieldAlert,
  Network,
  Timer,
  Sliders,
  Zap,
  ScrollText,
  List,
  History,
  Quote,
} from "lucide-react";

interface NavItem {
  to: string;
  label: string;
  Icon: React.ComponentType<{ size?: number }>;
}

const ALL_ROLES: NavItem[] = [{ to: "/market", label: "Market Overview", Icon: BarChart2 }];

const TRADER_ITEMS: NavItem[] = [
  { to: "/workspace", label: "Trading Workspace", Icon: Layers },
  { to: "/orders/entry", label: "Order Entry", Icon: BookOpen },
  { to: "/orders", label: "Active Orders", Icon: List },
  { to: "/orders/history", label: "Trade History", Icon: History },
  { to: "/positions", label: "Positions", Icon: TrendingUp },
];

const MM_ITEMS: NavItem[] = [
  { to: "/quotes", label: "Quote Management", Icon: Quote },
  { to: "/quotes/bootstrap", label: "Quote Bootstrap", Icon: Briefcase },
  { to: "/positions", label: "Positions", Icon: TrendingUp },
];

const ADMIN_ITEMS: NavItem[] = [
  { to: "/admin/dashboard", label: "System Dashboard", Icon: LayoutDashboard },
  { to: "/admin/symbols", label: "Symbol Management", Icon: Settings },
  { to: "/admin/indexes", label: "Index Admin", Icon: Activity },
  { to: "/admin/session", label: "Session Control", Icon: Timer },
  { to: "/admin/risk", label: "Risk Controls", Icon: Sliders },
  { to: "/admin/circuit-breakers", label: "Circuit Breakers", Icon: ShieldAlert },
  { to: "/admin/gateways", label: "Gateways", Icon: Network },
  { to: "/admin/monitor", label: "Monitor Log", Icon: ScrollText },
];

function SidebarLink({ to, label, Icon }: NavItem) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex items-center gap-2 px-3 py-1.5 rounded text-sm transition-colors ${
          isActive
            ? "bg-[#1a1a28] text-[#e8e8f0]"
            : "text-[#9090b0] hover:text-[#e8e8f0] hover:bg-[#1a1a28]"
        }`
      }
    >
      <Icon size={14} />
      <span>{label}</span>
    </NavLink>
  );
}

export function Sidebar() {
  const role = useAuthStore((s) => s.role);

  const roleItems =
    role === "TRADER"
      ? TRADER_ITEMS
      : role === "MARKET_MAKER"
        ? MM_ITEMS
        : role === "ADMIN"
          ? ADMIN_ITEMS
          : [];

  return (
    <nav
      className="w-56 flex-shrink-0 bg-[#12121a] border-r border-[#2a2a45] overflow-y-auto py-3"
      aria-label="Main navigation"
    >
      <div className="px-2 space-y-0.5">
        {ALL_ROLES.map((item) => (
          <SidebarLink key={item.to} {...item} />
        ))}

        {roleItems.length > 0 && <div className="border-t border-[#2a2a45] my-2" />}

        {roleItems.map((item) => (
          <SidebarLink key={item.to} {...item} />
        ))}
      </div>
    </nav>
  );
}
