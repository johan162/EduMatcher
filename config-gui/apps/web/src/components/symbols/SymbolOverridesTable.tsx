import { useMemo, useState } from "react";
import clsx from "clsx";
import {
  applyOverrideToMany,
  clearOverrides,
  selectOverridePage,
  type OverrideField,
  type SymbolOverrideRow,
} from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { fractionToPercent, percentToFraction } from "@/lib/format";
import { NumberInput } from "@/components/fields/inputs";
import { Switch } from "@/components/ui/Switch";
import { ColumnHead } from "@/components/ui/ColumnHead";

const PAGE_SIZES = [25, 50, 100];

/** Columns the bulk toolbar can set across a selection. */
const BULK_FIELDS: { value: OverrideField; label: string; kind: "pct" | "sec" | "bool" }[] = [
  { value: "staticBandPct", label: "Collar static %", kind: "pct" },
  { value: "dynamicBandPct", label: "Collar dynamic %", kind: "pct" },
  { value: "aceEnabled", label: "ACE enabled", kind: "bool" },
  { value: "aceInitialBandPct", label: "ACE corridor ±%", kind: "pct" },
  { value: "aceRandomEndMaxNs", label: "ACE random end (s)", kind: "sec" },
];

/** Muted when the value is inherited rather than set on the symbol. */
function cellClass(overridden: boolean): string {
  return clsx(
    "w-20 text-sm",
    !overridden && "text-fg-subtle opacity-60",
  );
}

export function SymbolOverridesTable() {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);

  const [search, setSearch] = useState("");
  const [onlyOverridden, setOnlyOverridden] = useState(false);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0]!);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkField, setBulkField] = useState<OverrideField>("aceInitialBandPct");
  const [bulkValue, setBulkValue] = useState<number | undefined>(undefined);

  // Recomputed only when the draft or the query changes — at 250+ symbols
  // this runs on every keystroke otherwise.
  const result = useMemo(
    () => selectOverridePage(draft, { search, onlyOverridden, page, pageSize }),
    [draft, search, onlyOverridden, page, pageSize],
  );

  const pageSymbols = result.rows.map((r) => r.symbol);
  const allOnPageSelected =
    pageSymbols.length > 0 && pageSymbols.every((s) => selected.has(s));
  const bulkKind = BULK_FIELDS.find((f) => f.value === bulkField)?.kind ?? "pct";

  function toggle(symbol: string): void {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      return next;
    });
  }

  function set(symbol: string, field: OverrideField, value: number | boolean | undefined): void {
    update((d) => applyOverrideToMany(d, [symbol], field, value));
  }

  function runBulk(): void {
    if (selected.size === 0) return;
    let value: number | boolean | undefined;
    if (bulkKind === "bool") value = bulkValue === 1;
    else if (bulkValue === undefined) value = undefined;
    else if (bulkKind === "pct") value = percentToFraction(bulkValue);
    else value = Math.round(bulkValue * 1_000_000_000);
    update((d) => applyOverrideToMany(d, selected, bulkField, value));
  }

  return (
    <div>
      {/* --- filter bar --- */}
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <input
          type="search"
          aria-label="Filter symbols"
          placeholder="Filter symbols…"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(0);
          }}
          className="w-48 rounded-md border border-border bg-surface px-2 py-1 text-sm"
        />
        <label className="flex items-center gap-1.5 text-sm">
          <input
            type="checkbox"
            checked={onlyOverridden}
            onChange={(e) => {
              setOnlyOverridden(e.target.checked);
              setPage(0);
            }}
          />
          Only overridden
        </label>
        <span className="text-sm text-fg-subtle">
          {result.total} symbol{result.total === 1 ? "" : "s"}
        </span>
        <div className="ml-auto flex items-center gap-1.5 text-sm">
          <span className="text-fg-subtle">Rows</span>
          <select
            aria-label="Rows per page"
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setPage(0);
            }}
            className="rounded-md border border-border bg-surface px-2 py-1"
          >
            {PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* --- bulk toolbar --- */}
      {selected.size > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-2 rounded-md border border-accent/40 bg-accent/5 px-3 py-2 text-sm">
          <span className="font-medium">{selected.size} selected</span>
          <span className="text-fg-subtle">Set</span>
          <select
            aria-label="Bulk field"
            value={bulkField}
            onChange={(e) => setBulkField(e.target.value as OverrideField)}
            className="rounded-md border border-border bg-surface px-2 py-1"
          >
            {BULK_FIELDS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
          <span className="text-fg-subtle">to</span>
          {bulkKind === "bool" ? (
            <select
              aria-label="Bulk value"
              value={bulkValue ?? 1}
              onChange={(e) => setBulkValue(Number(e.target.value))}
              className="rounded-md border border-border bg-surface px-2 py-1"
            >
              <option value={1}>enabled</option>
              <option value={0}>disabled</option>
            </select>
          ) : (
            <NumberInput
              aria-label="Bulk value"
              value={bulkValue}
              onChange={(v) => setBulkValue(v ?? undefined)}
              className="w-24"
            />
          )}
          <button
            type="button"
            onClick={runBulk}
            className="rounded-md border border-border px-3 py-1 hover:bg-muted"
          >
            Apply
          </button>
          <button
            type="button"
            onClick={() => update((d) => clearOverrides(d, selected))}
            className="rounded-md border border-border px-3 py-1 hover:bg-muted"
          >
            Clear overrides
          </button>
          <button
            type="button"
            onClick={() => setSelected(new Set())}
            className="ml-auto text-fg-subtle hover:text-fg"
          >
            Deselect all
          </button>
        </div>
      )}

      {/* --- table --- */}
      <div className="overflow-hidden rounded-md border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted text-left text-xs uppercase text-fg-subtle">
            <tr>
              <th className="px-2 py-2">
                <input
                  type="checkbox"
                  aria-label="Select all on page"
                  checked={allOnPageSelected}
                  onChange={(e) =>
                    setSelected((prev) => {
                      const next = new Set(prev);
                      for (const s of pageSymbols) {
                        if (e.target.checked) next.add(s);
                        else next.delete(s);
                      }
                      return next;
                    })
                  }
                />
              </th>
              <th className="px-3 py-2">Symbol</th>
              <th className="px-3 py-2">
                <ColumnHead
                  label="Collar static %"
                  help="Per-symbol static collar band. Greyed values are inherited from the exchange default."
                />
              </th>
              <th className="px-3 py-2">
                <ColumnHead
                  label="Collar dyn %"
                  help="Per-symbol dynamic collar band. Greyed values are inherited."
                />
              </th>
              <th className="px-3 py-2">
                <ColumnHead
                  label="ACE"
                  help="Automated Corridor Expansion for this symbol's reopening auction. Off means a halt reopens at the equilibrium price with no corridor."
                />
              </th>
              <th className="px-3 py-2">
                <ColumnHead
                  label="Corridor ±%"
                  help="Corridor half-width at the start of the first call phase. The expansion ladder itself is exchange-wide — set it on the Circuit Breakers tab."
                />
              </th>
              <th className="px-3 py-2">
                <ColumnHead
                  label="Random end (s)"
                  help="Random tail added to every call phase so the reopen instant cannot be targeted. 0 makes it exactly predictable."
                />
              </th>
              <th className="px-2 py-2" />
            </tr>
          </thead>
          <tbody>
            {result.rows.map((row: SymbolOverrideRow) => (
              <tr
                key={row.symbol}
                className={clsx(
                  "border-t border-border",
                  selected.has(row.symbol) && "bg-accent/5",
                )}
              >
                <td className="px-2 py-1.5">
                  <input
                    type="checkbox"
                    aria-label={`Select ${row.symbol}`}
                    checked={selected.has(row.symbol)}
                    onChange={() => toggle(row.symbol)}
                  />
                </td>
                <td className="px-3 py-1.5 font-medium">
                  {row.symbol}
                  {row.hasAnyOverride && (
                    <span className="ml-1.5 text-xs text-accent" title="has overrides">
                      •
                    </span>
                  )}
                </td>
                <td className="px-3 py-1.5">
                  <NumberInput
                    aria-label={`${row.symbol} static band percent`}
                    value={
                      row.staticBandPct.value === undefined
                        ? undefined
                        : fractionToPercent(row.staticBandPct.value)
                    }
                    min={0}
                    max={100}
                    step={0.5}
                    onChange={(v) =>
                      set(
                        row.symbol,
                        "staticBandPct",
                        v === undefined || v === null ? undefined : percentToFraction(v),
                      )
                    }
                    className={cellClass(row.staticBandPct.overridden)}
                  />
                </td>
                <td className="px-3 py-1.5">
                  <NumberInput
                    aria-label={`${row.symbol} dynamic band percent`}
                    value={
                      row.dynamicBandPct.value === undefined
                        ? undefined
                        : fractionToPercent(row.dynamicBandPct.value)
                    }
                    min={0}
                    max={100}
                    step={0.5}
                    onChange={(v) =>
                      set(
                        row.symbol,
                        "dynamicBandPct",
                        v === undefined || v === null ? undefined : percentToFraction(v),
                      )
                    }
                    className={cellClass(row.dynamicBandPct.overridden)}
                  />
                </td>
                <td className="px-3 py-1.5">
                  <Switch
                    aria-label={`${row.symbol} ACE enabled`}
                    checked={row.aceEnabled.value}
                    onCheckedChange={(c) => set(row.symbol, "aceEnabled", c)}
                  />
                </td>
                <td className="px-3 py-1.5">
                  <NumberInput
                    aria-label={`${row.symbol} ACE corridor percent`}
                    value={fractionToPercent(row.aceInitialBandPct.value)}
                    min={0}
                    max={100}
                    step={0.5}
                    onChange={(v) =>
                      set(
                        row.symbol,
                        "aceInitialBandPct",
                        v === undefined || v === null ? undefined : percentToFraction(v),
                      )
                    }
                    className={cellClass(row.aceInitialBandPct.overridden)}
                  />
                </td>
                <td className="px-3 py-1.5">
                  <NumberInput
                    aria-label={`${row.symbol} ACE random end seconds`}
                    value={row.aceRandomEndMaxNs.value / 1_000_000_000}
                    min={0}
                    onChange={(v) =>
                      set(
                        row.symbol,
                        "aceRandomEndMaxNs",
                        v === undefined || v === null
                          ? undefined
                          : Math.round(v * 1_000_000_000),
                      )
                    }
                    className={cellClass(row.aceRandomEndMaxNs.overridden)}
                  />
                </td>
                <td className="px-2 py-1.5 text-right">
                  {row.hasAnyOverride && (
                    <button
                      type="button"
                      aria-label={`Clear ${row.symbol} overrides`}
                      title="Return this symbol to the exchange defaults"
                      onClick={() => update((d) => clearOverrides(d, [row.symbol]))}
                      className="text-fg-subtle hover:text-error"
                    >
                      ×
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {result.rows.length === 0 && (
              <tr className="border-t border-border">
                <td colSpan={8} className="px-3 py-4 text-center text-sm text-fg-subtle">
                  {onlyOverridden
                    ? "No symbol overrides the exchange defaults."
                    : "No symbols match that filter."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* --- pager --- */}
      {result.pageCount > 1 && (
        <div className="mt-2 flex items-center gap-2 text-sm">
          <button
            type="button"
            disabled={result.page === 0}
            onClick={() => setPage(result.page - 1)}
            className="rounded-md border border-border px-2 py-1 disabled:opacity-40 hover:bg-muted"
          >
            ‹ Prev
          </button>
          <span className="text-fg-subtle">
            Page {result.page + 1} of {result.pageCount}
          </span>
          <button
            type="button"
            disabled={result.page >= result.pageCount - 1}
            onClick={() => setPage(result.page + 1)}
            className="rounded-md border border-border px-2 py-1 disabled:opacity-40 hover:bg-muted"
          >
            Next ›
          </button>
        </div>
      )}

      <p className="mt-2 text-xs text-fg-subtle">
        Greyed values are inherited from the exchange defaults; typing a value creates a
        per-symbol override and clearing it returns the symbol to inheriting. The ACE
        expansion ladder is exchange-wide — set it on the Circuit Breakers tab.
      </p>
    </div>
  );
}
