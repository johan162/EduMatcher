/**
 * Cross-field validation and consistency engine (design §8).
 *
 * Each rule is a pure function of the draft returning zero or more Diagnostics.
 * Rule ids and messages mirror `src/edumatcher/config_gen/warnings.py` where an
 * equivalent exists (referenced in comments), so the CLI and GUI stay aligned.
 *
 * MAINTENANCE: when a validation rule changes in warnings.py or cli.py, update
 * the corresponding rule here (and vice versa).
 */

import {
  effectiveDefaultCollar,
  type Diagnostic,
  type EngineConfigDraft,
} from "@edumatcher/schema";

type Rule = (draft: EngineConfigDraft) => Diagnostic[];

const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/;

function definedRiskLevels(draft: EngineConfigDraft): Set<string> {
  const levels = new Set<string>(Object.keys(draft.riskControls.levels));
  if (effectiveDefaultCollar(draft)) levels.add("DEFAULT");
  return levels;
}

function hasMarketMakerGateway(draft: EngineConfigDraft): boolean {
  return draft.gateways.some((g) => g.role === "MARKET_MAKER");
}

// -- §8.1 baseline rules (mirror warnings.py / cli.py) -------------------------

/** warnings.py: undefined risk level. */
const undefinedRiskLevel: Rule = (draft) => {
  const defined = definedRiskLevels(draft);
  const out: Diagnostic[] = [];
  for (const symbol of draft.symbolOrder) {
    const level = draft.symbols[symbol]?.level;
    if (level && !defined.has(level)) {
      out.push({
        id: "undefined-risk-level",
        severity: "error",
        message: `Symbol ${symbol} references undefined risk level ${level}. Define it under Risk & Collars or the engine will reject the config.`,
        fieldPaths: [`symbols.${symbol}.level`, "riskControls.levels"],
        tab: "symbols",
      });
    }
  }
  return out;
};

/** warnings.py: MARKET_MAKER gateway requires quote seeds. */
const mmGatewayNeedsSeeds: Rule = (draft) => {
  if (!hasMarketMakerGateway(draft)) return [];
  if (draft.seeding.mmMidRange) return [];
  // No warning if every symbol already carries explicit quotes.
  const allExplicit =
    draft.symbolOrder.length > 0 &&
    draft.symbolOrder.every(
      (s) => (draft.symbols[s]?.marketMakerQuotes?.length ?? 0) > 0,
    );
  if (allExplicit) return [];
  return [
    {
      id: "mm-gateway-needs-quote-seeds",
      severity: "warning",
      message:
        "A MARKET_MAKER gateway is configured but no mid-range seeding is set. Null bid/ask stubs will be emitted — set a seed mid-range, add explicit quotes, or fill in prices before starting the engine.",
      fieldPaths: ["seeding.mmMidRange"],
      tab: "market-maker",
    },
  ];
};

/** warnings.py: collars/CB disabled. */
const enforcementDisabled: Rule = (draft) => {
  if (draft.enforceCollars && draft.enforceCircuitBreakers) return [];
  const paths: string[] = [];
  if (!draft.enforceCollars) paths.push("enforceCollars");
  if (!draft.enforceCircuitBreakers) paths.push("enforceCircuitBreakers");
  return [
    {
      id: "collars-cb-disabled",
      severity: "warning",
      message:
        "enforce_collars/enforce_circuit_breakers disabled. Suitable for tests only.",
      fieldPaths: paths,
      tab: paths.includes("enforceCollars") ? "risk" : "circuit-breakers",
    },
  ];
};

/** warnings.py: tick_decimals == 0. */
const tickDecimalsZero: Rule = (draft) => {
  const out: Diagnostic[] = [];
  if (draft.tickDecimals === 0) {
    out.push({
      id: "tick-decimals-zero",
      severity: "warning",
      message: "tick_decimals=0 means all prices are whole numbers. Confirm this is intentional.",
      fieldPaths: ["tickDecimals"],
      tab: "symbols",
    });
  }
  for (const symbol of draft.symbolOrder) {
    if (draft.symbols[symbol]?.tickDecimals === 0) {
      out.push({
        id: "tick-decimals-zero",
        severity: "warning",
        message: `Symbol ${symbol} has tick_decimals=0 (whole-number prices only). Confirm this is intentional.`,
        fieldPaths: [`symbols.${symbol}.tickDecimals`],
        tab: "symbols",
      });
    }
  }
  return out;
};

/** warnings.py: single gateway. */
const singleGateway: Rule = (draft) =>
  draft.gateways.length === 1
    ? [
        {
          id: "single-gateway",
          severity: "warning",
          message:
            "Only one gateway configured. Consider adding an ADMIN gateway for operational control.",
          fieldPaths: ["gateways"],
          tab: "basics",
        },
      ]
    : [];

/** warnings.py: no ADMIN gateway. */
const noAdminGateway: Rule = (draft) =>
  draft.gateways.length > 0 && !draft.gateways.some((g) => g.role === "ADMIN")
    ? [
        {
          id: "no-admin-gateway",
          severity: "info",
          message:
            "No ADMIN gateway configured. Without one, exchange-wide halt/resume commands cannot be sent.",
          fieldPaths: ["gateways"],
          tab: "basics",
        },
      ]
    : [];

function scheduleIsDefault(draft: EngineConfigDraft): boolean {
  const s = draft.schedule;
  return (
    s.preOpen === "09:00" &&
    s.openingAuction === "09:25" &&
    s.continuous === "09:30" &&
    s.closingAuction === "16:00" &&
    s.closingEnd === "16:05"
  );
}

/** warnings.py: sessions enabled, default schedule. */
const sessionsDefaultSchedule: Rule = (draft) =>
  draft.sessionsEnabled && draft.emitSchedule && scheduleIsDefault(draft)
    ? [
        {
          id: "sessions-enabled-default-schedule",
          severity: "info",
          message:
            "sessions_enabled: true with the default schedule (09:00-16:05). Start pm-scheduler to drive session transitions.",
          fieldPaths: ["sessionsEnabled", "schedule"],
          tab: "sessions",
        },
      ]
    : [];

/** warnings.py: --seed-last-prices-from-mm without mid-range. */
const seedFromMmWithoutRange: Rule = (draft) =>
  draft.seeding.seedLastPricesFromMm && !draft.seeding.mmMidRange
    ? [
        {
          id: "seed-last-prices-from-mm-without-range",
          severity: "error",
          message:
            "Seed last prices from MM is enabled but no mid-range is set. Set a mid-range or disable this option.",
          fieldPaths: ["seeding.seedLastPricesFromMm", "seeding.mmMidRange"],
          tab: "market-maker",
        },
      ]
    : [];

const WILDCARD_ADDRESSES = new Set(["0.0.0.0", "::"]);

function addressesCollide(a: string, b: string): boolean {
  if (a === b) return true;
  return WILDCARD_ADDRESSES.has(a) || WILDCARD_ADDRESSES.has(b);
}

/** warnings.py: _port_collision_warnings. */
const portCollision: Rule = (draft) => {
  const endpoints: Array<{ label: string; address: string; port: number; path: string }> = [];
  if (draft.postTradeGateway.enabled) {
    endpoints.push({
      label: `post_trade_gateway '${draft.postTradeGateway.name}'`,
      address: draft.postTradeGateway.bindAddress,
      port: draft.postTradeGateway.port,
      path: "postTradeGateway.port",
    });
  }
  if (draft.marketDataGateway.enabled) {
    endpoints.push({
      label: `market_data_gateway '${draft.marketDataGateway.name}'`,
      address: draft.marketDataGateway.bindAddress,
      port: draft.marketDataGateway.port,
      path: "marketDataGateway.port",
    });
  }
  if (draft.balfGateway.enabled) {
    endpoints.push({
      label: `balf_gateway '${draft.balfGateway.name}'`,
      address: draft.balfGateway.bindAddress,
      port: draft.balfGateway.port,
      path: "balfGateway.port",
    });
  }
  for (const gw of draft.apiGateways) {
    if (gw.enabled) {
      endpoints.push({
        label: `api_gateway '${gw.name}'`,
        address: gw.host,
        port: gw.port,
        path: `apiGateways.${gw.name}.port`,
      });
    }
  }

  const out: Diagnostic[] = [];
  for (let i = 0; i < endpoints.length; i += 1) {
    for (let j = i + 1; j < endpoints.length; j += 1) {
      const a = endpoints[i]!;
      const b = endpoints[j]!;
      if (a.port === b.port && addressesCollide(a.address, b.address)) {
        const where = a.address === b.address ? a.address : `${a.address}/${b.address}`;
        out.push({
          id: "port-collision",
          severity: "warning",
          message: `Port collision: ${a.label} and ${b.label} both listen on ${where}:${a.port}. Set distinct ports or bind addresses.`,
          fieldPaths: [a.path, b.path],
          tab: "gateways",
        });
      }
    }
  }
  return out;
};

/** cli.py: _validate_schedule_order (fatal in CLI). */
const scheduleOrder: Rule = (draft) => {
  if (!draft.sessionsEnabled || !draft.emitSchedule) return [];
  const s = draft.schedule;
  const ordered: Array<[string, string]> = [
    ["preOpen", s.preOpen],
    ["openingAuction", s.openingAuction],
    ["continuous", s.continuous],
    ["closingAuction", s.closingAuction],
    ["closingEnd", s.closingEnd],
  ];
  const paths = ordered.map(([k]) => `schedule.${k}`);
  for (const [, value] of ordered) {
    if (!TIME_RE.test(value)) {
      return [
        {
          id: "schedule-out-of-order",
          severity: "error",
          message: `Invalid schedule time '${value}'. Expected HH:MM (24-hour).`,
          fieldPaths: paths,
          tab: "sessions",
        },
      ];
    }
  }
  const minutes = ordered.map(([, v]) => {
    const [h, m] = v.split(":").map(Number);
    return h! * 60 + m!;
  });
  for (let i = 1; i < minutes.length; i += 1) {
    if (minutes[i]! <= minutes[i - 1]!) {
      return [
        {
          id: "schedule-out-of-order",
          severity: "error",
          message:
            "Schedule times must be strictly increasing: pre_open < opening_auction < continuous < closing_auction < closing_end.",
          fieldPaths: paths,
          tab: "sessions",
        },
      ];
    }
  }
  return [];
};

// -- §8.2 new GUI-only rules ---------------------------------------------------

const indexMissingConstituents: Rule = (draft) =>
  draft.indices
    .filter((idx) => idx.constituents.length === 0)
    .map((idx) => ({
      id: "index-missing-constituents",
      severity: "error" as const,
      message: `Index ${idx.id} has no constituents. Add at least one symbol.`,
      fieldPaths: [`indices.${idx.id}.constituents`],
      tab: "indices",
    }));

const indexConstituentNotInUniverse: Rule = (draft) => {
  const universe = new Set(draft.symbolOrder);
  const out: Diagnostic[] = [];
  for (const idx of draft.indices) {
    for (const symbol of idx.constituents) {
      if (!universe.has(symbol)) {
        out.push({
          id: "index-constituent-not-in-universe",
          severity: "error",
          message: `Index ${idx.id} references unknown symbol ${symbol}. Add it to the symbol universe or remove it.`,
          fieldPaths: [`indices.${idx.id}.constituents`, "symbols"],
          tab: "indices",
        });
      }
    }
  }
  return out;
};

const outstandingSharesMissingForConstituent: Rule = (draft) => {
  const out: Diagnostic[] = [];
  const seen = new Set<string>();
  for (const idx of draft.indices) {
    for (const symbol of idx.constituents) {
      if (seen.has(symbol)) continue;
      const cfg = draft.symbols[symbol];
      if (cfg && cfg.outstandingShares === undefined) {
        seen.add(symbol);
        out.push({
          id: "outstanding-shares-missing-for-index-constituent",
          severity: "warning",
          message: `Symbol ${symbol} is an index constituent but has no outstanding_shares set (used for index weighting).`,
          fieldPaths: [`symbols.${symbol}.outstandingShares`],
          tab: "symbols",
        });
      }
    }
  }
  return out;
};

const comboLegRules: Rule = (draft) => {
  const universe = new Set(draft.symbolOrder);
  const out: Diagnostic[] = [];
  for (const combo of draft.combos) {
    if (combo.legs.length < 2 || combo.legs.length > 10) {
      out.push({
        id: "combo-leg-count",
        severity: "error",
        message: `Combo ${combo.comboId} must have between 2 and 10 legs (has ${combo.legs.length}).`,
        fieldPaths: [`combos.${combo.comboId}.legs`],
        tab: "combos",
      });
    }
    const seen = new Set<string>();
    for (const leg of combo.legs) {
      if (!universe.has(leg.symbol)) {
        out.push({
          id: "combo-leg-symbol-unknown",
          severity: "error",
          message: `Combo ${combo.comboId} has a leg for unknown symbol ${leg.symbol}.`,
          fieldPaths: [`combos.${combo.comboId}.legs`, "symbols"],
          tab: "combos",
        });
      }
      if (seen.has(leg.symbol)) {
        out.push({
          id: "combo-duplicate-leg-symbol",
          severity: "error",
          message: `Combo ${combo.comboId} uses symbol ${leg.symbol} in more than one leg.`,
          fieldPaths: [`combos.${combo.comboId}.legs`],
          tab: "combos",
        });
      }
      seen.add(leg.symbol);
    }
  }
  return out;
};

const apiGatewayRules: Rule = (draft) => {
  const out: Diagnostic[] = [];
  const owners = new Map<string, string>();
  for (const gw of draft.apiGateways) {
    for (const id of gw.gatewayIds) {
      const existing = owners.get(id);
      if (existing && existing !== gw.name) {
        out.push({
          id: "api-gateway-id-overlap",
          severity: "error",
          message: `ALF gateway ${id} is assigned to more than one API gateway instance (${existing}, ${gw.name}).`,
          fieldPaths: [`apiGateways.${existing}.gatewayIds`, `apiGateways.${gw.name}.gatewayIds`],
          tab: "gateways",
        });
      }
      owners.set(id, gw.name);
    }
    if (gw.gatewayIds.length > 0 && gw.credentials.length > 0) {
      out.push({
        id: "api-instance-credentials-mode-conflict",
        severity: "error",
        message: `API gateway ${gw.name} mixes multi-instance scoping (gatewayIds) with explicit credentials. Use one mode.`,
        fieldPaths: [`apiGateways.${gw.name}.gatewayIds`, `apiGateways.${gw.name}.credentials`],
        tab: "gateways",
      });
    }
  }
  return out;
};

const largeSymbolUniverse: Rule = (draft) =>
  draft.symbolOrder.length > 10
    ? [
        {
          id: "large-symbol-universe",
          severity: "info",
          message: `Large symbol universe (${draft.symbolOrder.length} symbols). Consider whether all participants need all symbols.`,
          fieldPaths: ["symbols"],
          tab: "basics",
        },
      ]
    : [];

/**
 * Every symbol must carry both a last_buy_price and a last_sell_price. These
 * seed the opening book and the collar static reference. Satisfied implicitly
 * when global MM mid-range seeding is enabled (the builder fills them in).
 */
const symbolMissingReferencePrices: Rule = (draft) => {
  const seededFromMm =
    draft.seeding.seedLastPricesFromMm && draft.seeding.mmMidRange !== undefined;
  if (seededFromMm) return [];
  const out: Diagnostic[] = [];
  for (const symbol of draft.symbolOrder) {
    const cfg = draft.symbols[symbol];
    if (!cfg) continue;
    const missingBuy = cfg.lastBuyPrice === undefined || cfg.lastBuyPrice === null;
    const missingSell = cfg.lastSellPrice === undefined || cfg.lastSellPrice === null;
    if (missingBuy || missingSell) {
      out.push({
        id: "symbol-missing-reference-prices",
        severity: "error",
        message: `Symbol ${symbol} must set both last_buy_price and last_sell_price (reference prices for the opening book and collar). Enter them on the symbol, or enable MM mid-range seeding.`,
        fieldPaths: [
          `symbols.${symbol}.lastBuyPrice`,
          `symbols.${symbol}.lastSellPrice`,
        ],
        tab: "basics",
      });
    }
  }
  return out;
};

/**
 * Explicit MM quotes must reference a configured MARKET_MAKER gateway, and each
 * quote must be internally consistent (bid < ask, positive quantities).
 */
const mmQuoteRules: Rule = (draft) => {
  const mmGatewayIds = new Set(
    draft.gateways.filter((g) => g.role === "MARKET_MAKER").map((g) => g.id),
  );
  const out: Diagnostic[] = [];
  for (const symbol of draft.symbolOrder) {
    const quotes = draft.symbols[symbol]?.marketMakerQuotes;
    if (!quotes || quotes.length === 0) continue;
    quotes.forEach((q, i) => {
      const path = `symbols.${symbol}.marketMakerQuotes.${i}`;
      if (!q.gatewayId || !mmGatewayIds.has(q.gatewayId)) {
        out.push({
          id: "mm-quote-gateway-invalid",
          severity: "error",
          message: `Symbol ${symbol} quote #${i + 1} references gateway "${q.gatewayId || "(none)"}", which is not a configured MARKET_MAKER gateway.`,
          fieldPaths: [`${path}.gatewayId`, "gateways"],
          tab: "symbols",
        });
      }
      if (q.bidPrice !== null && q.askPrice !== null && q.bidPrice >= q.askPrice) {
        out.push({
          id: "mm-quote-bid-ask",
          severity: "error",
          message: `Symbol ${symbol} quote #${i + 1} requires bid_price < ask_price.`,
          fieldPaths: [`${path}.bidPrice`, `${path}.askPrice`],
          tab: "symbols",
        });
      }
      if (q.bidQty <= 0 || q.askQty <= 0) {
        out.push({
          id: "mm-quote-qty",
          severity: "error",
          message: `Symbol ${symbol} quote #${i + 1} requires positive bid and ask quantities.`,
          fieldPaths: [`${path}.bidQty`, `${path}.askQty`],
          tab: "symbols",
        });
      }
    });
  }
  return out;
};

/**
 * The last buy/sell reference price should lie within the seeded opening quote
 * so the visible book, the last price, and the collar reference stay
 * consistent. Only checked for symbols carrying explicit priced quotes.
 */
const lastPriceWithinSeededQuote: Rule = (draft) => {
  const out: Diagnostic[] = [];
  for (const symbol of draft.symbolOrder) {
    const cfg = draft.symbols[symbol];
    if (!cfg?.marketMakerQuotes || cfg.marketMakerQuotes.length === 0) continue;
    const bids = cfg.marketMakerQuotes
      .map((q) => q.bidPrice)
      .filter((p): p is number => p !== null);
    const asks = cfg.marketMakerQuotes
      .map((q) => q.askPrice)
      .filter((p): p is number => p !== null);
    if (bids.length === 0 || asks.length === 0) continue;
    const bestBid = Math.max(...bids);
    const bestAsk = Math.min(...asks);
    const refs: number[] = [];
    if (cfg.lastBuyPrice !== undefined && cfg.lastBuyPrice !== null) refs.push(cfg.lastBuyPrice);
    if (cfg.lastSellPrice !== undefined && cfg.lastSellPrice !== null) refs.push(cfg.lastSellPrice);
    const outside = refs.some((r) => r < bestBid || r > bestAsk);
    if (outside) {
      out.push({
        id: "last-price-outside-seeded-quote",
        severity: "warning",
        message: `Symbol ${symbol}'s last buy/sell reference is outside its seeded opening quote [${bestBid}, ${bestAsk}]. The book, last price, and collar reference will disagree.`,
        fieldPaths: [`symbols.${symbol}.lastBuyPrice`, `symbols.${symbol}.lastSellPrice`],
        tab: "symbols",
      });
    }
  }
  return out;
};

/** A listed symbol should declare its issued share count (its "IPO" size). */
const symbolMissingOutstandingShares: Rule = (draft) => {
  // Index constituents are covered by the more specific constituent rule.
  const constituents = new Set<string>();
  for (const idx of draft.indices) for (const c of idx.constituents) constituents.add(c);
  const out: Diagnostic[] = [];
  for (const symbol of draft.symbolOrder) {
    const cfg = draft.symbols[symbol];
    if (!cfg || constituents.has(symbol)) continue;
    if (cfg.outstandingShares === undefined) {
      out.push({
        id: "symbol-missing-outstanding-shares",
        severity: "warning",
        message: `Symbol ${symbol} has no outstanding_shares set. Set the issued share count (used for market cap and index weighting).`,
        fieldPaths: [`symbols.${symbol}.outstandingShares`],
        tab: "symbols",
      });
    }
  }
  return out;
};

const RULES: Rule[] = [
  undefinedRiskLevel,
  mmGatewayNeedsSeeds,
  enforcementDisabled,
  tickDecimalsZero,
  singleGateway,
  noAdminGateway,
  sessionsDefaultSchedule,
  seedFromMmWithoutRange,
  portCollision,
  scheduleOrder,
  indexMissingConstituents,
  indexConstituentNotInUniverse,
  outstandingSharesMissingForConstituent,
  comboLegRules,
  apiGatewayRules,
  largeSymbolUniverse,
  symbolMissingReferencePrices,
  mmQuoteRules,
  lastPriceWithinSeededQuote,
  symbolMissingOutstandingShares,
];

/** Run every rule against the draft and return the aggregated diagnostics. */
export function evaluateDiagnostics(draft: EngineConfigDraft): Diagnostic[] {
  return RULES.flatMap((rule) => rule(draft));
}

export function hasErrors(diagnostics: Diagnostic[]): boolean {
  return diagnostics.some((d) => d.severity === "error");
}

export function countBySeverity(diagnostics: Diagnostic[]): {
  error: number;
  warning: number;
  info: number;
} {
  return {
    error: diagnostics.filter((d) => d.severity === "error").length,
    warning: diagnostics.filter((d) => d.severity === "warning").length,
    info: diagnostics.filter((d) => d.severity === "info").length,
  };
}
