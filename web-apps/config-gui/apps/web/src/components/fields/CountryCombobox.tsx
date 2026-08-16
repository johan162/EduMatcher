import { useMemo, useRef, useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import clsx from "clsx";
import { COUNTRIES, type CountryOption } from "@edumatcher/schema";

/** Minimum characters typed before suggestions appear (avoids a 250-row list on focus). */
const MIN_CHARS_FOR_SUGGESTIONS = 3;
/** Cap the visible suggestion list so it never grows into an unscrollable wall. */
const MAX_SUGGESTIONS = 8;

interface Props {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  "aria-label"?: string;
}

function matches(option: CountryOption, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return false;
  return (
    option.name.toLowerCase().includes(q) ||
    option.code.toLowerCase() === q.toUpperCase()
  );
}

/**
 * Free-text country field with typeahead suggestions.
 *
 * Any text the user types is accepted verbatim (matching pm-scheduler's own
 * tolerant behaviour -- an unrecognised value just falls back to Sweden at
 * runtime rather than blocking input here). Suggestions from the bundled
 * python-holidays country list appear once at least
 * MIN_CHARS_FOR_SUGGESTIONS characters are typed, and picking one commits its
 * ISO 3166-1 alpha-2 code (the unambiguous form -- see countries.ts).
 */
export function CountryCombobox({
  id,
  value,
  onChange,
  placeholder,
  disabled,
  className,
  ...rest
}: Props) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const suggestions = useMemo(() => {
    if (value.trim().length < MIN_CHARS_FOR_SUGGESTIONS) return [];
    return COUNTRIES.filter((c) => matches(c, value)).slice(0, MAX_SUGGESTIONS);
  }, [value]);

  const showSuggestions = open && suggestions.length > 0;

  const commit = (option: CountryOption) => {
    onChange(option.code);
    setOpen(false);
    setActiveIndex(0);
    inputRef.current?.focus();
  };

  return (
    <Popover.Root open={showSuggestions}>
      <Popover.Anchor asChild>
        <input
          ref={inputRef}
          id={id}
          type="text"
          role="combobox"
          aria-expanded={showSuggestions}
          aria-autocomplete="list"
          aria-label={rest["aria-label"]}
          value={value}
          placeholder={placeholder}
          disabled={disabled}
          autoComplete="off"
          onChange={(e) => {
            onChange(e.target.value);
            setOpen(true);
            setActiveIndex(0);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          onKeyDown={(e) => {
            if (!showSuggestions) return;
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActiveIndex((i) => Math.min(i + 1, suggestions.length - 1));
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setActiveIndex((i) => Math.max(i - 1, 0));
            } else if (e.key === "Enter") {
              e.preventDefault();
              const chosen = suggestions[activeIndex];
              if (chosen) commit(chosen);
            } else if (e.key === "Escape") {
              setOpen(false);
            }
          }}
          className={clsx(
            "h-9 w-64 rounded-md border border-border bg-surface px-3 text-sm text-fg",
            "placeholder:text-optional-default",
            "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent",
            disabled && "cursor-not-allowed opacity-50",
            className,
          )}
        />
      </Popover.Anchor>
      <Popover.Portal>
        <Popover.Content
          onOpenAutoFocus={(e) => e.preventDefault()}
          onCloseAutoFocus={(e) => e.preventDefault()}
          sideOffset={4}
          align="start"
          className="z-50 w-64 overflow-hidden rounded-md border border-border bg-surface-raised shadow-lg"
        >
          <ul role="listbox" className="max-h-56 overflow-y-auto p-1">
            {suggestions.map((option, i) => (
              <li
                key={option.code}
                role="option"
                aria-selected={i === activeIndex}
              >
                <button
                  type="button"
                  // onMouseDown (not onClick) fires before the input's onBlur closes the popover.
                  onMouseDown={(e) => {
                    e.preventDefault();
                    commit(option);
                  }}
                  onMouseEnter={() => setActiveIndex(i)}
                  className={clsx(
                    "flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm",
                    i === activeIndex && "bg-accent text-accent-fg",
                  )}
                >
                  <span>{option.name}</span>
                  <span className="text-xs text-fg-subtle">{option.code}</span>
                </button>
              </li>
            ))}
          </ul>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
