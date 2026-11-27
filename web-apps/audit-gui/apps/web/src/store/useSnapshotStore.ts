/**
 * The pinned evidence snapshot every workspace reads (design §7.2), held in
 * memory like the key: a reload starts again from the collection picker. A
 * snapshot is named by id only; its descriptor comes from the API.
 */
import { create } from "zustand";

interface SnapshotState {
  collectionId: string | null;
  snapshotId: string | null;
  select: (collectionId: string, snapshotId: string) => void;
  clear: () => void;
}

export const useSnapshotStore = create<SnapshotState>((set) => ({
  collectionId: null,
  snapshotId: null,
  select: (collectionId, snapshotId) => set({ collectionId, snapshotId }),
  clear: () => set({ collectionId: null, snapshotId: null }),
}));
