/**
 * Symbol switcher (design §9.5) — pm-viewer's picker, in a browser.
 *
 * `s` or `F1` anywhere opens it, typing narrows the list by *prefix*, ↑/↓
 * move, Enter switches, Esc closes. A click works too. Switching is a route
 * change, so every book has a URL.
 */

import clsx from "clsx";
import { ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useBookStore } from "../store/useBookStore.js";

/** The characters a symbol can contain — pm-viewer's `_FILTER_CHARS`. */
const FILTER_CHARS = /^[A-Z0-9._-]$/;

/** pm-viewer's rule: prefix, not substring — "A" offers what starts with A. */
export function matches(symbols: readonly string[], query: string): string[] {
  const sorted = [...new Set(symbols)].sort();
  return query ? sorted.filter((s) => s.startsWith(query)) : sorted;
}

function typingInField(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && (target.tagName === "INPUT" || target.tagName === "TEXTAREA");
}

export function SymbolPicker() {
  const symbols = useBookStore((s) => s.symbols);
  const watched = useBookStore((s) => s.watched);
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const list = matches(
    symbols.map((s) => s.symbol),
    query,
  );
  const selected = list[Math.min(index, list.length - 1)];

  const show = () => {
    setQuery("");
    setIndex(0);
    setOpen(true);
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (open || typingInField(e.target)) return;
      if (e.key === "s" || e.key === "S" || e.key === "F1") {
        e.preventDefault();
        show();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const choose = (sym: string | undefined) => {
    setOpen(false);
    if (sym && sym !== watched) navigate(`/book/${sym}`);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") setOpen(false);
    else if (e.key === "Enter") choose(selected);
    else if (e.key === "ArrowDown") setIndex((i) => Math.min(i + 1, Math.max(list.length - 1, 0)));
    else if (e.key === "ArrowUp") setIndex((i) => Math.max(i - 1, 0));
    else if (e.key === "Backspace") {
      setQuery((q) => q.slice(0, -1));
      setIndex(0);
    } else if (FILTER_CHARS.test(e.key.toUpperCase()) && e.key.length === 1) {
      setQuery((q) => q + e.key.toUpperCase());
      setIndex(0);
    } else return;
    e.preventDefault();
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={show}
        title="Change symbol (s / F1)"
        aria-label="Change symbol"
        className="flex items-center gap-2 rounded border border-border bg-bg-raised px-3 py-1 font-mono text-sm font-bold text-fg hover:bg-bg-inset"
      >
        {watched ?? "—"}
        <ChevronDown size={14} className="text-fg-subtle" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} aria-hidden="true" />
          <div
            role="dialog"
            aria-label="Choose symbol"
            className="absolute left-0 top-9 z-50 w-56 rounded border border-border bg-bg-raised p-2 shadow-2xl"
          >
            <input
              ref={inputRef}
              aria-label="Filter symbols"
              value={query}
              readOnly
              onKeyDown={onKeyDown}
              placeholder="type to filter"
              className="w-full rounded border border-border bg-bg-inset px-2 py-1 font-mono text-sm text-fg outline-none placeholder:text-fg-faint"
            />
            <ul role="listbox" aria-label="Symbols" className="mt-2 max-h-72 overflow-auto">
              {symbols.length === 0 && <li className="px-2 py-1 text-xs text-fg-faint">loading…</li>}
              {symbols.length > 0 && list.length === 0 && (
                <li className="px-2 py-1 text-xs text-fg-faint">no match</li>
              )}
              {list.map((sym) => (
                <li
                  key={sym}
                  role="option"
                  aria-selected={sym === selected}
                  onClick={() => choose(sym)}
                  className={clsx(
                    "cursor-pointer rounded px-2 py-1 font-mono text-sm",
                    sym === selected ? "bg-accent text-accent-fg" : "text-fg hover:bg-bg-inset",
                    sym === watched && sym !== selected && "text-accent",
                  )}
                >
                  {sym}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-[10px] text-fg-faint">↑/↓ move · Enter switch · Esc close</p>
          </div>
        </>
      )}
    </div>
  );
}
