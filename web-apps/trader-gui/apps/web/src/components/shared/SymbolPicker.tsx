import { useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { useSettingsStore } from "@/store/useSettingsStore.js";

export interface SymbolPickerProps {
  symbols: string[];
  value: string;
  onChange: (symbol: string) => void;
  /** Accessible label for the control (applied to the select or the search input). */
  label: string;
}

/**
 * Symbol picker for the Trading Workspace header (and anywhere else a single
 * symbol needs choosing from the full loaded list). A plain <select> is fine
 * for a handful of symbols but unusable once a venue lists 100+ — so this
 * renders either that <select> or a type-to-filter combobox, chosen by
 * `symbolPickerMode`/`symbolPickerThreshold` in useSettingsStore (configurable
 * in the Settings cog-wheel menu).
 */
export function SymbolPicker({ symbols, value, onChange, label }: SymbolPickerProps) {
  const mode = useSettingsStore((s) => s.symbolPickerMode);
  const threshold = useSettingsStore((s) => s.symbolPickerThreshold);

  const useSearch = mode === "search" || (mode === "auto" && symbols.length >= threshold);

  if (useSearch) {
    return <SearchSymbolPicker symbols={symbols} value={value} onChange={onChange} label={label} />;
  }

  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      aria-label={label}
      className="bg-raised border border-line rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[#3a3a60]"
    >
      {symbols.map((s) => (
        <option key={s} value={s}>
          {s}
        </option>
      ))}
    </select>
  );
}

function SearchSymbolPicker({ symbols, value, onChange, label }: SymbolPickerProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const matches = useMemo(() => {
    const q = query.trim().toUpperCase();
    return q === "" ? symbols : symbols.filter((s) => s.includes(q));
  }, [symbols, query]);

  useEffect(() => {
    setActiveIndex((i) => (matches.length === 0 ? 0 : Math.min(i, matches.length - 1)));
  }, [matches.length]);

  // Click-away close.
  useEffect(() => {
    if (!open) return;
    const onDocMouseDown = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [open]);

  const openList = () => {
    setQuery("");
    setActiveIndex(0);
    setOpen(true);
    // Focus after the input mounts/becomes visible.
    requestAnimationFrame(() => inputRef.current?.focus());
  };

  const select = (symbol: string) => {
    onChange(symbol);
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(matches.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const symbol = matches[activeIndex];
      if (symbol) select(symbol);
    } else if (e.key === "Escape") {
      e.preventDefault();
      setOpen(false);
    }
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => (open ? setOpen(false) : openList())}
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex items-center gap-1.5 bg-raised border border-line rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-[#3a3a60]"
      >
        <Search size={11} className="text-fg-faint" />
        <span>{value || "Select…"}</span>
      </button>

      {open && (
        <div
          role="listbox"
          aria-label={label}
          className="absolute left-0 top-full z-50 mt-1 w-56 overflow-hidden rounded border border-line bg-deep shadow-2xl"
        >
          <div className="flex items-center gap-1.5 border-b border-line px-2 py-1">
            <Search size={11} className="text-fg-faint" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setActiveIndex(0);
              }}
              onKeyDown={onKeyDown}
              aria-label={`Filter ${label.toLowerCase()}`}
              placeholder="Type to filter…"
              className="w-full bg-transparent text-xs text-fg placeholder:text-fg-faint focus:outline-none"
            />
          </div>
          <ul className="max-h-56 overflow-auto py-1">
            {matches.length === 0 && (
              <li className="px-2 py-3 text-center text-xs text-fg-faint">No matches.</li>
            )}
            {matches.map((s, i) => (
              <li
                key={s}
                role="option"
                aria-selected={s === value}
                onMouseEnter={() => setActiveIndex(i)}
                onClick={() => select(s)}
                className={`cursor-pointer px-2 py-1 font-mono text-xs ${
                  i === activeIndex ? "bg-elevated text-fg" : "text-fg-soft hover:bg-raised"
                }`}
              >
                {s}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
