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
  engineConfigDraftSchema,
  writtenLastPrices,
  writtenMmQuotes,
  type Diagnostic,
  type EngineConfigDraft,
  type Schedule,
} from "@edumatcher/schema";

type Rule = (draft: EngineConfigDraft) => Diagnostic[];

const TIME_RE = /^([01]\d|2[0-3]):[0-5]\d$/;

function definedRiskLevels(draft: EngineConfigDraft): Set<string> {
  const levels = new Set<string>(Object.keys(draft.riskControls.levels));
  if (effectiveDefaultCollar(draft)) levels.add("DEFAULT");
  return levels;
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

/**
 * Every written quote seed needs both prices: the engine loader refuses a
 * `bid_price`/`ask_price` of null. Covers explicit quotes left blank and the
 * null-price stubs written when no mid-range is set.
 */
const mmQuotePricesMissing: Rule = (draft) => {
  const out: Diagnostic[] = [];
  for (const symbol of draft.symbolOrder) {
    const cfg = draft.symbols[symbol];
    if (!cfg) continue;
    writtenMmQuotes(draft, cfg).forEach((q, i) => {
      if (q.bidPrice !== null && q.askPrice !== null) return;
      const explicit = q.origin === "explicit";
      out.push({
        id: "mm-quote-price-missing",
        severity: "error",
        message: explicit
          ? `Symbol ${symbol} quote #${i + 1} (${q.gatewayId}) has no ${q.bidPrice === null ? "bid" : "ask"} price. The engine refuses a quote seed without both prices.`
          : `Symbol ${symbol} would get a quote stub for ${q.gatewayId} with null prices, which the engine refuses. Set a seed mid-range, add explicit quotes for the symbol, or turn off "Require MM seed quotes".`,
        fieldPaths: explicit
          ? [
              `symbols.${symbol}.marketMakerQuotes.${i}.bidPrice`,
              `symbols.${symbol}.marketMakerQuotes.${i}.askPrice`,
            ]
          : ["seeding.mmMidRange", "requireMmSeedQuotes"],
        tab: explicit ? "symbols" : "market-maker",
      });
    });
  }
  return out;
};

/** CV1 / CV2 / CV14: the ALF allowlist. */
const gatewayIdRules: Rule = (draft) => {
  const out: Diagnostic[] = [];
  if (draft.gateways.length === 0) {
    out.push({
      id: "no-gateways",
      severity: "error",
      message: "At least one ALF gateway is required (gateways.alf must not be empty).",
      fieldPaths: ["gateways"],
      tab: "basics",
    });
  }
  const ids = draft.gateways.map((g) => g.id);
  const seen = new Set<string>();
  for (const id of ids) {
    if (seen.has(id)) {
      out.push({
        id: "duplicate-gateway-id",
        severity: "error",
        message: `Gateway id ${id} is used more than once.`,
        fieldPaths: ["gateways"],
        tab: "basics",
      });
    }
    seen.add(id);
  }
  const unique = [...seen].filter((id) => id.length > 0);
  for (const a of unique) {
    for (const b of unique) {
      if (a !== b && b.startsWith(a)) {
        out.push({
          id: "gateway-id-prefix",
          severity: "error",
          message: `Gateway id ${a} is a prefix of ${b}. pm-alf-gwy and pm-balf-gwy refuse ids that prefix one another.`,
          fieldPaths: ["gateways"],
          tab: "basics",
        });
      }
    }
  }
  return out;
};

/** CV7 and the DEFAULT-level clash. */
const riskLevelRules: Rule = (draft) => {
  const out: Diagnostic[] = [];
  const rc = draft.riskControls;
  if (rc.defaultLevel && !definedRiskLevels(draft).has(rc.defaultLevel)) {
    out.push({
      id: "undefined-default-level",
      severity: "error",
      message: `Default risk level ${rc.defaultLevel} is not defined. Define it or choose another default.`,
      fieldPaths: ["riskControls.defaultLevel"],
      tab: "risk",
    });
  }
  if (effectiveDefaultCollar(draft) && rc.levels.DEFAULT !== undefined) {
    out.push({
      id: "default-level-clash",
      severity: "error",
      message:
        "A named risk level DEFAULT exists alongside the global collar, which is written as level DEFAULT too. Rename the named level or clear the global collar.",
      fieldPaths: ["riskControls.levels", "riskControls.globalStaticBandPct"],
      tab: "risk",
    });
  }
  return out;
};

/** A symbol-only circuit-breaker level must set its own shift. */
const symbolCbLevelShift: Rule = (draft) => {
  const cb = draft.circuitBreakerDefaults;
  const out: Diagnostic[] = [];
  for (const symbol of draft.symbolOrder) {
    const levels = draft.symbols[symbol]?.circuitBreaker?.levels ?? {};
    for (const [name, lvl] of Object.entries(levels)) {
      const inherited = cb.include && cb.levels[name] !== undefined;
      if (!inherited && lvl.priceShiftPct === undefined) {
        out.push({
          id: "cb-level-shift-missing",
          severity: "error",
          message: `Symbol ${symbol} circuit-breaker level ${name} is not in the exchange ladder, so it must set its own shift %. The engine requires price_shift_pct.`,
          fieldPaths: [`symbols.${symbol}.circuitBreaker.levels`],
          tab: "symbols",
        });
      }
    }
  }
  return out;
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
  const isDefaultBlock = (block: Schedule | undefined): boolean =>
    !!block &&
    block.preOpen === "09:00" &&
    block.openingAuction === "09:25" &&
    block.continuous === "09:30" &&
    block.closingAuction === "16:00" &&
    block.closingEnd === "16:05";
  return (
    isDefaultBlock(s.weekdays) &&
    !s.mon &&
    !s.tue &&
    !s.wed &&
    !s.thu &&
    !s.fri &&
    !s.sat &&
    !s.sun &&
    !s.weekend &&
    !s.holidays
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

/**
 * Field law from the Zod schema (spec §4–§6 ranges and enums), reported as
 * diagnostics so it blocks export like every other error. Sections that are
 * not written are skipped — their values never reach the file.
 */
const SECTION_TABS: Record<string, string> = {
  symbols: "symbols",
  gateways: "basics",
  country: "basics",
  tickDecimals: "symbols",
  riskControls: "risk",
  circuitBreakerDefaults: "circuit-breakers",
  mmObligationDefaults: "market-maker",
  seeding: "market-maker",
  indices: "indices",
  combos: "combos",
  alfGateway: "gateways",
  postTradeGateway: "gateways",
  marketDataGateway: "gateways",
  balfGateway: "gateways",
  dcGateway: "gateways",
  logServer: "gateways",
  apiGateways: "gateways",
  schedule: "sessions",
  output: "review",
};

const schemaRule: Rule = (draft) => {
  const result = engineConfigDraftSchema.safeParse(draft);
  if (result.success) return [];
  const omitted = new Set<string>();
  if (!draft.alfGateway.include) omitted.add("alfGateway");
  if (!draft.postTradeGateway.include) omitted.add("postTradeGateway");
  if (!draft.marketDataGateway.include) omitted.add("marketDataGateway");
  if (!draft.balfGateway.include) omitted.add("balfGateway");
  if (!draft.dcGateway.include) omitted.add("dcGateway");
  if (!draft.logServer.include) omitted.add("logServer");
  if (!draft.circuitBreakerDefaults.include) omitted.add("circuitBreakerDefaults");
  if (!draft.emitSchedule) omitted.add("schedule");
  const out: Diagnostic[] = [];
  for (const issue of result.error.issues) {
    const head = String(issue.path[0] ?? "");
    if (omitted.has(head)) continue;
    const path = issue.path.map(String).join(".");
    out.push({
      id: "schema",
      severity: "error",
      message: `${path}: ${issue.message}`,
      fieldPaths: [path],
      tab: SECTION_TABS[head] ?? "engine-tuning",
    });
  }
  return out;
};

const WILDCARD_ADDRESSES = new Set(["0.0.0.0", "::"]);

function addressesCollide(a: string, b: string): boolean {
  if (a === b) return true;
  return WILDCARD_ADDRESSES.has(a) || WILDCARD_ADDRESSES.has(b);
}

/** warnings.py: _port_collision_warnings. */
const portCollision: Rule = (draft) => {
  const endpoints: Array<{ label: string; address: string; port: number; path: string }> = [];
  if (draft.alfGateway.include && draft.alfGateway.enabled) {
    endpoints.push({
      label: `alf_gateway '${draft.alfGateway.name}'`,
      address: draft.alfGateway.bindAddress,
      port: draft.alfGateway.port,
      path: "alfGateway.port",
    });
  }
  if (draft.postTradeGateway.include) {
    endpoints.push({
      label: `post_trade_gateway '${draft.postTradeGateway.name}'`,
      address: draft.postTradeGateway.bindAddress,
      port: draft.postTradeGateway.port,
      path: "postTradeGateway.port",
    });
  }
  if (draft.marketDataGateway.include && draft.marketDataGateway.enabled) {
    endpoints.push({
      label: `market_data_gateway '${draft.marketDataGateway.name}'`,
      address: draft.marketDataGateway.bindAddress,
      port: draft.marketDataGateway.port,
      path: "marketDataGateway.port",
    });
  }
  if (draft.balfGateway.include && draft.balfGateway.enabled) {
    endpoints.push({
      label: `balf_gateway '${draft.balfGateway.name}'`,
      address: draft.balfGateway.bindAddress,
      port: draft.balfGateway.port,
      path: "balfGateway.port",
    });
  }
  if (draft.dcGateway.include) {
    endpoints.push({
      label: `dc_gateway '${draft.dcGateway.name}'`,
      address: draft.dcGateway.bindAddress,
      port: draft.dcGateway.port,
      path: "dcGateway.port",
    });
  }
  if (draft.logServer.include && draft.logServer.enabled) {
    endpoints.push({
      label: `log_server '${draft.logServer.name}'`,
      address: draft.logServer.bindAddress,
      port: draft.logServer.port,
      path: "logServer.port",
    });
    // pm-log-srv is the only section that binds more than one listener: the
    // LALF-PS ZeroMQ sockets sit alongside its LALF/TCP port and are just as
    // capable of colliding with another gateway. Skipped when the interface
    // is off, since then nothing is bound.
    if (draft.logServer.pubsubEnabled) {
      endpoints.push({
        label: `log_server '${draft.logServer.name}' LALF-PS PUB`,
        address: draft.logServer.bindAddress,
        port: draft.logServer.pubPort,
        path: "logServer.pubPort",
      });
      endpoints.push({
        label: `log_server '${draft.logServer.name}' LALF-PS PULL`,
        address: draft.logServer.bindAddress,
        port: draft.logServer.pullPort,
        path: "logServer.pullPort",
      });
    }
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
      // Two of pm-log-srv's own three ports colliding is fatal rather than
      // merely suspect, and logServerPubsubPorts reports it as an error —
      // so skip the pair here instead of also warning about it.
      if (a.path.startsWith("logServer.") && b.path.startsWith("logServer.")) {
        continue;
      }
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

/**
 * layer2_schema.py: S102 — pm-log-srv's three listeners must be distinct.
 *
 * Reported as an error, not a warning: unlike two *different* gateways
 * sharing a port (which at least starts, then fails on the second bind),
 * pm-log-srv validates this at config-load time and refuses to start at all.
 */
const logServerPubsubPorts: Rule = (draft) => {
  const g = draft.logServer;
  if (!g.include || !g.pubsubEnabled) return [];

  const named: Array<[string, string, number]> = [
    ["port", "LALF/TCP", g.port],
    ["pubPort", "LALF-PS PUB", g.pubPort],
    ["pullPort", "LALF-PS PULL", g.pullPort],
  ];

  const out: Diagnostic[] = [];
  for (let i = 0; i < named.length; i += 1) {
    for (let j = i + 1; j < named.length; j += 1) {
      const [aKey, aName, aPort] = named[i]!;
      const [bKey, bName, bPort] = named[j]!;
      if (aPort !== bPort) continue;
      out.push({
        id: "log-server-port-overlap",
        severity: "error",
        message: `pm-log-srv's ${aName} and ${bName} listeners are both on port ${aPort}. It binds all three of port, pub port and pull port, so they must be different — the server refuses to start otherwise.`,
        fieldPaths: [`logServer.${aKey}`, `logServer.${bKey}`],
        tab: "gateways",
      });
    }
  }
  return out;
};

/**
 * layer2_schema.py: S103 — the LALF-PS lease ceiling cannot sit below the
 * default lease it is meant to cap.
 */
const logServerLeaseBounds: Rule = (draft) => {
  const g = draft.logServer;
  if (!g.include || !g.pubsubEnabled) return [];
  if (g.maxLeaseSec >= g.leaseSec) return [];
  return [
    {
      id: "log-server-lease-bounds",
      severity: "error",
      message: `Max lease (${g.maxLeaseSec}s) is below the default lease (${g.leaseSec}s). Max lease is the ceiling applied to a subscriber's request, so a value below the default the server itself grants is contradictory.`,
      fieldPaths: ["logServer.maxLeaseSec", "logServer.leaseSec"],
      tab: "gateways",
    },
  ];
};

/**
 * Advisory: a notify interval far above the lease means a NOTIFY-mode
 * subscriber could be reaped between ticks.
 *
 * Not an error — the server accepts it — but it makes the interface behave
 * in a way nobody intends: the subscriber has to renew on a timer entirely
 * unrelated to the ticks it is actually waiting for, and any UI that
 * naively renews "when something arrives" would silently expire.
 */
const logServerNotifyVsLease: Rule = (draft) => {
  const g = draft.logServer;
  if (!g.include || !g.pubsubEnabled) return [];
  if (g.notifyIntervalMs <= g.leaseSec * 1000) return [];
  return [
    {
      id: "log-server-notify-exceeds-lease",
      severity: "warning",
      message: `Notify interval (${g.notifyIntervalMs}ms) is longer than the lease (${g.leaseSec}s). A NOTIFY subscriber can be reaped before its next tick arrives, so it must renew on an independent timer.`,
      fieldPaths: ["logServer.notifyIntervalMs", "logServer.leaseSec"],
      tab: "gateways",
    },
  ];
};

const SCHEDULE_BLOCK_KEYS = [
  "weekdays",
  "mon",
  "tue",
  "wed",
  "thu",
  "fri",
  "sat",
  "sun",
  "weekend",
  "holidays",
] as const;

/**
 * cli.py: _validate_schedule_order (fatal in CLI), and layer3_semantic.py's
 * M006/M021 -- run once per present block now that each
 * weekdays/day/weekend/holidays block is independently a full day's
 * timeline, not once against one flat dict. Completeness (M024) has no
 * equivalent here: a `Schedule` in the draft always carries all five
 * fields by type, so an incomplete block cannot occur.
 */
const scheduleOrder: Rule = (draft) => {
  // pm-scheduler reads a written schedule even with sessions disabled.
  if (!draft.emitSchedule) return [];
  const out: Diagnostic[] = [];
  for (const key of SCHEDULE_BLOCK_KEYS) {
    const block = draft.schedule[key];
    if (!block) continue;
    const ordered: Array<[string, string]> = [
      ["preOpen", block.preOpen],
      ["openingAuction", block.openingAuction],
      ["continuous", block.continuous],
      ["closingAuction", block.closingAuction],
      ["closingEnd", block.closingEnd],
    ];
    const paths = ordered.map(([k]) => `schedule.${key}.${k}`);
    const invalid = ordered.find(([, v]) => !TIME_RE.test(v));
    if (invalid) {
      out.push({
        id: "schedule-out-of-order",
        severity: "error",
        message: `Invalid schedule time '${invalid[1]}' in '${key}'. Expected HH:MM (24-hour).`,
        fieldPaths: paths,
        tab: "sessions",
      });
      continue;
    }
    const minutes = ordered.map(([, v]) => {
      const [h, m] = v.split(":").map(Number);
      return h! * 60 + m!;
    });
    for (let i = 1; i < minutes.length; i += 1) {
      if (minutes[i]! <= minutes[i - 1]!) {
        out.push({
          id: "schedule-out-of-order",
          severity: "error",
          message: `Schedule times in '${key}' must be strictly increasing: pre_open < opening_auction < continuous < closing_auction < closing_end.`,
          fieldPaths: paths,
          tab: "sessions",
        });
        break;
      }
    }
  }
  return out;
};

/**
 * cverifier M028 / config_loader: 'weekend' and an individual 'sat'/'sun'
 * are mutually exclusive. The GUI's own Schedule editor never sets sat/sun
 * individually (it only exposes weekdays/weekend/holidays), so this is only
 * reachable via an imported file -- but import is tolerant (it does not
 * reject the file), so this is what actually flags the conflict.
 */
const scheduleWeekendConflict: Rule = (draft) => {
  const s = draft.schedule;
  if (!s.weekend || !(s.sat || s.sun)) return [];
  return [
    {
      id: "schedule-weekend-conflict",
      severity: "error",
      message:
        "'weekend' and 'sat'/'sun' are mutually exclusive -- use one or the other, not both.",
      fieldPaths: ["schedule.weekend", "schedule.sat", "schedule.sun"],
      tab: "sessions",
    },
  ];
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

/** CV10: at most 5 indices, unique ids. */
const indexIdRules: Rule = (draft) => {
  const out: Diagnostic[] = [];
  if (draft.indices.length > 5) {
    out.push({
      id: "too-many-indices",
      severity: "error",
      message: `At most 5 indices are supported (has ${draft.indices.length}).`,
      fieldPaths: ["indices"],
      tab: "indices",
    });
  }
  const seen = new Set<string>();
  for (const idx of draft.indices) {
    if (seen.has(idx.id)) {
      out.push({
        id: "duplicate-index-id",
        severity: "error",
        message: `Index id ${idx.id} is used more than once.`,
        fieldPaths: [`indices.${idx.id}.id`],
        tab: "indices",
      });
    }
    seen.add(idx.id);
  }
  return out;
};

const indexConstituentNotInUniverse: Rule = (draft) => {
  const universe = new Set(draft.symbolOrder);
  const out: Diagnostic[] = [];
  for (const idx of draft.indices) {
    if (new Set(idx.constituents).size !== idx.constituents.length) {
      out.push({
        id: "index-duplicate-constituent",
        severity: "error",
        message: `Index ${idx.id} lists a constituent more than once.`,
        fieldPaths: [`indices.${idx.id}.constituents`],
        tab: "indices",
      });
    }
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
          severity: "error",
          message: `Symbol ${symbol} is an index constituent but has no outstanding_shares set. The engine refuses an index constituent without it.`,
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
    combo.legs.forEach((leg, li) => {
      if (PRICED_ORDER_TYPES.has(leg.orderType) && (leg.price === null || leg.price === undefined)) {
        out.push({
          id: "combo-leg-price-missing",
          severity: "error",
          message: `Combo ${combo.comboId} leg ${li + 1} is a ${leg.orderType} order and needs a price.`,
          fieldPaths: [`combos.${combo.comboId}.legs.${li}.price`],
          tab: "combos",
        });
      }
    });
  }
  return out;
};

/** Leg order types that carry a limit price (spec §4.5 ComboLegSpec.price). */
const PRICED_ORDER_TYPES = new Set(["LIMIT", "FOK", "STOP_LIMIT", "ICEBERG"]);

/** CV15 and the api_gateways loader's own checks. */
const apiGatewayRules: Rule = (draft) => {
  const out: Diagnostic[] = [];
  const names = new Set<string>();
  const owners = new Map<string, string>();
  const alfIds = new Set(draft.gateways.map((g) => g.id));
  for (const gw of draft.apiGateways) {
    if (names.has(gw.name)) {
      out.push({
        id: "api-instance-name-duplicate",
        severity: "error",
        message: `API gateway instance name ${gw.name} is used more than once; only one would be written.`,
        fieldPaths: [`apiGateways.${gw.name}.name`],
        tab: "gateways",
      });
    }
    names.add(gw.name);
    const keys = new Set<string>();
    for (const c of gw.credentials) {
      if (keys.has(c.apiKey)) {
        out.push({
          id: "api-key-duplicate",
          severity: "error",
          message: `API gateway ${gw.name} lists the same api_key more than once.`,
          fieldPaths: [`apiGateways.${gw.name}.credentials`],
          tab: "gateways",
        });
      }
      keys.add(c.apiKey);
      if (c.gatewayId === null) continue;
      if (!alfIds.has(c.gatewayId)) {
        out.push({
          id: "api-credential-gateway-unknown",
          severity: "warning",
          message: `API gateway ${gw.name} has a credential for ${c.gatewayId}, which is not a configured ALF gateway.`,
          fieldPaths: [`apiGateways.${gw.name}.credentials`],
          tab: "gateways",
        });
      }
      const existing = owners.get(c.gatewayId);
      if (existing !== undefined && existing !== gw.name) {
        out.push({
          id: "api-gateway-id-overlap",
          severity: "error",
          message: `ALF gateway ${c.gatewayId} has credentials in more than one API gateway instance (${existing}, ${gw.name}).`,
          fieldPaths: [`apiGateways.${existing}.credentials`, `apiGateways.${gw.name}.credentials`],
          tab: "gateways",
        });
      }
      owners.set(c.gatewayId, gw.name);
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
  const out: Diagnostic[] = [];
  for (const symbol of draft.symbolOrder) {
    const cfg = draft.symbols[symbol];
    if (!cfg) continue;
    // Judged on what is written, so mid-range seeding counts only where it
    // actually fills the prices in.
    const written = writtenLastPrices(draft, cfg);
    const missingBuy = written.lastBuyPrice === undefined || written.lastBuyPrice === null;
    const missingSell = written.lastSellPrice === undefined || written.lastSellPrice === null;
    if (missingBuy || missingSell) {
      out.push({
        id: "symbol-missing-reference-prices",
        // A warning, not an error: the spec makes both prices optional and
        // the *-nomm example configs omit them on purpose (an empty book).
        severity: "warning",
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

/**
 * A gateway's per-symbol MM obligation override should reference a configured
 * symbol. The engine tolerates unknown keys, but they are almost always a typo.
 */
const gatewayMmObligationUnknownSymbol: Rule = (draft) => {
  const universe = new Set(draft.symbolOrder);
  const out: Diagnostic[] = [];
  for (const gw of draft.gateways) {
    if (!gw.mmObligations) continue;
    for (const sym of Object.keys(gw.mmObligations)) {
      if (!universe.has(sym)) {
        out.push({
          id: "gateway-mm-obligation-unknown-symbol",
          severity: "warning",
          message: `Gateway ${gw.id} has a market-maker obligation override for unknown symbol ${sym}. Add the symbol or remove the override.`,
          fieldPaths: ["gateways", "symbols"],
          tab: "basics",
        });
      }
    }
  }
  return out;
};

/**
 * layer2_schema.py S078: every price in the file is display money the engine
 * converts to integer ticks, and it refuses one that is not a whole number of
 * them. The GUI used to round these off on export, which turned a typo into a
 * silently different price; it now writes what was typed, so the typo has to
 * be reported here instead.
 */
function offGrid(price: number, tickDecimals: number): boolean {
  const scaled = price * Math.pow(10, tickDecimals);
  return Math.abs(scaled - Math.round(scaled)) > 1e-6;
}

const priceTickGrid: Rule = (draft) => {
  const out: Diagnostic[] = [];
  const decimalsOf = (symbol: string): number =>
    draft.symbols[symbol]?.tickDecimals ?? draft.tickDecimals;
  const check = (
    price: number | null | undefined,
    symbol: string,
    label: string,
    fieldPath: string,
    tab: Diagnostic["tab"],
  ): void => {
    if (price === null || price === undefined) return;
    const td = decimalsOf(symbol);
    if (!offGrid(price, td)) return;
    out.push({
      id: "price-off-tick-grid",
      severity: "error",
      message:
        `${label} ${price} is not a multiple of ${symbol}'s tick size ` +
        `${Math.pow(10, -td).toFixed(td)} (tick_decimals=${td}).`,
      fieldPaths: [fieldPath],
      tab,
    });
  };

  for (const symbol of draft.symbolOrder) {
    const cfg = draft.symbols[symbol];
    if (!cfg) continue;
    const sp = `symbols.${symbol}`;
    const lbl = `Symbol ${symbol}`;
    check(cfg.lastBuyPrice, symbol, `${lbl} last_buy_price`, `${sp}.lastBuyPrice`, "symbols");
    check(cfg.lastSellPrice, symbol, `${lbl} last_sell_price`, `${sp}.lastSellPrice`, "symbols");
    (cfg.marketMakerQuotes ?? []).forEach((q, i) => {
      const qp = `${sp}.marketMakerQuotes.${i}`;
      const qlbl = `${lbl} quote #${i + 1}`;
      check(q.bidPrice, symbol, `${qlbl} bid_price`, `${qp}.bidPrice`, "symbols");
      check(q.askPrice, symbol, `${qlbl} ask_price`, `${qp}.askPrice`, "symbols");
    });
  }
  for (const combo of draft.combos) {
    combo.legs.forEach((leg, li) => {
      const lp = `combos.${combo.comboId}.legs.${li}`;
      const llbl = `Combo ${combo.comboId} leg ${li + 1}`;
      check(leg.price, leg.symbol, `${llbl} price`, `${lp}.price`, "combos");
      check(leg.stopPrice, leg.symbol, `${llbl} stop_price`, `${lp}.stopPrice`, "combos");
    });
  }
  return out;
};

const RULES: Rule[] = [
  schemaRule,
  gatewayIdRules,
  riskLevelRules,
  symbolCbLevelShift,
  indexIdRules,
  undefinedRiskLevel,
  gatewayMmObligationUnknownSymbol,
  mmQuotePricesMissing,
  enforcementDisabled,
  tickDecimalsZero,
  singleGateway,
  noAdminGateway,
  sessionsDefaultSchedule,
  seedFromMmWithoutRange,
  portCollision,
  logServerPubsubPorts,
  logServerLeaseBounds,
  logServerNotifyVsLease,
  scheduleOrder,
  scheduleWeekendConflict,
  indexMissingConstituents,
  indexConstituentNotInUniverse,
  outstandingSharesMissingForConstituent,
  comboLegRules,
  apiGatewayRules,
  largeSymbolUniverse,
  symbolMissingReferencePrices,
  mmQuoteRules,
  priceTickGrid,
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
