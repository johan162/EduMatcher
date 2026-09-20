import { useMemo, useState } from "react";
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
import { tickStep, uppercaseId } from "@/lib/format";
import { renameSymbol } from "@/lib/symbols";
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
 * Create a symbol as an "IPO" — one reference price drives the seeded last
 * buy/sell and the opening market-maker quote — or edit an existing one.
 *
 * Editing shows and saves the symbol's actual values: separate last buy and
 * last sell prices and the full quote list. Nothing is re-derived on save, so
 * opening a symbol and pressing Save changes nothing.
 *
 * Radix unmounts the content while closed, so each form initialises its
 * staged state from the draft when it mounts; no reset effect is needed.
 */
export function SymbolEditorDialog({ open, onOpenChange, mode, symbolName }: Props) {
  const close = () => onOpenChange(false);
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-black/50" />
        <RadixDialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[min(760px,94vw)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-border bg-surface-raised p-5 shadow-xl">
          {mode === "edit" && symbolName ? (
            <EditSymbolForm key={symbolName} symbolName={symbolName} onDone={close} />
          ) : (
            <CreateSymbolForm onDone={close} />
          )}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}

function useMmGatewayIds(): string[] {
  const gateways = useDraftStore((s) => s.draft.gateways);
  return useMemo(
    () => gateways.filter((g) => g.role === "MARKET_MAKER").map((g) => g.id),
    [gateways],
  );
}

function quotesInvalid(quotes: MmQuoteSeed[], mmGatewayIds: string[]): boolean {
  return quotes.some(
    (q) =>
      !q.gatewayId ||
      !mmGatewayIds.includes(q.gatewayId) ||
      (q.bidPrice !== null && q.askPrice !== null && q.bidPrice >= q.askPrice) ||
      q.bidQty <= 0 ||
      q.askQty <= 0,
  );
}

function Footer({ canSave, label, onCancel, onSave }: { canSave: boolean; label: string; onCancel: () => void; onSave: () => void }) {
  return (
    <div className="mt-5 flex justify-end gap-2">
      <button
        type="button"
        onClick={onCancel}
        className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
      >
        Cancel
      </button>
      <button
        type="button"
        disabled={!canSave}
        onClick={onSave}
        className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-fg disabled:cursor-not-allowed disabled:opacity-50"
      >
        {label}
      </button>
    </div>
  );
}

function CreateSymbolForm({ onDone }: { onDone: () => void }) {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const { canSee } = usePersona();
  const mmGatewayIds = useMmGatewayIds();
  const hasMm = mmGatewayIds.length > 0;

  const [name, setName] = useState("");
  const [tickDecimals, setTickDecimals] = useState(draft.tickDecimals);
  const [referencePrice, setReferencePrice] = useState<number | undefined>(undefined);
  const [outstandingShares, setOutstandingShares] = useState<number | undefined>(
    DEFAULT_OUTSTANDING_SHARES,
  );
  const [primaryGateway, setPrimaryGateway] = useState<string>(mmGatewayIds[0] ?? "");
  const [spreadTicks, setSpreadTicks] = useState(DEFAULT_OPENING_SPREAD_TICKS);
  const [size, setSize] = useState(DEFAULT_MM_STUB_QTY);
  // Extra quotes beyond the auto-derived primary one (expert multi-MM).
  const [extraQuotes, setExtraQuotes] = useState<MmQuoteSeed[]>([]);

  const trimmedName = uppercaseId(name);
  const nameClash = trimmedName.length > 0 && Boolean(draft.symbols[trimmedName]);

  const primaryQuote =
    hasMm && primaryGateway && referencePrice !== undefined
      ? deriveIpoQuote(primaryGateway, referencePrice, tickDecimals, spreadTicks, size)
      : undefined;
  const allQuotes = primaryQuote ? [primaryQuote, ...extraQuotes] : extraQuotes;

  const canSave =
    trimmedName.length > 0 &&
    !nameClash &&
    referencePrice !== undefined &&
    referencePrice > 0 &&
    outstandingShares !== undefined &&
    outstandingShares > 0 &&
    (!hasMm || Boolean(primaryGateway)) &&
    !quotesInvalid(extraQuotes, mmGatewayIds);

  const commit = () => {
    if (referencePrice === undefined) return;
    update((d) => {
      const config: SymbolConfig = {
        tickDecimals,
        lastBuyPrice: referencePrice,
        lastSellPrice: referencePrice,
        outstandingShares,
      };
      if (allQuotes.length > 0) config.marketMakerQuotes = allQuotes;
      d.symbolOrder.push(trimmedName);
      d.symbols[trimmedName] = config;
    });
    onDone();
  };

  return (
    <>
      <RadixDialog.Title className="text-base font-semibold">List a new symbol (IPO)</RadixDialog.Title>
      <RadixDialog.Description className="mt-1 text-sm text-fg-subtle">
        A single reference price sets the opening last buy/sell and the market maker's opening
        quote, so the book, the last price, and the collar reference all agree.
      </RadixDialog.Description>

      <div className="mt-4 space-y-4">
        <div className="grid grid-cols-3 gap-3">
          <label className="text-sm">
            <span className="mb-1 block font-medium">
              Symbol <span className="text-required">*</span>
            </span>
            <TextInput
              aria-label="Symbol name"
              value={name}
              onChange={setName}
              onBlur={() => setName(uppercaseId(name))}
              placeholder="e.g. AAPL"
              className="w-full"
            />
            {nameClash && <span className="mt-1 block text-xs text-error">Symbol already exists.</span>}
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">
              IPO reference price <span className="text-required">*</span>
            </span>
            <NumberInput
              aria-label="IPO reference price"
              value={referencePrice}
              min={0}
              step={tickStep(tickDecimals)}
              onChange={setReferencePrice}
              className="w-full"
            />
            <span className="mt-1 block text-xs text-fg-subtle">Sets last buy = last sell = this price.</span>
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

            {canSee("E") && (
              <div className="mt-3">
                <div className="mb-1 text-sm font-medium">Additional market makers</div>
                <MmQuotesEditor
                  quotes={extraQuotes}
                  mmGatewayIds={mmGatewayIds}
                  tickDecimals={tickDecimals}
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
                Default for new symbols: {draft.tickDecimals}
              </span>
            </label>
          </div>
        )}
      </div>

      <Footer canSave={canSave} label="List symbol" onCancel={onDone} onSave={commit} />
    </>
  );
}

function EditSymbolForm({ symbolName, onDone }: { symbolName: string; onDone: () => void }) {
  const draft = useDraftStore((s) => s.draft);
  const update = useDraftStore((s) => s.update);
  const { canSee } = usePersona();
  const mmGatewayIds = useMmGatewayIds();

  // Staged copy of the symbol's own values; committed only on Save.
  const [initial] = useState<SymbolConfig | undefined>(() =>
    draft.symbols[symbolName] ? structuredClone(draft.symbols[symbolName]!) : undefined,
  );
  const [name, setName] = useState(symbolName);
  const [tickDecimals, setTickDecimals] = useState(initial?.tickDecimals ?? draft.tickDecimals);
  const [lastBuyPrice, setLastBuyPrice] = useState<number | null | undefined>(initial?.lastBuyPrice);
  const [lastSellPrice, setLastSellPrice] = useState<number | null | undefined>(initial?.lastSellPrice);
  const [outstandingShares, setOutstandingShares] = useState<number | undefined>(
    initial?.outstandingShares,
  );
  const [quotes, setQuotes] = useState<MmQuoteSeed[]>(initial?.marketMakerQuotes ?? []);

  if (!initial) {
    return (
      <>
        <RadixDialog.Title className="text-base font-semibold">Edit {symbolName}</RadixDialog.Title>
        <RadixDialog.Description className="mt-1 text-sm text-fg-subtle">Symbol not found.</RadixDialog.Description>
        <Footer canSave={false} label="Save" onCancel={onDone} onSave={onDone} />
      </>
    );
  }

  const trimmedName = uppercaseId(name);
  const nameClash =
    trimmedName.length > 0 && trimmedName !== symbolName && Boolean(draft.symbols[trimmedName]);
  const step = tickStep(tickDecimals);

  const canSave =
    trimmedName.length > 0 &&
    !nameClash &&
    (outstandingShares === undefined || outstandingShares > 0) &&
    !quotesInvalid(quotes, mmGatewayIds);

  const commit = () => {
    update((d) => {
      if (trimmedName !== symbolName) renameSymbol(d, symbolName, trimmedName);
      const config: SymbolConfig = { ...d.symbols[trimmedName]!, tickDecimals };
      // An undefined value is a key the file leaves out; keep it that way.
      if (lastBuyPrice === undefined) delete config.lastBuyPrice;
      else config.lastBuyPrice = lastBuyPrice;
      if (lastSellPrice === undefined) delete config.lastSellPrice;
      else config.lastSellPrice = lastSellPrice;
      if (outstandingShares === undefined) delete config.outstandingShares;
      else config.outstandingShares = outstandingShares;
      if (quotes.length > 0) config.marketMakerQuotes = quotes;
      else delete config.marketMakerQuotes;
      d.symbols[trimmedName] = config;
    });
    onDone();
  };

  return (
    <>
      <RadixDialog.Title className="text-base font-semibold">Edit {symbolName}</RadixDialog.Title>
      <RadixDialog.Description className="mt-1 text-sm text-fg-subtle">
        The symbol's values as they will be written. Nothing is re-derived: Save writes exactly
        what is shown.
      </RadixDialog.Description>

      <div className="mt-4 space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <label className="text-sm">
            <span className="mb-1 block font-medium">
              Symbol <span className="text-required">*</span>
            </span>
            <TextInput
              aria-label="Symbol name"
              value={name}
              onChange={setName}
              onBlur={() => setName(uppercaseId(name))}
              className="w-full"
            />
            {nameClash && <span className="mt-1 block text-xs text-error">Symbol already exists.</span>}
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Outstanding shares</span>
            <NumberInput
              aria-label="Outstanding shares"
              value={outstandingShares}
              min={1}
              onChange={setOutstandingShares}
              className="w-full"
            />
            <span className="mt-1 block text-xs text-fg-subtle">Empty = not set.</span>
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Last buy price</span>
            <NumberInput
              aria-label="Last buy price"
              value={lastBuyPrice}
              min={0}
              step={step}
              onChange={(v) => setLastBuyPrice(v ?? null)}
              className="w-full"
            />
          </label>
          <label className="text-sm">
            <span className="mb-1 block font-medium">Last sell price</span>
            <NumberInput
              aria-label="Last sell price"
              value={lastSellPrice}
              min={0}
              step={step}
              onChange={(v) => setLastSellPrice(v ?? null)}
              className="w-full"
            />
          </label>
        </div>

        {(mmGatewayIds.length > 0 || quotes.length > 0) && (
          <div className="border-t border-border pt-4">
            <div className="mb-1 text-sm font-medium">Market-maker quotes</div>
            <MmQuotesEditor
              quotes={quotes}
              mmGatewayIds={mmGatewayIds}
              tickDecimals={tickDecimals}
              onChange={setQuotes}
              showQuoteId={canSee("E")}
            />
          </div>
        )}

        {canSee("I") && (
          <div className="border-t border-border pt-4">
            <label className="text-sm">
              <span className="mb-1 block font-medium">Tick decimals</span>
              <NumberInput
                aria-label="Tick decimals"
                value={tickDecimals}
                min={0}
                max={8}
                onChange={(v) => setTickDecimals(v ?? initial.tickDecimals)}
                className="w-40"
              />
            </label>
          </div>
        )}
      </div>

      <Footer canSave={canSave} label="Save" onCancel={onDone} onSave={commit} />
    </>
  );
}
