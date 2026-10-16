import { useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";

export interface SymbolPickerProps {
  symbols: string[];
  value: string;
  onChange: (symbol: string) => void;
  /** Accessible label for the control, applied to the trigger and the filter input. */
  label: string;
  /** Trigger styling — the Symbol Detail header wants its large title look. */
  triggerClassName?: string;
}

/**
 * Searchable symbol combobox, mirroring pm-trader's Trading Workspace picker
 * (web-apps/trader-gui .../components/shared/SymbolPicker.tsx) so switching
 * symbols works the same way across both terminals.
 */
export function SymbolPicker({ symbols, value, onChange, label, triggerClassName }: SymbolPickerProps) {
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
        className={
          triggerClassName ??
          "flex items-center gap-1.5 rounded border border-border bg-surface px-2 py-1 text-xs font-mono hover:bg-muted"
        }
      >
        <Search size={11} className="text-fg-faint" />
        <span>{value || "Select…"}</span>
      </button>

      {open && (
        <div
          role="listbox"
          aria-label={label}
          className="absolute left-0 top-full z-50 mt-1 w-56 overflow-hidden rounded border border-border bg-surface shadow-2xl"
        >
          <div className="flex items-center gap-1.5 border-b border-border px-2 py-1">
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
              className="w-full bg-transparent text-xs placeholder:text-fg-faint focus:outline-none"
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
                  i === activeIndex ? "bg-muted" : "hover:bg-muted"
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
