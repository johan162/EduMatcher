import { Navigate, Outlet } from "react-router-dom";
import { useAuthStore, type Role } from "@/store/useAuthStore";

/**
 * Wraps a group of routes: to /login when nobody is logged in, to the role's
 * landing page when the role is not allowed. A convenience only -- a typed
 * URL that slipped past it would still be refused by the API
 * (`403 ROLE_DENIED` / `SCOPE_DENIED`), which is where scope is enforced.
 */
export function RoleGuard({ roles }: { roles: Role[] }) {
  const apiKey = useAuthStore((s) => s.apiKey);
  const role = useAuthStore((s) => s.role);
  if (!apiKey || !role) return <Navigate to="/login" replace />;
  if (!roles.includes(role)) return <Navigate to="/" replace />;
  return <Outlet />;
}

/** Where each role starts. */
export function landingPath(role: Role | null): string {
  if (role === "ADMIN") return "/overview";
  if (role === "TRADER" || role === "MARKET_MAKER") return "/me/positions";
  return "/login";
}
