import type { EngineConfigDraft } from "@edumatcher/schema";

/**
 * Remove a symbol and every reference the draft holds to it, so no dangling
 * key is left to be written: index constituents, combo legs and per-gateway
 * obligation overrides.
 */
export function removeSymbol(d: EngineConfigDraft, symbol: string): void {
  delete d.symbols[symbol];
  d.symbolOrder = d.symbolOrder.filter((s) => s !== symbol);
  for (const index of d.indices) {
    index.constituents = index.constituents.filter((c) => c !== symbol);
  }
  for (const combo of d.combos) {
    combo.legs = combo.legs.filter((leg) => leg.symbol !== symbol);
  }
  for (const gw of d.gateways) {
    if (gw.mmObligations?.[symbol] === undefined) continue;
    delete gw.mmObligations[symbol];
    if (Object.keys(gw.mmObligations).length === 0)
      gw.mmObligations = undefined;
  }
}

/** Rename a symbol in place, carrying every reference to it along. */
export function renameSymbol(
  d: EngineConfigDraft,
  from: string,
  to: string,
): void {
  const idx = d.symbolOrder.indexOf(from);
  d.symbols[to] = d.symbols[from]!;
  delete d.symbols[from];
  if (idx >= 0) d.symbolOrder[idx] = to;
  else d.symbolOrder.push(to);
  for (const index of d.indices) {
    index.constituents = index.constituents.map((c) => (c === from ? to : c));
  }
  for (const combo of d.combos) {
    for (const leg of combo.legs) if (leg.symbol === from) leg.symbol = to;
  }
  for (const gw of d.gateways) {
    if (gw.mmObligations?.[from] === undefined) continue;
    gw.mmObligations[to] = gw.mmObligations[from]!;
    delete gw.mmObligations[from];
  }
}
