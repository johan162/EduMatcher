import { create } from "zustand";

/**
 * App-level overlay state (§20). Two right-edge overlays share one tiny store
 * so the top-bar bell, the Event Center, and any deep-link (e.g. a fill entry
 * opening the Order Detail drawer) all read one source of truth without prop
 * drilling. The Order Detail drawer is rendered once in the AppShell and driven
 * by `orderDetailId`, so it can be opened from the blotter, Trade History, and
 * the Event Center alike.
 */
interface UiStore {
  eventCenterOpen: boolean;
  toggleEventCenter: () => void;
  closeEventCenter: () => void;

  /** Order id whose lifecycle drawer is open, or null. */
  orderDetailId: string | null;
  /** Open the Order Detail drawer; closes the Event Center so they never stack. */
  openOrderDetail: (orderId: string) => void;
  closeOrderDetail: () => void;
}

export const useUiStore = create<UiStore>((set) => ({
  eventCenterOpen: false,
  toggleEventCenter: () => set((s) => ({ eventCenterOpen: !s.eventCenterOpen })),
  closeEventCenter: () => set({ eventCenterOpen: false }),

  orderDetailId: null,
  openOrderDetail: (orderId) => set({ orderDetailId: orderId, eventCenterOpen: false }),
  closeOrderDetail: () => set({ orderDetailId: null }),
}));
