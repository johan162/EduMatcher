import { useState } from "react";
import { Settings } from "lucide-react";
import { FONT_SIZE_ORDER, useFontSizeStore } from "../../store/useFontSizeStore.js";
import { usePrefsStore, type StatColorMode, type ThemePreference } from "../../store/usePrefsStore.js";

const THEMES: { value: ThemePreference; label: string }[] = [
  { value: "dark", label: "Dark" },
  { value: "light", label: "Light" },
];

const STAT_MODES: { value: StatColorMode; label: string }[] = [
  { value: "value", label: "Value" },
  { value: "background", label: "Background" },
];

const radio = (checked: boolean) =>
  `flex-1 rounded px-1 py-1 text-[10px] font-medium ${
    checked ? "bg-accent text-accent-fg" : "bg-bg-inset text-fg-subtle hover:bg-bg-subtle"
  }`;

/**
 * Settings popover (design D1.5): theme, terminal-gui's font-size control,
 * and how stat tiles show their threshold colour. All remembered per browser.
 */
export function SettingsPopover() {
  const [open, setOpen] = useState(false);
  const fontSize = useFontSizeStore((s) => s.fontSize);
  const setFontSize = useFontSizeStore((s) => s.setFontSize);
  const theme = usePrefsStore((s) => s.theme);
  const setTheme = usePrefsStore((s) => s.setTheme);
  const statColorMode = usePrefsStore((s) => s.statColorMode);
  const setStatColorMode = usePrefsStore((s) => s.setStatColorMode);

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

            <span className="text-xs text-fg">Theme</span>
            <div role="radiogroup" aria-label="Theme" className="mb-3 mt-1.5 flex gap-1">
              {THEMES.map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={theme === value}
                  onClick={() => setTheme(value)}
                  className={radio(theme === value)}
                >
                  {label}
                </button>
              ))}
            </div>

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

            <span className="mt-3 block text-xs text-fg">Stat tiles colour the</span>
            <div role="radiogroup" aria-label="Stat tile colour" className="mt-1.5 flex gap-1">
              {STAT_MODES.map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  role="radio"
                  aria-checked={statColorMode === value}
                  onClick={() => setStatColorMode(value)}
                  className={radio(statColorMode === value)}
                >
                  {label}
                </button>
              ))}
            </div>

          </div>
        </>
      )}
    </div>
  );
}
