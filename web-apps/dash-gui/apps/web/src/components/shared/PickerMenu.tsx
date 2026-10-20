/**
 * A top-bar button that opens a list of choices (the time picker and the
 * refresh selector, design §12.2). Closes on a choice, a click outside or
 * Escape.
 */

import { useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";
import clsx from "clsx";

interface PickerMenuProps<T extends string> {
  /** Accessible name of the button and the list, e.g. "Time range". */
  name: string;
  icon: ReactNode;
  value: T;
  options: readonly T[];
  /** Text of an option in the list. */
  optionLabel: (option: T) => string;
  /** Text on the button for the current value. */
  valueLabel: (value: T) => string;
  onSelect: (option: T) => void;
}

export function PickerMenu<T extends string>({
  name,
  icon,
  value,
  options,
  optionLabel,
  valueLabel,
  onSelect,
}: PickerMenuProps<T>) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative" onKeyDown={(e) => e.key === "Escape" && setOpen(false)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={`${name}: ${optionLabel(value)}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded px-2 py-1 text-xs text-fg-subtle hover:bg-bg-inset hover:text-fg"
      >
        {icon}
        <span className="tabular">{valueLabel(value)}</span>
        <ChevronDown size={12} />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} aria-hidden="true" />
          <ul
            role="listbox"
            aria-label={name}
            className="absolute right-0 top-8 z-50 min-w-40 rounded border border-border bg-bg-raised py-1 shadow-2xl"
          >
            {options.map((option) => (
              <li
                key={option}
                role="option"
                aria-selected={option === value}
                tabIndex={0}
                onClick={() => {
                  onSelect(option);
                  setOpen(false);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(option);
                    setOpen(false);
                  }
                }}
                className={clsx(
                  "cursor-pointer px-3 py-1 text-xs hover:bg-bg-inset",
                  option === value ? "font-semibold text-accent" : "text-fg",
                )}
              >
                {optionLabel(option)}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
