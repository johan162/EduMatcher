import { useEffect, useMemo, useState } from "react";
import * as RadixDialog from "@radix-ui/react-dialog";
import {
  DEFAULT_MM_STUB_QTY,
  DEFAULT_OPENING_SPREAD_TICKS,
  DEFAULT_OUTSTANDING_SHARES,
  deriveIpoQuote,
  type MmQuoteSeed,
  type SymbolConfig,
} from "@edumatcher/schema";
import { useDraftStore } from "@/store/draftStore";
import { usePersona } from "@/lib/usePersona";
import { uppercaseId } from "@/lib/format";
import { NumberInput, TextInput } from "@/components/fields/inputs";
import { Select } from "@/components/ui/Select";
import { MmQuotesEditor } from "./MmQuotesEditor";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: "create" | "edit";
  /** Existing symbol name when mode === "edit". */
  symbolName?: string;
}

/**
 * Create/edit a symbol as an "IPO": a single reference price drives the seeded
 * last buy/sell prices and the opening market-maker quote, keeping them
 * mutually consistent. Higher personas can fine-tune precision and add more
 * market makers. Edits are staged locally and only committed on Save.
 */
export function SymbolEditorDialog({ open, onOpenChange, mode, symbolName }: Props) {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const { canSee } = usePersona();

  const mmGatewayIds = useMemo(
    () => draft.gateways.filter((g) => g.role === "MARKET_MAKER").map((g) => g.id),
    [draft.gateways],
  );
  const hasMm = mmGatewayIds.length > 0;

  const [name, setName] = useState("");
  const [tickDecimals, setTickDecimals] = useState(draft.tickDecimals);
  const [referencePrice, setReferencePrice] = useState<number | undefined>(undefined);
  const [outstandingShares, setOutstandingShares] = useState<number | undefined>(
    DEFAULT_OUTSTANDING_SHARES,
  );
  const [primaryGateway, setPrimaryGateway] = useState<string>("");
  const [spreadTicks, setSpreadTicks] = useState(DEFAULT_OPENING_SPREAD_TICKS);
  const [size, setSize] = useState(DEFAULT_MM_STUB_QTY);
  // Extra quotes beyond the auto-derived primary one (expert multi-MM).
  const [extraQuotes, setExtraQuotes] = useState<MmQuoteSeed[]>([]);
  const [otherFields, setOtherFields] = useState<Partial<SymbolConfig>>({});

  // Reset the staged values whenever the dialog (re)opens.
  useEffect(() => {
    if (!open) return;
    if (mode === "edit" && symbolName && draft.symbols[symbolName]) {
      const cfg = structuredClone(draft.symbols[symbolName]!);
      setName(symbolName);
      setTickDecimals(cfg.tickDecimals);
      setReferencePrice(cfg.lastBuyPrice ?? cfg.lastSellPrice ?? undefined);
      setOutstandingShares(cfg.outstandingShares ?? DEFAULT_OUTSTANDING_SHARES);
      const quotes = cfg.marketMakerQuotes ?? [];
      // Treat the first quote as the "primary" IPO quote; keep the rest as extras.
      const primary = quotes[0];
      setPrimaryGateway(primary?.gatewayId ?? mmGatewayIds[0] ?? "");
      setSpreadTicks(DEFAULT_OPENING_SPREAD_TICKS);
      setSize(primary?.bidQty ?? DEFAULT_MM_STUB_QTY);
      setExtraQuotes(quotes.slice(1));
      // Preserve unrelated per-symbol config (level, collar, cb, mm obligations).
      const {
        lastBuyPrice: _lb,
        lastSellPrice: _ls,
        marketMakerQuotes: _mq,
        outstandingShares: _os,
        tickDecimals: _td,
        ...rest
      } = cfg;
      setOtherFields(rest);
    } else {
      setName("");
      setTickDecimals(draft.tickDecimals);
      setReferencePrice(undefined);
      setOutstandingShares(DEFAULT_OUTSTANDING_SHARES);
      setPrimaryGateway(mmGatewayIds[0] ?? "");
      setSpreadTicks(DEFAULT_OPENING_SPREAD_TICKS);
      setSize(DEFAULT_MM_STUB_QTY);
      setExtraQuotes([]);
      setOtherFields({});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const trimmedName = uppercaseId(name.trim());
  const nameClash =
    trimmedName.length > 0 &&
    trimmedName !== symbolName &&
    Boolean(draft.symbols[trimmedName]);

  const primaryQuote = useMemo(() => {
    if (!hasMm || !primaryGateway || referencePrice === undefined) return undefined;
    return deriveIpoQuote(primaryGateway, referencePrice, tickDecimals, spreadTicks, size);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasMm, primaryGateway, referencePrice, tickDecimals, spreadTicks, size]);

  const allQuotes: MmQuoteSeed[] = useMemo(
    () => (primaryQuote ? [primaryQuote, ...extraQuotes] : extraQuotes),
    [primaryQuote, extraQuotes],
  );

  const extrasInvalid = extraQuotes.some(
    (q) =>
      !q.gatewayId ||
      !mmGatewayIds.includes(q.gatewayId) ||
      (q.bidPrice !== null && q.askPrice !== null && q.bidPrice >= q.askPrice) ||
      q.bidQty <= 0 ||
      q.askQty <= 0,
  );

  const canSave =
    trimmedName.length > 0 &&
    !nameClash &&
    referencePrice !== undefined &&
    referencePrice > 0 &&
    outstandingShares !== undefined &&
    outstandingShares > 0 &&
    (!hasMm || Boolean(primaryGateway)) &&
    !extrasInvalid;

  const commit = () => {
    if (referencePrice === undefined) return;
    update((d) => {
      const normalized: SymbolConfig = {
        ...otherFields,
        tickDecimals,
        lastBuyPrice: referencePrice,
        lastSellPrice: referencePrice,
        outstandingShares,
      };
      if (allQuotes.length > 0) normalized.marketMakerQuotes = allQuotes;

      if (mode === "edit" && symbolName && symbolName !== trimmedName) {
        const idx = d.symbolOrder.indexOf(symbolName);
        delete d.symbols[symbolName];
        if (idx >= 0) d.symbolOrder[idx] = trimmedName;
        else d.symbolOrder.push(trimmedName);
        for (const index of d.indices) {
          index.constituents = index.constituents.map((c) =>
            c === symbolName ? trimmedName : c,
          );
        }
        for (const combo of d.combos) {
          for (const leg of combo.legs) {
            if (leg.symbol === symbolName) leg.symbol = trimmedName;
          }
        }
      } else if (mode === "create" && !d.symbols[trimmedName]) {
        d.symbolOrder.push(trimmedName);
      }
      d.symbols[trimmedName] = normalized;
    });
    onOpenChange(false);
  };

  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-black/50" />
        <RadixDialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[min(760px,94vw)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-border bg-surface-raised p-5 shadow-xl">
          <RadixDialog.Title className="text-base font-semibold">
            {mode === "create" ? "List a new symbol (IPO)" : `Edit ${symbolName}`}
          </RadixDialog.Title>
          <RadixDialog.Description className="mt-1 text-sm text-fg-subtle">
            A single reference price sets the opening last buy/sell and the market maker's opening
            quote, so the book, the last price, and the collar reference all agree.
          </RadixDialog.Description>

          <div className="mt-4 space-y-4">
            {/* Identity + IPO reference (all personas) */}
            <div className="grid grid-cols-3 gap-3">
              <label className="text-sm">
                <span className="mb-1 block font-medium">
                  Symbol <span className="text-required">*</span>
                </span>
                <TextInput
                  aria-label="Symbol name"
                  value={name}
                  onChange={setName}
                  onBlur={() => setName(uppercaseId(name.trim()))}
                  placeholder="e.g. AAPL"
                  className="w-full"
                />
                {nameClash && (
                  <span className="mt-1 block text-xs text-error">Symbol already exists.</span>
                )}
              </label>
              <label className="text-sm">
                <span className="mb-1 block font-medium">
                  IPO reference price <span className="text-required">*</span>
                </span>
                <NumberInput
                  aria-label="IPO reference price"
                  value={referencePrice}
                  min={0}
                  step={0.01}
                  onChange={setReferencePrice}
                  className="w-full"
                />
                <span className="mt-1 block text-xs text-fg-subtle">
                  Sets last buy = last sell = this price.
                </span>
              </label>
              <label className="text-sm">
                <span className="mb-1 block font-medium">
                  Outstanding shares <span className="text-required">*</span>
                </span>
                <NumberInput
                  aria-label="Outstanding shares"
                  value={outstandingShares}
                  min={1}
                  onChange={setOutstandingShares}
                  className="w-full"
                />
                <span className="mt-1 block text-xs text-fg-subtle">
                  Suggested: {DEFAULT_OUTSTANDING_SHARES.toLocaleString()}
                </span>
              </label>
            </div>

            {/* Opening quote (only when an MM gateway exists) */}
            {hasMm ? (
              <div className="border-t border-border pt-4">
                <div className="mb-2 text-sm font-medium">Opening market-maker quote</div>
                <div className="grid grid-cols-3 gap-3">
                  <label className="text-sm">
                    <span className="mb-1 block font-medium">
                      Primary market maker <span className="text-required">*</span>
                    </span>
                    <Select
                      aria-label="Primary market maker"
                      value={primaryGateway}
                      onValueChange={setPrimaryGateway}
                      options={mmGatewayIds.map((id) => ({ value: id, label: id }))}
                    />
                  </label>
                  <label className="text-sm">
                    <span className="mb-1 block font-medium">Opening spread (ticks)</span>
                    <NumberInput
                      aria-label="Opening spread ticks"
                      value={spreadTicks}
                      min={1}
                      onChange={(v) => setSpreadTicks(v ?? DEFAULT_OPENING_SPREAD_TICKS)}
                      className="w-full"
                    />
                  </label>
                  <label className="text-sm">
                    <span className="mb-1 block font-medium">Quote size</span>
                    <NumberInput
                      aria-label="Quote size"
                      value={size}
                      min={1}
                      onChange={(v) => setSize(v ?? DEFAULT_MM_STUB_QTY)}
                      className="w-full"
                    />
                  </label>
                </div>
                {primaryQuote && (
                  <p className="mt-2 text-xs text-fg-subtle">
                    Derived opening quote:{" "}
                    <span className="font-medium text-fg">
                      bid {primaryQuote.bidPrice} / ask {primaryQuote.askPrice}
                    </span>{" "}
                    ({primaryQuote.bidQty} × {primaryQuote.askQty}), last = {referencePrice}.
                  </p>
                )}

                {/* Expert: additional market makers */}
                {canSee("E") && (
                  <div className="mt-3">
                    <div className="mb-1 text-sm font-medium">Additional market makers</div>
                    <MmQuotesEditor
                      quotes={extraQuotes}
                      mmGatewayIds={mmGatewayIds}
                      onChange={setExtraQuotes}
                      showQuoteId
                    />
                  </div>
                )}
              </div>
            ) : (
              <p className="border-t border-border pt-4 text-sm text-fg-subtle">
                No MARKET_MAKER gateway is configured, so no opening quote is seeded. The reference
                price still seeds the book's last prices and the collar reference; participants
                supply liquidity manually.
              </p>
            )}

            {/* Intermediate: precision */}
            {canSee("I") && (
              <div className="border-t border-border pt-4">
                <label className="text-sm">
                  <span className="mb-1 block font-medium">Tick decimals</span>
                  <NumberInput
                    aria-label="Tick decimals"
                    value={tickDecimals}
                    min={0}
                    max={8}
                    onChange={(v) => setTickDecimals(v ?? draft.tickDecimals)}
                    className="w-40"
                  />
                  <span className="mt-1 block text-xs text-fg-subtle">
                    Global default: {draft.tickDecimals}
                  </span>
                </label>
              </div>
            )}
          </div>

          <div className="mt-5 flex justify-end gap-2">
            <button
              type="button"
              onClick={() => onOpenChange(false)}
              className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={!canSave}
              onClick={commit}
              className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg disabled:cursor-not-allowed disabled:opacity-50"
            >
              {mode === "create" ? "List symbol" : "Save"}
            </button>
          </div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
