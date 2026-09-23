/**
 * Import → export must not change what a file means (990-app-config-spec.md).
 *
 * Every case here was a real defect: an absent key taking the GUI's new-config
 * default instead of the loader's, a value dropped or invented on the way
 * through, or a section left out where the spec defaults it to enabled.
 */

import { describe, expect, it } from "vitest";
import yaml from "js-yaml";
import {
  buildConfigDocument,
  generateYaml,
  parseYamlToDraft,
} from "../src/index.js";

type Doc = Record<string, any>;

function roundTrip(text: string): Doc {
  const { draft } = parseYamlToDraft(text);
  return buildConfigDocument(draft) as Doc;
}

const MINIMAL =
  "gateways:\n  alf:\n    - id: TRADER01\nsymbols:\n  AAPL:\n    tick_decimals: 2\n";

describe("absent keys take the loader's defaults", () => {
  it("keeps sessions_enabled true when the key is omitted", () => {
    expect(roundTrip(MINIMAL).sessions_enabled).toBe(true);
  });

  it("keeps mm_max_spread_ticks at the loader default (10), not the GUI's 20", () => {
    const doc = roundTrip(
      MINIMAL + "mm_obligation_defaults:\n  enforce_mm_obligation: true\n",
    );
    expect(doc.mm_obligation_defaults.mm_max_spread_ticks).toBe(10);
  });

  it("does not add circuit_breaker_defaults to a file that has none", () => {
    expect(roundTrip(MINIMAL)).not.toHaveProperty("circuit_breaker_defaults");
  });

  it("does not add a schedule to a file that has none", () => {
    const doc = roundTrip(MINIMAL + "sessions_enabled: true\n");
    expect(doc).not.toHaveProperty("schedule");
  });

  it("reads require_mm_seed_quotes and writes no stubs when it is false", () => {
    const doc = roundTrip(
      MINIMAL.replace(
        "- id: TRADER01",
        "- id: TRADER01\n    - id: MM01\n      role: MARKET_MAKER",
      ) + "require_mm_seed_quotes: false\n",
    );
    expect(doc.require_mm_seed_quotes).toBe(false);
    expect(doc.symbols.AAPL).not.toHaveProperty("market_maker_quotes");
  });
});

describe("nothing is dropped or invented", () => {
  it("keeps a gateway's smp_action", () => {
    const doc = roundTrip(
      MINIMAL.replace(
        "- id: TRADER01",
        "- id: TRADER01\n      smp_action: CANCEL_BOTH",
      ),
    );
    expect(doc.gateways.alf[0].smp_action).toBe("CANCEL_BOTH");
  });

  it("keeps an omitted combo-leg smp_action omitted (gateway default), and an explicit NONE", () => {
    const text =
      MINIMAL +
      "  MSFT:\n    tick_decimals: 2\n" +
      "market_maker_combos:\n  - combo_id: C1\n    legs:\n" +
      "      - {symbol: AAPL, side: BUY, order_type: LIMIT, quantity: 1, price: 1.0}\n" +
      "      - {symbol: MSFT, side: SELL, order_type: LIMIT, quantity: 1, price: 2.0, smp_action: NONE}\n";
    const legs = roundTrip(text).market_maker_combos[0].legs;
    expect(legs[0]).not.toHaveProperty("smp_action");
    expect(legs[1].smp_action).toBe("NONE");
  });

  it("keeps circuit_breaker_defaults that carry no levels, without inventing a ladder", () => {
    const doc = roundTrip(
      MINIMAL +
        "circuit_breaker_defaults:\n  reference_window_ns: 90000000000\n",
    );
    expect(doc.circuit_breaker_defaults.reference_window_ns).toBe(
      90_000_000_000,
    );
    expect(doc.circuit_breaker_defaults).not.toHaveProperty("levels");
  });

  it("keeps circuit_breaker_defaults when enforcement is off", () => {
    const doc = roundTrip(
      MINIMAL +
        "enforce_circuit_breakers: false\ncircuit_breaker_defaults:\n  levels:\n    L1: {price_shift_pct: 0.1, halt_duration_ns: null}\n",
    );
    expect(doc.circuit_breaker_defaults.levels).toEqual({
      L1: { price_shift_pct: 0.1, halt_duration_ns: null },
    });
  });

  it("keeps a schedule when sessions are disabled (pm-scheduler still reads it)", () => {
    const doc = roundTrip(
      MINIMAL + "sessions_enabled: false\nschedule:\n  weekdays:\n    pre_open: '08:00'\n",
    );
    expect(doc.schedule.weekdays.pre_open).toBe("08:00");
  });

  it("round-trips a weekdays-only shortcut byte-for-byte", () => {
    const doc = roundTrip(
      MINIMAL +
        "schedule:\n  weekdays:\n    pre_open: '09:00'\n    opening_auction_start: '09:25'\n    continuous_start: '09:30'\n    closing_auction_start: '16:00'\n    closing_auction_end: '16:05'\n",
    );
    expect(doc.schedule).toEqual({
      weekdays: {
        pre_open: "09:00",
        opening_auction_start: "09:25",
        continuous_start: "09:30",
        closing_auction_start: "16:00",
        closing_auction_end: "16:05",
      },
    });
  });

  it("collapses five identical explicit day blocks back to weekdays", () => {
    const day =
      "    pre_open: '09:00'\n    opening_auction_start: '09:25'\n    continuous_start: '09:30'\n    closing_auction_start: '16:00'\n    closing_auction_end: '16:05'\n";
    const doc = roundTrip(
      MINIMAL +
        `schedule:\n  mon:\n${day}  tue:\n${day}  wed:\n${day}  thu:\n${day}  fri:\n${day}`,
    );
    expect(doc.schedule).toEqual({
      weekdays: {
        pre_open: "09:00",
        opening_auction_start: "09:25",
        continuous_start: "09:30",
        closing_auction_start: "16:00",
        closing_auction_end: "16:05",
      },
    });
  });

  it("keeps days explicit when one of them diverges", () => {
    const short =
      "    pre_open: '09:00'\n    opening_auction_start: '09:25'\n    continuous_start: '09:30'\n    closing_auction_start: '16:00'\n    closing_auction_end: '16:05'\n";
    const fri =
      "    pre_open: '09:00'\n    opening_auction_start: '09:25'\n    continuous_start: '09:30'\n    closing_auction_start: '13:00'\n    closing_auction_end: '13:05'\n";
    const doc = roundTrip(
      MINIMAL +
        `schedule:\n  mon:\n${short}  tue:\n${short}  wed:\n${short}  thu:\n${short}  fri:\n${fri}`,
    );
    expect(doc.schedule).not.toHaveProperty("weekdays");
    expect(Object.keys(doc.schedule).sort()).toEqual(["fri", "mon", "thu", "tue", "wed"]);
    expect(doc.schedule.fri.closing_auction_start).toBe("13:00");
    expect(doc.schedule.mon.closing_auction_start).toBe("16:00");
  });

  it("collapses identical sat/sun blocks back to weekend", () => {
    const day =
      "    pre_open: '10:00'\n    opening_auction_start: '10:25'\n    continuous_start: '10:30'\n    closing_auction_start: '14:00'\n    closing_auction_end: '14:05'\n";
    const doc = roundTrip(MINIMAL + `schedule:\n  sat:\n${day}  sun:\n${day}`);
    expect(doc.schedule).toEqual({
      weekend: {
        pre_open: "10:00",
        opening_auction_start: "10:25",
        continuous_start: "10:30",
        closing_auction_start: "14:00",
        closing_auction_end: "14:05",
      },
    });
  });

  it("keeps a holidays block alongside weekdays", () => {
    const weekdays =
      "    pre_open: '09:00'\n    opening_auction_start: '09:25'\n    continuous_start: '09:30'\n    closing_auction_start: '16:00'\n    closing_auction_end: '16:05'\n";
    const holidays =
      "    pre_open: '10:00'\n    opening_auction_start: '10:25'\n    continuous_start: '10:30'\n    closing_auction_start: '13:00'\n    closing_auction_end: '13:05'\n";
    const doc = roundTrip(
      MINIMAL + `schedule:\n  weekdays:\n${weekdays}  holidays:\n${holidays}`,
    );
    expect(Object.keys(doc.schedule).sort()).toEqual(["holidays", "weekdays"]);
    expect(doc.schedule.holidays.closing_auction_start).toBe("13:00");
  });

  it("keeps a DEFAULT level that is not the default level as a plain named level", () => {
    const doc = roundTrip(
      MINIMAL +
        "risk_controls:\n  default_level: CORE\n  levels:\n    DEFAULT: {collar: {static_band_pct: 0.3}}\n    CORE: {collar: {dynamic_band_pct: 0.05}}\n",
    );
    expect(doc.risk_controls).toEqual({
      default_level: "CORE",
      levels: {
        DEFAULT: { collar: { static_band_pct: 0.3 } },
        CORE: { collar: { dynamic_band_pct: 0.05 } },
      },
    });
  });

  it("keeps a risk level with no collar as a level without one", () => {
    const doc = roundTrip(
      MINIMAL.replace(
        "tick_decimals: 2",
        "tick_decimals: 2\n    level: LOOSE",
      ) + "risk_controls:\n  levels:\n    LOOSE: {}\n",
    );
    expect(doc.risk_controls.levels.LOOSE).toEqual({});
  });

  it("writes disabled sections with enabled: false instead of dropping them", () => {
    const doc = roundTrip(
      MINIMAL +
        "market_data_gateway: {enabled: false}\nbalf_gateway: {enabled: false}\nlog_server: {enabled: false}\n" +
        "api_gateways:\n  public: {enabled: false, audit_db: /var/a.db}\n",
    );
    expect(doc.market_data_gateway.enabled).toBe(false);
    expect(doc.balf_gateway.enabled).toBe(false);
    expect(doc.log_server.enabled).toBe(false);
    expect(doc.api_gateways.public.enabled).toBe(false);
    expect(doc.api_gateways.public.audit_db).toBe("/var/a.db");
  });

  it("round-trips alf_gateway and the market-data connection limits", () => {
    const doc = roundTrip(
      MINIMAL +
        "alf_gateway: {port: 6565, idle_timeout_sec: 45}\n" +
        "market_data_gateway: {max_connections: 10, max_messages_per_second: 20}\n",
    );
    expect(doc.alf_gateway.port).toBe(6565);
    expect(doc.alf_gateway.idle_timeout_sec).toBe(45);
    expect(doc.market_data_gateway.max_connections).toBe(10);
    expect(doc.market_data_gateway.max_messages_per_second).toBe(20);
  });

  it("does not invent an index description", () => {
    const doc = roundTrip(
      MINIMAL.replace(
        "tick_decimals: 2",
        "tick_decimals: 2\n    outstanding_shares: 1",
      ) + "indices:\n  - id: EDU\n    constituents: [AAPL]\n",
    );
    expect(doc.indices[0].description).toBe("");
  });

  it("does not invent quote quantities", () => {
    const doc = roundTrip(
      MINIMAL.replace(
        "- id: TRADER01",
        "- id: TRADER01\n    - id: MM01\n      role: MARKET_MAKER",
      ).replace(
        "tick_decimals: 2",
        "tick_decimals: 2\n    market_maker_quotes:\n      - {gateway_id: MM01, bid_price: 1.0, ask_price: 1.1}",
      ),
    );
    expect(doc.symbols.AAPL.market_maker_quotes[0].bid_qty).toBe(0);
  });

  it("accepts a null symbol value as an empty spec", () => {
    const doc = roundTrip(MINIMAL + "  MSFT:\n");
    expect(doc.symbols).toHaveProperty("MSFT");
  });
});

describe("case normalisation (spec §1.6)", () => {
  it("upper-cases ids, symbols and enums so references still resolve", () => {
    const text = [
      "gateways:",
      "  alf:",
      "    - {id: mm01, role: market_maker, disconnect_behaviour: cancel_all}",
      "symbols:",
      "  aapl:",
      "    level: core",
      "    market_maker_quotes:",
      "      - {gateway_id: mm01, bid_price: 1.0, ask_price: 1.1, bid_qty: 1, ask_qty: 1, tif: gtc}",
      "risk_controls:",
      "  levels: {core: {collar: {static_band_pct: 0.1}}}",
      "",
    ].join("\n");
    const { draft } = parseYamlToDraft(text);
    expect(draft.gateways[0]).toMatchObject({
      id: "MM01",
      role: "MARKET_MAKER",
      disconnectBehaviour: "CANCEL_ALL",
    });
    expect(draft.symbolOrder).toEqual(["AAPL"]);
    expect(draft.symbols.AAPL!.level).toBe("CORE");
    expect(draft.symbols.AAPL!.marketMakerQuotes![0]).toMatchObject({
      gatewayId: "MM01",
      tif: "GTC",
    });
    expect(Object.keys(draft.riskControls.levels)).toEqual(["CORE"]);
  });

  it("normalises an unquoted H:MM schedule time the way the loader does", () => {
    const { draft } = parseYamlToDraft(
      MINIMAL + "schedule:\n  weekdays:\n    pre_open: 8:00\n",
    );
    expect(draft.schedule.weekdays!.preOpen).toBe("08:00");
  });
});

describe("prices are written on each symbol's own tick grid", () => {
  it("snaps mid-range seeds to the symbol's tick_decimals, not the global default", () => {
    const text =
      "gateways:\n  alf:\n    - {id: MM01, role: MARKET_MAKER}\n" +
      "symbols:\n  WHOLE: {tick_decimals: 0}\n  FINE: {tick_decimals: 4}\n";
    const { draft } = parseYamlToDraft(text);
    draft.seeding.mmMidRange = { min: 100.25, max: 100.25 };
    draft.seeding.seedLastPricesFromMm = true;
    const doc = yaml.load(generateYaml(draft)) as Doc;
    // 0 decimals: midpoint 100 (a whole tick), quote 99 / 101.
    expect(doc.symbols.WHOLE.last_buy_price).toBe(100);
    expect(doc.symbols.WHOLE.market_maker_quotes[0]).toMatchObject({
      bid_price: 99,
      ask_price: 101,
    });
    // 4 decimals: one tick is 0.0001.
    expect(doc.symbols.FINE.market_maker_quotes[0]).toMatchObject({
      bid_price: 100.2499,
      ask_price: 100.2501,
    });
  });
});
