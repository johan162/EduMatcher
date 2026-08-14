import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Search, Star } from "lucide-react";
import { useUiStore } from "@/store/useUiStore.js";
import { useAuthStore } from "@/store/useAuthStore.js";
import { useSymbolStore } from "@/store/useSymbolStore.js";
import { useBookStore } from "@/store/useBookStore.js";
import { useWatchlistStore } from "@/store/useWatchlistStore.js";
import { useSymbolDetailStore } from "@/store/useSymbolDetailStore.js";
import { actionCommandsForRole, filterByLabel, type ActionCommand } from "@/lib/commandItems.js";
import { formatPrice } from "@/lib/formatters.js";

const MAX_SYMBOLS = 8;

type FlatItem =
  | { kind: "symbol"; id: string; symbol: string; last: number | null; tickDecimals: number; watched: boolean }
  | { kind: "action"; id: string; command: ActionCommand };

/**
 * Command palette (§21.1) — `Ctrl+K`. Keyboard-first fuzzy search over symbols
 * and role-aware actions: type to filter, ↑/↓ to move, Enter to run, Escape to
 * close. Selecting a symbol sets the active symbol and opens Symbol Detail; the
 * star toggles watchlist membership; actions navigate or fire a UI toggle. This
 * is the backbone of mouse-free navigation.
 */
export function CommandPalette() {
  const close = useUiStore((s) => s.closeCommandPalette);
  const toggleEventCenter = useUiStore((s) => s.toggleEventCenter);
  const toggleHelp = useUiStore((s) => s.toggleHelp);
  const toggleShortcuts = useUiStore((s) => s.toggleShortcuts);
  const role = useAuthStore((s) => s.role);
  const symbols = useSymbolStore((s) => s.symbols);
  const watchlist = useWatchlistStore((s) => s.symbols);
  const toggleWatch = useWatchlistStore((s) => s.toggle);
  const openSymbolDetail = useSymbolDetailStore((s) => s.open);
  const navigate = useNavigate();

  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const items = useMemo<FlatItem[]>(() => {
    const q = query.trim().toUpperCase();
    const books = useBookStore.getState().books;
    const watched = new Set(watchlist);
    const symbolItems: FlatItem[] = symbols
      .filter((s) => q === "" || s.symbol.includes(q))
      .slice(0, MAX_SYMBOLS)
      .map((s) => ({
        kind: "symbol",
        id: `sym-${s.symbol}`,
        symbol: s.symbol,
        last: books[s.symbol]?.lastPrice ?? null,
        tickDecimals: books[s.symbol]?.tickDecimals ?? s.tick_decimals ?? 2,
        watched: watched.has(s.symbol),
      }));
    const actionItems: FlatItem[] = filterByLabel(actionCommandsForRole(role), query).map((c) => ({
      kind: "action",
      id: c.id,
      command: c,
    }));
    return [...symbolItems, ...actionItems];
  }, [query, symbols, watchlist, role]);

  // Keep the highlight in range as the filtered list changes.
  useEffect(() => {
    setActiveIndex((i) => (items.length === 0 ? 0 : Math.min(i, items.length - 1)));
  }, [items.length]);

  const runAction = (command: ActionCommand) => {
    switch (command.kind) {
      case "navigate":
        if (command.to) navigate(command.to);
        break;
      case "toggle-event-center":
        toggleEventCenter();
        break;
      case "toggle-help":
        toggleHelp();
        break;
      case "open-shortcuts":
        toggleShortcuts();
        break;
      case "flatten-all":
        // Flatten All lives on the Positions screen (needs the positions list +
        // its always-confirm dialog); the command takes the operator there.
        navigate("/positions");
        break;
    }
  };

  const run = (item: FlatItem) => {
    if (item.kind === "symbol") openSymbolDetail(item.symbol);
    else runAction(item.command);
    close();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(items.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = items[activeIndex];
      if (item) run(item);
    } else if (e.key === "Escape") {
      e.preventDefault();
      close();
    }
  };

  // Track where the ACTIONS group starts, to render a divider/header once.
  const firstActionIndex = items.findIndex((i) => i.kind === "action");

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center bg-black/50 pt-[12vh]"
      onClick={close}
    >
      <div
        role="dialog"
        aria-label="Command palette"
        className="w-[560px] max-w-[92vw] overflow-hidden rounded border border-[#2a2a45] bg-[#0d0d14] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-[#2a2a45] px-3 py-2">
          <Search size={14} className="text-[#505070]" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActiveIndex(0);
            }}
            onKeyDown={onKeyDown}
            aria-label="Search symbols and actions"
            placeholder="Search symbols, actions…"
            className="w-full bg-transparent text-sm text-[#e8e8f0] placeholder:text-[#505070] focus:outline-none"
          />
        </div>

        <ul role="listbox" aria-label="Results" className="max-h-[50vh] overflow-auto py-1">
          {items.length === 0 && (
            <li className="px-3 py-6 text-center text-xs text-[#505070]">No matches.</li>
          )}
          {items.map((item, i) => {
            const active = i === activeIndex;
            const showSymbolsHeader = i === 0 && item.kind === "symbol";
            const showActionsHeader = i === firstActionIndex && item.kind === "action";
            return (
              <div key={item.id}>
                {showSymbolsHeader && (
                  <li className="px-3 pb-0.5 pt-1 text-[9px] font-semibold uppercase tracking-wide text-[#505070]">
                    Symbols
                  </li>
                )}
                {showActionsHeader && (
                  <li className="px-3 pb-0.5 pt-1 text-[9px] font-semibold uppercase tracking-wide text-[#505070]">
                    Actions
                  </li>
                )}
                <li
                  role="option"
                  aria-selected={active}
                  onMouseEnter={() => setActiveIndex(i)}
                  onClick={() => run(item)}
                  className={`flex cursor-pointer items-center gap-2 px-3 py-1.5 text-xs ${
                    active ? "bg-[#20203a] text-[#e8e8f0]" : "text-[#c8c8e0] hover:bg-[#1a1a28]"
                  }`}
                >
                  {item.kind === "symbol" ? (
                    <>
                      <button
                        type="button"
                        aria-label={item.watched ? `Unwatch ${item.symbol}` : `Watch ${item.symbol}`}
                        aria-pressed={item.watched}
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleWatch(item.symbol);
                        }}
                        className={item.watched ? "text-amber-400" : "text-[#505070] hover:text-[#9090b0]"}
                      >
                        <Star size={12} fill={item.watched ? "currentColor" : "none"} />
                      </button>
                      <span className="font-mono font-medium">{item.symbol}</span>
                      <span className="ml-auto font-mono text-[#9090b0]">
                        {item.last === null ? "—" : formatPrice(item.last, item.tickDecimals)}
                      </span>
                    </>
                  ) : (
                    <>
                      <span>{item.command.label}</span>
                      {item.command.keys && (
                        <kbd className="ml-auto rounded border border-[#2a2a45] bg-[#1a1a28] px-1 py-0.5 font-mono text-[9px] text-[#9090b0]">
                          {item.command.keys}
                        </kbd>
                      )}
                    </>
                  )}
                </li>
              </div>
            );
          })}
        </ul>

        <div className="border-t border-[#2a2a45] px-3 py-1.5 text-[9px] text-[#505070]">
          ↑↓ navigate · ↵ select · esc close
        </div>
      </div>
    </div>
  );
}
