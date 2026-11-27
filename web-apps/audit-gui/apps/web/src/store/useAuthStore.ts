/**
 * Who is logged in. The API key is held in memory only -- never written to
 * browser storage -- so a reload returns to the login page (as in
 * clearing-gui). Only an ADMIN key is ever stored: every audit route is
 * ADMIN-only, and the API enforces it.
 */
import { create } from "zustand";
import { useSnapshotStore } from "@/store/useSnapshotStore";

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
  logout: () => {
    useSnapshotStore.getState().clear();
    set({ apiKey: null, gatewayId: null, role: null });
  },
}));
