import { create } from "zustand";
import type { GatewayRole } from "@/types/index.js";

export interface AuthState {
  apiKey: string | null;
  gatewayId: string | null;
  role: GatewayRole | null;
  /** Number of connected gateways — present only for ADMIN keys (§6.2). */
  gatewayCount: number | null;
  login: (key: string, gatewayId: string, role: GatewayRole, gatewayCount?: number) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  apiKey: null,
  gatewayId: null,
  role: null,
  gatewayCount: null,

  login: (key, gatewayId, role, gatewayCount) =>
    set({ apiKey: key, gatewayId, role, gatewayCount: gatewayCount ?? null }),

  logout: () => set({ apiKey: null, gatewayId: null, role: null, gatewayCount: null }),
}));
