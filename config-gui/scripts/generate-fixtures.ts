/**
 * Generates representative engine_config.yaml fixtures from drafts and writes
 * them to a target directory. Used by the golden-file cross-language check
 * (design §12.4): the emitted files are piped through the real Python
 * `load_engine_config()` to prove GUI output is parser-valid.
 *
 * Usage: tsx scripts/generate-fixtures.ts <outDir>
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import {
  createBlankDraft,
  createGateway,
  createIndex,
  type EngineConfigDraft,
} from "@edumatcher/schema";
import { generateYaml } from "@edumatcher/yaml-codec";

function minimalTwoTrader(): EngineConfigDraft {
  const d = createBlankDraft();
  d.symbols = { AAPL: { tickDecimals: 2 } };
  d.symbolOrder = ["AAPL"];
  d.gateways = [createGateway("TRADER01"), createGateway("TRADER02"), createGateway("OPS01", "ADMIN")];
  return d;
}

function classroomWithSchedule(): EngineConfigDraft {
  const d = createBlankDraft();
  d.symbols = {
    AAPL: { tickDecimals: 2, level: "CORE", outstandingShares: 15_400_000_000 },
    MSFT: { tickDecimals: 2, level: "CORE", outstandingShares: 7_400_000_000 },
    TSLA: { tickDecimals: 2 },
  };
  d.symbolOrder = ["AAPL", "MSFT", "TSLA"];
  d.gateways = [
    createGateway("TRADER01"),
    createGateway("TRADER02"),
    createGateway("OPS01", "ADMIN"),
    createGateway("MM01", "MARKET_MAKER"),
  ];
  d.sessionsEnabled = true;
  d.riskControls.globalStaticBandPct = 0.2;
  d.riskControls.globalDynamicBandPct = 0.02;
  d.riskControls.levels = {
    CORE: { staticBandPct: 0.18, dynamicBandPct: 0.02 },
    HIGH_BETA: { staticBandPct: 0.12, dynamicBandPct: 0.04 },
  };
  d.mmObligationDefaults = { enforceMmObligation: true, mmMaxSpreadTicks: 12, mmMinQty: 200 };
  d.seeding.mmMidRange = { min: 20, max: 300 };
  d.seeding.seedLastPricesFromMm = true;
  d.postTradeGateway.enabled = true;
  d.marketDataGateway.enabled = true;
  return d;
}

function expertFull(): EngineConfigDraft {
  const d = classroomWithSchedule();
  const edu = createIndex("EDU100");
  edu.constituents = ["AAPL", "MSFT"];
  d.indices = [edu];
  d.combos = [
    {
      comboId: "SEED-PAIR",
      comboType: "AON",
      tif: "DAY",
      legs: [
        { symbol: "AAPL", side: "BUY", orderType: "LIMIT", quantity: 100, price: 209.5, smpAction: "NONE" },
        { symbol: "MSFT", side: "SELL", orderType: "LIMIT", quantity: 50, price: 415.5, smpAction: "NONE" },
      ],
    },
  ];
  d.balfGateway.enabled = true;
  d.output.commentDefaultFields = true;

  // P1.1: non-default quote refresh policy on the market maker.
  const mm = d.gateways.find((g) => g.id === "MM01");
  if (mm) mm.quoteRefreshPolicy = "INACTIVATE_ON_FULL_FILL";

  // P1.4: per-symbol circuit-breaker reference-window override.
  if (d.symbols.AAPL) {
    d.symbols.AAPL.circuitBreaker = { referenceWindowNs: 600_000_000_000, levels: {} };
  }

  // P1.2/P1.3: per-gateway MM obligation overrides (flat + per-symbol).
  if (mm) {
    mm.enforceMmObligation = true;
    mm.mmMaxSpreadTicks = 8;
    mm.mmMinQty = 300;
    mm.mmObligations = {
      AAPL: { enforceMmObligation: true, maxSpreadTicks: 6, minQty: 500 },
    };
  }
  return d;
}

const outDir = process.argv[2] ?? join(process.cwd(), ".fixtures");
mkdirSync(outDir, { recursive: true });

const fixtures: Record<string, EngineConfigDraft> = {
  "minimal-two-trader.yaml": minimalTwoTrader(),
  "classroom-schedule.yaml": classroomWithSchedule(),
  "expert-full.yaml": expertFull(),
};

for (const [name, draft] of Object.entries(fixtures)) {
  const yaml = generateYaml(draft, { generatedDate: "2026-07-09" });
  writeFileSync(join(outDir, name), yaml, "utf8");
  console.log(`wrote ${join(outDir, name)}`);
}
