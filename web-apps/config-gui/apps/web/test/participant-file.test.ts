/** Bulk participant import/export: a row is exactly the Participants table's fields. */

import { describe, expect, it } from "vitest";
import { createBlankDraft, createGateway, type EngineConfigDraft } from "@edumatcher/schema";
import { addImportedParticipants, readParticipantFile, writeParticipantFile } from "../src/lib/participantFile";
import { readTable, writeTable } from "../src/lib/tableFile";

const HEADER = "id,role,disconnect_behaviour,smp_action,description";

function importInto(d: EngineConfigDraft, text: string, format: "csv" | "json" = "csv"): string[] {
  const { items, errors } = readParticipantFile(text, format, d);
  if (errors.length === 0) addImportedParticipants(d, items);
  return errors;
}

describe("participant file import", () => {
  it("creates the gateway + Add gateway would, with the given fields", () => {
    const d = createBlankDraft();
    d.gateways = [];
    const errors = importInto(
      d,
      `${HEADER}\nt1,,,,\nmm1,market_maker,LEAVE_ALL,CANCEL_BOTH,"Desk A, floor 2"\n`,
    );
    expect(errors).toEqual([]);
    expect(d.gateways).toEqual([
      createGateway("T1"),
      {
        ...createGateway("MM1", "MARKET_MAKER"),
        disconnectBehaviour: "LEAVE_ALL",
        smpAction: "CANCEL_BOTH",
        description: "Desk A, floor 2",
      },
    ]);
  });

  it("accepts JSON with the same keys", () => {
    const d = createBlankDraft();
    d.gateways = [];
    expect(importInto(d, JSON.stringify([{ id: "A1", role: "ADMIN", smp_action: null }]), "json")).toEqual([]);
    expect(d.gateways).toEqual([createGateway("A1", "ADMIN")]);
  });

  it("rejects the whole file on any error and reports every problem", () => {
    const d = createBlankDraft();
    d.gateways = [createGateway("OLD")];
    const errors = importInto(
      d,
      [HEADER, "NEW,,,,", "OLD,,,,", "NEW,,,,", ",BOSS,,,", "X,,KEEP,SOMETIMES,"].join("\n"),
    );
    expect(errors).toEqual([
      "line 3: id OLD already exists.",
      "line 4: id NEW appears more than once.",
      "line 5: id is required.",
      'line 5: role "BOSS" must be one of TRADER, MARKET_MAKER, ADMIN.',
      'line 6: disconnect_behaviour "KEEP" must be one of CANCEL_ALL, CANCEL_QUOTES_ONLY, LEAVE_ALL.',
      'line 6: smp_action "SOMETIMES" must be one of NONE, CANCEL_AGGRESSOR, CANCEL_RESTING, CANCEL_BOTH.',
    ]);
    expect(d.gateways.map((g) => g.id)).toEqual(["OLD"]);
  });
});

describe("participant file export", () => {
  it("round-trips participants exactly, in CSV and JSON, including awkward descriptions", () => {
    const src = createBlankDraft();
    src.gateways = [
      { ...createGateway("T1"), smpAction: "NONE", description: 'Says "hi", twice' },
      createGateway("MM1", "MARKET_MAKER"),
    ];
    for (const format of ["csv", "json"] as const) {
      const { text, warnings } = writeParticipantFile(src, format);
      expect(warnings).toEqual([]);
      const dst = createBlankDraft();
      dst.gateways = [];
      expect(importInto(dst, text, format)).toEqual([]);
      expect(dst.gateways).toEqual(src.gateways);
    }
    expect(writeParticipantFile(src, "csv").text).toBe(
      `${HEADER}\nT1,TRADER,CANCEL_ALL,NONE,"Says ""hi"", twice"\nMM1,MARKET_MAKER,CANCEL_QUOTES_ONLY,,\n`,
    );
  });

  it("writes an inherited disconnect behaviour as its current value and names the gateway", () => {
    const d = createBlankDraft();
    d.gateways = [{ id: "T1", role: "TRADER" }, { id: "", role: "TRADER", disconnectBehaviour: "CANCEL_ALL" }];
    d.gatewayDefault.disconnectBehaviour = "LEAVE_ALL";
    const { text, warnings } = writeParticipantFile(d, "csv");
    expect(text).toContain("\nT1,TRADER,LEAVE_ALL,,\n");
    expect(warnings).toEqual(["T1: inherits its disconnect behaviour; written as LEAVE_ALL.", "A participant has no id."]);
  });
});

describe("table file CSV", () => {
  it("reports an unterminated quote", () => {
    const errors: string[] = [];
    readTable('a\n"x\n', "csv", ["a"], ["a"], "row", errors);
    expect(errors).toEqual(["line 2: unterminated quote."]);
  });

  it("quotes cells with commas, quotes or edge spaces", () => {
    expect(writeTable([{ a: "x,y", b: " z" }], ["a", "b"], "csv")).toBe('a,b\n"x,y"," z"\n');
  });
});
