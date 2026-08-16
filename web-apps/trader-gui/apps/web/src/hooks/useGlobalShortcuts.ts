import { useHotkeys } from "react-hotkeys-hook";
import { useNavigate } from "react-router-dom";
import { useUiStore } from "@/store/useUiStore.js";
import { useAuthStore } from "@/store/useAuthStore.js";

/**
 * Global navigation / action shortcuts (§21), mounted once at the app root.
 * Complements the shortcuts that live where their behaviour does (`B`/`S`/`F1`
 * in the ticket, `Ctrl+/`/`?` in the help hook, blotter row keys, `F2` on the
 * quote screen).
 *
 *  - `Ctrl+K` — command palette (works even while a field has focus).
 *  - `Ctrl+.` — toggle the Notification / Event Center.
 *  - `Ctrl+L` — Watchlist.
 *  - `F3` — Positions (TRADER / MM).
 *  - `F4` — Active Orders blotter (TRADER).
 *  - `Ctrl+Shift+F` — Flatten All → the Positions screen (where the always-confirm
 *    flatten-all dialog lives).
 *
 * Role is read fresh from the store inside each handler so a role change does
 * not leave a stale binding. Note: `Ctrl+L` (and to a lesser extent `F3`) are
 * also browser shortcuts; `preventDefault` wins when the app has focus.
 */
export function useGlobalShortcuts(): void {
  const navigate = useNavigate();
  const toggleCommandPalette = useUiStore((s) => s.toggleCommandPalette);
  const toggleEventCenter = useUiStore((s) => s.toggleEventCenter);

  const opts = { enableOnFormTags: true, preventDefault: true } as const;

  useHotkeys("ctrl+k", () => toggleCommandPalette(), opts);
  useHotkeys("ctrl+.", () => toggleEventCenter(), opts);
  useHotkeys("ctrl+l", () => navigate("/watchlist"), opts);

  useHotkeys(
    "f3",
    () => {
      const role = useAuthStore.getState().role;
      if (role === "TRADER" || role === "MARKET_MAKER") navigate("/positions");
    },
    opts,
  );

  useHotkeys(
    "f4",
    () => {
      if (useAuthStore.getState().role === "TRADER") navigate("/orders");
    },
    opts,
  );

  useHotkeys(
    "ctrl+shift+f",
    () => {
      const role = useAuthStore.getState().role;
      if (role === "TRADER" || role === "MARKET_MAKER") navigate("/positions");
    },
    opts,
  );
}
