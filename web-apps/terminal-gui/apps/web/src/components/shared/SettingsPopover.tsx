import { useState } from "react";
import { Settings } from "lucide-react";
import { FONT_SIZE_ORDER, useFontSizeStore } from "../../store/useFontSizeStore.js";

/**
 * Settings popover in the top bar: the font-size control, which zoom-scales
 * the whole app (see useFontSizeStore). Density and theme have their own
 * dedicated TopBar buttons already, so this popover is font-size only.
 */
export function SettingsPopover() {
  const [open, setOpen] = useState(false);
  const fontSize = useFontSizeStore((s) => s.fontSize);
  const setFontSize = useFontSizeStore((s) => s.setFontSize);

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Settings"
        aria-expanded={open}
        className="rounded p-1.5 text-fg-subtle hover:bg-bg-inset hover:text-fg"
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
            className="absolute right-0 top-8 z-50 w-64 rounded border border-border bg-bg-raised p-3 shadow-2xl"
          >
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-fg-faint">Settings</h3>

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
                      ? "bg-accent text-accent-fg"
                      : "bg-bg-inset text-fg-subtle hover:bg-bg-subtle"
                  }`}
                >
                  {size}
                </button>
              ))}
            </div>
            <p className="mt-1.5 text-[10px] text-fg-faint">Works in Chrome and Safari only.</p>
          </div>
        </>
      )}
    </div>
  );
}
