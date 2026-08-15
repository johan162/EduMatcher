import { Navigate, Outlet } from "react-router-dom";
import { useAuthStore } from "@/store/useAuthStore.js";
import type { GatewayRole } from "@/types/index.js";

interface RoleGuardProps {
  roles: GatewayRole[];
}

/**
 * Wraps a set of routes and redirects to /login when unauthenticated, or to
 * the root (role landing) when the current role is not in the allowed list.
 * This is a presentation-layer guard only — the API enforces authorisation
 * server-side.
 */
export function RoleGuard({ roles }: RoleGuardProps) {
  const role = useAuthStore((s) => s.role);
  const apiKey = useAuthStore((s) => s.apiKey);

  if (!apiKey || !role) {
    return <Navigate to="/login" replace />;
  }

  if (!roles.includes(role)) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}
