import { useAuthStore } from "@/store/useAuthStore.js";
import type { GatewayRole } from "@/types/index.js";

/** Returns the current gateway role or null if unauthenticated. */
export function useRole(): GatewayRole | null {
  return useAuthStore((s) => s.role);
}

/** Returns true if the current role is one of the provided roles. */
export function useHasRole(...roles: GatewayRole[]): boolean {
  const role = useAuthStore((s) => s.role);
  return role !== null && roles.includes(role);
}
