import { useState } from "react";
import { Settings } from "lucide-react";
import { FONT_SIZE_ORDER, useFontSizeStore } from "../../store/useFontSizeStore.js";
import { MAX_LEVELS_ORDER, usePrefsStore } from "../../store/usePrefsStore.js";

const radio = (checked: boolean) =>
  `flex-1 rounded px-1 py-1 text-[10px] font-medium ${
    checked ? "bg-accent text-accent-fg" : "bg-bg-inset text-fg-subtle hover:bg-bg-subtle"
  }`;

/**
 * Settings popover (design §9.7): terminal-gui's font-size control, plus the
 * two pm-viewer options that still mean something in a browser — zebra rows
 * (`--zebra-lines`) and a cap on the levels shown (`--depth`).
 */
export function SettingsPopover() {
  const [open, setOpen] = useState(false);
  const fontSize = useFontSizeStore((s) => s.fontSize);
  const setFontSize = useFontSizeStore((s) => s.setFontSize);
  const zebra = usePrefsStore((s) => s.zebra);
  const setZebra = usePrefsStore((s) => s.setZebra);
  const maxLevels = usePrefsStore((s) => s.maxLevels);
  const setMaxLevels = usePrefsStore((s) => s.setMaxLevels);

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
                  className={radio(fontSize === size)}
                >
                  {size}
                </button>
              ))}
            </div>
            <p className="mt-1.5 text-[10px] text-fg-faint">Works in Chrome and Safari only.</p>

            <span className="mt-3 block text-xs text-fg">Max levels</span>
            <div role="radiogroup" aria-label="Max levels" className="mt-1.5 flex gap-1">
              {MAX_LEVELS_ORDER.map((levels) => (
                <button
                  key={levels}
                  type="button"
                  role="radio"
                  aria-checked={maxLevels === levels}
                  onClick={() => setMaxLevels(levels)}
                  className={radio(maxLevels === levels)}
                >
                  {levels === "fit" ? "Fit" : levels}
                </button>
              ))}
            </div>

            <label className="mt-3 flex items-center justify-between text-xs text-fg">
              Zebra rows
              <button
                type="button"
                role="switch"
                aria-label="Zebra rows"
                aria-checked={zebra}
                onClick={() => setZebra(!zebra)}
                className={`h-4 w-8 rounded-full p-0.5 ${zebra ? "bg-accent" : "bg-bg-inset"}`}
              >
                <span
                  className={`block h-3 w-3 rounded-full bg-fg transition-transform ${zebra ? "translate-x-4" : ""}`}
                />
              </button>
            </label>
          </div>
        </>
      )}
    </div>
  );
}
