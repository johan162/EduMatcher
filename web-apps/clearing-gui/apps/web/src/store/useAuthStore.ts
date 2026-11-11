/**
 * Who is logged in. The API key is held in memory only -- never written to
 * browser storage -- so a reload returns to the login page (as in
 * trader-gui). The role is the engine's, as `GET /api/v1/status` reported it;
 * it decides which screens are offered, while the API enforces what each key
 * may actually read.
 */
import { create } from "zustand";

export type Role = "TRADER" | "MARKET_MAKER" | "ADMIN";

export interface AuthState {
  apiKey: string | null;
  gatewayId: string | null;
  role: Role | null;
  login: (apiKey: string, gatewayId: string, role: Role) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  apiKey: null,
  gatewayId: null,
  role: null,
  login: (apiKey, gatewayId, role) => set({ apiKey, gatewayId, role }),
  logout: () => set({ apiKey: null, gatewayId: null, role: null }),
}));
