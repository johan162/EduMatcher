/**
 * A text input with a searchable list of known values (ARIA 1.2 combobox,
 * list autocomplete), for the Gateway / Symbol / Account filters (CG22).
 *
 * Typing narrows the list (case-insensitive, anywhere in the value); Up/Down
 * move through it, Enter or a click picks, Escape closes it and keeps the
 * text. The input stays free text: a value that is not listed is still a
 * valid filter (a gateway that connected but never traded, say), and empty
 * means All. Enter with no list item active submits the form, as before.
 */
import { useState, type KeyboardEvent } from "react";

interface ComboboxProps {
  id: string;
  value: string;
  options: string[];
  placeholder?: string;
  onChange: (value: string) => void;
}

export function Combobox({ id, value, options, placeholder = "All", onChange }: ComboboxProps) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const listId = `${id}-list`;
  const needle = value.trim().toUpperCase();
  const matches = options.filter((o) => o.toUpperCase().includes(needle));
  const shown = open && matches.length > 0;

  function pick(option: string) {
    onChange(option);
    setOpen(false);
    setActive(-1);
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!shown) {
        setOpen(true);
        setActive(0);
      } else {
        setActive((a) => Math.min(a + 1, matches.length - 1));
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter" && shown && active >= 0) {
      e.preventDefault();
      pick(matches[active]!);
    } else if (e.key === "Escape" && shown) {
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
      setActive(-1);
    }
  }

  return (
    <div className="relative">
      <input
        id={id}
        type="text"
        role="combobox"
        autoComplete="off"
        aria-autocomplete="list"
        aria-expanded={shown}
        aria-controls={shown ? listId : undefined}
        aria-activedescendant={shown && active >= 0 ? `${listId}-${active}` : undefined}
        value={value}
        placeholder={placeholder}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
          setActive(-1);
        }}
        onKeyDown={onKeyDown}
        onBlur={() => setOpen(false)}
        className="w-40 rounded border border-line bg-raised px-2 py-1 text-xs"
      />
      {shown && (
        <ul
          id={listId}
          role="listbox"
          aria-label="Suggestions"
          className="absolute left-0 top-full z-20 mt-0.5 max-h-60 w-40 overflow-y-auto rounded border border-line bg-panel py-0.5 text-xs shadow-lg"
        >
          {matches.map((option, i) => (
            <li
              key={option}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              // mousedown, not click: the pick happens before the input blurs.
              onMouseDown={(e) => {
                e.preventDefault();
                pick(option);
              }}
              className={`cursor-pointer px-2 py-0.5 font-mono ${i === active ? "bg-accent text-accent-fg" : "hover:bg-raised"}`}
            >
              {option}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
