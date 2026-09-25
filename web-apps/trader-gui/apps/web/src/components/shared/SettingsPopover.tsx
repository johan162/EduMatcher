import { useState } from "react";
import { Settings } from "lucide-react";
import { useSettingsStore } from "@/store/useSettingsStore.js";
import { FONT_SIZE_ORDER, useFontSizeStore } from "@/store/useFontSizeStore.js";

/**
 * Settings popover in the top bar (§20.3): the power-user toggle — "Confirm
 * order/quote cancellations" (default on; when off, reversible cancels skip
 * the dialog and use an undo-toast instead, always-confirm exceptions like
 * Flatten All and kill switch unaffected) — and the font-size control, which
 * zoom-scales the whole app (see useFontSizeStore).
 */
export function SettingsPopover() {
  const [open, setOpen] = useState(false);
  const confirmCancellations = useSettingsStore((s) => s.confirmCancellations);
  const toggle = useSettingsStore((s) => s.toggleConfirmCancellations);
  const fontSize = useFontSizeStore((s) => s.fontSize);
  const setFontSize = useFontSizeStore((s) => s.setFontSize);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Settings"
        aria-expanded={open}
        className="text-fg-dim hover:text-fg"
      >
        <Settings size={16} />
      </button>

      {open && (
        <>
          {/* Click-away backdrop */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} aria-hidden="true" />
          <div
            role="menu"
            aria-label="Settings"
            className="absolute right-0 top-7 z-50 w-72 rounded border border-line bg-panel p-3 shadow-2xl"
          >
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-fg-mute">
              Settings
            </h3>
            <label className="flex cursor-pointer items-start gap-2">
              <input
                type="checkbox"
                checked={confirmCancellations}
                onChange={toggle}
                aria-label="Confirm order and quote cancellations"
                className="mt-0.5"
              />
              <span className="flex flex-col">
                <span className="text-xs text-fg">Confirm cancellations</span>
                <span className="text-[10px] text-fg-dim">
                  When off (power-user), single-order cancels fire immediately with an undo-toast.
                  Flatten All and kill switches always confirm.
                </span>
              </span>
            </label>

            <div className="mt-3 border-t border-line pt-3">
              <span className="text-xs text-fg">Font size</span>
              <div role="radiogroup" aria-label="Font size" className="mt-1.5 flex gap-1">
                {FONT_SIZE_ORDER.map((size) => (
                  <button
                    key={size}
                    type="button"
                    role="radio"
                    aria-checked={fontSize === size}
                    onClick={() => setFontSize(size)}
                    className={`flex-1 rounded px-1 py-1 text-[10px] font-medium ${
                      fontSize === size
                        ? "bg-elevated text-fg"
                        : "bg-raised text-fg-dim hover:bg-elevated2"
                    }`}
                  >
                    {size}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
