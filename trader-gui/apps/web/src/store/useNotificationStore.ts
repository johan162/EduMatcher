import { create } from "zustand";

export type NotificationKind =
  | "ACK"
  | "FILL"
  | "REJECT"
  | "CANCEL"
  | "CB"
  | "SESSION"
  | "SYSTEM";

export interface NotificationEntry {
  id: string;
  ts: number; // Unix ms
  kind: NotificationKind;
  title: string;
  detail: string;
  read: boolean;
  /** Deep-links to Order Detail drawer when present. */
  orderId?: string;
}

const BUFFER_SIZE = 500;

interface NotificationStore {
  entries: NotificationEntry[];
  unread: number;
  push: (e: Omit<NotificationEntry, "id" | "read">) => void;
  markAllRead: () => void;
  clear: () => void;
}

let _seq = 0;

export const useNotificationStore = create<NotificationStore>((set) => ({
  entries: [],
  unread: 0,

  push: (e) =>
    set((s) => {
      const entry: NotificationEntry = {
        ...e,
        id: `notif-${Date.now()}-${++_seq}`,
        read: false,
      };
      const next = [entry, ...s.entries].slice(0, BUFFER_SIZE);
      return { entries: next, unread: s.unread + 1 };
    }),

  markAllRead: () =>
    set((s) => ({
      entries: s.entries.map((e) => ({ ...e, read: true })),
      unread: 0,
    })),

  clear: () => set({ entries: [], unread: 0 }),
}));
