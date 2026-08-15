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

  /** Help drawer (§19.1). Shares the right edge with the Event Center. */
  helpOpen: boolean;
  toggleHelp: () => void;
  closeHelp: () => void;

  /** Keyboard shortcut reference dialog (§19.4) — a modal, independent overlay. */
  shortcutsOpen: boolean;
  toggleShortcuts: () => void;
  closeShortcuts: () => void;

  /** Command palette (§21.1) — a modal, independent overlay. */
  commandPaletteOpen: boolean;
  toggleCommandPalette: () => void;
  closeCommandPalette: () => void;
}

export const useUiStore = create<UiStore>((set) => ({
  // Only one right-edge sheet (Event Center, Help) is open at a time.
  eventCenterOpen: false,
  toggleEventCenter: () => set((s) => ({ eventCenterOpen: !s.eventCenterOpen, helpOpen: false })),
  closeEventCenter: () => set({ eventCenterOpen: false }),

  orderDetailId: null,
  openOrderDetail: (orderId) =>
    set({ orderDetailId: orderId, eventCenterOpen: false, helpOpen: false }),
  closeOrderDetail: () => set({ orderDetailId: null }),

  helpOpen: false,
  toggleHelp: () => set((s) => ({ helpOpen: !s.helpOpen, eventCenterOpen: false })),
  closeHelp: () => set({ helpOpen: false }),

  shortcutsOpen: false,
  toggleShortcuts: () => set((s) => ({ shortcutsOpen: !s.shortcutsOpen })),
  closeShortcuts: () => set({ shortcutsOpen: false }),

  commandPaletteOpen: false,
  toggleCommandPalette: () => set((s) => ({ commandPaletteOpen: !s.commandPaletteOpen })),
  closeCommandPalette: () => set({ commandPaletteOpen: false }),
}));
