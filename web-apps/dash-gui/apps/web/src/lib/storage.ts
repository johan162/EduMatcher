/**
 * `localStorage` for the persisted preference stores, where every access may
 * throw (a private window, storage disabled, the quota full) and none may
 * break the page (design D1.5). A preference that cannot be saved is simply
 * not remembered.
 */

import { createJSONStorage, type StateStorage } from "zustand/middleware";

const safeLocalStorage: StateStorage = {
  getItem: (name) => {
    try {
      return window.localStorage.getItem(name);
    } catch {
      return null;
    }
  },
  setItem: (name, value) => {
    try {
      window.localStorage.setItem(name, value);
    } catch {
      // not remembered
    }
  },
  removeItem: (name) => {
    try {
      window.localStorage.removeItem(name);
    } catch {
      // nothing to forget
    }
  },
};

export const prefsStorage = createJSONStorage(() => safeLocalStorage);
