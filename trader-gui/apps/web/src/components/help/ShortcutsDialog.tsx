import { Modal } from "@/components/shared/Modal.js";
import { useUiStore } from "@/store/useUiStore.js";
import { ShortcutsTable } from "./ShortcutsTable.js";

/**
 * Keyboard shortcut reference dialog (§19.4). Opened by `?` (when not typing in
 * a field), dismissible with Escape (Modal handles it) or the close button.
 */
export function ShortcutsDialog() {
  const close = useUiStore((s) => s.closeShortcuts);
  return (
    <Modal title="Keyboard shortcuts" onClose={close} widthClass="w-[560px]">
      <div className="max-h-[70vh] overflow-auto">
        <ShortcutsTable />
      </div>
    </Modal>
  );
}
