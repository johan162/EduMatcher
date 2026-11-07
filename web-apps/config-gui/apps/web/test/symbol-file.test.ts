/** Bulk symbol import/export: a row is exactly the IPO dialog's fields. */

import { describe, expect, it } from "vitest";
import {
  DEFAULT_OUTSTANDING_SHARES,
  createBlankDraft,
  createGateway,
  deriveIpoQuote,
  type EngineConfigDraft,
} from "@edumatcher/schema";
import { addImportedSymbols, readSymbolFile, writeSymbolFile } from "../src/lib/symbolFile";

const HEADER = "symbol,reference_price,outstanding_shares,tick_decimals,mm_gateway,spread_ticks,quote_size";

function draftWithMm(): EngineConfigDraft {
  const d = createBlankDraft();
  d.gateways = [createGateway("MM1", "MARKET_MAKER"), createGateway("T1")];
  return d;
}

function importInto(d: EngineConfigDraft, text: string, format: "csv" | "json" = "csv"): string[] {
  const { symbols, errors } = readSymbolFile(text, format, d);
  if (errors.length === 0) addImportedSymbols(d, symbols);
  return errors;
}

describe("symbol file import", () => {
  it("creates the symbol the IPO dialog would", () => {
    const d = draftWithMm();
    expect(importInto(d, `${HEADER}\naapl,182.5,5000,2,mm1,4,200\n`)).toEqual([]);
    expect(d.symbolOrder).toEqual(["AAPL"]);
    expect(d.symbols.AAPL).toEqual({
      tickDecimals: 2,
      lastBuyPrice: 182.5,
      lastSellPrice: 182.5,
      outstandingShares: 5000,
      marketMakerQuotes: [deriveIpoQuote("MM1", 182.5, 2, 4, 200)],
    });
  });

  it("fills blank optional fields with the dialog defaults and seeds no quote without mm_gateway", () => {
    const d = draftWithMm();
    d.tickDecimals = 3;
    expect(importInto(d, "symbol,reference_price\nMSFT,410\n")).toEqual([]);
    expect(d.symbols.MSFT).toEqual({
      tickDecimals: 3,
      lastBuyPrice: 410,
      lastSellPrice: 410,
      outstandingShares: DEFAULT_OUTSTANDING_SHARES,
    });
  });

  it("uses the default spread and size when only mm_gateway is given", () => {
    const d = draftWithMm();
    expect(importInto(d, "symbol,reference_price,mm_gateway\nX,10,MM1\n")).toEqual([]);
    expect(d.symbols.X!.marketMakerQuotes).toEqual([deriveIpoQuote("MM1", 10, d.tickDecimals)]);
  });

  it("accepts JSON with the same keys, null as blank", () => {
    const d = draftWithMm();
    const json = JSON.stringify([
      { symbol: "A", reference_price: 1.5, mm_gateway: "MM1", quote_size: null },
      { symbol: "B", reference_price: "2" },
    ]);
    expect(importInto(d, json, "json")).toEqual([]);
    expect(d.symbolOrder).toEqual(["A", "B"]);
    expect(d.symbols.B!.lastBuyPrice).toBe(2);
  });

  it("tolerates a BOM, CRLF, quoted cells and blank lines", () => {
    const d = draftWithMm();
    expect(importInto(d, '﻿symbol,"reference_price"\r\n"A",1\r\n\r\nB,2\r\n')).toEqual([]);
    expect(d.symbolOrder).toEqual(["A", "B"]);
  });

  it("rejects the whole file on any error and reports every problem", () => {
    const d = draftWithMm();
    d.symbolOrder.push("OLD");
    d.symbols.OLD = { tickDecimals: 2 };
    const errors = importInto(
      d,
      [
        HEADER,
        "GOOD,1,,,,,",
        "OLD,1,,,,,",
        "GOOD,1,,,,,",
        ",0,,,,,",
        "BAD,1,0,9,T1,,",
        "LONE,1,,,,2,",
        "SHORT,1",
      ].join("\n"),
    );
    // Malformed lines are reported first, then field problems.
    expect(errors).toEqual([
      "line 8: expected 7 fields, found 2.",
      "line 3: symbol OLD already exists.",
      "line 4: symbol GOOD appears more than once.",
      "line 5: symbol is required.",
      "line 5: reference_price must be a number > 0.",
      "line 6: outstanding_shares must be an integer >= 1.",
      "line 6: tick_decimals must be an integer in 0..8.",
      'line 6: mm_gateway "T1" is not a MARKET_MAKER gateway.',
      "line 7: spread_ticks and quote_size need an mm_gateway.",
    ]);
    expect(d.symbolOrder).toEqual(["OLD"]);
  });

  it("rejects unknown, duplicate and missing columns", () => {
    const { errors } = readSymbolFile("symbol,symbol,level\nA,A,X\n", "csv", draftWithMm());
    expect(errors).toEqual([
      'Column "symbol" appears twice.',
      'Unknown column "level".',
      'Missing required column "reference_price".',
    ]);
  });

  it("rejects empty files, bad JSON and unknown JSON keys", () => {
    const d = draftWithMm();
    expect(readSymbolFile("", "csv", d).errors).toEqual(["The file is empty."]);
    expect(readSymbolFile(`${HEADER}\n`, "csv", d).errors).toEqual(["The file holds no symbols."]);
    expect(readSymbolFile("{}", "json", d).errors).toEqual([
      "The JSON file must hold an array of symbol objects.",
    ]);
    expect(readSymbolFile("[", "json", d).errors[0]).toMatch(/^Not valid JSON/);
    expect(readSymbolFile('[{"symbol":"A","reference_price":1,"level":"X"}, 3]', "json", d).errors).toEqual([
      'entry 1: unknown key "level".',
      "entry 2: not an object.",
    ]);
  });
});

describe("symbol file export", () => {
  it("round-trips IPO-created symbols exactly, in CSV and JSON", () => {
    const src = draftWithMm();
    importInto(src, `${HEADER}\nAAPL,182.5,5000,2,MM1,3,200\nMSFT,410,,,,,\n`);
    for (const format of ["csv", "json"] as const) {
      const { text, warnings } = writeSymbolFile(src, format);
      expect(warnings).toEqual([]);
      const dst = draftWithMm();
      expect(importInto(dst, text, format)).toEqual([]);
      expect(dst.symbolOrder).toEqual(src.symbolOrder);
      expect(dst.symbols).toEqual(src.symbols);
    }
    expect(writeSymbolFile(src, "csv").text).toBe(
      `${HEADER}\nAAPL,182.5,5000,2,MM1,3,200\nMSFT,410,${DEFAULT_OUTSTANDING_SHARES},2,,,\n`,
    );
  });

  it("names symbols the IPO fields cannot describe exactly", () => {
    const d = draftWithMm();
    importInto(d, `${HEADER}\nOK,10,,,MM1,,\nSPLIT,10,,,,,\nEDITED,10,,,MM1,,\nTWO,10,,,MM1,,\nNOPRICE,10,,,,,\n`);
    d.symbols.SPLIT!.lastSellPrice = 11;
    d.symbols.EDITED!.marketMakerQuotes![0]!.askQty = 7;
    d.symbols.TWO!.marketMakerQuotes!.push(deriveIpoQuote("MM1", 10, 2));
    d.symbols.NOPRICE!.lastBuyPrice = null;
    d.symbols.NOPRICE!.lastSellPrice = null;
    const { text, warnings } = writeSymbolFile(d, "csv");
    expect(warnings).toEqual(["SPLIT", "EDITED", "TWO", "NOPRICE"]);
    // Written as near as the fields allow: last buy is the reference price.
    expect(text).toContain("\nSPLIT,10,");
    expect(text).toContain("\nNOPRICE,,");
  });
});
