import { useHotkeys } from "react-hotkeys-hook";
import { useUiStore } from "@/store/useUiStore.js";

/**
 * Global help shortcuts (§19). Mounted once at the app root:
 *  - `Ctrl+/` toggles the help drawer (works even while a field has focus).
 *  - `?` (Shift+/) opens the keyboard shortcut reference — only when focus is
 *    NOT in a text input, so typing "?" in a field is unaffected (§19.4).
 *
 * `F1` (focus the order ticket) already lives in the Order Ticket itself.
 */
export function useHelpKeyboard(): void {
  const toggleHelp = useUiStore((s) => s.toggleHelp);
  const toggleShortcuts = useUiStore((s) => s.toggleShortcuts);

  useHotkeys("ctrl+/", () => toggleHelp(), { enableOnFormTags: true, preventDefault: true });
  useHotkeys("shift+/", () => toggleShortcuts(), { enableOnFormTags: false, preventDefault: true });
}
